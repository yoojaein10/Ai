"""Amaranth 전표출력조회 데이터를 로컬에 보관하는 읽기 캐시."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VoucherCache(Base):
    __tablename__ = "a10_voucher_cache"
    __table_args__ = (
        UniqueConstraint(
            "voucher_date", "voucher_no", "line_no", "division_code",
            name="uq_a10_voucher_cache_line",
        ),
        # 입금·미수금 CTE가 raw_json이 든 본체를 훑지 않도록 하는 커버링 인덱스.
        # 기존 DB에는 2026-07-21 수동 CREATE INDEX로 반영됨 (create_all은 기존 테이블을 건드리지 않는다).
        Index(
            "ix_a10_voucher_cache_acct_mgmt_cover",
            "account_code", "management_no",
            mssql_include=["voucher_date", "voucher_no", "division_code", "debit_credit", "amount"],
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    voucher_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    voucher_no: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    line_no: Mapped[str] = mapped_column(String(10), nullable=False)
    division_code: Mapped[str] = mapped_column(String(4), nullable=False)
    # 공식 문서는 ctNb 35자이나 실제 데이터에는 장문 관리값이 존재한다.
    management_no: Mapped[str | None] = mapped_column(String(500), index=True)
    debit_credit: Mapped[str | None] = mapped_column(String(1))
    account_code: Mapped[str | None] = mapped_column(String(8), index=True)
    account_name: Mapped[str | None] = mapped_column(String(100))
    partner_code: Mapped[str | None] = mapped_column(String(10))
    partner_name: Mapped[str | None] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    remark: Mapped[str | None] = mapped_column(String(500))
    document_status: Mapped[str | None] = mapped_column(String(10))
    raw_json: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )
