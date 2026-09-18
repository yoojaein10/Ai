from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import holidays


@dataclass(frozen=True)
class CalendarOverrides:
    additional_holidays: frozenset[date] = frozenset()
    forced_workdays: frozenset[date] = frozenset()

    @classmethod
    def load(cls, path: Path) -> "CalendarOverrides":
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        additional = frozenset(date.fromisoformat(value) for value in raw.get("additional_holidays", []))
        forced = frozenset(date.fromisoformat(value) for value in raw.get("forced_workdays", []))
        overlap = additional & forced
        if overlap:
            raise ValueError(f"공휴일과 강제 영업일이 중복되었습니다: {sorted(overlap)}")
        return cls(additional, forced)


def is_business_day(day: date, overrides: CalendarOverrides) -> bool:
    if day in overrides.forced_workdays:
        return True
    if day.weekday() >= 5 or day in overrides.additional_holidays:
        return False
    korean_holidays = holidays.country_holidays("KR", years=[day.year], language="ko")
    return day not in korean_holidays


def last_business_day(year: int, month: int, overrides: CalendarOverrides) -> date:
    day = date(year, month, calendar.monthrange(year, month)[1])
    while not is_business_day(day, overrides):
        day -= timedelta(days=1)
    return day

