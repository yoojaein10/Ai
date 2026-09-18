"""팝빌 테스트베드 발행분(is_test=1)은 화면·집계에 섞이면 안 된다.

2026-07-24 테스트 발행이 01-2607-3-2302 에 그대로 남아 감정서 상세에
'발급'으로 떴다(상호 이카드밴(주), 승인번호 8888…). 국세청에 없는 문서다.
"""

import inspect

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services import receivables
from app.services.appraisals import AppraisalService

_DDL = [
    """CREATE TABLE dbo.a10_issued_taxinvoice (
        id INTEGER PRIMARY KEY, doc_type TEXT, doc_id TEXT, receiver_name TEXT,
        supply_cost NUMERIC, tax NUMERIC, total NUMERIC, nts_confirm TEXT,
        issue_dt TEXT, is_test INTEGER, created_at TEXT)""",
    """CREATE TABLE dbo.a10_tams_tax_cache (
        appraisal_no TEXT, bal_date DATE, company_nm TEXT, status_cd TEXT,
        electronic_yn TEXT, sup_am NUMERIC, vat_am NUMERIC, total_am NUMERIC,
        bill_year TEXT, seq_no INTEGER)""",
    """CREATE TABLE dbo.a10_tams_cash_receipt_cache (
        appraisal_no TEXT, transaction_date DATE, approval_no TEXT,
        transaction_type TEXT, report_yn TEXT, supply_amount NUMERIC,
        vat_amount NUMERIC, total_amount NUMERIC, send_date DATE, seq_no INTEGER)""",
]


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    session = sessionmaker(bind=engine, future=True)()
    session.execute(text("ATTACH DATABASE ':memory:' AS dbo"))
    for ddl in _DDL:
        session.execute(text(ddl))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _issued(db, id_, doc_id, name, total, confirm, is_test):
    db.execute(text(
        "INSERT INTO dbo.a10_issued_taxinvoice "
        "(id, doc_type, doc_id, receiver_name, supply_cost, tax, total, nts_confirm,"
        " issue_dt, is_test, created_at) VALUES "
        "(:id, '세금계산서', :doc, :name, :sup, :vat, :total, :confirm,"
        " '20260724112001', :test, '2026-07-24 11:20:01')"
    ), {"id": id_, "doc": doc_id, "name": name, "sup": total / 1.1, "vat": total - total / 1.1,
        "total": total, "confirm": confirm, "test": is_test})
    db.commit()


def test_감정서_상세는_테스트_발행분을_숨긴다(db):
    _issued(db, 1, "01-2607-3-2302", "이카드밴(주)", 1497100, "202607248888888800000169", 1)
    _issued(db, 2, "01-2607-3-2302", "농협은행 파크원센터", 969100, "202608244100020300001c23", 0)

    rows = AppraisalService(db)._tax_invoices("01-2607-3-2302")

    assert [row["company_name"] for row in rows] == ["농협은행 파크원센터"]


def test_감정서_상세는_실발행이_없으면_비어_있다(db):
    _issued(db, 1, "01-2607-3-2302", "이카드밴(주)", 1497100, "202607248888888800000169", 1)

    assert AppraisalService(db)._tax_invoices("01-2607-3-2302") == []


def _issued_blocks(source: str) -> list[str]:
    """a10_issued_taxinvoice 를 읽는 SQL 조각마다 그 WHERE 절 부근을 잘라 낸다."""
    marker = "FROM dbo.a10_issued_taxinvoice i"
    blocks, start = [], source.find(marker)
    assert start >= 0, "issued_taxinvoice 조회가 없어졌다"
    while start >= 0:
        blocks.append(source[start:start + 400])
        start = source.find(marker, start + 1)
    return blocks


def test_입금현황_계산서_합계는_테스트_발행분을_뺀다():
    """반제 CTE(tax_doc)와 목록 합계(_tax_invoice_totals) 두 곳 모두."""
    sources = [receivables._SETTLE_CTE, inspect.getsource(receivables._tax_invoice_totals)]
    blocks = [block for source in sources for block in _issued_blocks(source)]
    assert len(blocks) == 2
    for block in blocks:
        assert "i.is_test = 0" in block, block
