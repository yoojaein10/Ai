import unittest

from notice_app.sms import SmsClient, SmsError, mask_phone, normalize_mobile_phone


class SmsValidationTests(unittest.TestCase):
    def test_mobile_phone_is_normalized(self) -> None:
        self.assertEqual(normalize_mobile_phone("010-0000-0000"), '010-0000-0000')

    def test_non_mobile_phone_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_mobile_phone("02-000-0000")

    def test_phone_is_masked_for_logs(self) -> None:
        self.assertEqual(mask_phone('010-0000-0000'), "010****0000")

    def test_subject_and_body_fit_stored_procedure_limits(self) -> None:
        SmsClient._validate_text("개별부담비용 이의신청 안내", "안내 본문")

    def test_oversized_body_is_rejected(self) -> None:
        with self.assertRaises(SmsError):
            SmsClient._validate_text("제목", "가" * 1001)


if __name__ == "__main__":
    unittest.main()
