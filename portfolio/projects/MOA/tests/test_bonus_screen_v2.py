"""상여 화면 v2 (4단계) — 문자열 검사: 탭·API·마감 버튼·캐시 버전·구 화면 대피 경로."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "desktop" / "ui" / "bonus.html").read_text(encoding="utf-8")
JS = (ROOT / "desktop" / "ui" / "bonus.js").read_text(encoding="utf-8")
LEGACY_HTML = (ROOT / "desktop" / "ui" / "bonus-legacy.html").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
CONTEXT = (ROOT / "desktop" / "ui" / "context.js").read_text(encoding="utf-8")


def test_탭_넷과_마감_재개_버튼이_있다():
    for tab in ("shareholders", "associates", "summary", "held"):
        assert f'data-tab="{tab}"' in HTML
    for button in ("closeButton", "reopenButton", "settingsButton", "exportButton"):
        assert f'id="{button}"' in HTML
    assert 'id="deductDialog"' in HTML and 'id="overrideDialog"' in HTML


def test_v2_API_만_쓰고_구_API_는_안_쓴다():
    assert "/api/bonus/v2?period=" in JS
    assert "/api/bonus/v2/status" in JS and "/api/bonus/v2/export.xlsx?period=" in JS
    assert "/api/bonus/v2/deductions/" in JS and "/api/bonus/v2/overrides/" in JS
    assert "/api/bonus/v2/close/" in JS and "/api/bonus/v2/reopen/" in JS
    assert "/api/bonus?" not in JS and "/api/bonus/adjust" not in JS


def test_쓰기는_집행부이고_마감된_달은_잠긴다():
    assert "is_operations" in JS
    assert "report.status !== 'CLOSED'" in JS


def test_캐시_버전이_새로_붙었고_구_화면은_legacy_경로로_남는다():
    assert "bonus.js?v=20260827-8" in HTML
    assert "bonus-legacy.js?v=" in LEGACY_HTML and "bonus.js?v=" not in LEGACY_HTML
    assert '@app.get("/desktop/bonus-legacy", include_in_schema=False)' in MAIN
    assert "'/desktop/bonus-legacy': 'bonus'" in CONTEXT


def test_공제_창에_지급액_미리보기가_있고_표_헤더_폭을_조절할_수_있다():
    assert 'id="deductPreview"' in HTML and "bonus-calc.js?v=" in HTML
    assert 'id="bonusCols"' in HTML                                     # colgroup 이 있어야 A10_COLUMN_RESIZE 가 붙는다
    assert "window.A10_COLUMN_RESIZE($('bonusTable')" in JS
    assert "BonusCalc.preview(report, person, selectedDeductions())" in JS
    assert "now.payment < 0 ? 'neg'" in JS                              # 음수면 빨간 글씨


def test_본사만_쓴다():
    assert "ctx.office_id !== '10'" in JS


def test_검색_탭에서_여러_달을_감정서번호_유치자로_찾는다():
    """2026-08-27 사용자 요청 — 지급월 구간(~), 감정서번호·유치자 부분 일치 검색."""
    assert 'data-tab="search"' in HTML
    for field in ("periodTo", "docFilter", "personFilter"):
        assert f'id="{field}"' in HTML
    assert "/api/bonus/v2/search?" in JS
    assert "held_reason" in JS, "보류 행도 사유와 함께 검색에 나와야 한다"


def test_선지급_탭과_감정서_추가_창이_있다():
    assert 'data-tab="advances"' in HTML and 'id="docDialog"' in HTML
    assert "/api/bonus/v2/deduction-items?kind=ADVANCE_PAID" in JS
    assert "/api/bonus/v2/docs?person=" in JS and "add-doc-button" in JS
    assert "actions: { ...current, INCLUDE: null }" in JS                   # 추가 = INCLUDE 오버라이드
