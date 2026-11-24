from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, analytics, auth, dashboard, market, news, notifications, trades
from app.config import ALLOWED_SYMBOLS, ALLOWED_TIMEFRAMES, SYMBOL_META, TIMEFRAME_META, get_settings
from app.database import SessionLocal, init_db
from app.engine.scheduler import (
    background_engine_loop,
    bootstrap_initial_engine_data,
    ensure_initial_admin,
    get_or_create_engine_config,
)
from app.security import SESSION_COOKIE_NAME, resolve_session_from_token
from app.services.realtime import realtime_hub

logger = logging.getLogger("nexvora.startup")
APP_BUILD_ID = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "local")[:8]


def _run_bootstrap_in_thread(bootstrap_done: asyncio.Event | None = None, loop: asyncio.AbstractEventLoop | None = None) -> None:
    db = SessionLocal()
    try:
        print(f"[NEXVORA] build={APP_BUILD_ID} starting background engine & news bootstrap...", flush=True)
        bootstrap_initial_engine_data(db)
        print(f"[NEXVORA] build={APP_BUILD_ID} initial bootstrap completed.", flush=True)
    except Exception as exc:  # pragma: no cover
        db.rollback()
        logger.exception("[NEXVORA] Non-fatal error during background bootstrap: %s", exc)
    finally:
        db.close()
        if bootstrap_done is not None and loop is not None:
            loop.call_soon_threadsafe(bootstrap_done.set)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    cfg_settings = get_settings()
    db_kind = "sqlite" if cfg_settings.database_url.startswith("sqlite") else "postgresql"
    print(
        f"[NEXVORA] Starting API build={APP_BUILD_ID} env={cfg_settings.nexvora_env} "
        f"data_mode={cfg_settings.nexvora_data_mode} db={db_kind}",
        flush=True,
    )
    init_db()
    # Always ensure admin & engine_config synchronously (< 50ms) so auth works immediately
    db = SessionLocal()
    try:
        ensure_initial_admin(db)
        get_or_create_engine_config(db)
        if cfg_settings.nexvora_env != "production":
            # In dev/test (demo/local), run synchronous bootstrap so tests see seeded data right away
            try:
                bootstrap_initial_engine_data(db)
            except Exception as exc:  # pragma: no cover
                db.rollback()
                logger.exception("[NEXVORA] Non-fatal error during startup bootstrap: %s", exc)
    finally:
        db.close()

    stop_event = asyncio.Event()
    bootstrap_done = asyncio.Event()
    bootstrap_task = None
    if cfg_settings.nexvora_env == "production":
        # In production (e.g. Railway), run heavy market/RSS bootstrap in background
        # so /api/v1/health responds 200 OK within ~1-2 seconds and never hits healthcheck timeout.
        loop = asyncio.get_running_loop()
        bootstrap_task = asyncio.create_task(asyncio.to_thread(_run_bootstrap_in_thread, bootstrap_done, loop))
    else:
        bootstrap_done.set()

    task = asyncio.create_task(background_engine_loop(stop_event, bootstrap_done=bootstrap_done))
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        if bootstrap_task is not None and not bootstrap_task.done():
            bootstrap_task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


