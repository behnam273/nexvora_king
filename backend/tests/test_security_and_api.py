from __future__ import annotations

import os
from pathlib import Path

# Configure isolated test DB before importing app
TEST_DB = Path(__file__).resolve().parent / "test_security_api.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["NEXVORA_DATA_MODE"] = "demo"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["TELEGRAM_DRY_RUN"] = "true"
os.environ["COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient

from app.database import SessionLocal, init_db
from app.main import app
from app.models import Notification, User, UserSession, UserTradeJournal
from app.security import rate_limiter


def _cleanup_test_users():
    init_db()
    db = SessionLocal()
    try:
        test_users = db.query(User).filter(User.email.in_(["usera@nexvora.test", "userb@nexvora.test"])).all()
        ids = [u.id for u in test_users]
        if ids:
            db.query(UserSession).filter(UserSession.user_id.in_(ids)).delete(synchronize_session=False)
            db.query(Notification).filter(Notification.user_id.in_(ids)).delete(synchronize_session=False)
            db.query(UserTradeJournal).filter(UserTradeJournal.user_id.in_(ids)).delete(synchronize_session=False)
            db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)
            db.commit()
    finally:
        db.close()


def test_full_security_isolation_rbac_csrf_and_api_flow():
    rate_limiter.reset()
    _cleanup_test_users()
    with TestClient(app) as client_a, TestClient(app) as client_b, TestClient(app) as client_admin:
        # 1. Health & meta public endpoints
        r = client_a.get("/api/v1/health")
        assert r.status_code == 200
        assert len(r.json()["allowed_symbols"]) == 6
        assert r.json()["allowed_timeframes"] == ["4H", "15m", "5m"]

        # Unauthenticated private endpoints MUST fail with 401
        assert client_a.get("/api/v1/dashboard").status_code == 401
        assert client_a.get("/api/v1/trades/live").status_code == 401

        # 2. Register User A & verify HttpOnly cookie + no secrets in payload
        reg_a = client_a.post(
            "/api/v1/auth/register",
            json={"email": "usera@nexvora.test", "full_name": "کاربر الف", "password": "StrongPassword!123"},
        )
        assert reg_a.status_code == 201
        csrf_a = reg_a.json()["csrf_token"]
        assert reg_a.json()["user"]["role"] == "USER"
        set_cookie = reg_a.headers.get("set-cookie", "").lower()
        assert "httponly" in set_cookie

        # 3. CSRF enforcement on state-changing requests
        no_csrf = client_a.patch("/api/v1/auth/profile", json={"full_name": "تست بدون CSRF"})
        assert no_csrf.status_code == 403

        # Mass assignment protection: attempting to inject role="ADMIN" via profile update must be ignored
        ok_prof = client_a.patch(
            "/api/v1/auth/profile",
            headers={"X-CSRF-Token": csrf_a},
            json={"full_name": "کاربر الف جدید", "role": "ADMIN"},
        )
        assert ok_prof.status_code == 200
        assert ok_prof.json()["role"] == "USER"

        # 4. RBAC protection: User A cannot access admin routes
        assert client_a.get("/api/v1/admin/overview").status_code == 403
        assert client_a.get("/api/v1/admin/audit-logs").status_code == 403

        # 5. Register User B & verify cross-account BOLA/IDOR isolation on journals & sessions
        reg_b = client_b.post(
            "/api/v1/auth/register",
            json={"email": "userb@nexvora.test", "full_name": "کاربر ب", "password": "StrongPassword!456"},
        )
        assert reg_b.status_code == 201
        csrf_b = reg_b.json()["csrf_token"]

        # Get first trade ID
        hist = client_a.get("/api/v1/trades/history").json()
        assert hist["total"] > 0
        trade_id = hist["items"][0]["id"]

        # User A writes private journal note
        j_put = client_a.put(
            f"/api/v1/trades/{trade_id}/journal",
            headers={"X-CSRF-Token": csrf_a},
            json={"notes": "یادداشت کاملاً خصوصی کاربر الف", "personal_risk_usd": 150},
        )
        assert j_put.status_code == 200

        # User B checks trade detail & my journals -> MUST NOT see User A's private journal!
        detail_b = client_b.get(f"/api/v1/trades/{trade_id}").json()
        assert detail_b["user_journal"] is None
        assert client_b.get("/api/v1/trades/journal/mine").json() == []

        # User B cannot revoke User A's session
        sess_a_id = client_a.get("/api/v1/auth/sessions").json()[0]["id"]
        del_b = client_b.delete(f"/api/v1/auth/sessions/{sess_a_id}", headers={"X-CSRF-Token": csrf_b})
        assert del_b.status_code == 404

        # 6. Dashboard, Analytics, Qualifications, News, Calendar, Market, CSV Export
        dash = client_a.get("/api/v1/dashboard")
        assert dash.status_code == 200
        assert dash.headers.get("cache-control", "").startswith("no-store")
        assert len(dash.json()["market_strip"]) == 6
        assert dash.json()["is_demo_data"] is True  # Honest non-live demo labelling!

        quals = client_a.get("/api/v1/analytics/qualifications").json()
        assert len(quals) == 18  # 6 symbols x 3 timeframes

        news_resp = client_a.get("/api/v1/news").json()
        assert news_resp["count"] >= 4
        assert "market_impact_pct" in news_resp["items"][0]

        cal_resp = client_a.get("/api/v1/calendar").json()
        assert cal_resp["count"] >= 4

        csv_resp = client_a.get("/api/v1/trades/export.csv")
        assert csv_resp.status_code == 200
        assert "trade_code" in csv_resp.text

        # 7. Admin login, engine config update, manual scan, and audit log verification
        adm_login = client_admin.post(
            "/api/v1/auth/login",
            json={"email": "admin@nexvora.local", "password": "NexvoraAdmin!2026"},
        )
        assert adm_login.status_code == 200
        csrf_adm = adm_login.json()["csrf_token"]
        assert adm_login.json()["user"]["role"] == "SUPER_ADMIN"

        adm_ov = client_admin.get("/api/v1/admin/overview")
        assert adm_ov.status_code == 200

        upd_cfg = client_admin.put(
            "/api/v1/admin/engine-config",
            headers={"X-CSRF-Token": csrf_adm},
            json={"min_adx": 26.0, "min_backtest_winrate": 58.0},
        )
        assert upd_cfg.status_code == 200

        scan_res = client_admin.post("/api/v1/admin/actions/scan-now", headers={"X-CSRF-Token": csrf_adm})
        assert scan_res.status_code == 200

        logs = client_admin.get("/api/v1/admin/audit-logs").json()
        actions = [x["action"] for x in logs]
        assert "ADMIN_ACCESS_DENIED" in actions
        assert "ENGINE_CONFIG_UPDATED" in actions
        assert "LOGIN_SUCCESS" in actions

        # 8. Logout invalidates session server-side
        lo = client_a.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf_a})
        assert lo.status_code == 200
        assert client_a.get("/api/v1/auth/me").status_code == 401

    if TEST_DB.exists():
        TEST_DB.unlink()


