from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db.models import Notification


def create(
    db: Session,
    *,
    user_id: int,
    type: str,
    title: str,
    message: Optional[str] = None,
    link: Optional[str] = None,
) -> Notification:
    """Insert a notification row. Caller controls flush/commit timing."""
    note = Notification(
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        link=link,
        is_read=False,
    )
    db.add(note)
    db.flush()
    return note


def create_many(
    db: Session,
    *,
    user_ids: list[int],
    type: str,
    title: str,
    message: Optional[str] = None,
    link: Optional[str] = None,
) -> list[Notification]:
    notes = [
        Notification(
            user_id=uid,
            type=type,
            title=title,
            message=message,
            link=link,
            is_read=False,
        )
        for uid in user_ids
    ]
    if notes:
        db.add_all(notes)
        db.flush()
    return notes


def list_mine(db: Session, user_id: int, *, limit: int = 20, only_unread: bool = False) -> dict:
    base = db.query(Notification).filter(Notification.user_id == user_id)
    if only_unread:
        base = base.filter(Notification.is_read.is_(False))
    total = base.count()
    unread = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read.is_(False))
        .count()
    )
    items = (
        base.order_by(desc(Notification.created_at), desc(Notification.id))
        .limit(limit)
        .all()
    )
    return {"items": items, "total": total, "unread": unread}


def unread_count(db: Session, user_id: int) -> int:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read.is_(False))
        .count()
    )


def mark_read(db: Session, user_id: int, notification_id: int) -> Optional[Notification]:
    note = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if not note:
        return None
    if not note.is_read:
        note.is_read = True
        db.flush()
    return note


def mark_all_read(db: Session, user_id: int) -> int:
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read.is_(False))
        .update({Notification.is_read: True}, synchronize_session=False)
    )
    db.flush()
    return updated
