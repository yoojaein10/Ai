"""전기이월 해 넘기기와 '이월 없으면 안 보낸다' 안전장치 (2026-08-24 사용자 요청).

왜 있나
    계정별원장의 전일이월은 전기이월 + 그 해 누계다. 전기이월은 2026년치 하나를
    사람이 아마란스 화면을 보고 적어 넣은 것뿐인데, build_ledger 는 그 해 이월이
    없으면 **0 으로 두고 원장을 그대로 낸다.**

    그래서 아무도 손대지 않으면 2027-01-01 부터 지사 원장의 전일이월이 전부 틀린
    채로 지사에 나간다. 숫자만 봐서는 아무도 모른다 — 가장 나쁜 종류의 오류다.

    막는 방법은 둘이다.
        ① scripts/roll_account_opening.py 로 새해 이월을 만든다
        ② 그 해 이월이 없는 계정은 **보내지 않는다**(라우터 fail-closed)
    ①을 잊어도 ②가 잡는다.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.account_opening import AccountOpening
from scripts.roll_account_opening import roll

ROOT = Path(__file__).resolve().parent.parent
ROUTER = (ROOT / "app" / "routers" / "account_ledger.py").read_text(encoding="utf-8")
UI = ROOT / "desktop" / "ui"

# 파이썬 3.12 부터 sqlite 가 date 를 자동 변환하지 않는다(경고). 시험에서만 쓰는
# 변환이라 여기서 붙여 둔다 — 운영은 MSSQL 이라 해당 없다.
sqlite3.register_adapter(date, lambda value: value.isoformat())

# 전표 캐시는 운영에서 dbo. 로 부른다. sqlite 에는 스키마가 없으므로 같은 이름의
# 메모리 DB 를 dbo 로 붙여 준다 — 그래야 운영과 **같은 쿼리**를 시험할 수 있다.
_CACHE_DDL = """
CREATE TABLE dbo.a10_voucher_cache (
    voucher_date DATE, division_code TEXT, account_code TEXT,
    debit_credit TEXT, amount NUMERIC
)
"""


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[AccountOpening.__table__])
    session = sessionmaker(bind=engine, future=True)()
    session.execute(text("ATTACH DATABASE ':memory:' AS dbo"))
    session.execute(text(_CACHE_DDL))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _opening(db, code, year, debit, credit=0):
    db.add(AccountOpening(account_code=code, fiscal_year=year, debit=debit, credit=credit))
    db.commit()


def _line(db, code, day, kind, amount, division="1000"):
    db.execute(text(
        "INSERT INTO dbo.a10_voucher_cache "
        "(voucher_date, division_code, account_code, debit_credit, amount) "
        "VALUES (:d, :div, :acct, :dc, :amt)"
    ), {"d": day, "div": division, "acct": code, "dc": kind, "amt": amount})
    db.commit()


def _saved(db, code, year):
    row = db.scalars(
        select(AccountOpening).where(
            AccountOpening.account_code == code, AccountOpening.fiscal_year == year
        )
    ).first()
    return None if row is None else float(row.debit) - float(row.credit)


# ── 해 넘기기 ───────────────────────────────────────────────────────────

def test_새해_이월은_지난해_이월에_그_해_증감을_더한_값이다(db_session):
    """전기이월(2027) = 전기이월(2026) + 2026 차변 - 2026 대변."""
    _opening(db_session, "1410011", 2026, -46_529_401)
    _line(db_session, "1410011", date(2026, 3, 2), "3", 1_000_000)
    _line(db_session, "1410011", date(2026, 9, 9), "4", 250_000)

    roll(db_session, 2027)

    assert _saved(db_session, "1410011", 2027) == -46_529_401 + 1_000_000 - 250_000


def test_그_해_밖의_전표는_섞이지_않는다(db_session):
    """작년 12월 31일과 새해 1월 1일이 한 칸 어긋나면 이월이 통째로 틀린다."""
    _opening(db_session, "1410011", 2026, 0)
    _line(db_session, "1410011", date(2025, 12, 31), "3", 500)   # 재작년
    _line(db_session, "1410011", date(2026, 1, 1), "3", 7)       # 첫날 — 포함
    _line(db_session, "1410011", date(2026, 12, 31), "3", 70)    # 마지막날 — 포함
    _line(db_session, "1410011", date(2027, 1, 1), "3", 900)     # 새해

    roll(db_session, 2027)

    assert _saved(db_session, "1410011", 2027) == 77


def test_다른_회계단위_전표는_세지_않는다(db_session):
    _opening(db_session, "1410011", 2026, 0)
    _line(db_session, "1410011", date(2026, 5, 1), "3", 100)
    _line(db_session, "1410011", date(2026, 5, 1), "3", 900, division="2000")

    roll(db_session, 2027)

    assert _saved(db_session, "1410011", 2027) == 100


def test_이미_있는_해는_덮어쓰지_않는다(db_session):
    """아마란스를 보고 손으로 맞춰 둔 값을 배치가 조용히 지우면 안 된다."""
    _opening(db_session, "1410011", 2026, 1_000)
    _opening(db_session, "1410011", 2027, 999)
    _line(db_session, "1410011", date(2026, 5, 1), "3", 500)

    result = roll(db_session, 2027)

    assert _saved(db_session, "1410011", 2027) == 999
    assert [i["account_code"] for i in result["skipped"]] == ["1410011"]
    assert result["written"] == []


def test_force_면_덮어쓴다(db_session):
    """소급 전표가 들어와 값이 달라졌을 때 다시 굳히는 길이 있어야 한다."""
    _opening(db_session, "1410011", 2026, 1_000)
    _opening(db_session, "1410011", 2027, 999)
    _line(db_session, "1410011", date(2026, 5, 1), "3", 500)

    roll(db_session, 2027, force=True)

    assert _saved(db_session, "1410011", 2027) == 1_500


def test_dry_run_은_저장하지_않는다(db_session):
    _opening(db_session, "1410011", 2026, 1_000)
    _line(db_session, "1410011", date(2026, 5, 1), "3", 500)

    result = roll(db_session, 2027, dry_run=True)

    assert _saved(db_session, "1410011", 2027) is None
    assert result["written"][0]["closing"] == 1_500


def test_명단에_없는_새_계정을_알려_준다(db_session):
    """새 지사가 생겼는데 이월 명단에 없으면 그 지사만 0 이월로 나간다."""
    _opening(db_session, "1410011", 2026, 0)
    _line(db_session, "1410011", date(2026, 5, 1), "3", 1)
    _line(db_session, "1410099", date(2026, 5, 1), "3", 1)   # 명단에 없는 141 계정

    result = roll(db_session, 2027)

    assert result["unknown"] == ["1410099"]


def test_지사가_아닌_계정은_경고하지_않는다(db_session):
    """본사·본지점(손익)은 이월을 두지 않는다. 매번 경고하면 진짜 새 지사가 묻힌다."""
    _opening(db_session, "1410011", 2026, 0)
    _line(db_session, "1410001", date(2026, 5, 1), "3", 1)
    _line(db_session, "1410017", date(2026, 5, 1), "4", 1)

    result = roll(db_session, 2027)

    assert result["unknown"] == []


def test_지난해_이월이_아예_없으면_멈춘다(db_session):
    """근거 없이 0 에서 시작한 이월을 만들면 그게 더 위험하다."""
    with pytest.raises(SystemExit):
        roll(db_session, 2027)


# ── 안전장치 ────────────────────────────────────────────────────────────

def test_전기이월이_없으면_보내지_않는다():
    """이월이 없으면 전일이월이 0 부터 시작한다 — 원장이 통째로 틀린 채 나간다."""
    assert 'if not ledger["opening"]["known"]:' in ROUTER
    assert "전기이월이 없습니다" in ROUTER
    # 실패로 로그에 남아야 나중에 '안 보냈다'를 확인할 수 있다
    block = ROUTER[ROUTER.index('if not ledger["opening"]["known"]:'):]
    assert 'status="FAILED"' in block[:900]


def test_미리보기에도_눈에_띄게_알린다():
    js = (UI / "account-ledger.js").read_text(encoding="utf-8")
    html = (UI / "account-ledger.html").read_text(encoding="utf-8")

    assert "opening && p.data.opening.known" in js
    assert "전기이월이 없습니다" in js
    assert ".al-warn{" in html
    assert "account-ledger.js?v=20260824-5" in html, "JS 를 고쳤으면 ?v= 를 올린다"


# ── 예약 작업 ───────────────────────────────────────────────────────────

def test_해마다_1월_2일에_저절로_돈다():
    """사람이 잊어도 굴러가야 한다 — 1월 첫 발송 전에 이월이 만들어진다."""
    deploy = (ROOT / "scripts" / "server_redeploy.ps1").read_text(encoding="utf-8")

    assert '/tn "A10Bridge_AccountOpeningRoll" /sc monthly /m JAN /d 2' in deploy
    assert "run_account_opening_roll.cmd" in deploy
    # 로그가 없으면 돌았는지 안 돌았는지 알 수 없다
    assert "logs" + chr(92) + "account_opening_roll.log" in deploy


def test_배치는_연도를_주지_않는다():
    """1월 2일에 도는 작업이 연도를 계산하지 않아도 되게 기본값이 올해다."""
    deploy = (ROOT / "scripts" / "server_redeploy.ps1").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "roll_account_opening.py").read_text(encoding="utf-8")

    assert "-m scripts.roll_account_opening >>" in deploy, "배치는 --year 없이 부른다"
    assert 'default=date.today().year' in script
    # 배치가 멋대로 덮어쓰면 손으로 맞춘 값이 사라진다
    assert "--force" not in deploy.split("run_account_opening_roll.cmd")[-1][:400]
