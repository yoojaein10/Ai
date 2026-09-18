"""메일 발송 — 계정별원장을 지사에 보내는 용도 (2026-08-21).

이 프로젝트에는 메일 기능이 없었다. 알림톡은 비즈뿌리오 DB(BIZ_MSG)에 넣는
방식이라 메일에는 못 쓴다. 그래서 표준 SMTP 를 쓴다.

**설정이 하나라도 비면 보내지 않는다(fail-closed).** 비밀번호는 .env 에만 둔다 —
코드·저장소에 넣지 않는다.

지사 주소가 정리되기 전이라, LEDGER_MAIL_TEST_TO 가 설정돼 있으면 **누구에게
보내든 그 주소로만** 간다. 실수로 지사에 나가는 것을 막는 안전장치다. 이때
참조(CC)도 함께 지운다 — 참조만 지사로 나가면 막은 의미가 없다.
"""

import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

from app.config import get_settings


class MailError(RuntimeError):
    pass


def _join(addresses: "str | list[str]") -> str:
    """주소 여럿을 메일 헤더 한 줄로 — 빈 값은 버린다."""
    if isinstance(addresses, str):
        addresses = [addresses]
    return ", ".join(a.strip() for a in addresses if a and a.strip())


def resolve_recipient(requested: str) -> "tuple[str, bool]":
    """실제로 보낼 주소와 '테스트로 돌렸는지'를 돌려준다.

    테스트 수신자가 설정돼 있으면 요청한 주소를 무시하고 거기로만 보낸다.
    """
    settings = get_settings()
    test_to = (settings.ledger_mail_test_to or "").strip()
    if test_to:
        return test_to, True
    address = (requested or "").strip()
    if not address:
        raise MailError("받는 사람이 없습니다.")
    return address, False


def send_html_mail(
    to: "str | list[str]",
    subject: str,
    html: str,
    text_fallback: str = "",
    cc: "list[str] | None" = None,
) -> "dict[str, Any]":
    """HTML 메일 한 통. 실제로 보낸 주소와 테스트 여부를 돌려준다.

    받는사람·참조는 여럿일 수 있다 — 지사 담당자가 한 명이 아니다.
    """
    settings = get_settings()
    if not settings.is_smtp_configured:
        raise MailError(
            "메일 설정(SMTP_HOST·SMTP_USER·SMTP_PASSWORD)이 없습니다. "
            ".env 에 넣어 주세요."
        )
    address, test_mode = resolve_recipient(_join(to))
    # 테스트로 돌린 건이면 참조도 지운다 — 참조만 지사로 나가면 막은 의미가 없다.
    cc_line = "" if test_mode else _join(cc or [])

    message = EmailMessage()
    message["Subject"] = subject
    sender = (settings.smtp_from or settings.smtp_user).strip()
    message["From"] = formataddr((settings.smtp_from_name, sender))
    message["To"] = address
    if cc_line:
        message["Cc"] = cc_line
    message.set_content(text_fallback or "이 메일은 HTML 로 되어 있습니다.")
    message.add_alternative(html, subtype="html")

    try:
        if settings.smtp_use_ssl:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
        with server:
            if settings.smtp_use_tls and not settings.smtp_use_ssl:
                server.starttls()
            server.login(settings.smtp_user, settings.smtp_password.get_secret_value())
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(f"메일 로그인에 실패했습니다 — {exc.smtp_code}") from exc
    except OSError as exc:
        raise MailError(f"메일 서버에 연결하지 못했습니다 — {exc}") from exc

    return {"to": address, "cc": cc_line, "test_mode": test_mode, "subject": subject}
