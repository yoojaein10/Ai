"""거래처 캐시 — 가맹점 조회를 아마란스 왕복 대신 우리 DB에서 끝낸다.

한 건씩 묻던 방식은 한 달치 카드내역에 2분이 걸렸다(2026-08-20 실측).
캐시는 빠르게 하는 장치라, 비었거나 낡아도 호출부가 아마란스로 되돌아갈 수
있어야 한다 — 그래서 '없으면 그냥 빠진다'가 규칙이다.
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.partner_cache import PartnerCache
from app.services import partner_cache as pc


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    PartnerCache.__table__.create(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class _StubClient:
    """api16S11 페이지 응답 스텁."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = 0

    def post(self, endpoint, json_body=None, timeout=None):
        self.calls += 1
        index = int(json_body["pagingOffset"]) // pc.PAGE_SIZE
        rows = self.pages[index] if index < len(self.pages) else []
        return {"resultData": rows}


def _row(code, reg, name, *, use="1", fg="1"):
    return {"trCd": code, "regNb": reg, "trNm": name, "useYn": use, "trFg": fg}


def test_사업자번호로_거래처를_찾는다(db):
    db.add_all([
        PartnerCache(partner_code="0000000001", reg_no="1118513651",
                     partner_name="에이치베이커리", use_yn="1"),
        PartnerCache(partner_code="0000000002", reg_no="4840300117",
                     partner_name="정진식당", use_yn="1"),
    ])
    db.commit()

    found = pc.find_partners_by_reg_no(db, {"1118513651", "4840300117", "9999999999"})

    assert found["1118513651"]["code"] == "0000000001"
    assert found["4840300117"]["name"] == "정진식당"
    assert "9999999999" not in found, "캐시에 없으면 빠져야 호출부가 아마란스에 묻는다"


def test_같은_사업자번호면_사용중을_먼저_고른다(db):
    """미사용 거래처를 물려주면 전송이 '미사용 거래처'로 막힌다 (7/7 전표 실사고)."""
    db.add_all([
        PartnerCache(partner_code="0000009999", reg_no="1118513651",
                     partner_name="폐지된 지점", use_yn="0"),
        PartnerCache(partner_code="0000000001", reg_no="1118513651",
                     partner_name="현재 지점", use_yn="1"),
    ])
    db.commit()

    found = pc.find_partners_by_reg_no(db, {"1118513651"})

    assert found["1118513651"]["code"] == "0000000001", "코드가 커도 미사용이면 안 된다"


def test_사용중이_여럿이면_최근_등록분을_쓴다(db):
    db.add_all([
        PartnerCache(partner_code="0000000001", reg_no="1118513651",
                     partner_name="옛 등록", use_yn="1"),
        PartnerCache(partner_code="0000000007", reg_no="1118513651",
                     partner_name="새 등록", use_yn="1"),
    ])
    db.commit()

    assert pc.find_partners_by_reg_no(db, {"1118513651"})["1118513651"]["name"] == "새 등록"


def test_짧은_사업자번호는_묻지도_않는다(db):
    assert pc.find_partners_by_reg_no(db, {"123", ""}) == {}


def test_전체를_받아_캐시를_갈아끼운다(db):
    db.add(PartnerCache(partner_code="8888888888", reg_no="7777777777",
                        partner_name="지난 회차 잔재", use_yn="1"))
    db.commit()
    pages = [
        [_row(f"{i:010d}", f"{1000000000 + i}", f"거래처{i}") for i in range(pc.PAGE_SIZE)],
        [_row("9999999999", "1118513651", "마지막 거래처")],
    ]

    result = pc.refresh_partner_cache(db, _StubClient(pages), "1000", progress=lambda m: None)

    assert result["stored"] == pc.PAGE_SIZE + 1
    codes = set(db.execute(select(PartnerCache.partner_code)).scalars())
    assert "8888888888" not in codes, "지난 회차 잔재가 남으면 사라진 거래처를 계속 물려준다"
    assert "9999999999" in codes


def test_빈_응답이면_멀쩡한_캐시를_지우지_않는다(db):
    """아마란스가 한 회차 삐끗했다고 캐시를 비우면 그날 조회가 통째로 느려진다."""
    db.add(PartnerCache(partner_code="0000000001", reg_no="1118513651",
                        partner_name="에이치베이커리", use_yn="1"))
    db.commit()

    with pytest.raises(RuntimeError):
        pc.refresh_partner_cache(db, _StubClient([[]]), "1000", progress=lambda m: None)

    assert pc.cache_status(db)["rows"] == 1, "실패해도 옛 캐시는 남아야 한다"


def test_캐시가_최근이면_없는_것도_안_묻는다(db):
    """캐시는 거래처 전체를 담으므로 '여기 없다'가 곧 '아마란스에 없다'다.

    2026-08-20 실측: 19일치에서 못 찾은 117곳이 전부 진짜 미등록이었고,
    그걸 확인하는 왕복에만 26초를 썼다. 결과는 1,043건 전부 같았다.
    """
    from datetime import timedelta

    assert not pc.is_fresh(db), "빈 캐시는 믿으면 안 된다"

    db.add(PartnerCache(partner_code="0000000001", reg_no="1118513651",
                        partner_name="에이치베이커리", use_yn="1",
                        synced_at=datetime.now()))
    db.commit()
    assert pc.is_fresh(db)

    db.query(PartnerCache).update(
        {PartnerCache.synced_at: datetime.now() - timedelta(hours=pc.FRESH_HOURS + 1)}
    )
    db.commit()
    assert not pc.is_fresh(db), "낡은 캐시로 '없음'을 단정하면 새 가맹점이 보류로 잘못 뜬다"
