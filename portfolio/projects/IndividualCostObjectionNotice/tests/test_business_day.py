import unittest
from datetime import date

from notice_app.business_day import CalendarOverrides, last_business_day


class LastBusinessDayTests(unittest.TestCase):
    def test_calendar_month_end_weekday(self) -> None:
        self.assertEqual(
            last_business_day(2026, 8, CalendarOverrides()),
            date(2026, 8, 31),
        )

    def test_weekend_moves_to_friday(self) -> None:
        self.assertEqual(
            last_business_day(2026, 5, CalendarOverrides()),
            date(2026, 5, 29),
        )

    def test_chuseok_and_weekend_move_backward(self) -> None:
        self.assertEqual(
            last_business_day(2023, 9, CalendarOverrides()),
            date(2023, 9, 27),
        )

    def test_additional_company_holiday(self) -> None:
        overrides = CalendarOverrides(additional_holidays=frozenset({date(2026, 8, 31)}))
        self.assertEqual(last_business_day(2026, 8, overrides), date(2026, 8, 28))


if __name__ == "__main__":
    unittest.main()

