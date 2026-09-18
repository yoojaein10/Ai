import tempfile
import unittest
from pathlib import Path

from notice_app.history import SendHistory


class SendHistoryTests(unittest.TestCase):
    def test_records_each_recipient_once_per_month(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.db"
            with SendHistory(path) as history:
                self.assertFalse(history.was_sent("2026-08", "t_5000"))
                history.mark_sent("2026-08", "t_5000")
                history.mark_sent("2026-08", "t_5000")
                self.assertTrue(history.was_sent("2026-08", "t_5000"))
                self.assertFalse(history.was_sent("2026-09", "t_5000"))


if __name__ == "__main__":
    unittest.main()

