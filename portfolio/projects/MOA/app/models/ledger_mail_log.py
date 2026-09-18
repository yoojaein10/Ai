"""계정별원장 메일 발송 로그 (a10_ledger_mail_log).

'그 지사에 언제 무엇을 보냈나' 를 답하기 위한 표다. 지사가 "못 받았다"고 하면
여기만 보면 된다. **성공·실패를 모두 남긴다** — 실패만 조용히 사라지면 안 보낸
지사를 보낸 줄 안다.

한 통(계정 하나)이 한 행이다. 받는사람·참조는 실제로 메일 헤더에 넣은 주소를
그대로 적는다(테스트 수신자로 바뀌었으면 바뀐 주소가 남는다 — test_mode='Y').
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Date, DateTime, Index, Integer, Numeric, String, Unicode, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LedgerMailLog(Base):
    __tablename__ = "a10_ledger_mail_log"
    __table_args__ = (
        Index("ix_a10_ledger_mail_log_sent_at", "sent_at"),
        Index("ix_a10_ledger_mail_log_account", "account_code", "sent_at"),
    )

    # BigInteger 그대로 두면 **sqlite 에서 자동증가가 안 된다** — sqlite 는
    # INTEGER PRIMARY KEY 에만 rowid 를 붙여 주고 BIGINT 에는 안 붙인다.
    # 운영(MSSQL)은 BIGINT IDENTITY 로 나가고, 시험용 sqlite 에서만 INTEGER 가 된다.
    log_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True, autoincrement=True,
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    account_code: Mapped[str] = mapped_column(String(20), nullable=False)
    account_name: Mapped[str | None] = mapped_column(Unicode(60))
    # 보낸 원장의 기간 — 어느 날짜 원장을 보냈는지가 문의의 핵심이다.
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    to_email: Mapped[str | None] = mapped_column(Unicode(400))
    cc_email: Mapped[str | None] = mapped_column(Unicode(400))
    subject: Mapped[str | None] = mapped_column(Unicode(300))
    # 'SENT' 보냄 · 'FAILED' 실패
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    fail_reason: Mapped[str | None] = mapped_column(Unicode(400))
    # 테스트 수신자(LEDGER_MAIL_TEST_TO)로 돌려보낸 건인지 — 지사는 못 받은 것이다.
    test_mode: Mapped[str] = mapped_column(String(1), nullable=False, server_default="N")
    # 보낸 내용을 나중에 대조하려고 요약만 남긴다(본문은 안 남긴다 — 용량).
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    closing_balance: Mapped[float | None] = mapped_column(Numeric(19, 4))
    requested_by_usr_seq: Mapped[int | None] = mapped_column(BigInteger)
