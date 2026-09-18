"""아마란스 삭제 동기화 — 전송완료(S) 전표를 api11A16과 대조해 X로 닫는다.

아마란스에서 전표를 삭제해도 MOA로 신호가 없어 6·7번이 고아로 남았던 건
(2026-08-14)의 재발 방지. 판정 근거: 승인(발행)된 자동전표도 api11A16에
남는 것을 실측으로 확인했으므로 '조회 결과에 없음 = 삭제'다.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.card_voucher import CardVoucher, CardVoucherItem
from app.services.card_voucher_service import CardVoucherService


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CardVoucher.__table__.create(engine)
    CardVoucherItem.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class _StubClient:
    """api11A16 응답 스텁 — 날짜(frDt)별 menuSq 목록을 돌려준다."""

    def __init__(self, by_date: "dict[str, list[int]]",
                 fail_dates: "set[str] | None" = None):
        self.by_date = by_date
        self.fail_dates = fail_dates or set()
        self.calls: "list[str]" = []

    def post(self, endpoint, json_body=None, timeout=None):
        day = json_body["frDt"]
        self.calls.append(day)
        if day in self.fail_dates:
            raise RuntimeError("아마란스 조회 실패")
        return {"resultData": {"datas": [
            {"menuSq": sq} for sq in self.by_date.get(day, [])
        ]}}


# sqlite는 BigInteger PK를 자동 채번하지 않아 id를 직접 준다
def _voucher(vid: int, day: date, *, status: str = "S",
             checked: "datetime | None" = None) -> CardVoucher:
    return CardVoucher(
        id=vid, voucher_date=day, division_code="1000", menu_sq=10000 + vid,
        item_count=1, total_amount=Decimal("1000"), status=status,
        amaranth_checked_at=checked,
    )


def _item(iid: int, vid: int) -> CardVoucherItem:
    return CardVoucherItem(
        id=iid, voucher_id=vid, dedup_key=f"KEY-{vid}-{iid}",
        card_no="5404978001283967", use_date="20260731",
        total=Decimal("1000"), supply=Decimal("909"), vat=Decimal("91"),
    )


def _service(db, client) -> CardVoucherService:
    service = CardVoucherService(db, client=client)
    service._company_code = "1000"  # 회사코드 조회 API 생략
    return service


def test_아마란스에_없는_전송완료_전표는_X로_닫고_건을_풀어준다(db):
    day = date(2026, 7, 31)
    db.add(_voucher(6, day))            # 아마란스에서 삭제됨
    db.add(_voucher(9, day))            # 잔존 (menu_sq 10009)
    db.add(_item(1, 6))
    db.add(_item(2, 9))
    db.commit()
    client = _StubClient({"20260731": [10009, 1001]})

    result = _service(db, client).sync_amaranth_deleted()

    assert result["checked"] == 2
    assert [d["id"] for d in result["deleted"]] == [6]
    gone = db.get(CardVoucher, 6)
    kept = db.get(CardVoucher, 9)
    assert gone.status == "X" and "삭제 확인" in gone.error_msg
    assert kept.status == "S" and kept.error_msg is None
    assert gone.amaranth_checked_at is not None
    assert kept.amaranth_checked_at is not None
    # X 전표의 건은 지워져 dedup_key가 풀린다 — 잔존 전표 건은 유지
    keys = set(db.scalars(select(CardVoucherItem.dedup_key)).all())
    assert keys == {"KEY-9-2"}


def test_조회_실패한_날짜는_판정하지_않는다(db):
    db.add(_voucher(6, date(2026, 7, 31)))
    db.add(_item(1, 6))
    db.commit()
    client = _StubClient({}, fail_dates={"20260731"})

    result = _service(db, client).sync_amaranth_deleted()

    assert result["checked"] == 0 and result["deleted"] == []
    voucher = db.get(CardVoucher, 6)
    assert voucher.status == "S" and voucher.amaranth_checked_at is None


def test_오래_안_본_전표일자부터_상한만큼만_검사한다(db):
    # 미검사(NULL)와 과거 검사 순으로 상한(SYNC_MAX_DATES=5)까지만 조회한다
    for offset in range(7):
        db.add(_voucher(
            offset + 1, date(2026, 7, 1 + offset),
            checked=None if offset < 6 else datetime(2026, 8, 1),
        ))
    db.commit()
    client = _StubClient({
        f"202607{day:02d}": [10000 + vid]
        for vid, day in ((i + 1, 1 + i) for i in range(7))
    })

    result = _service(db, client).sync_amaranth_deleted()

    assert result["checked"] == 5
    assert len(client.calls) == 5
    # 최근 검사된 전표(7번)는 이번 회차에서 빠진다
    assert "20260707" not in client.calls


def test_초안과_실패_전표는_검사하지_않는다(db):
    db.add(_voucher(1, date(2026, 7, 31), status="D"))
    db.add(_voucher(2, date(2026, 7, 31), status="F"))
    db.commit()
    client = _StubClient({"20260731": []})

    result = _service(db, client).sync_amaranth_deleted()

    assert result["checked"] == 0 and result["deleted"] == []
    assert client.calls == []


def test_확정된_전표는_기본_당일치만_보여준다(db):
    """2026-08-20 사용자 요청 — 기본 당일, 기간 조회로 지난 것을 본다.

    자르는 기준은 전표일자가 아니라 확정일(만든 날)이다. 카드전표는 지난 날짜를
    소급해 만드는 일이 잦아(7월분을 8월에 확정) 전표일자로 자르면 방금 만든 것이
    안 보인다.
    """
    today = date.today()

    def _v(vid, made, status, day=date(2026, 7, 7)):
        voucher = _voucher(vid, day, status=status)
        voucher.created_at = made
        return voucher

    db.add(_v(1, datetime.combine(today, datetime.min.time()) + timedelta(hours=9), "S"))
    db.add(_v(2, datetime(2026, 7, 1, 10, 0), "S"))   # 지난 것, 전송 끝 → 안 보임
    db.add(_v(3, datetime(2026, 7, 1, 10, 0), "F"))   # 지난 것, 실패 → 안 보이되 알림
    db.add(_v(5, datetime.combine(today, datetime.min.time()) + timedelta(hours=10),
              "S", day=date(2026, 6, 1)))            # 전표일자는 옛날, 오늘 만든 것
    db.commit()
    service = CardVoucherService(db, client=object())

    result = service.list_drafts()

    assert {row["id"] for row in result["items"]} == {1, 5}
    assert result["date_from"] == result["date_to"] == today.isoformat()
    assert result["outside"] == {"draft": 0, "failed": 1}, (
        "기간 밖에 남은 실패 전표를 알려주지 않으면 잊힌다"
    )


def test_확정된_전표를_기간으로_조회한다(db):
    def _v(vid, made, status):
        voucher = _voucher(vid, date(2026, 7, 7), status=status)
        voucher.created_at = made
        return voucher

    db.add(_v(1, datetime(2026, 7, 1, 10, 0), "S"))
    db.add(_v(2, datetime(2026, 7, 5, 23, 59), "S"))   # 종료일 끝시각까지 포함되어야 한다
    db.add(_v(3, datetime(2026, 7, 6, 0, 1), "S"))
    db.commit()
    service = CardVoucherService(db, client=object())

    result = service.list_drafts(date_from=date(2026, 7, 1), date_to=date(2026, 7, 5))

    assert {row["id"] for row in result["items"]} == {1, 2}

    # 시작·종료를 뒤집어 줘도 같은 기간으로 본다
    flipped = service.list_drafts(date_from=date(2026, 7, 5), date_to=date(2026, 7, 1))
    assert {row["id"] for row in flipped["items"]} == {1, 2}
