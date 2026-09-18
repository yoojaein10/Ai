"""일계표 대사 — 리더·리포트 조립 (sqlite 픽스처, 은행 쪽은 원천 행을 직접 준다)."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.bank_account_map import BankAccountMap
from app.models.deposit_outbox import DepositOutbox
from app.models.voucher_cache import VoucherCache
from app.services.bank_reconcile import build_report, export_sheets, normalize_bank_rows

DAY = date(2026, 8, 25)
SOUTH = ("10000004", "48420101128982")   # 국민남부 (매핑 있음)
NORTH = ("10000004", "19460104017375")   # 북부지사 계좌 (매핑 없음)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for table in (BankAccountMap.__table__, DepositOutbox.__table__, VoucherCache.__table__):
        table.create(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def raw(uf, acct, amount, *, inout="2", jeokyo="", memo="", nick="남부터미널", day="20260825"):
    """CB2_ACCT_HIS 원천 행 모양 그대로 (fetch_transactions 결과)."""
    return {"UNIQUE_FIELD": uf, "BANK_CD": acct[0], "ACCT_NO": acct[1], "ACCT_TXDAY": day, "ACCT_TXTIME": "101500",
            "INOUT_GUBUN": inout, "TX_AMT": str(amount) + ".00", "JEOKYO": jeokyo, "Memo": memo, "ACCT_NICKNAME": nick}


def cache(db, id, amount, *, drcr="3", partner="01-04-0001", pname="국민남부", division="1000",
          remark="", mgmt=None, account="1030000", status="1", day=DAY, synced=None):
    db.add(VoucherCache(
        id=id, voucher_date=day, voucher_no=f"{id:05d}", line_no="00001", division_code=division,
        management_no=mgmt, debit_credit=drcr, account_code=account, account_name="보통예금",
        partner_code=partner, partner_name=pname, amount=Decimal(amount), remark=remark,
        document_status=status, synced_at=synced or datetime(2026, 8, 26, 10, 50),
    ))


def test_원천_행을_정규화한다():
    rows = normalize_bank_rows([raw("u1", SOUTH, 52_800, jeokyo="400578078/대체입금/", memo=" 영도 ")])
    assert rows == [{
        "key": "u1", "bank_cd": "10000004", "acct_no": "48420101128982", "nickname": "남부터미널",
        "day": DAY, "time": "101500", "inout": "2", "amount": Decimal("52800"),
        "jeokyo": "400578078/대체입금/", "memo": "영도",
    }]


def test_계좌별로_은행과_전표를_맞추고_요약과_회계단위_소계를_낸다(db):
    db.add(BankAccountMap(id=1, bank_cd=SOUTH[0], acct_no=SOUTH[1], nickname="남부터미널",
                          partner_code="01-04-0001", partner_name="국민남부", active="Y"))
    cache(db, 1, 52_800, remark="수수료입금", mgmt="01-2608-3-2601")
    cache(db, 2, 7_000, drcr="4", remark="이체수수료")
    cache(db, 3, 999, account="8110000")                      # 보통예금이 아니면 무시
    db.commit()
    report = build_report(db, DAY, DAY, bank_rows=[
        raw("u1", SOUTH, 52_800, memo="01-2608-3-2601"),
        raw("u2", SOUTH, 7_000, inout="1", jeokyo="수수료"),
    ])
    assert report["synced_at"] == "2026-08-26 10:50"
    assert len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["day"] == "2026-08-25" and row["nickname"] == "남부터미널" and row["partner_name"] == "국민남부"
    assert row["mapped"] is True and row["divisions"] == ["1000"]
    assert row["deposit"]["status"] == "MATCHED" and row["deposit"]["bank_total"] == 52_800
    assert row["withdrawal"]["status"] == "MATCHED" and row["withdrawal"]["voucher_total"] == 7_000
    assert row["status"] == "MATCHED"
    summary = report["summary"]
    assert (summary["deposit"]["bank_total"], summary["deposit"]["voucher_total"], summary["deposit"]["diff"]) == (52_800, 52_800, 0)
    assert (summary["withdrawal"]["bank_total"], summary["withdrawal"]["voucher_total"]) == (7_000, 7_000)
    assert summary["accounts"] == 1 and summary["mismatched"] == 0
    assert report["division_totals"] == [
        {"division_code": "1000", "debit_count": 1, "debit_total": 52_800, "credit_count": 1, "credit_total": 7_000},
    ]


def test_매핑_없는_계좌는_매핑필요로_전표만_있는_거래처는_따로_보인다(db):
    """사이버브랜치에는 본사와 일부 지사 계좌만 있다 — 매핑 없는 거래처의 전표는 대개
    사이버브랜치가 모르는 지사 계좌라 대사 대상이 아니다. 숨기지 않되 따로 둔다."""
    cache(db, 1, 79_558_830, partner="01-04-0099", pname="(북부)국민일산병원", division="1300")
    cache(db, 2, 5_000_500, drcr="4", partner="01-04-0099", pname="(북부)국민일산병원", division="1300")
    db.commit()
    report = build_report(db, DAY, DAY, bank_rows=[raw("n1", NORTH, 79_558_830, nick="북부")])
    assert [(r["nickname"], r["status"], r["mapped"]) for r in report["rows"]] == [("북부", "UNMAPPED", False)]
    assert report["rows"][0]["deposit"]["bank_total"] == 79_558_830
    assert report["voucher_only"] == [{
        "day": "2026-08-25", "partner_code": "01-04-0099", "partner_name": "(북부)국민일산병원",
        "divisions": ["1300"], "deposit_count": 1, "deposit_total": 79_558_830,
        "withdrawal_count": 1, "withdrawal_total": 5_000_500,
    }]
    summary = report["summary"]
    assert summary["unmapped"] == 1 and summary["voucher_only"] == 1
    assert summary["voucher_only_deposit_total"] == 79_558_830
    # 매핑 없는 계좌는 회계단위로 걸러도 사라지지 않는다 (손봐야 할 것이 숨으면 안 된다)
    assert [r["nickname"] for r in build_report(db, DAY, DAY, division="1000",
                                                bank_rows=[raw("n1", NORTH, 79_558_830, nick="북부")])["rows"]] == ["북부"]


def test_대사_전용_매핑은_배치용이_아니어도_대사에_쓴다(db):
    """지사 계좌는 지사가 직접 전표를 넣으니 입금전표 배치(active='Y'만)가 쓰면 안 된다.
    그래도 일계표 대사는 맞춰 봐야 하므로 active='N' + reconcile_only='Y' 로 둔다."""
    db.add(BankAccountMap(id=1, bank_cd=NORTH[0], acct_no=NORTH[1], nickname="북부",
                          partner_code="01-04-0099", partner_name="(북부)국민일산병원",
                          active="N", reconcile_only="Y"))
    cache(db, 1, 79_558_830, partner="01-04-0099", pname="(북부)국민일산병원", division="1300")
    db.commit()
    report = build_report(db, DAY, DAY, bank_rows=[raw("n1", NORTH, 79_558_830, nick="북부")])
    row = report["rows"][0]
    assert row["mapped"] is True and row["status"] == "MATCHED" and row["divisions"] == ["1300"]
    assert report["voucher_only"] == []


def test_대사_전용_열은_멱등_마이그레이션으로_붙는다():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    sql = (root / "scripts" / "sql" / "20260826_bank_account_map_reconcile_only.sql").read_text(encoding="utf-8")
    assert "COL_LENGTH(N'dbo.a10_bank_account_map', N'reconcile_only') IS NULL" in sql
    assert "ADD reconcile_only CHAR(1) NOT NULL" in sql
    create_tables = (root / "scripts" / "create_tables.py").read_text(encoding="utf-8")
    assert '"20260826_bank_account_map_reconcile_only.sql"' in create_tables, "재배포 때 자동 적용돼야 한다"
    # 입금전표 배치는 여전히 active='Y' 만 본다 — 대사 전용 계좌로 전표를 만들면 안 된다
    vouchers = (root / "app" / "services" / "deposit_vouchers.py").read_text(encoding="utf-8")
    assert "reconcile_only" not in vouchers
    assert vouchers.count('BankAccountMap.active == "Y"') >= 3


def test_회계단위_필터는_그_회계단위_전표가_있는_계좌만_남긴다(db):
    db.add(BankAccountMap(id=1, bank_cd=SOUTH[0], acct_no=SOUTH[1], nickname="남부터미널",
                          partner_code="01-04-0001", partner_name="국민남부", active="Y"))
    db.add(BankAccountMap(id=2, bank_cd=NORTH[0], acct_no=NORTH[1], nickname="북부",
                          partner_code="01-04-0099", partner_name="(북부)국민일산병원", active="Y"))
    cache(db, 1, 1_000)
    cache(db, 2, 2_000, partner="01-04-0099", pname="(북부)국민일산병원", division="1300")
    db.commit()
    rows = [raw("a", SOUTH, 1_000), raw("b", NORTH, 2_000, nick="북부")]
    assert [r["nickname"] for r in build_report(db, DAY, DAY, division="1300", bank_rows=rows)["rows"]] == ["북부"]
    assert [r["nickname"] for r in build_report(db, DAY, DAY, division="1000", bank_rows=rows)["rows"]] == ["남부터미널"]
    assert len(build_report(db, DAY, DAY, bank_rows=rows)["rows"]) == 2


def test_배치가_보낸_묶음은_outbox_작성번호로_한_줄에_맞춘다(db):
    db.add(BankAccountMap(id=1, bank_cd=SOUTH[0], acct_no=SOUTH[1], nickname="남부터미널",
                          partner_code="01-04-0001", partner_name="국민남부", active="Y"))
    for i, (uf, amt) in enumerate([("y1", 52_800), ("y2", 85_800)], start=1):
        db.add(DepositOutbox(id=700 + i, unique_field=uf, bank_cd=SOUTH[0], acct_no=SOUTH[1], tx_day=DAY,
                             tx_amount=Decimal(amt), jeokyo="400/대체입금/", doc_id=f"40000000{i}",
                             voucher_kind="YAK", status="S", menu_sq=50744))
    cache(db, 1, 138_600, remark="약식평가수수료 입금")
    db.commit()
    report = build_report(db, DAY, DAY, bank_rows=[
        raw("y1", SOUTH, 52_800, jeokyo="400000001/대체입금/"),
        raw("y2", SOUTH, 85_800, jeokyo="400000002/대체입금/"),
    ])
    row = report["rows"][0]
    assert row["deposit"]["status"] == "MATCHED"
    assert row["deposit"]["pairs"][0]["kind"] == "bundle" and sorted(row["deposit"]["pairs"][0]["bank"]) == ["y1", "y2"]


def test_전표만_있고_거래가_없으면_차이로_보인다(db):
    db.add(BankAccountMap(id=1, bank_cd=SOUTH[0], acct_no=SOUTH[1], nickname="남부터미널",
                          partner_code="01-04-0001", partner_name="국민남부", active="Y"))
    cache(db, 1, 5_000, remark="수기 입력")
    db.commit()
    report = build_report(db, DAY, DAY, bank_rows=[])
    row = report["rows"][0]
    assert row["status"] == "DIFF" and row["deposit"]["diff"] == -5_000
    assert row["deposit"]["unmatched_lines"][0]["voucher_no"] == "00001"
    assert report["summary"]["mismatched"] == 1


def test_엑셀_시트_두_장을_만든다(db):
    db.add(BankAccountMap(id=1, bank_cd=SOUTH[0], acct_no=SOUTH[1], nickname="남부터미널",
                          partner_code="01-04-0001", partner_name="국민남부", active="Y"))
    cache(db, 1, 1_000)
    db.commit()
    report = build_report(db, DAY, DAY, bank_rows=[raw("a", SOUTH, 1_000), raw("b", SOUTH, 300)])
    sheets = export_sheets(report)
    assert [s[0] for s in sheets] == ["계좌 요약", "미일치 건"]
    summary_rows = sheets[0][2]
    assert summary_rows[0]["nickname"] == "남부터미널" and summary_rows[0]["deposit_diff"] == 300
    unmatched = sheets[1][2]
    assert unmatched == [{
        "day": "2026-08-25", "nickname": "남부터미널", "direction": "입금", "side": "은행",
        "amount": 300, "voucher_no": "", "division_code": "", "text": "", "memo": "",
    }]