settings = get_settings()
app = FastAPI(
    title="NEXVORA Trading Hub 3.0 API",
    version="1.0.0",
    docs_url="/api/docs" if settings.nexvora_env != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if request.url.path.startswith("/api/"):
        # Never cache private API responses in browser/shared/SW caches
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
    return response


@app.exception_handler(Exception)
async def safe_global_exception_handler(_request: Request, _exc: Exception):
    # Safe error without leaking stack traces, internal paths, or secrets
    return JSONResponse(
        status_code=500,
        content={"detail": "خطای داخلی سرور رخ داد. لطفاً دوباره تلاش کنید."},
    )


# Register routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(trades.router)
app.include_router(analytics.router)
app.include_router(news.router)
app.include_router(market.router)
app.include_router(notifications.router)
app.include_router(admin.router)


@app.get("/api/v1/health")
def health():
    """
    Liveness + readiness for the platform healthcheck.

    Reports enough runtime facts that a bad deploy is diagnosable from the curl
    alone: whether the DB is reachable, whether bundled card fonts are present
    (missing fonts silently break Persian Telegram cards), and the live policy
    version actually in force.
    """
    from app.database import engine as db_engine
    from app.engine.policy import TRADING_POLICY_VERSION

    db_state = "ok"
    try:
        from sqlalchemy import text

        with db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - defensive
        db_state = f"error: {type(exc).__name__}"

    try:
        from app.services.signal_card import _bundled_font

        fa_font = bool(_bundled_font(bold=False))
    except Exception:
        fa_font = False

    return {
        "status": "ok" if db_state == "ok" else "degraded",
        "service": "nexvora-hub3-backend",
        "build": APP_BUILD_ID,
        "env": settings.nexvora_env,
        "data_mode": settings.nexvora_data_mode,
        "database": db_state,
        "persian_card_fonts": fa_font,
        "policy_version": TRADING_POLICY_VERSION,
        "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_channel_id),
        "allowed_symbols": ALLOWED_SYMBOLS,
        "allowed_timeframes": ALLOWED_TIMEFRAMES,
    }


@app.get("/api/v1/meta")
def public_meta():
    return {
        "symbols": {k: {"display": v["display"], "name_fa": v["name_fa"], "digits": v["digits"], "market_class": v["market_class"]} for k, v in SYMBOL_META.items()},
        "timeframes": {k: {"label_fa": v["label_fa"], "risk_tier": v["risk_tier"], "risk_label_fa": v["risk_label_fa"]} for k, v in TIMEFRAME_META.items()},
    }


@app.websocket("/ws/realtime")
async def websocket_realtime(ws: WebSocket):
    raw_token = ws.cookies.get(SESSION_COOKIE_NAME)
    db = SessionLocal()
    try:
        resolved = resolve_session_from_token(db, raw_token)
    finally:
        db.close()

    if not resolved:
        await ws.close(code=4401, reason="Unauthorized")
        return

    user, _sess = resolved
    conn = await realtime_hub.connect(ws, user_id=user.id, role=user.role, session_token=raw_token or "")
    try:
        await ws.send_json({"type": "connected", "data": {"user_id": user.id, "role": user.role}})
        while True:
            raw_msg = await ws.receive_text()
            if len(raw_msg) > 1024:
                await ws.close(code=4413, reason="Message too large")
                break
            # Revalidate session on ping
            db_check = SessionLocal()
            try:
                still_valid = resolve_session_from_token(db_check, raw_token)
            finally:
                db_check.close()
            if not still_valid:
                await ws.close(code=4401, reason="Session expired")
                break
            if raw_msg.strip().lower() == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await realtime_hub.disconnect(conn)


# Built SPA serving for single-server production deployments (e.g. Railway Docker)
def _resolve_frontend_dist() -> Path | None:
    candidates = []
    env_dir = os.environ.get("FRONTEND_DIST_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    here = Path(__file__).resolve()
    # Repo root: /app/frontend/dist or /home/user/Nexvora-Hub3-WE/frontend/dist
    if len(here.parents) > 3:
        candidates.append(here.parents[3] / "frontend" / "dist")
    if len(here.parents) > 2:
        candidates.append(here.parents[2] / "frontend" / "dist")
    for c in candidates:
        if (c / "index.html").is_file():
            return c.resolve()
    return None


_FRONTEND_DIST = _resolve_frontend_dist()
if _FRONTEND_DIST is not None:
    assets_dir = _FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("ws/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        if full_path:
            candidate = (_FRONTEND_DIST / full_path).resolve()
            # Guard against path traversal outside frontend/dist
            if candidate.is_relative_to(_FRONTEND_DIST) and candidate.is_file():
                resp = FileResponse(str(candidate))
                if full_path in ("sw.js", "manifest.webmanifest", "index.html"):
                    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                return resp

        resp = FileResponse(str(_FRONTEND_DIST / "index.html"))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp
