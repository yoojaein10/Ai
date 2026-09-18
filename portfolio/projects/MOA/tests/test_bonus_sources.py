"""실적 후보 감정서 (2단계 10) — 앱 소유 표만 읽는 SQL 이라 sqlite 로 실행해 본다.

후보 = {입금월에 4010001 감정수수료 대변이 있는 본사 감정서} ∪ {그 달 완납된 감정서}.
미수 잔액이 있으면 보류(HELD_UNPAID), 입금이 월말 뒤면 다음 달 몫(HELD_PAID_LATER),
순수수료가 0 이하면 HELD_NO_FEE. 묶음 청구(청구·입금 0)는 포함하되 PAID_BY_BUNDLE 표시.
"""

import sqlite3
from datetime import date

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.bonus.sources import candidate_docs, classify_candidate

sqlite3.register_adapter(date, lambda value: value.isoformat())

_DDL = [
    """CREATE TABLE dbo.a10_voucher_cache (
        voucher_date DATE, voucher_no TEXT, line_no TEXT, division_code TEXT, management_no TEXT,
        account_code TEXT, debit_credit TEXT, amount NUMERIC)""",
    """CREATE TABLE dbo.a10_receivable_summary (
        doc_id TEXT, billed_amount NUMERIC, received_amount NUMERIC, outstanding_amount NUMERIC,
        last_received_date DATE)""",
    """CREATE TABLE dbo.a10_payment_status (doc_id TEXT, paid_date DATE, paid_amount NUMERIC, pay_result TEXT)""",
]


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session = sessionmaker(bind=engine, future=True)()
    session.execute(text("ATTACH DATABASE ':memory:' AS dbo"))
    for ddl in _DDL:
        session.execute(text(ddl))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _line(db, day, doc, acct, dc, amount, division="1000", no="00001"):
    db.execute(text(
        "INSERT INTO dbo.a10_voucher_cache (voucher_date, voucher_no, division_code, management_no, account_code, debit_credit, amount) "
        "VALUES (:d, :no, :div, :doc, :acct, :dc, :amt)"
    ), {"d": day, "no": no, "div": division, "doc": doc, "acct": acct, "dc": dc, "amt": amount})


def _summary(db, doc, billed, received, outstanding, last_received):
    db.execute(text(
        "INSERT INTO dbo.a10_receivable_summary (doc_id, billed_amount, received_amount, outstanding_amount, last_received_date) "
        "VALUES (:doc, :b, :r, :o, :l)"
    ), {"doc": doc, "b": billed, "r": received, "o": outstanding, "l": last_received})


def _status(db, doc, paid_date, result="입금완료"):
    db.execute(text("INSERT INTO dbo.a10_payment_status (doc_id, paid_date, paid_amount, pay_result) VALUES (:d, :p, 0, :r)"),
               {"d": doc, "p": paid_date, "r": result})


JULY = (date(2026, 7, 1), date(2026, 7, 31))


def _by_doc(rows):
    return {row["doc_id"]: row for row in rows}


def test_당월_감정수수료_대변이_있고_미수가_없으면_포함이다(db):
    _line(db, date(2026, 7, 14), "01-2603-1-0114", "4010001", "4", 453_000)
    _summary(db, "01-2603-1-0114", 498_300, 498_300, 0, date(2026, 7, 14))
    db.commit()
    rows = _by_doc(candidate_docs(db, *JULY))
    row = rows["01-2603-1-0114"]
    assert row["fee_total"] == 453_000 and row["fee_month"] == 453_000
    assert row["sources"] == ["SALES", "PAID"]
    assert classify_candidate(row, perf_to=JULY[1]) == ("INCLUDED", [])


def test_미수_잔액이_있으면_보류로_뺀다(db):
    _line(db, date(2026, 7, 3), "01-2604-3-1310", "4010001", "4", 900_000)
    _summary(db, "01-2604-3-1310", 990_000, 0, 990_000, None)
    db.commit()
    row = _by_doc(candidate_docs(db, *JULY))["01-2604-3-1310"]
    assert classify_candidate(row, perf_to=JULY[1]) == ("HELD_UNPAID", [])


def test_전월_매출이_당월에_완납되면_당월_후보고_수수료는_전_기간_순액이다(db):
    _line(db, date(2026, 6, 20), "01-2605-3-1500", "4010001", "4", 700_000)
    _summary(db, "01-2605-3-1500", 770_000, 770_000, 0, date(2026, 7, 9))
    _status(db, "01-2605-3-1500", date(2026, 7, 9))
    db.commit()
    row = _by_doc(candidate_docs(db, *JULY))["01-2605-3-1500"]
    assert row["fee_total"] == 700_000 and row["fee_month"] == 0
    assert row["sources"] == ["PAID"] and row["first_sale_date"] == date(2026, 6, 20)
    assert classify_candidate(row, perf_to=JULY[1]) == ("INCLUDED", [])


def test_기타수수료만_있는_건과_지사_건과_다른_사업장은_후보가_아니다(db):
    _line(db, date(2026, 7, 6), "01-2401-3-0055", "4010002", "4", 144_800)          # 담보 건의 사본발급 등
    _line(db, date(2026, 7, 6), "02-2607-3-0001", "4010001", "4", 500_000)          # 지사
    _line(db, date(2026, 7, 6), "01-2607-3-0002", "4010001", "4", 500_000, division="2000")
    db.commit()
    assert candidate_docs(db, *JULY) == []


def test_가격자문_유형6은_기타수수료_계정에_매출이_잡힌다(db):
    """재무팀 지침(2026-08-06): 유형 6(가격자문)은 4010002 로 매출을 낸다 — 8월 시트 가격자문 19건이 여기 있었다."""
    _line(db, date(2026, 7, 22), "01-2606-6-0406", "4010002", "4", 10_000)
    _line(db, date(2026, 7, 22), "01-2606-6-0406", "4010001", "4", 999)             # 가격자문 건의 감정수수료는 세지 않는다
    _summary(db, "01-2606-6-0406", 11_000, 11_000, 0, date(2026, 7, 22))
    db.commit()
    row = _by_doc(candidate_docs(db, *JULY))["01-2606-6-0406"]
    assert row["fee_total"] == 10_000 and row["sources"] == ["SALES", "PAID"]
    assert classify_candidate(row, perf_to=JULY[1]) == ("INCLUDED", [])


def test_입금이_월말_뒤면_다음_달_몫이고_순액이_0_이하면_수수료_없음이다(db):
    _line(db, date(2026, 7, 20), "01-2604-3-1065", "4010001", "4", 600_000)
    _summary(db, "01-2604-3-1065", 660_000, 660_000, 0, date(2026, 8, 3))
    _line(db, date(2026, 7, 21), "01-2604-7-0035", "4010001", "4", 100_000)
    _line(db, date(2026, 7, 22), "01-2604-7-0035", "4010001", "3", 100_000)         # 취소
    _summary(db, "01-2604-7-0035", 0, 0, 0, None)
    db.commit()
    rows = _by_doc(candidate_docs(db, *JULY))
    assert classify_candidate(rows["01-2604-3-1065"], perf_to=JULY[1]) == ("HELD_PAID_LATER", [])
    assert rows["01-2604-7-0035"]["fee_total"] == 0
    assert classify_candidate(rows["01-2604-7-0035"], perf_to=JULY[1]) == ("HELD_NO_FEE", [])


def test_묶음_배분_전표는_건별_순액으로_잡히고_묶음_표시를_단다(db):
    # 든든전세: 일괄 −81.2M 은 관리번호가 감정서가 아니라 후보가 아니고, 건별 +45만 만 잡힌다
    _line(db, date(2026, 7, 14), "든든전세 26년 2분기 수수료 배분", "4010001", "4", -81_191_000, no="00156")
    _line(db, date(2026, 7, 14), "01-2603-1-0114", "4010001", "4", 453_000, no="00156")
    _line(db, date(2026, 7, 14), "01-2603-1-0115", "4010001", "4", 446_000, no="00156")
    _summary(db, "01-2603-1-0114", 0, 0, 0, None)
    db.commit()
    rows = _by_doc(candidate_docs(db, *JULY))
    assert set(rows) == {"01-2603-1-0114", "01-2603-1-0115"}
    assert classify_candidate(rows["01-2603-1-0114"], perf_to=JULY[1]) == ("INCLUDED", ["PAID_BY_BUNDLE"])
    assert classify_candidate(rows["01-2603-1-0115"], perf_to=JULY[1]) == ("INCLUDED", ["PAID_BY_BUNDLE"])


def test_입금완료_판정만_있고_요약이_없어도_후보다(db):
    _line(db, date(2026, 5, 4), "01-2604-3-1076", "4010001", "4", 580_000)
    _status(db, "01-2604-3-1076", date(2026, 7, 28))
    db.commit()
    row = _by_doc(candidate_docs(db, *JULY))["01-2604-3-1076"]
    assert row["sources"] == ["PAID"] and row["pay_result"] == "입금완료"
    assert classify_candidate(row, perf_to=JULY[1]) == ("INCLUDED", ["PAID_BY_BUNDLE"])


def test_당월감정서경비는_적요의_감정서번호로_귀속하고_못_한_것은_참고로_남긴다(db):
    from app.services.bonus.sources import voucher_expenses

    db.execute(text("ALTER TABLE dbo.a10_voucher_cache ADD COLUMN account_name TEXT"))
    db.execute(text("ALTER TABLE dbo.a10_voucher_cache ADD COLUMN remark TEXT"))
    db.execute(text(
        "INSERT INTO dbo.a10_voucher_cache (voucher_date, voucher_no, division_code, management_no, account_code, debit_credit, amount, account_name, remark) VALUES "
        "('2026-07-15', '00001', '1000', NULL, '8170000', '3', 40000, '세금과공과금', '01-2604-1-0252/01-2604-1-0253 전자수입인지'), "
        "('2026-07-16', '00002', '1000', NULL, '8170000', '3', 20000, '세금과공과금', '(주)동해종합기술공사 전자수입인지-강무진,정인수'), "
        "('2026-07-17', '00003', '1000', NULL, '8170000', '4', 999, '세금과공과금', '01-2604-1-0252 대변은 세지 않는다'), "
        "('2026-07-18', '00004', '2000', NULL, '8170000', '3', 999, '세금과공과금', '01-2604-1-0252 지사 사업장'), "
        "('2026-07-19', '00005', '1000', NULL, '8540000', '3', 30000, '용역비', '01-2607-3-9999 이번 달 목록에 없는 감정서')"
    ))
    db.commit()
    by_doc, unmatched = voucher_expenses(db, date(2026, 7, 1), date(2026, 7, 31), known_docs={"01-2604-1-0252", "01-2604-1-0253"})
    assert by_doc == {"01-2604-1-0252": 20_000, "01-2604-1-0253": 20_000}
    assert [u["remark"].split(" ")[0] for u in unmatched] == ["01-2607-3-9999", "(주)동해종합기술공사"]


def test_경비_전표_줄_단위_리더는_안정된_키와_감정서번호를_준다(db):
    from app.services.bonus.sources import voucher_expense_rows

    db.execute(text("ALTER TABLE dbo.a10_voucher_cache ADD COLUMN account_name TEXT"))
    db.execute(text("ALTER TABLE dbo.a10_voucher_cache ADD COLUMN remark TEXT"))
    db.execute(text(
        "INSERT INTO dbo.a10_voucher_cache (voucher_date, voucher_no, line_no, division_code, account_code, debit_credit, amount, account_name, remark) VALUES "
        "('2026-08-06', '00012', '1', '1000', '8170000', '3', 20000, '세금과공과금', '01-2606-5-0094 수입인지-성지연'), "
        "('2026-08-07', '00013', '2', '1000', '8260000', '3', 30000, '도서인쇄비', '제본 01-2607-3-0001/01-2607-3-0002'), "
        "('2026-08-10', '00014', '1', '1000', '8170000', '3', 10068920, '세금과공과금', '26.7월분 주민세 종업원분')"
    ))
    db.commit()
    rows = voucher_expense_rows(db, date(2026, 8, 1), date(2026, 8, 31))
    assert [(r["key"], r["amount"], r["doc_ids"]) for r in rows] == [
        ("20260810:00014:1", 10_068_920, []),
        ("20260807:00013:2", 30_000, ["01-2607-3-0001", "01-2607-3-0002"]),
        ("20260806:00012:1", 20_000, ["01-2606-5-0094"]),
    ]
    assert rows[2]["voucher_date"] == date(2026, 8, 6) and rows[2]["account_name"] == "세금과공과금"


def test_가지번호_감정서도_본사_후보이고_유형은_8번째_글자로_본다(db):
    """'012607-4-0236-1' 처럼 앞에 대시가 없는 가지번호 — 7월 98M 건이 여기 있었다."""
    _line(db, date(2026, 7, 20), "012607-4-0236-1", "4010001", "4", 98_134_000)
    _summary(db, "012607-4-0236-1", 107_947_400, 107_947_400, 0, date(2026, 7, 23))
    _line(db, date(2026, 7, 21), "012606-6-0388-1", "4010002", "4", 10_000)           # 가지번호 가격자문
    _summary(db, "012606-6-0388-1", 11_000, 11_000, 0, date(2026, 7, 21))
    _line(db, date(2026, 7, 22), "0126073-2244", "4010001", "4", 1)                  # 감정서번호가 아닌 것
    db.commit()
    rows = _by_doc(candidate_docs(db, *JULY))
    assert set(rows) == {"012607-4-0236-1", "012606-6-0388-1"}
    assert rows["012607-4-0236-1"]["fee_total"] == 98_134_000
    assert rows["012606-6-0388-1"]["fee_total"] == 10_000


def test_현금_없이_외상매출금만_잡힌_매출은_미입금으로_보류한다(db):
    """01-2604-7-0035: 외상매출금 차변의 관리번호가 거래처코드라 입금요약이 청구를 모른다 — 전표 모양으로 잡는다."""
    _line(db, date(2026, 7, 9), "8100012665", "1080000", "3", 85_855_000, no="00032")
    _line(db, date(2026, 7, 9), "01-2604-7-0035", "4010001", "4", 78_050_000, no="00032")
    _line(db, date(2026, 7, 9), None, "2550000", "4", 7_805_000, no="00032")
    # 든든전세 배분 전표: 외상매출금 차변이 없으니 묶음 입금으로 본다
    _line(db, date(2026, 7, 14), "든든전세 배분", "4010001", "4", -81_191_000, no="00156")
    _line(db, date(2026, 7, 14), "01-2603-1-0114", "4010001", "4", 453_000, no="00156")
    # 보통 입금전표: 현금이 같이 움직인다
    _line(db, date(2026, 7, 15), None, "1030000", "3", 550_000, no="00040")
    _line(db, date(2026, 7, 15), "01-2607-3-0001", "4010001", "4", 500_000, no="00040")
    db.commit()
    rows = _by_doc(candidate_docs(db, *JULY))
    assert rows["01-2604-7-0035"]["invoice_only"] is True
    assert classify_candidate(rows["01-2604-7-0035"], perf_to=JULY[1]) == ("HELD_UNPAID", [])
    assert rows["01-2603-1-0114"]["invoice_only"] is False
    assert classify_candidate(rows["01-2603-1-0114"], perf_to=JULY[1]) == ("INCLUDED", ["PAID_BY_BUNDLE"])
    assert classify_candidate(rows["01-2607-3-0001"], perf_to=JULY[1]) == ("INCLUDED", ["PAID_BY_BUNDLE"])
    # 나중에 입금이 확인되면(입금완료 판정) 외상 전표라도 포함이다
    _status(db, "01-2604-7-0035", date(2026, 7, 30)); db.commit()
    row = _by_doc(candidate_docs(db, *JULY))["01-2604-7-0035"]
    assert classify_candidate(row, perf_to=JULY[1])[0] == "INCLUDED"


def test_국민약식_전표_합은_400_관리번호의_4010002_순액이다(db):
    from app.services.bonus.sources import simple_appraisal_total

    _line(db, date(2026, 7, 31), "400576990", "4010002", "4", 78_000, no="00101")
    _line(db, date(2026, 7, 31), "400576518", "4010002", "4", 80_000, no="00102")
    _line(db, date(2026, 7, 20), "400574925", "4010002", "3", 30_000, no="00103")     # 차변(취소)은 뺀다
    _line(db, date(2026, 7, 10), "01-2607-6-0433", "4010002", "4", 10_000, no="00104")  # 일반 가격자문은 제외
    _line(db, date(2026, 6, 30), "400500000", "4010002", "4", 50_000, no="00105")      # 달 밖
    _line(db, date(2026, 7, 15), "400576990", "4010002", "4", 5_000, division="2000", no="00106")   # 지사 제외
    db.commit()
    assert simple_appraisal_total(db, date(2026, 7, 1), date(2026, 7, 31)) == (128_000.0, 3)
