from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
from datetime import date
from pathlib import Path

from notice_app.business_day import CalendarOverrides, last_business_day
from notice_app.config import AppConfig
from notice_app.history import SendHistory
from notice_app.sms import SmsClient, SmsError, mask_phone, normalize_mobile_phone


ROOT = Path(__file__).resolve().parent
PRODUCTION_DEPARTMENTS = ("sim", "yj", "ju", "jip")
MAX_PRODUCTION_RECIPIENTS = 100
AUTHORIZED_TEST_PHONE_SHA256 = "64a9fe629dfcee8e71f1eae62a979d9b29dafb5d613a38b34622bdc955590189"


def configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format=formatter._fmt, handlers=handlers, force=True)


def make_client(config: AppConfig) -> SmsClient:
    return SmsClient(
        server=config.db_server,
        database=config.db_name,
        username=config.db_user,
        password=config.db_password,
        driver=config.odbc_driver,
        encrypt=config.db_encrypt,
        trust_server_certificate=config.db_trust_server_certificate,
        call_from=config.call_from,
        connection_timeout_seconds=config.connection_timeout_seconds,
        query_timeout_seconds=config.query_timeout_seconds,
    )


def load_message(config: AppConfig) -> str:
    message = config.message_path.read_text(encoding="utf-8").strip()
    if not message:
        raise ValueError("발송 문구가 비어 있습니다.")
    return message


def load_subject(config: AppConfig) -> str:
    subject = config.subject_path.read_text(encoding="utf-8").strip()
    if not subject:
        raise ValueError("문자 제목이 비어 있습니다.")
    return subject


def history_key(phone: str) -> str:
    return hashlib.sha256(phone.encode("ascii")).hexdigest()


def authorized_test_phone() -> str:
    value = os.environ.get("SMS_TEST_PHONE", "")
    phone = normalize_mobile_phone(value)
    if history_key(phone) != AUTHORIZED_TEST_PHONE_SHA256:
        raise ValueError("승인된 테스트 번호가 아닙니다.")
    return phone


def run_scheduled(config: AppConfig, today: date) -> int:
    overrides = CalendarOverrides.load(config.calendar_overrides_path)
    target = last_business_day(today.year, today.month, overrides)
    if today < target:
        logging.info("발송일 아님: 오늘=%s, 이번 달 발송일=%s", today, target)
        return 0

    notice_month = today.strftime("%Y-%m")
    message = load_message(config)
    subject = load_subject(config)
    failures = 0
    client = make_client(config)
    try:
        recipients = client.load_recipient_phones(
            config.recipient_db_name,
            PRODUCTION_DEPARTMENTS,
        )
        if not recipients:
            raise SmsError("운영 수신번호가 없어 발송을 중단했습니다.")
        if len(recipients) > MAX_PRODUCTION_RECIPIENTS:
            raise SmsError("운영 수신자가 안전 한도를 초과하여 발송을 중단했습니다.")
        logging.info("운영 수신자 조회 완료: count=%d", len(recipients))

        with SendHistory(config.state_db_path) as history:
            pending = [
                phone
                for phone in recipients
                if not history.was_sent(notice_month, history_key(phone))
            ]
            if not pending:
                logging.info("이미 모든 수신자에게 발송 완료: %s", notice_month)
                return 0

            for recipient in pending:
                try:
                    client.send_mms(recipient, subject, message)
                    history.mark_sent(notice_month, history_key(recipient))
                    logging.info("문자 큐 등록 성공: recipient=%s", mask_phone(recipient))
                except SmsError as exc:
                    failures += 1
                    logging.error(
                        "문자 큐 등록 실패: recipient=%s, reason=%s",
                        mask_phone(recipient),
                        exc,
                    )
    finally:
        client.close()

    logging.info("발송 종료: 성공=%d, 실패=%d", len(pending) - failures, failures)
    return 1 if failures else 0


def run_test_send(config: AppConfig, recipients: tuple[str, ...]) -> int:
    message = load_message(config)
    subject = load_subject(config)
    client = make_client(config)
    failures = 0
    try:
        for recipient in recipients:
            try:
                client.send_mms(recipient, subject, message)
                logging.info("수동 문자 큐 등록 성공: recipient=%s", mask_phone(recipient))
            except SmsError as exc:
                failures += 1
                logging.error(
                    "수동 문자 큐 등록 실패: recipient=%s, reason=%s",
                    mask_phone(recipient),
                    exc,
                )
    finally:
        client.close()
    return 1 if failures else 0


def check_date(config: AppConfig, value: date) -> int:
    overrides = CalendarOverrides.load(config.calendar_overrides_path)
    target = last_business_day(value.year, value.month, overrides)
    print(f"{value:%Y-%m} 마지막 영업일: {target}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="개별부담비용 이의신청 문자 발송")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="예약 발송일 때 운영 수신자에게 발송")
    subparsers.add_parser("test-send", help="승인된 테스트 번호에만 원문을 수동 발송")
    check_parser = subparsers.add_parser("check-date", help="지정 월의 마지막 영업일 확인")
    check_parser.add_argument("month", help="YYYY-MM")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    require_recipients = args.command == "run"
    require_credentials = args.command in ("run", "test-send")
    try:
        config = AppConfig.load(
            ROOT,
            require_recipients=require_recipients,
            require_credentials=require_credentials,
        )
        configure_logging(config.log_path)
        if args.command == "run":
            return run_scheduled(config, date.today())
        if args.command == "test-send":
            return run_test_send(config, (authorized_test_phone(),))
        value = date.fromisoformat(args.month + "-01")
        return check_date(config, value)
    except (SmsError, OSError, ValueError) as exc:
        logging.error("실행 실패: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
