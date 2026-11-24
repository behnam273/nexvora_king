from __future__ import annotations

from typing import List, Tuple

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserSession, utcnow
from app.schemas import (
    AuthResponse,
    LoginRequest,
    PasswordChangeRequest,
    RegisterRequest,
    SessionOut,
    UserOut,
    UserProfileUpdate,
)
from app.security import (
    SESSION_COOKIE_NAME,
    clear_session_cookie,
    create_user_session,
    get_client_ip,
    get_current_session,
    get_current_user,
    hash_password,
    rate_limiter,
    verify_password,
    write_audit,
)
from app.services.realtime import realtime_hub

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _validate_password_strength(pw: str) -> None:
    if len(pw) < 10 or not any(c.isdigit() for c in pw) or not any(c.isalpha() for c in pw):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="رمز عبور باید حداقل ۱۰ کاراکتر و شامل حروف و اعداد باشد.",
        )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    ip = get_client_ip(request)
    rate_limiter.check(f"register:{ip}", limit=10, window_sec=300)
    _validate_password_strength(payload.password)

    email = payload.email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="این ایمیل قبلاً در سیستم ثبت شده است.",
        )

    user = User(
        email=email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role="USER",  # Never trust client-supplied role!
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _, csrf_token = create_user_session(db, user, request, response)
    write_audit(db, action="USER_REGISTERED", actor=user, target_type="user", target_id=str(user.id), ip_address=ip)
    return AuthResponse(user=UserOut.model_validate(user), csrf_token=csrf_token)


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    ip = get_client_ip(request)
    rate_limiter.check(f"login:{ip}", limit=15, window_sec=300)
    email = payload.email.lower().strip()
    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(payload.password, user.password_hash):
        write_audit(
            db,
            action="LOGIN_FAILED",
            outcome="DENIED",
            target_type="user",
            target_id=email,
            ip_address=ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ایمیل یا رمز عبور اشتباه است.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="حساب کاربری غیرفعال شده است. با پشتیبانی تماس بگیرید.",
        )

    if user.mfa_enabled and user.mfa_secret:
        if not payload.mfa_code or not pyotp.TOTP(user.mfa_secret).verify(payload.mfa_code.strip(), valid_window=1):
            write_audit(db, action="LOGIN_MFA_FAILED", outcome="DENIED", actor=user, ip_address=ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="کد احراز هویت دومرحله‌ای (MFA) نامعتبر یا وارد نشده است.",
            )

    _, csrf_token = create_user_session(db, user, request, response)
    write_audit(db, action="LOGIN_SUCCESS", actor=user, target_type="user", target_id=str(user.id), ip_address=ip)
    return AuthResponse(user=UserOut.model_validate(user), csrf_token=csrf_token)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    pair: Tuple[User, UserSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    user, sess = pair
    raw_token = request.cookies.get(SESSION_COOKIE_NAME) or ""
    sess.revoked_at = utcnow()
    db.commit()
    clear_session_cookie(response, request)
    await realtime_hub.disconnect_session(user.id, raw_token)
    write_audit(db, action="LOGOUT", actor=user, target_type="session", target_id=str(sess.id), ip_address=get_client_ip(request))
    return {"status": "ok", "message": "خروج با موفقیت انجام شد و نشست ابطال گردید."}


@router.get("/me", response_model=AuthResponse)
def me(pair: Tuple[User, UserSession] = Depends(get_current_session)):
    user, sess = pair
    return AuthResponse(user=UserOut.model_validate(user), csrf_token=sess.csrf_token)


@router.patch("/profile", response_model=UserOut)
def update_profile(
    payload: UserProfileUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Strictly allowlisted fields — prevents mass assignment on role / is_active
    for field in (
        "full_name",
        "timezone_pref",
        "quiet_hours_start",
        "quiet_hours_end",
        "notify_signals",
        "notify_tracking",
        "notify_high_news",
    ):
        val = getattr(payload, field)
        if val is not None:
            setattr(user, field, val)
    db.commit()
    db.refresh(user)
    write_audit(db, action="PROFILE_UPDATED", actor=user, target_type="user", target_id=str(user.id), ip_address=get_client_ip(request))
    return UserOut.model_validate(user)


@router.post("/change-password")
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    pair: Tuple[User, UserSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    user, current_sess = pair
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="رمز عبور فعلی اشتباه است.")
    _validate_password_strength(payload.new_password)

    user.password_hash = hash_password(payload.new_password)
    # Revoke all OTHER active sessions upon password change
    now = utcnow()
    other_sessions = (
        db.query(UserSession)
        .filter(UserSession.user_id == user.id, UserSession.id != current_sess.id, UserSession.revoked_at.is_(None))
        .all()
    )
    for s in other_sessions:
        s.revoked_at = now
    db.commit()
    write_audit(
        db,
        action="PASSWORD_CHANGED",
        actor=user,
        target_type="user",
        target_id=str(user.id),
        ip_address=get_client_ip(request),
        details={"revoked_other_sessions": len(other_sessions)},
    )
    return {"status": "ok", "message": "رمز عبور با موفقیت تغییر یافت و سایر نشست‌ها ابطال شدند."}


@router.get("/sessions", response_model=List[SessionOut])
def list_my_sessions(
    pair: Tuple[User, UserSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    user, current_sess = pair
    rows = (
        db.query(UserSession)
        .filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .order_by(UserSession.last_seen_at.desc())
        .all()
    )
    return [
        SessionOut(
            id=r.id,
            ip_address=r.ip_address,
            user_agent=r.user_agent,
            created_at=r.created_at,
            last_seen_at=r.last_seen_at,
            expires_at=r.expires_at,
            is_current=(r.id == current_sess.id),
        )
        for r in rows
    ]


@router.delete("/sessions/{session_id}")
def revoke_my_session(
    session_id: int,
    request: Request,
    pair: Tuple[User, UserSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    user, _ = pair
    sess = db.query(UserSession).filter(UserSession.id == session_id, UserSession.user_id == user.id).first()
    if not sess:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="نشست یافت نشد.")
    sess.revoked_at = utcnow()
    db.commit()
    write_audit(db, action="SESSION_REVOKED", actor=user, target_type="session", target_id=str(session_id), ip_address=get_client_ip(request))
    return {"status": "ok"}


@router.post("/mfa/setup")
def setup_mfa(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    secret = pyotp.random_base32()
    user.mfa_secret = secret
    db.commit()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="NEXVORA")
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/mfa/enable")
def enable_mfa(
    code: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user.mfa_secret:
        raise HTTPException(status_code=400, detail="ابتدا مراحل راه‌اندازی MFA را انجام دهید.")
    if not pyotp.TOTP(user.mfa_secret).verify(code.strip(), valid_window=1):
        raise HTTPException(status_code=400, detail="کد TOTP نامعتبر است.")
    user.mfa_enabled = True
    db.commit()
    write_audit(db, action="MFA_ENABLED", actor=user, target_type="user", target_id=str(user.id), ip_address=get_client_ip(request))
    return {"status": "ok", "mfa_enabled": True}
