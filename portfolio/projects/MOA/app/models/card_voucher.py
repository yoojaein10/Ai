"""법인카드 전표 초안 — 엑셀에서 확정한 분개를 아마란스로 보내기 전까지 보관한다.

status: D 초안(아마란스 미전송) / S 전송성공 / F 전송실패
        / X 아마란스에서 삭제 확인(동기화가 전환, 담긴 건은 지워져 재확정 가능)
전송 취소는 아마란스에서 직접 삭제한다(이 테이블은 전송 이력만 남긴다).
삭제는 MOA로 신호가 오지 않으므로 화면 로드 때 api11A16과 대조해 따라잡는다.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CardVoucher(Base):
    """전표 1장 (하루치 묶음 또는 한 번에 확정한 묶음)."""

    __tablename__ = "a10_card_voucher"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    voucher_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    division_code: Mapped[str] = mapped_column(String(4), nullable=False)
    menu_sq: Mapped[int] = mapped_column(nullable=False)  # 아마란스 작성번호
    item_count: Mapped[int] = mapped_column(nullable=False, default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(1), nullable=False, default="D", index=True)
    a10_voucher_no: Mapped[str | None] = mapped_column(String(30))
    request_body: Mapped[str | None] = mapped_column(Text)
    response_body: Mapped[str | None] = mapped_column(Text)
    error_msg: Mapped[str | None] = mapped_column(Text)
    source_file: Mapped[str | None] = mapped_column(String(260))
    created_by: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    # 아마란스 잔존 확인 시각 — 동기화가 오래 안 본 전표부터 돌아가며 검사한다
    amaranth_checked_at: Mapped[datetime | None] = mapped_column(DateTime)


class CardVoucherItem(Base):
    """전표에 담긴 카드 사용 1건. 원본 엑셀 값과 수정값을 함께 보관한다."""

    __tablename__ = "a10_card_voucher_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    voucher_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    dedup_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)

    # 원천 (수정 불가)
    card_no: Mapped[str] = mapped_column(String(20), nullable=False)
    card_alias: Mapped[str | None] = mapped_column(String(30))
    card_partner_code: Mapped[str | None] = mapped_column(String(10))
    user_name: Mapped[str | None] = mapped_column(String(50))
    use_date: Mapped[str] = mapped_column(String(8), nullable=False)
    appr_no: Mapped[str | None] = mapped_column(String(20))
    total: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)

    # 판단 항목 (화면에서 수정 가능)
    merchant: Mapped[str | None] = mapped_column(String(200))
    merchant_biz_no: Mapped[str | None] = mapped_column(String(20))
    merchant_partner_code: Mapped[str | None] = mapped_column(String(10))
    purpose: Mapped[str | None] = mapped_column(String(30))       # 사용용도 = 계정과목명
    account_code: Mapped[str | None] = mapped_column(String(8))
    deductible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supply: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    vat: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False, default=0)
    remark: Mapped[str | None] = mapped_column(String(100))

    # 원본 엑셀 값 (수정 추적용)
    origin_json: Mapped[str | None] = mapped_column(Text)
    edited_by: Mapped[str | None] = mapped_column(String(50))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
