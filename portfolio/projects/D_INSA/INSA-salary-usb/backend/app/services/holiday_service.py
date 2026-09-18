"""Holiday service + business-day calculation (PHASE 15).

Korean public holidays are stored in `insa_holiday`. Solar holidays are
`is_recurring=True` (observed every year on the same month-day). Lunar
holidays (Seollal, Chuseok) are entered per-year with `is_recurring=False`.

`business_days(start, end)` returns calendar days between start and end
inclusive, minus weekends and holidays.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import and_, extract, or_
from sqlalchemy.orm import Session

from app.db.models import Holiday


class HolidayError(Exception):
    pass


class HolidayNotFound(HolidayError):
    pass


class HolidayDuplicate(HolidayError):
    pass


def list_holidays(db: Session, year: Optional[int] = None) -> list[Holiday]:
    q = db.query(Holiday)
    if year is not None:
        q = q.filter(
            or_(
                Holiday.is_recurring.is_(True),
                extract("year", Holiday.date) == year,
            )
        )
    return q.order_by(Holiday.date).all()


def create_holiday(
    db: Session, *, on: date, name: str, is_recurring: bool = False
) -> Holiday:
    dup = db.query(Holiday).filter(Holiday.date == on).first()
    if dup is not None:
        raise HolidayDuplicate(f"holiday already exists on {on}")
    h = Holiday(date=on, name=name, is_recurring=is_recurring)
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


def delete_holiday(db: Session, holiday_id: int) -> None:
    h = db.query(Holiday).filter(Holiday.id == holiday_id).first()
    if h is None:
        raise HolidayNotFound(f"holiday {holiday_id} not found")
    db.delete(h)
    db.commit()


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5  # 5=Sat, 6=Sun


def _holiday_dates_for_year(db: Session, year: int) -> set[date]:
    """All holiday dates falling in `year`, expanding recurring ones."""
    rows = db.query(Holiday).all()
    result: set[date] = set()
    for h in rows:
        if h.is_recurring:
            try:
                result.add(date(year, h.date.month, h.date.day))
            except ValueError:
                continue  # Feb 29 on non-leap — skip
        elif h.date.year == year:
            result.add(h.date)
    return result


def is_holiday(db: Session, d: date) -> bool:
    cache = _holiday_dates_for_year(db, d.year)
    return d in cache


def business_days(db: Session, start: date, end: date) -> int:
    """Count weekdays between `start` and `end` inclusive, excluding holidays.

    Returns 0 if `start > end`.
    """
    if start > end:
        return 0

    years = set()
    y = start.year
    while y <= end.year:
        years.add(y)
        y += 1
    holiday_set: set[date] = set()
    for yr in years:
        holiday_set |= _holiday_dates_for_year(db, yr)

    count = 0
    current = start
    while current <= end:
        if not is_weekend(current) and current not in holiday_set:
            count += 1
        current += timedelta(days=1)
    return count
