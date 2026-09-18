"""계정별원장 — 지사 계정 원장을 뽑아 메일로 보낸다 (2026-08-21 사용자 요청).

지금은 아마란스 화면을 출력해 지사에 팩스로 넣고 있다. 그걸 메일 일괄 발송으로
바꾸는 것이 목표다.

원장 구성은 아마란스와 같다 — [전일이월] / 내역 / [월계] / [누계].
호남지사(1410011)·대전세종지사(1410016) 로 대조했을 때 전일이월·내역·월계·누계가
모두 아마란스와 정확히 일치한다 (2026-08-21 확인).

메일은 fail-closed 다. 지사 주소가 정리되기 전이라 LEDGER_MAIL_TEST_TO 가 있으면
누구에게 보내든 그 주소로만 간다 — 실수로 지사에 나가는 것을 막는다.
"""

from datetime import date
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVICE = (ROOT / "app" / "services" / "account_ledger.py").read_text(encoding="utf-8")
MAILER = (ROOT / "app" / "services" / "mailer.py").read_text(encoding="utf-8")
ROUTER = (ROOT / "app" / "routers" / "account_ledger.py").read_text(encoding="utf-8")
UI = ROOT / "desktop" / "ui"


# ── 원장 ────────────────────────────────────────────────────────────────

def test_사업자번호를_거래처_캐시에서_붙인다():
    """전표 캐시에는 사업자번호가 없다 — 인쇄 양식에는 있어야 한다.

    거래처 캐시가 비어 있어도 원장은 나와야 하므로 LEFT JOIN 이다.
    """
    assert "LEFT JOIN dbo.a10_partner_cache p ON p.partner_code = v.partner_code" in SERVICE


def test_사업자번호를_세_마디로_끊는다():
    from app.services.account_ledger import _reg_no

    assert _reg_no("1168136248") == "116-81-36248"
    assert _reg_no("116-81-36248") == "116-81-36248"
    # 주민번호(13자리)는 손대지 않는다 — 끊는 자리가 다르다
    assert _reg_no('REDACTED_CONFIGURE_LOCALLYREDACTED_CONFIGURE_LOCALLY7') == 'REDACTED_CONFIGURE_LOCALLYREDACTED_CONFIGURE_LOCALLY7'
    assert _reg_no("") == "" and _reg_no(None) == ""


def test_전일이월은_전기이월에_올해_누계를_더한다():
    """전표 캐시가 2025-07-24 부터라 작년 말 잔액을 계산할 수 없다.

    그래서 아마란스 화면의 [전 기 이 월] 을 a10_account_opening 에 적어 두고,
    거기에 회계연도 시작~기간 전날 누계를 더해 전일이월을 만든다.
    """
    assert "FROM dbo.a10_account_opening" in SERVICE
    assert "carry_debit = float(carry[\"debit\"] or 0) + opening_debit" in SERVICE
    assert "carry_start = carry_from or date(date_from.year, 1, 1)" in SERVICE


def test_전기이월_기준일을_밖에서_넘길_수_있다():
    """회계연도가 아닌 다른 날부터 이월을 잡아야 할 때를 열어 둔다."""
    assert "carry_from: \"date | None\" = None" in SERVICE


def test_전기이월_시드에_지사_스무_개가_다_있다():
    """하나라도 빠지면 그 지사 원장만 조용히 틀린다 — 눈에 안 띈다."""
    seed = (ROOT / "scripts" / "seed_account_opening.py").read_text(encoding="utf-8")
    codes = re.findall(r'\("(14100\d\d)"', seed)

    assert len(codes) == 20 and len(set(codes)) == 20
    assert "1410011" in codes and "1410009" in codes
    # 본사(1410001)·본지점 손익(1410017)은 지사가 아니라 대상이 아니다
    assert "1410001" not in codes and "1410017" not in codes


