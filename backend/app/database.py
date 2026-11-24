from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def normalize_database_url(raw_url: str) -> str:
    """
    Normalize Railway/Supabase URLs for SQLAlchemy 2.x + psycopg2.

    Supabase (and most managed Postgres) refuse non-TLS connections, and a URL
    pasted straight from a dashboard often omits `sslmode`. Rather than failing at
    boot with an opaque psycopg2 error, SSL is enforced for those hosts here.
    """
    url = raw_url.strip()
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql+psycopg://"):
        url = "postgresql+psycopg2://" + url[len("postgresql+psycopg://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]

    if url.startswith("postgresql+psycopg2://") and "sslmode=" not in url:
        host_part = url.split("@")[-1].lower()
        # Supabase (and its pooler) is reachable over the public internet and
        # rejects plaintext connections. Railway's private network
        # (db.railway.internal) must NOT be forced to TLS, so it is excluded.
        needs_tls = "supabase" in host_part or "pooler." in host_part
        if "railway.internal" in host_part:
            needs_tls = False
        if needs_tls:
            url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def _register_numpy_psycopg2_adapters() -> None:
    """Register NumPy scalar adapters for psycopg2 so PostgreSQL never fails on np.float64/np.int64/np.bool_."""
    try:
        import numpy as np
        from psycopg2.extensions import AsIs, register_adapter

        for np_float in (np.float16, np.float32, np.float64):
            register_adapter(np_float, lambda x: AsIs(repr(float(x))))
        for np_int in (np.int8, np.int16, np.int32, np.int64, np.uint8, np.uint16, np.uint32, np.uint64):
            register_adapter(np_int, lambda x: AsIs(int(x)))
        register_adapter(np.bool_, lambda x: AsIs(bool(x)))
    except Exception:
        pass


def _build_engine():
    _register_numpy_psycopg2_adapters()
    settings = get_settings()
    db_url = normalize_database_url(settings.database_url)
    is_sqlite = db_url.startswith("sqlite")

    engine_kwargs = {
        "pool_pre_ping": True,
        "future": True,
    }
    if is_sqlite:
        engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        # Production PostgreSQL pool tuning (Railway / Supabase)
        engine_kwargs["pool_size"] = 5
        engine_kwargs["max_overflow"] = 10
        engine_kwargs["pool_recycle"] = 300
        engine_kwargs["connect_args"] = {"connect_timeout": 10}

    eng = create_engine(db_url, **engine_kwargs)
    if is_sqlite:
        @event.listens_for(eng, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.close()
    return eng


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _existing_columns(table_name: str) -> set[str]:
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if not insp.has_table(table_name):
        return set()
    return {c["name"] for c in insp.get_columns(table_name)}


def _is_postgres() -> bool:
    return not str(engine.url).startswith("sqlite")


def _default_sql_for(column) -> str:
    """
    Render a safe literal default for an ADD COLUMN statement.

    Dialect-aware on purpose: PostgreSQL rejects `BOOLEAN DEFAULT 1` (it demands
    true/false), so a SQLite-shaped default would abort the boot-time migration
    on a Postgres deployment (Railway / Supabase).
    """
    from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text

    col_type = column.type
    default = column.default.arg if column.default is not None and not callable(column.default.arg) else None
    if isinstance(col_type, Boolean):
        value = bool(default) if default is not None else False
        if _is_postgres():
            return f"DEFAULT {'true' if value else 'false'} NOT NULL"
        return "DEFAULT " + ("1" if value else "0") + " NOT NULL"
    if isinstance(col_type, (Integer,)):
        return f"DEFAULT {int(default or 0)} NOT NULL"
    if isinstance(col_type, (Float,)):
        return f"DEFAULT {float(default or 0.0)} NOT NULL"
    if isinstance(col_type, DateTime):
        return ""  # nullable timestamps
    if isinstance(col_type, (String, Text)):
        return "DEFAULT '' NOT NULL"
    return ""


def ensure_schema_upgrades() -> None:
    """
    Lightweight, idempotent forward migration.

    `create_all` never alters an existing table, so a deployment that already has
    a database volume would otherwise crash when a new column is introduced.
    Missing *nullable-or-defaulted* columns are added in place; anything more
    complex is left to a proper migration tool.
    """
    from sqlalchemy import text

    added: list[str] = []
    for table in Base.metadata.sorted_tables:
        existing = _existing_columns(table.name)
        if not existing:
            continue
        for column in table.columns:
            if column.name in existing:
                continue
            if column.primary_key:
                continue
            suffix = _default_sql_for(column)
            if not suffix and not column.nullable:
                # Cannot add a NOT NULL column without a default on legacy data.
                continue
            ddl = f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {column.type.compile(dialect=engine.dialect)}'
            if suffix:
                ddl += " " + suffix
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                added.append(f"{table.name}.{column.name}")
            except Exception as exc:  # pragma: no cover - defensive
                print(f"[NEXVORA] schema upgrade skipped {table.name}.{column.name}: {exc}", flush=True)
    if added:
        print(f"[NEXVORA] schema upgraded: {', '.join(added)}", flush=True)


def init_db() -> None:
    import time
    from app import models  # noqa: F401

    last_err: Exception | None = None
    for attempt in range(5):
        try:
            Base.metadata.create_all(bind=engine)
            ensure_schema_upgrades()
            return
        except Exception as exc:
            last_err = exc
            if attempt < 4:
                time.sleep(1.5 * (attempt + 1))
    if last_err is not None:
        raise last_err
