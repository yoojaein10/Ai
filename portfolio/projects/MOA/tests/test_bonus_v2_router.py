"""상여 v2 API (2단계 14 + 3단계) — 권한 게이트와 지급월 검사."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "app" / "routers" / "bonus_v2.py").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def test_상여_메뉴_권한과_본인_범위를_지킨다():
    assert 'require_menu("bonus")' in ROUTER
    assert "scope_person=scoped_employee_name(access)" in ROUTER
    assert 'APIRouter(prefix="/api/bonus/v2"' in ROUTER


def test_쓰기_아홉_곳은_쓰기_권한_본인_요청_집행부_게이트를_전부_지난다():
    """공제 적용·대장 등록/수정/무효/분할, 오버라이드 저장, 마감, 재개 — 조회 게이트만으로는 못 들어온다."""
    writes = ROUTER.count("@router.put(") + ROUTER.count("@router.post(")
    assert writes == 9                                                   # + 공제 엑셀 올리기 + 분할
    assert ROUTER.count('require_menu_write("bonus")') == writes
    assert ROUTER.count("require_same_requester") >= writes
    assert ROUTER.count("require_operations_user") >= writes + 4      # 총괄표·전표, 공제 대장 조회·양식, 감정서 검색도 집행부만


def test_여러달_검색은_조회_게이트와_본인_범위를_지킨다():
    """2026-08-27 사용자 요청 — 지급월 구간 × 감정서번호·유치자 검색."""
    assert '@router.get("/search"' in ROUTER
    assert "search_bonus(" in ROUTER
    assert ROUTER.count("scope_person=scoped_employee_name(access)") >= 3   # 리포트·엑셀·검색


def test_main_에_등록돼_있다():
    assert "from app.routers.bonus_v2 import router as bonus_v2_router" in MAIN
    assert "app.include_router(bonus_v2_router)" in MAIN


def test_로그인_없이는_볼_수_없다():
    client = TestClient(app)
    assert client.get("/api/bonus/v2?period=202608").status_code in (401, 403)
    assert client.get("/api/bonus/v2/journal?period=202608").status_code in (401, 403)
    assert client.get("/api/bonus/v2/search?period_from=202601&period_to=202608").status_code in (401, 403)
    assert client.put("/api/bonus/v2/deductions/202609/강무진", json={"requester_usr_seq": 1, "applied_item_ids": []}).status_code in (401, 403)
    assert client.get("/api/bonus/v2/deduction-items?status=PENDING").status_code in (401, 403)
    assert client.post("/api/bonus/v2/deduction-items", json={"requester_usr_seq": 1, "person": "강무진", "kind": "WREATH", "amount": 1}).status_code in (401, 403)
    assert client.post("/api/bonus/v2/deduction-items/1/void", json={"requester_usr_seq": 1, "reason": "x"}).status_code in (401, 403)
    assert client.post("/api/bonus/v2/deduction-items/1/split", json={"requester_usr_seq": 1, "amount": 1000}).status_code in (401, 403)
    assert client.get("/api/bonus/v2/docs?person=%EA%B0%95%EB%AC%B4%EC%A7%84&date_from=2026-01-01&date_to=2026-08-31").status_code in (401, 403)
    assert client.get("/api/bonus/v2/deduction-items/template.xlsx").status_code in (401, 403)
    assert client.post("/api/bonus/v2/deduction-items/import", data={"requester_usr_seq": "1"}, files={"file": ("a.xlsx", b"x")}).status_code in (401, 403)
    assert client.put("/api/bonus/v2/overrides/202609", json={"requester_usr_seq": 1, "doc_id": "01-2607-3-0001", "person": "강무진", "actions": {}}).status_code in (401, 403)
    assert client.post("/api/bonus/v2/close/202609", json={"requester_usr_seq": 1}).status_code in (401, 403)
    assert client.post("/api/bonus/v2/reopen/202609", json={"requester_usr_seq": 1}).status_code in (401, 403)