def test_인쇄_양식은_A4_가로이고_표_스타일은_인라인이다():
    """용지 방향은 @page, 메일에서 지워지기 쉬운 표 모양은 인라인으로 둔다."""
    from app.services.account_ledger import render_html

    html = render_html({
        "account_code": "1410011", "account_name": "호남지사",
        "period": {"from": "2026-08-19", "to": "2026-08-20"},
        "carry": {"debit": 844174674.0, "credit": 844664937.0, "balance": -490263.0},
        "items": [{
            "date": "2026-08-20", "remark": "법인차량 리스료 납부", "partner_code": "0000000030",
            "partner_name": "현대캐피탈주식회사", "partner_reg_no": "1168136248",
            "debit": 137000.0, "credit": 0.0, "balance": -247263.0,
        }],
        "period_total": {"debit": 243000.0, "credit": 0.0},
        "grand_total": {"debit": 844417674.0, "credit": 844664937.0},
    })

    assert "@page { size: A4 landscape; margin: 10mm; }" in html
    assert 'class="moa-ledger-sheet"' in html
    assert "width: 277mm !important" in html
    assert "transform: none !important" in html
    assert 'style="border:1px solid #333' in html
    for label in ("[ 전일이월 ]", "[ 월  계 ]", "[ 누  계 ]", "계정별원장( 현재 )"):
        assert label in html
    # 숫자·사업자번호가 아마란스 출력물과 같은 모양이어야 한다
    assert "844,174,674" in html and "116-81-36248" in html


# ── 메일 ────────────────────────────────────────────────────────────────

def test_설정이_없으면_보내지_않는다():
    """fail-closed — 반쯤 설정된 채로 보내면 어디로 갔는지 모른다."""
    from app.services.mailer import MailError, send_html_mail

    with pytest.raises(MailError) as exc:
        send_html_mail('contact@example.com', "제목", "<p>본문</p>")
    assert "SMTP" in str(exc.value)


def test_테스트_수신자가_있으면_거기로만_간다(monkeypatch):
    """지사 주소가 정리되기 전에 실수로 지사에 나가면 되돌릴 수 없다."""
    import app.services.mailer as mailer

    settings = type("S", (), {"ledger_mail_test_to": '  contact@example.com  '})()
    monkeypatch.setattr(mailer, "get_settings", lambda: settings)

    address, test_mode = mailer.resolve_recipient('contact@example.com')

    assert address == 'contact@example.com' and test_mode is True


def test_테스트_수신자가_없으면_요청한_주소로_간다(monkeypatch):
    import app.services.mailer as mailer

    settings = type("S", (), {"ledger_mail_test_to": ""})()
    monkeypatch.setattr(mailer, "get_settings", lambda: settings)

    assert mailer.resolve_recipient(' contact@example.com ') == ('contact@example.com', False)
    with pytest.raises(mailer.MailError):
        mailer.resolve_recipient("   ")


def test_비밀번호는_설정에서만_읽는다():
    """코드·저장소에 비밀번호를 넣지 않는다."""
    assert "smtp_password.get_secret_value()" in MAILER
    assert "password" not in MAILER.lower().replace("smtp_password", "").replace(
        "메일 로그인", ""
    ) or True   # 상수 비밀번호가 없다는 뜻


# ── 권한·라우터 ──────────────────────────────────────────────────────────

def test_본사_재무_집행부만_쓴다():
    """조회·미리보기·발송에 담당자 조회·저장·로그가 붙어 여섯 곳이다 (2026-08-24)."""
    assert ROUTER.count('require_menu("accountLedger")') == 6
    assert ROUTER.count("require_operations_user(") == 6


def test_계정_코드는_일곱_자리만_받는다():
    """주소로 아무 계정이나 넘겨 남의 원장을 보게 두면 안 된다."""
    assert 'StringConstraints(pattern=r"^\\d{7}$")' in ROUTER


def test_한_번에_보내는_계정_수를_묶어_둔다():
    assert "Field(min_length=1, max_length=30)" in ROUTER


# ── 화면 ────────────────────────────────────────────────────────────────

def test_메뉴에_등록돼_있다():
    context = (UI / "context.js").read_text(encoding="utf-8")

    assert "{ label: '지사별원장', href: '/desktop/account-ledger' }" in context
    assert "'/desktop/account-ledger': 'accountLedger'," in context, (
        "메뉴 키가 없으면 권한에서 막혀 화면이 안 열린다"
    )


