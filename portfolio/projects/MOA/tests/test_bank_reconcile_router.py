"""일계표 대사 API — 문지기·기간 검사·등록."""

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.routers.bank_reconcile import MAX_DAYS, _period_error

ROOT = Path(__file__).resolve().parent.parent
SOURCE = (ROOT / "app" / "routers" / "bank_reconcile.py").read_text(encoding="utf-8")


def test_두_끝점_모두_메뉴_문지기와_운영부서_문지기를_거친다():
    assert SOURCE.count('require_menu("bankReconcile")') == 2
    assert SOURCE.count("require_operations_user(access, _GATE_MESSAGE)") == 2


def test_읽기만_한다():
    assert "@router.post" not in SOURCE and "@router.put" not in SOURCE and "@router.delete" not in SOURCE


def test_기간_검사():
    assert MAX_DAYS == 31
    assert _period_error(date(2026, 8, 25), date(2026, 8, 24)) == "종료일이 시작일보다 앞섭니다."
    assert _period_error(date(2026, 8, 1), date(2026, 8, 31)) is None
    assert _period_error(date(2026, 8, 1), date(2026, 9, 1)) == "조회 기간은 31일 이내로 잡으세요."


def test_무인증_요청은_거절된다():
    client = TestClient(app)
    for path in ("/api/bank-reconcile", "/api/bank-reconcile/export.xlsx"):
        response = client.get(path, params={"date_from": "2026-08-25", "date_to": "2026-08-25"})
        assert response.status_code in (401, 403), path


def test_main_에_등록돼_있다():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "app.include_router(bank_reconcile_router)" in main
