"""지사 입금 → 본지점 전표(docuTy 7) — 판별·묶음 모양·라우팅 검증.

수기 실측(2026-08-12): 전표 00086(1.png)·00069(2.png). 지사 판별은
① Memo 지사명(1410 계정명과 정확 일치) ② 400번호의 BANK_KB_MASTER
OfficeID(제주 400579347·400577516 = '22' 실증) 순이다.
"""

import itertools
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.bank_account_map import BankAccountMap
from app.models.deposit_outbox import DepositOutbox
from app.models.kb_yak_item import KbYakItem
from app.models.voucher_cache import VoucherCache
from app.services import deposit_vouchers as dv
from app.services.deposit_vouchers import (
    BRANCH_ACCOUNTS,
    OFFICE_BRANCH_NAME,
    DepositVoucherService,
    branch_bundle_lines,
    branch_from_memo,
    jeokyo_token,
)


def test_지사명은_계정명과_정확_일치만_인정():
    assert branch_from_memo("부산지사") == "부산지사"
    assert branch_from_memo(" 제주지사 ") == "제주지사"
    # 부분 문자열·변형·본사는 오탐이라 안 잡는다 (fail-closed)
    assert branch_from_memo("부산") is None
    assert branch_from_memo("수원지사 3층") is None
    assert branch_from_memo("본사") is None
    assert branch_from_memo(None) is None


def test_적요_첫_토큰이_접수번호다():
    assert jeokyo_token("302204344/대체입금/") == "302204344"
    assert jeokyo_token("2026204107/수수료/디금여/") == "2026204107"
    assert jeokyo_token(None) == ""


def test_지사_계정_매핑은_17개_지사를_다_안다():
    # office_id → 지사명 → 1410 계정이 끊긴 곳이 없어야 한다
    assert set(OFFICE_BRANCH_NAME.values()) <= set(BRANCH_ACCOUNTS)
    assert OFFICE_BRANCH_NAME["22"] == "제주지사"          # 2.png 실증
    assert BRANCH_ACCOUNTS["제주지사"] == "1410013"
    assert BRANCH_ACCOUNTS["부산지사"] == "1410009"        # 1.png 실증
    assert BRANCH_ACCOUNTS["경북지사"] == "1410020"
    assert BRANCH_ACCOUNTS["대전세종지사"] == "1410016"


def test_본지점_묶음전표는_수기_00086과_같은_모양():
    # 1.png(2026-08-10, 지사수수료 입금 6,424,000) 재현 — 은행 혼재 1장
    lines = branch_bundle_lines(
        items=[
            {"token": "302204344", "amount": Decimal("2951300"),
             "account_partner": "01-04-0001", "branch_account": "1410009"},
            {"token": "2026214239", "amount": Decimal("1804000"),
             "account_partner": "01-26-0002", "branch_account": "1410016"},
        ],
        voucher_date=date(2026, 8, 10),
        menu_sq=50500,
        division_code="1000",
    )
    assert [line["acctCd"] for line in lines] == [
        "1030000", "1410009", "1030000", "1410016"
    ]
    assert [line["drcrFg"] for line in lines] == ["3", "4", "3", "4"]
    assert [line["menuLnSq"] for line in lines] == [1, 2, 3, 4]
    assert all(line["docuTy"] == "7" for line in lines)  # 본지점 (00086 실측)
    assert all(line["isuDoc"] == "지사수수료 입금" for line in lines)
    # 차·대 양쪽 거래처 = 그 입금 계좌의 은행지점 (00086 실측)
    assert lines[0]["trCd"] == lines[1]["trCd"] == "01-04-0001"
    assert lines[2]["trCd"] == lines[3]["trCd"] == "01-26-0002"
    assert lines[0]["rmkDc"] == lines[1]["rmkDc"] == "302204344"
    assert lines[0]["acctAm"] == lines[1]["acctAm"] == 2951300.0
    # 관리번호(maNb)는 안 싣는다 — 수기 전표에도 없다
    assert all("maNb" not in line for line in lines)


