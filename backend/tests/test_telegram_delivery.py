"""Telegram channel hardening: throttling must not silently drop a signal."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from app.services import telegram_bot as tb  # noqa: E402


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def test_rate_limit_is_retried_and_eventually_succeeds(monkeypatch, tmp_path):
    """A 429 from Telegram must not lose the signal."""
    calls = {"n": 0}

    def fake_post(self, url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp(429, {"ok": False, "parameters": {"retry_after": 1}})
        return _Resp(200, {"ok": True, "result": {"message_id": 4242}})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(tb.time, "sleep", lambda *_: None)
    recorded = []
    monkeypatch.setattr(tb, "_record_telegram_health", lambda *a, **k: recorded.append(a))
    monkeypatch.setattr(tb, "write_audit", lambda *a, **k: None)

    msg_id = tb._post_with_retry(None, url="https://api.telegram.org/botX/sendMessage", json_payload={"a": 1})
    assert msg_id == "4242"
    assert calls["n"] == 2


def test_auth_error_is_not_retried_and_is_recorded(monkeypatch):
    """Bad token / wrong chat id are config errors: fail fast with the real reason."""
    calls = {"n": 0}

    def fake_post(self, url, **kwargs):
        calls["n"] += 1
        return _Resp(400, {"ok": False, "description": "Bad Request: chat not found"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    audits = []
    monkeypatch.setattr(tb, "_record_telegram_health", lambda *a, **k: None)
    monkeypatch.setattr(tb, "write_audit", lambda *a, **k: audits.append(k))

    assert tb._post_with_retry(None, url="https://api.telegram.org/botX/sendMessage", json_payload={}) is None
    assert calls["n"] == 1
    assert audits and audits[0]["outcome"] == "FAILURE"
    assert "chat not found" in str(audits[0]["details"])


def test_transient_5xx_is_retried_then_gives_up(monkeypatch):
    calls = {"n": 0}

    def fake_post(self, url, **kwargs):
        calls["n"] += 1
        return _Resp(502, {"ok": False})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(tb.time, "sleep", lambda *_: None)
    monkeypatch.setattr(tb, "_record_telegram_health", lambda *a, **k: None)
    monkeypatch.setattr(tb, "write_audit", lambda *a, **k: None)

    assert tb._post_with_retry(None, url="https://api.telegram.org/botX/sendMessage", json_payload={}) is None
    assert calls["n"] == tb._TG_MAX_ATTEMPTS
