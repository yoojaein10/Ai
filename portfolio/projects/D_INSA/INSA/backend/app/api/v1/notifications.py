"""API routes for in-app notifications."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.notification import NotificationListOut, NotificationOut, UnreadCountOut
from app.services import notification as svc

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/me", response_model=NotificationListOut)
def my_notifications(
    limit: int = Query(20, ge=1, le=100),
    only_unread: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return svc.list_mine(db, current_user.id, limit=limit, only_unread=only_unread)


@router.get("/unread-count", response_model=UnreadCountOut)
def my_unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return UnreadCountOut(unread=svc.unread_count(db, current_user.id))


@router.post("/{notification_id}/read", response_model=NotificationOut)
def read_one(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    note = svc.mark_read(db, current_user.id, notification_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return note


@router.post("/read-all", response_model=UnreadCountOut)
def read_all(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc.mark_all_read(db, current_user.id)
    return UnreadCountOut(unread=0)
