"""
Regression tests for the delivery layer: Persian signal cards, Telegram retry
behaviour, schema upgrades on legacy databases, and the fail-closed publish gate.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.signal_card import _bundled_font, _has_rtl, _shape_rtl  # noqa: E402


def test_persian_font_is_bundled_with_the_app():
    """Without a bundled Vazirmatn the card renders Persian as empty boxes."""
    regular = _bundled_font(bold=False)
    bold = _bundled_font(bold=True)
    assert regular and os.path.exists(regular)
    assert bold and os.path.exists(bold)
    assert "Vazirmatn" in os.path.basename(regular)


def test_rtl_shaping_reorders_persian_and_leaves_latin_alone():
    persian = "حد ضرر ساختاری"
    shaped = _shape_rtl(persian)
    assert _has_rtl(persian)
    assert shaped != persian, "Persian text must be reshaped/reordered for Pillow"
    assert _shape_rtl("STOP LOSS 1.15107") == "STOP LOSS 1.15107"


def test_rtl_shaping_is_idempotent_safe_for_numbers_only_strings():
    assert _shape_rtl("1.15107") == "1.15107"
    assert _shape_rtl("") == ""


def test_schema_upgrade_adds_missing_columns_to_a_legacy_database(tmp_path, monkeypatch):
    """
    Deployment hazard: create_all never ALTERs an existing table, so a DB created
    before a new column existed would crash the whole API on boot.
    """
    import importlib

    db_path = tmp_path / "legacy.db"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE engine_config (id INTEGER PRIMARY KEY, preset_name VARCHAR(64) NOT NULL DEFAULT 'x')")
    con.commit()
    con.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    for mod in [m for m in list(sys.modules) if m.startswith("app.")]:
        if mod in ("app.database", "app.models", "app.config"):
            sys.modules.pop(mod, None)

    import app.config as cfg_mod
    importlib.reload(cfg_mod)
    import app.database as db_mod
    importlib.reload(db_mod)
    import app.models  # noqa: F401

    db_mod.init_db()

    con = sqlite3.connect(db_path)
    cols = {row[1] for row in con.execute("PRAGMA table_info(engine_config)")}
    con.close()
    assert "policy_version" in cols
    assert "tp1_rr" in cols
    assert "preset_name" in cols


def test_demo_data_is_never_published_to_telegram():
    """
    The public channel must only ever receive live-data signals whose backtest
    edge is statistically valid; a replay feed must fail closed.
    """
    from app.engine import scheduler

    class _Qual:
        def __init__(self, eligible, trades=40, wr=72.0, pf=1.9):
            self.eligible_for_telegram = eligible
            self.total_trades = trades
            self.win_rate = wr
            self.profit_factor = pf

    sig = type(
        "S",
        (),
        dict(
            symbol="EURUSD",
            timeframe="4H",
            direction="LONG",
            timestamp=__import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc),
            entry_price=1.1,
            sl=1.09,
            tp1=1.12,
            tp2=1.14,
            tp3=1.16,
            tp1_exit_pct=50.0,
            tp2_exit_pct=30.0,
            tp3_exit_pct=20.0,
            position_size_lots=1.0,
            confluence_score=9.0,
            grade="A",
            checklist={},
            rationale_fa="",
            risk_tier="SAFE",
            entry_module="SWEEP",
            htf_bias="BULLISH",
            session_name="LONDON",
            bars_valid=10,
            risk_pips=100.0,
            risk_atr=1.2,
            early_be_price=1.11,
            pending_expiry_hours=96,
        ),
    )()

    class _DB:
        def query(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def first(self):
            return None

        def count(self):
            return 3

        def all(self):
            return []

        def commit(self):
            pass

        def refresh(self, _o):
            pass

        def add(self, _o):
            pass

        def flush(self):
            pass

    created = {}

    class _TradeCls:
        # class-level column doubles used by the idempotency lookup
        idempotency_key = "idem"
        id = 7

        def __init__(self, **kw):
            created.clear()
            created.update(kw)

    original = scheduler.SignalTrade
    scheduler.SignalTrade = _TradeCls
    try:
        scheduler._create_trade_from_signal(
            _DB(), sig, _Qual(True), "demo", True, 1.1, type("C", (), {"telegram_send_signals": True})(),
            publish_telegram=False,
        )
        assert created["eligible_for_telegram"] is False, "demo data must not be publishable"

        scheduler._create_trade_from_signal(
            _DB(), sig, _Qual(True), "oanda", False, 1.1, type("C", (), {"telegram_send_signals": True})(),
            publish_telegram=False,
        )
        assert created["eligible_for_telegram"] is True

        scheduler._create_trade_from_signal(
            _DB(), sig, _Qual(True, trades=3), "oanda", False, 1.1, type("C", (), {"telegram_send_signals": True})(),
            publish_telegram=False,
        )
        assert created["eligible_for_telegram"] is False, "a 3-trade sample is not statistical proof"
    finally:
        scheduler.SignalTrade = original


def test_each_timeframe_keeps_its_own_target_ladder(tmp_path):
    """
    Regression: one shared EngineConfig ladder used to overwrite all three
    timeframes, so the 4H SAFE profile silently traded the 15m targets.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    from app.engine.backtester import build_params_for_timeframe
    from app.models import EngineConfig

    engine = create_engine(f"sqlite:///{tmp_path/'cfg.db'}")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    cfg = EngineConfig(id=1)
    db.add(cfg)
    db.commit()

    p4 = build_params_for_timeframe(cfg, "4H").policy
    p15 = build_params_for_timeframe(cfg, "15m").policy
    p5 = build_params_for_timeframe(cfg, "5m").policy

    assert (p4.tp1_rr, p4.tp2_rr, p4.tp3_rr) == (1.3, 2.4, 3.6)
    assert (p15.tp1_rr, p15.tp2_rr, p15.tp3_rr) == (1.2, 2.2, 3.4)
    assert (p5.tp1_rr, p5.tp2_rr, p5.tp3_rr) == (1.1, 2.0, 3.0)
    # Ladders must stay ordered per timeframe (a broken ladder silently kills signals)
    for pol in (p4, p15, p5):
        assert pol.tp1_rr < pol.tp2_rr < pol.tp3_rr