@pytest.fixture
def branch_sessions():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (DepositOutbox, BankAccountMap, KbYakItem, VoucherCache):
        model.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    seq = itertools.count(1000)

    # sqlite는 BigInteger PK를 자동 채번하지 않는다 — scan()이 만드는 신규
    # 행에만 id를 채워 준다(직접 준 id는 그대로).
    @event.listens_for(factory, "before_flush")
    def _assign_ids(session, _ctx, _instances):
        for obj in session.new:
            if isinstance(obj, DepositOutbox) and obj.id is None:
                obj.id = next(seq)

    try:
        yield factory
    finally:
        engine.dispose()


def _entry(i: int, **over) -> DepositOutbox:
    base = dict(
        id=i + 1, unique_field=f"UF{i}", bank_cd="10000004",
        acct_no="48420101128982", tx_day=date(2026, 8, 10),
        tx_amount=Decimal("2951300"), jeokyo="302204344/대체입금/",
        memo="부산지사", voucher_kind="BRANCH", status="PENDING",
    )
    base.update(over)
    return DepositOutbox(**base)


def _account(db) -> None:
    db.add(BankAccountMap(
        id=1, bank_cd="10000004", acct_no="48420101128982",
        partner_code="01-04-0001", partner_name="국민남부", active="Y",
    ))


def test_스캔이_지사명_Memo를_본지점_대상으로_적재한다(branch_sessions, monkeypatch):
    rows = [
        {"UNIQUE_FIELD": "U1", "BANK_CD": "10000004", "ACCT_NO": "1",
         "ACCT_TXDAY": "20260810", "TX_AMT": "2951300",
         "JEOKYO": "302204344/대체입금/", "Memo": "부산지사"},
        # 지사명 변형은 지금처럼 제외 — 오탐 방지
        {"UNIQUE_FIELD": "U2", "BANK_CD": "10000004", "ACCT_NO": "1",
         "ACCT_TXDAY": "20260810", "TX_AMT": "1000",
         "JEOKYO": "타행이체/", "Memo": "수원지사 3층"},
    ]
    monkeypatch.setattr(dv, "fetch_deposits", lambda a, b: rows)
    with branch_sessions() as db:
        counts = DepositVoucherService(db).scan(
            date(2026, 8, 10), date(2026, 8, 10)
        )
        saved = {r.unique_field: r for r in db.scalars(select(DepositOutbox))}

    assert counts["doc"] == 1 and counts["excluded"] == 1
    assert saved["U1"].voucher_kind == "BRANCH"
    assert saved["U1"].status == "PENDING"
    assert saved["U1"].doc_id == "302204344"
    assert saved["U2"].status == "EXCLUDED"
    assert saved["U2"].reason == "지사 입금"


def test_재스캔이_제외됐던_지사_건을_복구한다(branch_sessions, monkeypatch):
    rows = [
        {"UNIQUE_FIELD": "U1", "BANK_CD": "10000004", "ACCT_NO": "1",
         "ACCT_TXDAY": "20260810", "TX_AMT": "2951300",
         "JEOKYO": "302204344/대체입금/", "Memo": "부산지사"},
    ]
    monkeypatch.setattr(dv, "fetch_deposits", lambda a, b: rows)
    with branch_sessions() as db:
        db.add(_entry(0, unique_field="U1", memo=None, doc_id=None,
                      voucher_kind=None, status="EXCLUDED", reason="Memo 없음"))
        db.commit()
        counts = DepositVoucherService(db).scan(
            date(2026, 8, 10), date(2026, 8, 10)
        )
        row = db.scalars(select(DepositOutbox)).one()

    assert counts["reclassified"] == 1
    assert row.voucher_kind == "BRANCH" and row.status == "PENDING"
    assert row.doc_id == "302204344" and row.reason is None


def test_지사_건은_17시_회차_전에는_이월된다(branch_sessions):
    with branch_sessions() as db:
        db.add(_entry(0))
        db.commit()
        counts = DepositVoucherService(db).send_pending(limit=10)
        row = db.scalars(select(DepositOutbox)).one()

    assert counts["yak_deferred"] == 1
    assert row.status == "PENDING" and row.sent_at is None


