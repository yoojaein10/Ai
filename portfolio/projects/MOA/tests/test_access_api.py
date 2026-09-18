from datetime import date

from fastapi.testclient import TestClient

from app.dependencies import get_current_access
from app.database import get_db
from app.main import app
from app.routers.appraisals import get_appraisal_service


class FakeAppraisalService:
    def __init__(self):
        self.kwargs = None

    def list(self, **kwargs):
        self.kwargs = kwargs
        return {"items": [], "total": 0, "page": 1, "page_size": 30}


def access_context(*, menu: bool = True, view_all: bool = False):
    return {
        "usr_seq": 100,
        "usr_id": "tester",
        "emp_name": "김평가",
        "office_id": "11",
        "office_name": "경기지사",
        "view_all_offices": view_all,
        "view_other_users": False,
        "menu_permissions": {"appraisals": menu},
        "offices": (
            [{"office_code": "10"}, {"office_code": "11"}]
            if view_all else [{"office_code": "11"}]
        ),
    }


def test_appraisal_api_forces_branch_and_self_scope():
    service = FakeAppraisalService()
    app.dependency_overrides[get_current_access] = lambda: access_context()
    app.dependency_overrides[get_appraisal_service] = lambda: service
    try:
        response = TestClient(app).get(
            "/api/appraisals",
            params={
                "office_code": "11",
                "date_from": date(2026, 7, 1).isoformat(),
                "date_to": date(2026, 7, 2).isoformat(),
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert service.kwargs["office_code"] == "11"
    assert service.kwargs["scope_person"] == "김평가"


def test_appraisal_api_rejects_other_branch_even_if_query_is_tampered():
    service = FakeAppraisalService()
    app.dependency_overrides[get_current_access] = lambda: access_context()
    app.dependency_overrides[get_appraisal_service] = lambda: service
    try:
        response = TestClient(app).get("/api/appraisals", params={"office_code": "10"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["code"] == "OFFICE_SCOPE_DENIED"
    assert service.kwargs is None


def test_appraisal_api_rejects_hidden_menu_direct_url():
    service = FakeAppraisalService()
    app.dependency_overrides[get_current_access] = lambda: access_context(menu=False)
    app.dependency_overrides[get_appraisal_service] = lambda: service
    try:
        response = TestClient(app).get("/api/appraisals", params={"office_code": "11"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["code"] == "MENU_ACCESS_DENIED"
    assert service.kwargs is None


# --- 반제리스트: 본사 전용 메뉴 키(receivableReconcile/advanceReconcile) 강제 ---


def banje_context(*, office_id: str = "10", menus: "dict[str, bool] | None" = None):
    return {
        "usr_seq": 200,
        "usr_id": "banje-tester",
        "emp_name": "박재무",
        "office_id": office_id,
        "office_name": "본사" if office_id == "10" else "경기지사",
        "view_all_offices": False,
        "view_other_users": True,
        "menu_permissions": menus if menus is not None else {
            "receivableReconcile": True, "advanceReconcile": True,
        },
        "offices": [{"office_code": office_id}],
    }


def call_banje(monkeypatch, context, params):
    """반제 목록 API를 부르고 (응답, 서비스에 전달된 office_code)를 돌려준다."""
    captured = {}

    def fake_open_list(db, kind, date_from, date_to, office_code, include_nonstd, as_of):
        captured["office_code"] = office_code
        return {"items": [], "total": 0}

    monkeypatch.setattr("app.routers.banje.banje_open_list", fake_open_list)
    app.dependency_overrides[get_current_access] = lambda: context
    app.dependency_overrides[get_db] = lambda: None
    try:
        response = TestClient(app).get("/api/banje", params={"mode": "open", **params})
    finally:
        app.dependency_overrides.clear()
    return response, captured.get("office_code")


def test_banje_rejects_branch_user_without_head_office_menu(monkeypatch):
    response, office_code = call_banje(
        monkeypatch,
        banje_context(office_id="11", menus={"appraisals": True}),
        {"kind": "receivable"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "MENU_ACCESS_DENIED"
    assert office_code is None


def test_banje_rejects_other_office_even_if_query_is_tampered(monkeypatch):
    response, office_code = call_banje(
        monkeypatch, banje_context(), {"kind": "receivable", "office_code": "18"}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "OFFICE_SCOPE_DENIED"
    assert office_code is None


def test_banje_checks_the_menu_key_matching_kind(monkeypatch):
    """선수금(advance) 권한만 있으면 외상매출금(receivable)은 볼 수 없다."""
    only_advance = {"receivableReconcile": False, "advanceReconcile": True}

    denied, _ = call_banje(
        monkeypatch, banje_context(menus=only_advance), {"kind": "receivable"}
    )
    allowed, office_code = call_banje(
        monkeypatch, banje_context(menus=only_advance), {"kind": "advance"}
    )

    assert denied.status_code == 403
    assert denied.json()["code"] == "MENU_ACCESS_DENIED"
    assert allowed.status_code == 200
    assert office_code == "10"


def test_branch_permission_manager_organization_is_scoped_to_own_office(monkeypatch):
    captured = {}

    def fake_organization_preview(_db, visible_office_id=None):
        captured["visible_office_id"] = visible_office_id
        return {
            "offices": [],
            "office_count": 0,
            "employee_count": 0,
            "missing_department_count": 0,
        }

    branch_access = access_context()
    branch_access["menu_permissions"]["permissionManage"] = True
    monkeypatch.setattr(
        "app.routers.permissions.organization_preview",
        fake_organization_preview,
    )
    app.dependency_overrides[get_current_access] = lambda: branch_access
    app.dependency_overrides[get_db] = lambda: object()
    try:
        response = TestClient(app).get("/api/permissions/organization-preview")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured["visible_office_id"] == "11"


def test_hq_permission_manager_organization_can_include_all_offices(monkeypatch):
    captured = {}

    def fake_organization_preview(_db, visible_office_id=None):
        captured["visible_office_id"] = visible_office_id
        return {
            "offices": [],
            "office_count": 0,
            "employee_count": 0,
            "missing_department_count": 0,
        }

    hq_access = access_context()
    hq_access["office_id"] = "10"
    hq_access["menu_permissions"]["permissionManage"] = True
    monkeypatch.setattr(
        "app.routers.permissions.organization_preview",
        fake_organization_preview,
    )
    app.dependency_overrides[get_current_access] = lambda: hq_access
    app.dependency_overrides[get_db] = lambda: object()
    try:
        response = TestClient(app).get("/api/permissions/organization-preview")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured["visible_office_id"] is None
