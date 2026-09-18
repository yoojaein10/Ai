from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.voucher_cache import VoucherCache
from app.models.voucher_sync import VoucherSync
from app.services.default_vouchers import (
    DefaultVoucherService,
    _partner_search_name,
    _voucher_lines,
)
from app.services.office_lookup import normalize_office_name as _normalize_office_name


def test_default_voucher_lines_are_balanced_and_management_number_is_scoped():
    lines = _voucher_lines(
        doc_id="01-2607-3-0001",
        customer_name="테스트 거래처",
        company_code="1000",
        division_code="1000",
        voucher_date=date(2026, 7, 20),
        menu_sq=12345,
        base_fee=Decimal("1100000"),
        vat=Decimal("110000"),
        total=Decimal("1210000"),
        partner_code="0000012345",
    )

    assert sum(line["acctAm"] for line in lines if line["drcrFg"] == "3") == 1210000
    assert sum(line["acctAm"] for line in lines if line["drcrFg"] == "4") == 1210000
    assert [line["acctCd"] for line in lines] == [
        "1080000", "4010001", "2550000"
    ]
    # 관리번호는 maNb(관리항목 EA). ctNb는 부가세계정 승인번호 필드라 쓰지 않는다.
    assert lines[0]["maNb"] == "01-2607-3-0001"
    assert lines[1]["maNb"] == "01-2607-3-0001"
    assert "maNb" not in lines[2]
    assert all("ctNb" not in line for line in lines)
    assert lines[2]["vatDivCd"] == "1000"
    assert lines[2]["issDt"] == "20260720"
    assert lines[2]["taxFg"] == "11"
    assert lines[2]["supAm"] == 1100000
    assert all(line["trCd"] == "0000012345" for line in lines)
    # 작성자는 api11A10 입력 필드가 없다 — empCd는 보내지 않는다
    assert all("empCd" not in line and "ctDept" not in line for line in lines)
    # 관리항목(매출구분 L2·은행구분 M1)은 매출 라인에만
    assert lines[1]["userlTy2"] == "03"  # 01-2607-3-… → 담보부문
    assert lines[1]["usermTy1"] == "880"  # 은행 아닌 거래처 → 기타
    assert all("userlTy2" not in lines[i] for i in (0, 2))
    # 적요는 재무팀 수기 관행 그대로
    assert lines[0]["rmkDc"] == "외상매출 발생"
    assert lines[1]["rmkDc"] == "일반 매출"
    assert lines[2]["rmkDc"].startswith("감정평가수수료 01-")


def test_department_is_sent_when_given():
    lines = _voucher_lines(
        doc_id="01-2607-3-0001",
        customer_name="테스트 거래처",
        company_code="1000",
        division_code="1000",
        voucher_date=date(2026, 7, 20),
        menu_sq=12345,
        base_fee=Decimal("1100000"),
        vat=Decimal("110000"),
        total=Decimal("1210000"),
        partner_code="0000012345",
        dept_cd="1010",
    )
    assert all(line["ctDept"] == "1010" for line in lines)
    assert all("empCd" not in line for line in lines)


def _lines(**extra):
    base = dict(
        doc_id="01-2607-3-0001",
        customer_name="테스트 거래처",
        company_code="1000",
        division_code="1000",
        voucher_date=date(2026, 7, 20),
        menu_sq=12345,
        base_fee=Decimal("1100000"),
        vat=Decimal("110000"),
        total=Decimal("1210000"),
        partner_code="0000012345",
    )
    base.update(extra)
    return _voucher_lines(**base)


def test_issued_tax_invoice_marks_vat_line_electronic():
    """세금계산서가 먼저 발행된 건은 부가세 라인에 전자발행·승인번호를 싣는다."""
    lines = _lines(tax_invoice_issno="202608114100020300001740")
    vat_line = lines[2]
    assert vat_line["jeonjaYn"] == "1"
    assert vat_line["issNo"] == "202608114100020300001740"
    assert vat_line["taxFg"] == "11"
    # 전자발행 표시는 부가세 라인에만
    assert all("jeonjaYn" not in line and "issNo" not in line for line in lines[:2])


def test_issued_tax_invoice_without_confirm_sets_flag_only():
    """승인번호 미확정이면 전자 여부만 표시하고 issNo는 보내지 않는다."""
    lines = _lines(tax_invoice_issno="")
    assert lines[2]["jeonjaYn"] == "1"
    assert "issNo" not in lines[2]


def test_no_tax_invoice_leaves_vat_line_plain():
    lines = _lines(tax_invoice_issno=None)
    assert "jeonjaYn" not in lines[2] and "issNo" not in lines[2]
    lines = _lines()
    assert "jeonjaYn" not in lines[2] and "issNo" not in lines[2]


def test_apworks_and_amaranth_office_names_match():
    assert _normalize_office_name("본사") == _normalize_office_name("(주)대화감정평가법인")
    assert _normalize_office_name("대구경북지사") == _normalize_office_name(
        "(주)대화감정평가법인 대구지사"
    )
    assert _normalize_office_name("부산경남지사") == _normalize_office_name(
        "(주)대화감정평가법인 부산지사"
    )


def test_partner_search_removes_only_trailing_titles():
    assert _partner_search_name("안양중부새마을금고이사장") == "안양중부새마을금고"
    assert _partner_search_name("국민은행 강남 지점장") == "국민은행 강남"
    assert _partner_search_name("지점장협회") == "지점장협회"


@pytest.fixture
def voucher_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    VoucherSync.__table__.create(engine)
    VoucherCache.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# sqlite는 BigInteger PK를 자동 채번하지 않아 id를 직접 준다
def _sync_row(row_id: int, doc_id: str, status: str) -> VoucherSync:
    return VoucherSync(
        id=row_id,
        src_voucher_no=f"APPRAISAL-SEND-{doc_id}", management_no=doc_id,
        voucher_date=date(2026, 8, 14), debit_total=Decimal("1"),
        credit_total=Decimal("1"), status=status,
    )


def test_exists는_생성기록이나_수기_청구전표를_모두_잡는다(voucher_db):
    """발급 팝업 '전표 생성' 버튼 상태 — create()의 중복 검사와 같은 기준이어야 한다."""
    service = DefaultVoucherService(voucher_db)
    assert service.exists("01-2608-3-0001") is False

    # MOA 생성 기록(성공)
    voucher_db.add(_sync_row(1, "01-2608-3-0001", "S"))
    # 재무팀 수기 청구 전표 (외상매출금 차변, 캐시 기준)
    voucher_db.add(VoucherCache(
        id=1,
        voucher_date=date(2026, 8, 13), voucher_no="00001", line_no="00001",
        division_code="1000", management_no="01-2608-3-0002",
        debit_credit="3", account_code="1080000", amount=Decimal("1210000"),
    ))
    # 실패 기록(F)은 재시도 가능이라 없음으로 친다
    voucher_db.add(_sync_row(2, "01-2608-3-0003", "F"))
    voucher_db.commit()

    assert service.exists("01-2608-3-0001") is True
    assert service.exists("01-2608-3-0002") is True
    assert service.exists("01-2608-3-0003") is False
    # 외상매출금이라도 대변(회수)뿐이면 청구 전표가 아니다
    voucher_db.add(VoucherCache(
        id=2,
        voucher_date=date(2026, 8, 13), voucher_no="00002", line_no="00001",
        division_code="1000", management_no="01-2608-3-0004",
        debit_credit="4", account_code="1080000", amount=Decimal("1210000"),
    ))
    voucher_db.commit()
    assert service.exists("01-2608-3-0004") is False