def test_railway_production_readiness_db_url_cors_and_spa():
    from app.config import Settings
    from app.database import normalize_database_url

    assert normalize_database_url("postgres://u:p@db.railway.internal:5432/railway") == (
        "postgresql+psycopg2://u:p@db.railway.internal:5432/railway"
    )
    assert normalize_database_url("postgresql://u:p@host:5432/db") == (
        "postgresql+psycopg2://u:p@host:5432/db"
    )
    assert normalize_database_url("sqlite:///./nexvora.db") == "sqlite:///./nexvora.db"

    s = Settings(
        railway_public_domain="nexvora-hub3.up.railway.app",
        nexvora_data_mode="LIVE_WITH_DEMO_FALLBACK",
        nexvora_env="PRODUCTION",
        database_url="",
    )
    assert "https://nexvora-hub3.up.railway.app" in s.cors_origin_list
    assert s.effective_public_url == "https://nexvora-hub3.up.railway.app"
    assert s.nexvora_data_mode == "auto"
    assert s.nexvora_env == "production"
    assert s.database_url.startswith("sqlite:///")
    assert Settings(nexvora_data_mode="LIVE_ONLY").nexvora_data_mode == "live"
    assert Settings(nexvora_data_mode="DEMO_REPLAY").nexvora_data_mode == "demo"

    # Built frontend/dist should be served cleanly in single-server mode
    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert "NEXVORA" in root.text

        spa_route = client.get("/analytics")
        assert spa_route.status_code == 200
        assert "NEXVORA" in spa_route.text

        sw = client.get("/sw.js")
        assert sw.status_code == 200
        assert "no-store" in sw.headers.get("cache-control", "")

        # API 404 must NOT fall through to SPA index.html
        missing_api = client.get("/api/v1/does-not-exist")
        assert missing_api.status_code == 404

        # Path traversal attempt must never leak backend files
        traversal = client.get("/..%2F..%2Fbackend/requirements.txt")
        assert "fastapi==" not in traversal.text

