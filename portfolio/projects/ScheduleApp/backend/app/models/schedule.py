"""
Event and EventAttendee model helpers.
"""
from typing import Optional


def row_to_event(row) -> Optional[dict]:
    if row is None:
        return None
    return {
        "event_id": row.event_id,
        "creator_id": row.creator_id,
        "title": row.title,
        "description": getattr(row, "description", None),
        "location": getattr(row, "location", None),
        "event_color": getattr(row, "event_color", None),
        "event_icon": getattr(row, "event_icon", None),
        "start_dt": str(row.start_dt) if row.start_dt else None,
        "end_dt": str(row.end_dt) if row.end_dt else None,
        "is_all_day": bool(getattr(row, "is_all_day", False)),
        "visibility": getattr(row, "visibility", "company"),
        "dept_code": getattr(row, "dept_code", None),
        "repeat_rule": getattr(row, "repeat_rule", None),
        "repeat_end_dt": str(row.repeat_end_dt) if getattr(row, "repeat_end_dt", None) else None,
        "is_daou_noti_enabled": bool(getattr(row, "is_daou_noti_enabled", False)),
        "version": row.version,
        "created_at": str(row.created_at) if row.created_at else None,
        "updated_at": str(row.updated_at) if row.updated_at else None,
        "creator_name": getattr(row, "creator_name", None),
    }


def row_to_attendee(row) -> Optional[dict]:
    if row is None:
        return None
    return {
        "event_id": row.event_id,
        "apwid": row.apwid,
        "status": row.status,
        "responded_at": str(row.responded_at) if getattr(row, "responded_at", None) else None,
        "name": getattr(row, "Uname", None),
        "dept_code": getattr(row, "Dept_Nm", None),
        "alimtalk_sent": getattr(row, "alimtalk_sent", "N"),
        "alimtalk_sent_at": str(row.alimtalk_sent_at) if getattr(row, "alimtalk_sent_at", None) else None,
    }