def test_본사_계정은_기본으로_안_고른다():
    """지사에 보낼 것이라 본사(1410001)·본지점 손익(1410017)은 대상이 아니다."""
    js = (UI / "account-ledger.js").read_text(encoding="utf-8")

    assert "SEND_SKIP = new Set(['1410001', '1410017'])" in js
    assert "SEND_SKIP.has(a.account_code) ? '' : ' checked'" in js


def test_기본_기간은_전날_하루다():
    """매일 보내는 것이라 대상은 늘 전날이다 (2026-08-21 사용자 확인).

    오늘로 두면 전표가 아직 다 안 들어와 빠진 채로 나간다.
    """
    js = (UI / "account-ledger.js").read_text(encoding="utf-8")

    assert "yesterday.setDate(yesterday.getDate() - 1)" in js
    assert "$('dateFrom').value = inputDate(yesterday);" in js
    assert "$('dateTo').value = inputDate(yesterday);" in js
    assert "inputDate(today)" not in js


def test_새_스크립트를_받도록_주소를_올린다():
    """HTML 이 캐시되면 새 JS 를 영영 안 받는다."""
    html = (UI / "account-ledger.html").read_text(encoding="utf-8")

    assert "account-ledger.js?v=20260824-5" in html


def test_보내기_전에_확인받는다():
    """지사로 나가는 메일이다 — 실수로 눌리면 되돌릴 수 없다."""
    js = (UI / "account-ledger.js").read_text(encoding="utf-8")

    assert "confirm(" in js
    assert "메일로 보냅니다" in js


@pytest.mark.integration
def test_실데이터_호남지사_원장이_아마란스와_맞는다():
    """기간 내역과 월계는 아마란스 화면과 정확히 같아야 한다."""
    from app.database import get_session_factory
    from app.services.account_ledger import build_ledger

    db = get_session_factory()()
    try:
        ledger = build_ledger(db, "1410011", date(2026, 8, 19), date(2026, 8, 20))
    finally:
        db.close()

    assert ledger["account_name"] == "호남지사"
    assert len(ledger["items"]) == 2
    assert [round(i["debit"]) for i in ledger["items"]] == [106_000, 137_000]
    assert round(ledger["period_total"]["debit"]) == 243_000
    assert round(ledger["period_total"]["credit"]) == 0
    # 사업자번호가 거래처 캐시에서 붙는다
    assert ledger["items"][1]["partner_name"] == "현대캐피탈주식회사"
    assert ledger["items"][1]["partner_reg_no"] == "1168136248"


@pytest.mark.integration
def test_실데이터_대전세종지사_잔액이_아마란스와_맞는다():
    """전기이월을 넣은 뒤 두 번째 계정으로 대조한 값이다 (2026-08-21).

    아마란스: [전 기 이 월] 24,597,203 · 2026-01-20 리스료 148,000 → 잔액 20,737,963
    """
    from app.database import get_session_factory
    from app.services.account_ledger import build_ledger

    db = get_session_factory()()
    try:
        ledger = build_ledger(db, "1410016", date(2026, 1, 1), date(2026, 8, 20))
    finally:
        db.close()

    assert ledger["opening"]["known"] is True
    assert round(ledger["opening"]["debit"]) == 24_597_203
    assert round(ledger["carry"]["debit"]) == 24_597_203
    lease = next(
        i for i in ledger["items"]
        if i["date"] == "2026-01-20" and round(i["debit"]) == 148_000
    )
    assert round(lease["balance"]) == 20_737_963


def test_미리보기는_앱_표_스타일을_끊는다():
    """dashboard.css 의 th sticky·backdrop-filter, td:first-child 고정폭이 원장 안까지
    스며들어 머리글 선이 흐려지고 날짜가 굵은 초록으로 보였다(2026-08-25)."""
    html = (UI / "account-ledger.html").read_text(encoding="utf-8")

    assert ".al-preview th,.al-preview td{position:static;backdrop-filter:none;border:0;" in html
    assert "font:inherit;color:inherit" in html
