"""상여 공제 대장 화면 — 문자열 검사: 라우트·권한 별칭·캐시 버전·API·쓰기 게이트, 그리고 상여 화면의 진입 버튼."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "desktop" / "ui" / "bonus-deductions.html").read_text(encoding="utf-8")
JS = (ROOT / "desktop" / "ui" / "bonus-deductions.js").read_text(encoding="utf-8")
BONUS_HTML = (ROOT / "desktop" / "ui" / "bonus.html").read_text(encoding="utf-8")
BONUS_JS = (ROOT / "desktop" / "ui" / "bonus.js").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
CONTEXT = (ROOT / "desktop" / "ui" / "context.js").read_text(encoding="utf-8")
ROUTER = (ROOT / "app" / "routers" / "bonus_v2.py").read_text(encoding="utf-8")


def test_라우트와_권한_별칭이_있고_캐시_버전이_붙는다():
    assert '@app.get("/desktop/bonus-deductions", include_in_schema=False)' in MAIN
    assert '_screen("bonus-deductions.html")' in MAIN
    assert "'/desktop/bonus-deductions': 'bonus'" in CONTEXT
    assert "bonus-deductions.js?v=" in HTML


def test_상여_화면에서_들어온다():
    assert 'id="ledgerButton"' in BONUS_HTML
    assert "location.href = '/desktop/bonus-deductions'" in BONUS_JS


def test_대장_API_만_쓰고_상태_전이는_서버에_맡긴다():
    assert "/api/bonus/v2/deduction-items?status=" in JS
    assert "'/api/bonus/v2/deduction-items'" in JS                      # POST 등록
    assert "/api/bonus/v2/deduction-items/${id}" in JS                   # PUT 수정
    assert "/api/bonus/v2/deduction-items/${id}/void" in JS              # 무효
    assert "/api/bonus/v2/deductions/${item.applied_period}/" in JS      # 대기로 되돌리기 = 적용 집합 교체
    assert "/api/bonus/v2/deduction-items/export.xlsx?" in JS


def test_본사_집행부만_쓰고_마감된_달은_잠긴다():
    assert "ctx.office_id !== '10' || !ctx.is_operations" in JS
    assert "isClosed(item.applied_period)" in JS
    assert "window.prompt" not in JS and "prompt(" not in JS            # 브라우저 모달 금지 — <dialog> 로


def test_내보내기는_집행부_게이트를_지나고_로그인_없이는_막힌다():
    assert '@router.get("/deduction-items/export.xlsx", response_model=None)' in ROUTER
    export_body = ROUTER[ROUTER.index('@router.get("/deduction-items/export.xlsx"'):ROUTER.index('@router.post("/deduction-items"')]
    assert "require_operations_user(access, _READ_MESSAGE)" in export_body
    client = TestClient(app)
    assert client.get("/api/bonus/v2/deduction-items/export.xlsx?status=PENDING").status_code in (401, 403)
    assert client.get("/desktop/bonus-deductions").status_code == 200


def test_미수금_회수_라벨과_단계_구분_분할이_있다():
    """2026-08-27 사용자 결정 — AB 기타공제 = 엑셀 미수금 탭 회수. 세전(W)/세후(AB)를 화면에서 구분해 고르고,
    부분 회수는 엑셀처럼 항목을 둘로 나눠서(분할) 한다."""
    for js in (JS, BONUS_JS):
        assert "미수금 회수(AB·세후)(−)" in js
        assert "기타공제(AB)(−)" not in js, "옛 라벨이 남으면 어느 단계에서 빠지는지 또 헷갈린다"
        assert "KIND_GROUPS" in js                                       # 종류를 단계(산출액/세전/세후)별 묶음으로
    assert "<optgroup" in JS and "<optgroup" in BONUS_JS
    assert 'id="splitDialog"' in HTML
    assert "split-button" in JS and "/split" in JS
    assert "bonus-deductions.js?v=20260827-3" in HTML


def test_엑셀_올리기_양식_돌아가기가_있다():
    assert 'id="importButton"' in HTML and 'id="importFile"' in HTML and 'id="templateButton"' in HTML
    assert 'class="back-button" href="/desktop/bonus"' in HTML
    assert "/api/bonus/v2/deduction-items/import" in JS and "/api/bonus/v2/deduction-items/template.xlsx" in JS
    settings = (ROOT / "desktop" / "ui" / "bonus-settings.html").read_text(encoding="utf-8")
    settings_js = (ROOT / "desktop" / "ui" / "bonus-settings.js").read_text(encoding="utf-8")
    assert 'class="bs-back" href="/desktop/bonus"' in settings and ".topbar .bs-back{" in settings
    assert "/api/bonus/settings/shares/lookup?doc_id=" in settings_js     # Booking·매출입력 지분 근거 조회