def test_resolve_branch_Memo_지사명이_1410_계정으로_간다(branch_sessions):
    with branch_sessions() as db:
        _account(db)
        entry = _entry(0)
        db.add(entry)
        db.commit()
        item = DepositVoucherService(db)._resolve_branch(entry)

    assert item == {
        "token": "302204344", "amount": Decimal("2951300"),
        "account_partner": "01-04-0001", "branch_account": "1410009",
        "branch_name": "부산지사", "yak_no": None,
    }


def test_resolve_branch_400은_OfficeID로_지사를_확정한다(branch_sessions, monkeypatch):
    # 2.png 실증: 400579347 → OfficeID 22 → 제주지사(1410013)
    with branch_sessions() as db:
        _account(db)
        entry = _entry(0, jeokyo="400579347/대체입금/", memo=None,
                       doc_id="400579347", voucher_kind="YAK",
                       tx_amount=Decimal("55000"))
        db.add(entry)
        db.commit()
        service = DepositVoucherService(db)
        monkeypatch.setattr(service, "_kb_office", lambda yak_no: "22")
        item = service._resolve_branch(entry)

    assert item["branch_account"] == "1410013"
    assert item["branch_name"] == "제주지사"
    assert item["token"] == "400579347" and item["yak_no"] == "400579347"


def test_resolve_branch_수기_전표가_있으면_보류한다(branch_sessions):
    # 재무팀이 먼저 딴 건(00086 등)을 배치가 또 만들면 이중계상 — 캐시로 방지
    with branch_sessions() as db:
        _account(db)
        db.add(VoucherCache(
            id=1, voucher_date=date(2026, 8, 10), voucher_no="00086",
            line_no="2", division_code="1000", account_code="1410009",
            debit_credit="4", amount=Decimal("2951300"), remark="302204344",
        ))
        entry = _entry(0)
        db.add(entry)
        db.commit()
        hold = DepositVoucherService(db)._resolve_branch(entry)

    assert isinstance(hold, str) and "이미 본지점 전표" in hold


def test_resolve_branch_지사를_못_찾으면_보류한다(branch_sessions, monkeypatch):
    with branch_sessions() as db:
        _account(db)
        entry = _entry(0, memo=None, jeokyo="400579999/대체입금/",
                       doc_id="400579999", voucher_kind="YAK")
        db.add(entry)
        db.commit()
        service = DepositVoucherService(db)
        monkeypatch.setattr(service, "_kb_office", lambda yak_no: None)
        hold = service._resolve_branch(entry)

    assert isinstance(hold, str) and "지사를 확정하지 못함" in hold


def test_17시_회차가_지사_접수_400을_본지점으로_라우팅한다(branch_sessions, monkeypatch):
    """OfficeID≠10인 YAK은 약식 매출이 아니라 본지점 묶음으로 가야 한다."""
    with branch_sessions() as db:
        db.add(_entry(0, jeokyo="400579347/대체입금/", memo=None,
                      doc_id="400579347", voucher_kind="YAK",
                      tx_amount=Decimal("55000")))
        db.add(_entry(1, unique_field="UF1", jeokyo="400576463/대체입금/",
                      memo=None, doc_id="400576463", voucher_kind="YAK",
                      tx_amount=Decimal("55000")))
        db.commit()
        service = DepositVoucherService(db)
        routed: dict[str, list[str]] = {"yak": [], "branch": []}
        monkeypatch.setattr(
            service, "_kb_office",
            lambda yak_no: {"400579347": "22", "400576463": "10"}[yak_no],
        )
        monkeypatch.setattr(
            service, "_send_yak_bundles",
            lambda entries, counts: routed["yak"].extend(
                e.doc_id for e in entries
            ),
        )
        monkeypatch.setattr(
            service, "_send_branch_bundles",
            lambda entries, counts: routed["branch"].extend(
                e.doc_id for e in entries
            ),
        )
        service.send_pending(limit=10, include_yak=True)

    assert routed == {"yak": ["400576463"], "branch": ["400579347"]}
