from __future__ import annotations

import hashlib
import ipaddress
import json
import secrets
import socket
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, Optional, Tuple
from urllib.parse import urlparse

import bleach
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import AuditLog, User, UserSession, utcnow

# Argon2id password hasher (OWASP recommended parameters)
_ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)

SESSION_COOKIE_NAME = "nexvora_session"
CSRF_HEADER_NAME = "x-csrf-token"

# Role hierarchy
ROLE_LEVEL = {
    "USER": 1,
    "PREMIUM": 2,
    "ADMIN": 3,
    "SUPER_ADMIN": 4,
}


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def hash_session_token(raw_token: str) -> str:
    settings = get_settings()
    return hashlib.sha256(f"{settings.secret_key}:{raw_token}".encode("utf-8")).hexdigest()


import re


def sanitize_text(text: str) -> str:
    """Strip script/style blocks and all HTML tags from untrusted external news/feed content."""
    if not text:
        return ""
    no_blocks = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    cleaned = bleach.clean(no_blocks, tags=[], attributes={}, strip=True)
    return " ".join(cleaned.split())


def validate_external_url(url: str, allowed_hosts: Optional[set[str]] = None) -> bool:
    """
    SSRF protection for external news/data fetchers:
    - Only http/https schemes
    - Blocks localhost, private/loopback/link-local/reserved IP ranges
    - Optional host allowlist
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower().strip(".")
        if not hostname:
            return False
        if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or hostname.endswith(".local"):
            return False
        if allowed_hosts is not None:
            if not any(hostname == h or hostname.endswith("." + h) for h in allowed_hosts):
                return False
        # Check literal IP first
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
            return True
        except ValueError:
            pass
        # Attempt DNS check if resolvable; if DNS fails (offline sandbox), allowlisted domains still pass syntax check
        try:
            infos = socket.getaddrinfo(hostname, None)
            for info in infos:
                ip = ipaddress.ip_address(info[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                    return False
        except OSError:
            # DNS might be unavailable in sandbox; rely on allowlist/hostname rules
            pass
        return True
    except Exception:
        return False


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._buckets: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_sec: int) -> None:
        now = time.monotonic()
        dq = self._buckets[key]
        cutoff = now - window_sec
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="تعداد درخواست‌ها بیش از حد مجاز است. لطفاً کمی بعد تلاش کنید.",
            )
        dq.append(now)

    def reset(self) -> None:
        self._buckets.clear()


rate_limiter = SlidingWindowRateLimiter()


def get_client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    if request.client:
        return request.client.host[:64]
    return "unknown"


def write_audit(
    db: Session,
    action: str,
    outcome: str = "SUCCESS",
    actor: Optional[User] = None,
    target_type: str = "",
    target_id: str = "",
    ip_address: str = "",
    details: Optional[dict] = None,
    correlation_id: Optional[str] = None,
) -> None:
    # Never log sensitive keys
    safe_details = {}
    if details:
        for k, v in details.items():
            kl = k.lower()
            if any(bad in kl for bad in ("password", "secret", "token", "key", "cookie")):
                safe_details[k] = "[REDACTED]"
            else:
                safe_details[k] = v
    row = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else "system",
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        outcome=outcome,
        ip_address=ip_address,
        correlation_id=correlation_id or uuid.uuid4().hex[:16],
        details_json=json.dumps(safe_details, ensure_ascii=False),
    )
    db.add(row)
    db.commit()


def _partition_preview_cookie(response: Response) -> None:
    # CHIPS lets supporting browsers retain an HttpOnly session in an embedded
    # preview even when ordinary third-party cookies are blocked. Starlette on
    # Python < 3.14 has no partitioned argument, so append the attribute here.
    for i in range(len(response.raw_headers) - 1, -1, -1):
        key, value = response.raw_headers[i]
        if key.lower() == b"set-cookie" and value.startswith(f"{SESSION_COOKIE_NAME}=".encode()):
            response.raw_headers[i] = (key, value + b"; Partitioned")
            break


def create_user_session(
    db: Session,
    user: User,
    request: Request,
    response: Response,
) -> Tuple[UserSession, str]:
    settings = get_settings()
    raw_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    now = utcnow()
    sess = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        csrf_token=csrf_token,
        ip_address=get_client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:250],
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)

    fwd_proto = (request.headers.get("x-forwarded-proto") or "").lower()
    host_hdr = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").lower()
    is_iframe_preview = ".e2b.app" in host_hdr
    is_https = fwd_proto == "https" or request.url.scheme == "https" or is_iframe_preview

    cookie_secure = True if (is_https or settings.nexvora_env == "production") else settings.cookie_secure
    if is_iframe_preview:
        cookie_samesite = "none"
    else:
        cookie_samesite = settings.cookie_samesite

    if is_iframe_preview:
        # Remove any legacy non-partitioned cookie with the same name so it
        # cannot shadow the new session when both are sent by the browser.
        response.delete_cookie(key=SESSION_COOKIE_NAME, path="/", httponly=True, secure=True, samesite="none")

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )
    if is_iframe_preview:
        _partition_preview_cookie(response)
    return sess, csrf_token


def clear_session_cookie(response: Response, request: Optional[Request] = None) -> None:
    settings = get_settings()
    is_iframe_preview = False
    is_https = False
    if request is not None:
        fwd_proto = (request.headers.get("x-forwarded-proto") or "").lower()
        host_hdr = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").lower()
        is_iframe_preview = ".e2b.app" in host_hdr
        is_https = fwd_proto == "https" or request.url.scheme == "https" or is_iframe_preview

    cookie_secure = True if (is_https or settings.nexvora_env == "production") else settings.cookie_secure
    cookie_samesite = "none" if is_iframe_preview else settings.cookie_samesite
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
    )
    if is_iframe_preview:
        _partition_preview_cookie(response)


def _as_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_session_from_token(db: Session, raw_token: Optional[str]) -> Optional[Tuple[User, UserSession]]:
    if not raw_token:
        return None
    settings = get_settings()
    token_hash = hash_session_token(raw_token)
    sess = db.query(UserSession).filter(UserSession.token_hash == token_hash).first()
    if not sess or sess.revoked_at is not None:
        return None
    now = utcnow()
    if _as_aware_utc(sess.expires_at) <= now:
        sess.revoked_at = now
        db.commit()
        return None
    idle_limit = timedelta(minutes=settings.session_idle_minutes)
    if now - _as_aware_utc(sess.last_seen_at) > idle_limit:
        sess.revoked_at = now
        db.commit()
        return None
    user = db.query(User).filter(User.id == sess.user_id).first()
    if not user or not user.is_active:
        return None
    sess.last_seen_at = now
    db.commit()
    return user, sess


def get_current_session(
    request: Request,
    db: Session = Depends(get_db),
) -> Tuple[User, UserSession]:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    resolved = resolve_session_from_token(db, raw_token)
    if not resolved:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="نشست کاربری معتبر نیست یا منقضی شده است. لطفاً دوباره وارد شوید.",
        )
    user, sess = resolved
    # CSRF check for state-changing requests
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        csrf_header = request.headers.get(CSRF_HEADER_NAME)
        if not csrf_header or not secrets.compare_digest(csrf_header, sess.csrf_token):
            write_audit(
                db,
                action="CSRF_CHECK_FAILED",
                outcome="DENIED",
                actor=user,
                ip_address=get_client_ip(request),
                details={"path": request.url.path, "method": request.method},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="توکن امنیتی CSRF نامعتبر است.",
            )
    return user, sess


def get_current_user(
    pair: Tuple[User, UserSession] = Depends(get_current_session),
) -> User:
    return pair[0]


def require_admin(
    request: Request,
    pair: Tuple[User, UserSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> User:
    user, _ = pair
    if ROLE_LEVEL.get(user.role, 0) < ROLE_LEVEL["ADMIN"]:
        write_audit(
            db,
            action="ADMIN_ACCESS_DENIED",
            outcome="DENIED",
            actor=user,
            ip_address=get_client_ip(request),
            details={"path": request.url.path, "role": user.role},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="دسترسی به این بخش فقط برای مدیران سیستم مجاز است.",
        )
    return user
