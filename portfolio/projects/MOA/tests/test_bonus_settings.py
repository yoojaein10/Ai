"""상여 설정 화면·API (1단계 6·7) — 사람·요율·지분을 재무팀이 화면에서 고친다.

권한 키는 새로 만들지 않고 상여(bonus)를 그대로 쓴다 — 상여 화면 안 '설정' 버튼으로
들어오는 딸림 화면(지사별원장 → 메일 주소 관리와 같은 구조).
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app" / "routers" / "bonus_settings.py").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
CONTEXT = (ROOT / "desktop" / "ui" / "context.js").read_text(encoding="utf-8")
BONUS_HTML = (ROOT / "desktop" / "ui" / "bonus.html").read_text(encoding="utf-8")
BONUS_JS = (ROOT / "desktop" / "ui" / "bonus.js").read_text(encoding="utf-8")
SETTINGS_HTML = (ROOT / "desktop" / "ui" / "bonus-settings.html").read_text(encoding="utf-8")
SETTINGS_JS = (ROOT / "desktop" / "ui" / "bonus-settings.js").read_text(encoding="utf-8")


def test_조회는_메뉴_권한_쓰기는_로그인_증표까지_요구한다():
    assert ROUTER.count('require_menu("bonus")') == 4          # persons·rates·shares 조회 + 지분 근거 조회(lookup)
    assert ROUTER.count('require_menu_write("bonus")') == 3
    assert ROUTER.count("require_operations_user(") == 7   # 조회 4(+lookup) + 쓰기 3
    assert ROUTER.count("require_same_requester(") == 3


def test_세_표마다_목록과_replace_all_저장이_있다():
    assert 'APIRouter(prefix="/api/bonus/settings"' in ROUTER
    for path in ('@router.get("/persons"', '@router.put("/persons"', '@router.get("/rates"',
                 '@router.put("/rates/{person}"', '@router.get("/shares"', '@router.put("/shares/{doc_id}"'):
        assert path in ROUTER, path
    assert "except BonusMasterError as exc:" in ROUTER


def test_로그인_없이는_설정을_볼_수_없다():
    client = TestClient(app)
    response = client.get("/api/bonus/settings/persons")
    assert response.status_code in (401, 403)
    assert response.json()["success"] is False


def test_화면은_screen_경유이고_상여_권한_키를_같이_쓴다():
    assert '@app.get("/desktop/bonus-settings"' in MAIN
    assert '_screen("bonus-settings.html")' in MAIN
    assert "from app.routers.bonus_settings import router as bonus_settings_router" in MAIN
    assert "app.include_router(bonus_settings_router)" in MAIN
    assert "'/desktop/bonus-settings': 'bonus'," in CONTEXT


def test_상여_화면에서_설정_버튼으로_들어간다():
    assert 'id="settingsButton"' in BONUS_HTML
    assert "location.href = '/desktop/bonus-settings'" in BONUS_JS
    # bonus.js 는 그동안 ?v= 없이 불려 브라우저가 옛 파일을 붙들 수 있었다
    assert "bonus.js?v=20260827-8" in BONUS_HTML


def test_설정_화면은_본사만_고치고_저장_안_한_변경을_지킨다():
    assert "bonus-settings.js?v=20260826-2" in SETTINGS_HTML
    assert "context.js?v=" in SETTINGS_HTML
    assert "ctx.office_id !== '10'" in SETTINGS_JS
    assert "beforeunload" in SETTINGS_JS
    for path in ("/api/bonus/settings/persons", "/api/bonus/settings/rates", "/api/bonus/settings/shares"):
        assert path in SETTINGS_JS, path
    assert "requester_usr_seq" in SETTINGS_JS
