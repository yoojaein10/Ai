import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app


class FakeClient:
    def __init__(self) -> None:
        self.close_count = 0
        self.recipient_query_count = 0
        self.sent: list[tuple[str, str, str]] = []

    def load_recipient_phones(
        self,
        _source_database: str,
        _departments: tuple[str, ...],
    ) -> tuple[str, ...]:
        self.recipient_query_count += 1
        return ('010-0000-0000',)

    def send_mms(self, recipient: str, subject: str, message: str) -> None:
        self.sent.append((recipient, subject, message))

    def close(self) -> None:
        self.close_count += 1


class ScheduledRunTests(unittest.TestCase):
    def make_config(self, temp_dir: str) -> SimpleNamespace:
        root = Path(temp_dir)
        message_path = root / "message.txt"
        message_path.write_text("테스트 공지", encoding="utf-8")
        subject_path = root / "subject.txt"
        subject_path.write_text("테스트 제목", encoding="utf-8")
        overrides_path = root / "calendar_overrides.json"
        overrides_path.write_text(
            '{"additional_holidays": [], "forced_workdays": []}',
            encoding="utf-8",
        )
        return SimpleNamespace(
            recipient_db_name="source_db",
            message_path=message_path,
            subject_path=subject_path,
            calendar_overrides_path=overrides_path,
            state_db_path=root / "history.db",
        )

    def test_skips_before_last_business_day(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.make_config(temp_dir)
            client = FakeClient()
            with patch("app.make_client", return_value=client):
                self.assertEqual(app.run_scheduled(config, date(2026, 5, 28)), 0)
            self.assertEqual(client.close_count, 0)
            self.assertEqual(client.sent, [])

    def test_catches_up_after_target_and_does_not_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.make_config(temp_dir)
            client = FakeClient()
            with patch("app.make_client", return_value=client):
                self.assertEqual(app.run_scheduled(config, date(2026, 5, 30)), 0)
                self.assertEqual(app.run_scheduled(config, date(2026, 5, 30)), 0)
            self.assertEqual(client.close_count, 2)
            self.assertEqual(client.recipient_query_count, 2)
            self.assertEqual(len(client.sent), 1)
            self.assertEqual(client.sent[0][0], '010-0000-0000')

    def test_manual_send_uses_exact_subject_and_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.make_config(temp_dir)
            client = FakeClient()
            with patch("app.make_client", return_value=client):
                self.assertEqual(app.run_test_send(config, ('010-0000-0000',)), 0)
            self.assertEqual(
                client.sent,
                [('010-0000-0000', "테스트 제목", "테스트 공지")],
            )
            self.assertEqual(client.close_count, 1)
            self.assertEqual(client.recipient_query_count, 0)

    def test_unapproved_test_number_is_rejected(self) -> None:
        with patch.dict("os.environ", {"SMS_TEST_PHONE": '010-0000-0000'}, clear=False):
            with self.assertRaises(ValueError):
                app.authorized_test_phone()


if __name__ == "__main__":
    unittest.main()
