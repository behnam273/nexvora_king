from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Notification, User
from app.schemas import NotificationOut
from app.security import get_current_user

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("", response_model=List[NotificationOut])
def list_my_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        q = q.filter(Notification.is_read == False)  # noqa: E712
    rows = q.order_by(Notification.created_at.desc()).limit(limit).all()
    return [NotificationOut.model_validate(r) for r in rows]


@router.post("/{notif_id}/read")
def mark_notification_read(
    notif_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Strictly scoped to user.id — prevents BOLA/IDOR
    row = db.query(Notification).filter(Notification.id == notif_id, Notification.user_id == user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="اعلان یافت نشد.")
    row.is_read = True
    db.commit()
    return {"status": "ok"}


@router.post("/read-all")
def mark_all_read(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).update({"is_read": True})  # noqa: E712
    db.commit()
    return {"status": "ok"}
