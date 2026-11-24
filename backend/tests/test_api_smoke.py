"""
Smoke tests for every PWA page endpoint.

A NameError in one serializer took down /api/v1/market/overview while the rest of
the API stayed healthy, which is invisible from the healthcheck. These tests walk
the endpoints the PWA actually calls so a broken page fails CI instead.
"""
import os
import sys
from pathlib import Path

TEST_DB = Path(__file__).resolve().parent / "test_api_smoke.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["NEXVORA_DATA_MODE"] = "demo"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["TELEGRAM_DRY_RUN"] = "true"
os.environ["COOKIE_SECURE"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN_EMAIL = os.environ.get("INITIAL_ADMIN_EMAIL", "admin@nexvora.local")
ADMIN_PASSWORD = os.environ.get("INITIAL_ADMIN_PASSWORD", "NexvoraAdmin!2026")

PWA_ENDPOINTS = [
    "/api/v1/dashboard",
    "/api/v1/trades/live",
    "/api/v1/trades/history",
    "/api/v1/market/overview",
    "/api/v1/analytics/performance",
    "/api/v1/analytics/qualifications",
    "/api/v1/analytics/policy",
    "/api/v1/news",
    "/api/v1/calendar",
    "/api/v1/notifications",
]


def _client() -> TestClient:
    client = TestClient(app)
    client.__enter__()
    resp = client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert resp.status_code == 200, resp.text
    return client


def test_every_pwa_endpoint_returns_200():
    client = _client()
    try:
        failures = []
        for path in PWA_ENDPOINTS:
            r = client.get(path)
            if r.status_code != 200:
                failures.append(f"{path} -> {r.status_code} {r.text[:200]}")
        assert not failures, "\n".join(failures)
    finally:
        client.__exit__(None, None, None)


def test_market_overview_shape_is_what_the_ui_consumes():
    """The market page reads these keys directly; a rename would blank the page."""
    client = _client()
    try:
        data = client.get("/api/v1/market/overview").json()
    finally:
        client.__exit__(None, None, None)

    assert data["instruments"], "market overview must return the 6 instruments"
    inst = data["instruments"][0]
    for key in ("symbol", "display", "name_fa", "digits", "price", "source", "is_demo_data", "timeframes"):
        assert key in inst, f"missing instrument key {key}"
    assert len(inst["timeframes"]) == 3
    tf = inst["timeframes"][0]
    for key in (
        "timeframe",
        "risk_tier",
        "state",
        "htf_bias",
        "adx",
        "why_no_trade_fa",
        "eligible_for_telegram",
        "backtest_win_rate",
        "backtest_profit_factor",
        "backtest_trades",
        "is_demo_data",
        "rejections",
    ):
        assert key in tf, f"missing timeframe key {key}"
