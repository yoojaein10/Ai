"""계정별원장 메일 — 지사별 담당자 표와 발송 로그 (2026-08-24 사용자 요청).

왜 있나
    원장을 보낼 주소를 화면에서 손으로 한 번에 하나씩 적고 있었다. 계정이 20개인데
    누가 어느 지사 담당인지는 어디에도 없었고, 보냈는지 여부도 남지 않았다.
    지사가 "못 받았다"고 하면 확인할 방법이 아예 없었다.

    그래서 두 표를 둔다.
        a10_ledger_recipient   지사 계정 → 담당자(받는사람 TO · 참조 CC)
        a10_ledger_mail_log    한 통이 한 행. 성공·실패를 **모두** 남긴다.

    이력은 '있는 줄 알았는데 없는' 것이 가장 나쁘다 — 실패만 조용히 사라지면
    안 보낸 지사를 보낸 줄 안다. 그래서 실패도 남는지를 여기서 확인한다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.ledger_mail_log import LedgerMailLog
from app.models.ledger_recipient import LedgerRecipient
from app.services.ledger_mail import (
    addresses_for,
    list_logs,
    list_recipients,
    log_mail,
    save_recipients,
)

ROOT = Path(__file__).resolve().parent.parent
ROUTER = (ROOT / "app" / "routers" / "account_ledger.py").read_text(encoding="utf-8")
MAILER = (ROOT / "app" / "services" / "mailer.py").read_text(encoding="utf-8")
MIGRATION = (
    ROOT / "scripts" / "sql" / "20260824_create_ledger_mail.sql"
).read_text(encoding="utf-8")
UI = ROOT / "desktop" / "ui"


@pytest.fixture()
def db_session():
    """담당자 표 + 로그 표만 만든 인메모리 DB.

    StaticPool 이 꼭 필요하다 — sqlite 인메모리는 연결마다 빈 DB 가 새로 생긴다.
    """
    engine = create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        LedgerRecipient.__table__, LedgerMailLog.__table__,
    ])
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


def _people(*rows):
    return [{"name": n, "email": e, "kind": k, "memo": ""} for n, e, k in rows]


# ── 담당자 ──────────────────────────────────────────────────────────────

def test_계정마다_받는사람과_참조를_나눠_담는다(db_session):
    """지사 담당자는 한 명이 아니다 — 지사장이 참조로 들어가는 식이다."""
    save_recipients(db_session, "1410011", _people(
        ("김호남", 'contact@example.com', "TO"),
        ("이경리", 'contact@example.com', "TO"),
        ("지사장", 'contact@example.com', "CC"),
    ), usr_seq=2012)

    addresses = addresses_for(db_session, "1410011")

    assert addresses["to"] == ['contact@example.com', 'contact@example.com']
    assert addresses["cc"] == ['contact@example.com']


def test_다른_계정의_담당자는_섞이지_않는다(db_session):
    """섞이면 부산지사 원장이 호남지사로 간다 — 되돌릴 수 없는 사고다."""
    save_recipients(db_session, "1410011", _people(("김호남", 'contact@example.com', "TO")))
    save_recipients(db_session, "1410009", _people(("박부산", 'contact@example.com', "TO")))

    assert addresses_for(db_session, "1410011")["to"] == ['contact@example.com']
    assert addresses_for(db_session, "1410009")["to"] == ['contact@example.com']


def test_담당자가_없는_계정은_주소가_비어_있다(db_session):
    """빈 주소로는 안 보낸다(fail-closed) — 라우터가 이걸 보고 실패로 남긴다."""
    assert addresses_for(db_session, "1410022") == {"to": [], "cc": []}


def test_같은_주소를_두_번_적어도_한_번만_들어간다(db_session):
    """두 줄로 저장되면 같은 사람에게 메일이 두 통 간다."""
    save_recipients(db_session, "1410011", _people(
        ("김호남", 'contact@example.com', "TO"),
        ("김호남(중복)", 'contact@example.com', "CC"),
    ))

    assert addresses_for(db_session, "1410011") == {"to": ['contact@example.com'], "cc": []}


def test_뺀_담당자는_지우지_않고_비활성으로_남긴다(db_session):
    """누가 언제 빠졌는지는 남아야 한다 — 지워 버리면 확인할 근거가 없다."""
    save_recipients(db_session, "1410011", _people(
        ("김호남", 'contact@example.com', "TO"),
        ("이경리", 'contact@example.com', "TO"),
    ))

    save_recipients(db_session, "1410011", _people(("김호남", 'contact@example.com', "TO")))

    assert addresses_for(db_session, "1410011")["to"] == ['contact@example.com']
    rows = db_session.scalars(select(LedgerRecipient)).all()
    assert {(r.email, r.active) for r in rows} == {
        ('contact@example.com', "Y"), ('contact@example.com', "N"),
    }


def test_이름과_구분만_바꿔도_주소는_그대로다(db_session):
    """담당자가 바뀌면 이름만 고치는 일이 흔하다 — 그때 행이 늘면 안 된다."""
    save_recipients(db_session, "1410011", _people(("김호남", 'contact@example.com', "TO")))
    save_recipients(db_session, "1410011", _people(("박호남", 'contact@example.com', "CC")))

    people = list_recipients(db_session, "1410011")
    assert len(people) == 1
    assert people[0]["name"] == "박호남" and people[0]["kind"] == "CC"


def test_빈_목록으로_저장하면_그_지사는_안_나간다(db_session):
    """담당자를 통째로 비우는 것도 뜻이 있는 조작이다 — 조용히 무시하면 안 된다."""
    save_recipients(db_session, "1410011", _people(("김호남", 'contact@example.com', "TO")))

    save_recipients(db_session, "1410011", [])

    assert addresses_for(db_session, "1410011")["to"] == []


# ── 발송 로그 ───────────────────────────────────────────────────────────

def test_보낸_것과_실패한_것을_모두_남긴다(db_session):
    """실패만 사라지면 안 보낸 지사를 보낸 줄 안다."""
    log_mail(
        db_session, account_code="1410011", account_name="호남지사",
        date_from=date(2026, 8, 23), date_to=date(2026, 8, 23), status="SENT",
        to_email='contact@example.com', subject="[계정별원장] 1410011.호남지사",
        item_count=2, closing_balance=-490263.0, requested_by_usr_seq=2012,
    )
    log_mail(
        db_session, account_code="1410009", account_name="부산지사",
        date_from=date(2026, 8, 23), date_to=date(2026, 8, 23), status="FAILED",
        fail_reason="담당자가 없습니다 — 담당자 관리에서 주소를 넣어 주세요.",
    )

    logs = list_logs(db_session)

    assert [log["status"] for log in logs] == ["FAILED", "SENT"]   # 최근 것이 먼저
    assert logs[0]["fail_reason"].startswith("담당자가 없습니다")
    assert logs[1]["to_email"] == 'contact@example.com' and logs[1]["item_count"] == 2


def test_테스트_수신자로_돌아간_건은_구분해서_남는다(db_session):
    """test_mode 는 '지사는 못 받았다'는 뜻이다 — 보낸 것과 같아 보이면 안 된다."""
    log_mail(
        db_session, account_code="1410011", account_name="호남지사",
        date_from=date(2026, 8, 23), date_to=date(2026, 8, 23), status="SENT",
        to_email='contact@example.com', test_mode=True,
    )

    assert list_logs(db_session)[0]["test_mode"] is True


def test_계정으로_추려_볼_수_있다(db_session):
    """지사가 '언제 받았냐'고 물으면 그 계정만 본다."""
    for code in ("1410011", "1410009"):
        log_mail(
            db_session, account_code=code, account_name="",
            date_from=date(2026, 8, 23), date_to=date(2026, 8, 23), status="SENT",
        )

    logs = list_logs(db_session, account_code="1410011")

    assert len(logs) == 1 and logs[0]["account_code"] == "1410011"


# ── 라우터·메일러 ───────────────────────────────────────────────────────

def test_발송은_담당자_표에서_주소를_읽는다():
    assert "addresses_for(db, account_code)" in ROUTER
    # 직접 지정이 있으면 그 주소로만 간다 — 참조는 따라가지 않는다
    assert '{"to": [override], "cc": []} if override' in ROUTER


def test_성공도_실패도_로그에_남긴다():
    assert 'status="SENT"' in ROUTER and 'status="FAILED"' in ROUTER


def test_로그_기록이_실패해도_발송을_되돌리지_않는다():
    """이미 나간 메일은 되돌릴 수 없다 — 로그 실패로 500 을 내면 두 번 보낸다."""
    assert "def _log(db: Session, **fields) -> int:" in ROUTER
    assert "except SQLAlchemyError as exc:" in ROUTER
    assert "로그 기록 실패" in ROUTER


def test_담당자_변경은_본사_재무_집행부만_한다():
    assert ROUTER.count('require_menu("accountLedger")') == 6
    assert ROUTER.count("require_operations_user(") == 6


def test_테스트_수신자면_참조도_지운다():
    """참조만 지사로 나가면 테스트 수신자로 막은 의미가 없다."""
    assert 'cc_line = "" if test_mode else _join(cc or [])' in MAILER


def test_받는사람이_여럿이면_한_줄로_묶는다():
    from app.services.mailer import _join

    assert _join(['contact@example.com', ' contact@example.com ']) == 'contact@example.com, contact@example.com'
    assert _join('contact@example.com') == 'contact@example.com'
    assert _join(["", "  "]) == ""


# ── 마이그레이션 ────────────────────────────────────────────────────────

def test_같은_계정에_같은_주소가_두_번_들어가지_않는다():
    """유니크는 살아 있는 행끼리다 — 뺐던 사람을 다시 넣을 수 있어야 한다."""
    assert "CREATE UNIQUE INDEX UX_a10_ledger_recipient_account_email" in MIGRATION
    assert "(account_code, email) WHERE active = 'Y'" in MIGRATION


def test_표가_이미_있어도_인덱스를_채운다():
    """배포 스크립트(create_tables.py)가 먼저 돌아 표만 만들어 놓았을 수 있다."""
    assert MIGRATION.count("NOT EXISTS (SELECT 1 FROM sys.indexes") == 3
    assert "THROW 50012" in MIGRATION, "표가 없는데 '완료'만 찍히면 다 된 줄 안다"


# ── 화면 ────────────────────────────────────────────────────────────────

def test_담당자_없는_계정이_눈에_띈다():
    """20곳 중 한 곳만 비어도 그 지사만 조용히 안 나간다 — 안 보이면 모른다."""
    js = (UI / "account-ledger.js").read_text(encoding="utf-8")

    assert "담당자 없음" in js
    assert "담당자가 없어 빠지는 계정" in js, "보내기 전에 확인창에서 알려야 한다"


def test_발송_로그를_원장_화면에서_본다():
    html = (UI / "account-ledger.html").read_text(encoding="utf-8")
    js = (UI / "account-ledger.js").read_text(encoding="utf-8")

    for element in ("paneLedger", "viewLogs", "logRows"):
        assert element in html
    assert "'/api/account-ledger/logs?limit=200'" in js


def test_관리_버튼이_발송_줄_맨_오른쪽에_있다():
    """주소를 고치는 입구는 발송 줄의 '관리' 버튼 하나다 (2026-08-24 요청)."""
    html = (UI / "account-ledger.html").read_text(encoding="utf-8")

    assert '<button id="manageButton" class="al-manage"' in html
    assert html.index('id="sendButton"') < html.index('id="manageButton"'), "발송 버튼 뒤에 온다"
    assert "margin-left:auto" in html.split(".al-manage{")[1][:80], "줄 맨 오른쪽으로 민다"
    # 편집 칸은 관리 화면으로 옮겼다 — 두 곳에서 고치면 어느 쪽이 맞는지 헷갈린다
    assert "paneRecipients" not in html and "saveRecipients" not in html
    # 머리말 링크는 뺐다 — 같은 곳으로 가는 입구가 둘이면 헷갈린다
    assert '<a class="al-manage"' not in html


def test_관리_버튼은_보던_계정으로_데려간다():
    js = (UI / "account-ledger.js").read_text(encoding="utf-8")

    assert "$('manageButton').addEventListener" in js
    assert "'?account=' + encodeURIComponent(lastPreview)" in js
    # 담당자 배지는 이제 보여 주기만 한다
    assert "data-who" not in js


def test_새_스크립트를_받도록_주소를_올린다():
    """HTML 이 캐시되면 새 JS 를 영영 안 받는다 — 화면이 옛날 것으로 남는다."""
    html = (UI / "account-ledger.html").read_text(encoding="utf-8")

    assert "account-ledger.js?v=20260824-5" in html


# ── 주소 관리 화면 ──────────────────────────────────────────────────────

def test_관리_화면이_한_곳을_지나_열린다():
    """_screen() 을 안 거치면 HTML 이 캐시돼 새 JS 를 영영 안 받는다."""
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    assert '@app.get("/desktop/ledger-recipients", include_in_schema=False)' in main
    assert 'return _screen("ledger-recipients.html")' in main


def test_관리_화면도_계정별원장_권한으로_지킨다():
    """주소를 고치는 화면이 원장보다 헐거우면 안 된다."""
    context = (UI / "context.js").read_text(encoding="utf-8")

    assert "'/desktop/ledger-recipients': 'accountLedger'," in context


def test_고친_지사만_저장한다():
    """17곳을 매번 다 덮어쓰면 남이 방금 고친 주소를 되돌려 놓는다."""
    js = (UI / "ledger-recipients.js").read_text(encoding="utf-8")

    assert "const dirty = new Set();" in js
    assert "for (const code of Array.from(dirty))" in js


def test_주소_형식을_저장_전에_다_본다():
    """한 곳만 틀려도 그 지사만 조용히 빠진다 — 저장 전에 잡는다."""
    js = (UI / "ledger-recipients.js").read_text(encoding="utf-8")

    assert "MAIL.test(person.email)" in js
    assert "beforeunload" in js, "저장 안 하고 나가면 적어 둔 주소가 사라진다"


def test_관리_화면은_본사만_쓴다():
    js = (UI / "ledger-recipients.js").read_text(encoding="utf-8")

    assert "ctx.office_id !== '10'" in js
    assert "SEND_SKIP = new Set(['1410001', '1410017'])" in js


# ── 담당자 시드 ─────────────────────────────────────────────────────────

def test_시드에_지사_열일곱_곳이_다_있다():
    """한 곳이라도 빠지면 그 지사만 조용히 안 나간다 (2026-08-24 명단표)."""
    import re

    seed = (ROOT / "scripts" / "seed_ledger_recipient.py").read_text(encoding="utf-8")
    codes = re.findall(r'\("(14100\d\d)"', seed)

    assert len(codes) == 17 and len(set(codes)) == 17
    # 폐기된 (구) 계정과 본사·본지점 손익은 대상이 아니다
    for dead in ("1410001", "1410007", "1410012", "1410014", "1410017"):
        assert dead not in codes


def test_시드는_주소가_빈_담당자를_넣지_않는다():
    """반만 들어가고 '완료'만 찍히면 안 들어간 지사를 들어간 줄 안다."""
    seed = (ROOT / "scripts" / "seed_ledger_recipient.py").read_text(encoding="utf-8")

    assert "if not email:" in seed and "missing.append" in seed
    assert "이 지사는 발송되지 않는다" in seed