def test_schema_upgrade_defaults_are_dialect_aware():
    """
    PostgreSQL rejects `BOOLEAN DEFAULT 1`, so the forward migration must emit
    true/false on Postgres while staying 1/0 on SQLite. Without this, boot dies on
    a Postgres deployment (Railway / Supabase) the moment a column is added.
    """
    from sqlalchemy import Boolean, Float, Integer, String

    from app import database as db_mod

    col_bool = type("C", (), {"type": Boolean(), "default": type("D", (), {"arg": True})()})()
    col_float = type("C", (), {"type": Float(), "default": type("D", (), {"arg": 0.5})()})()
    col_str = type("C", (), {"type": String(10), "default": type("D", (), {"arg": ""})()})()

    original = db_mod._is_postgres
    try:
        db_mod._is_postgres = lambda: False
        assert db_mod._default_sql_for(col_bool) == "DEFAULT 1 NOT NULL"
        assert db_mod._default_sql_for(col_float) == "DEFAULT 0.5 NOT NULL"
        assert "DEFAULT '' NOT NULL" == db_mod._default_sql_for(col_str)

        db_mod._is_postgres = lambda: True
        assert db_mod._default_sql_for(col_bool) == "DEFAULT true NOT NULL"
        assert db_mod._default_sql_for(col_float) == "DEFAULT 0.5 NOT NULL"
    finally:
        db_mod._is_postgres = original


def test_supabase_urls_get_ssl_enforced():
    """A URL pasted without sslmode would fail at boot on managed Postgres."""
    from app.database import normalize_database_url as n

    direct = n("postgres://postgres:pw@db.abc.supabase.co:5432/postgres")
    assert direct.startswith("postgresql+psycopg2://")
    assert "sslmode=require" in direct

    pooler = n("postgresql://postgres:pw@aws-0-eu-central-1.pooler.supabase.com:6543/postgres")
    assert "sslmode=require" in pooler

    # an explicit sslmode wins over our default
    explicit = n("postgresql://u:p@db.abc.supabase.co:5432/postgres?sslmode=verify-full")
    assert explicit.count("sslmode=") == 1
    assert "verify-full" in explicit

    # sqlite untouched
    assert n("sqlite:///./nexvora.db") == "sqlite:///./nexvora.db"
