import pytest
from fastapi import HTTPException

from app.routers import fee_basis


def test_fee_basis_requires_a_user():
    with pytest.raises(HTTPException) as error:
        fee_basis._require_hq_user(
            db=object(), header_usr_seq=None, query_usr_seq=None, query_usr=None
        )
    assert error.value.status_code == 401


def test_fee_basis_allows_a_branch_user_with_the_menu(monkeypatch):
    """지사 재무도 자기 지사 건을 본다 (2026-08-07 확정).

    종전에는 소속(office_id=='10')으로 막았다. 이제는 메뉴 권한(feeBasis)이
    유일한 문지기이고, 조회 범위는 _scoped_office 가 로그인 지사로 강제한다.
    """
    monkeypatch.setattr(
        fee_basis.UserContextService,
        "_resolve",
        lambda self, value: {
            "usr_seq": int(value), "office_id": "20",
            "menu_permissions": {"feeBasis": True},
        },
    )
    access = fee_basis._require_hq_user(
        db=object(), header_usr_seq=None, query_usr_seq="77", query_usr=None
    )
    assert access["office_id"] == "20"


def test_fee_basis_still_rejects_anyone_without_the_menu(monkeypatch):
    """소속을 안 보는 대신 메뉴 권한은 반드시 본다 — 본사든 지사든 같다."""
    for office in ("10", "20"):
        monkeypatch.setattr(
            fee_basis.UserContextService,
            "_resolve",
            lambda self, value, office=office: {
                "usr_seq": int(value), "office_id": office,
                "menu_permissions": {"feeBasis": False, "appraisals": True},
            },
        )
        with pytest.raises(HTTPException) as error:
            fee_basis._require_hq_user(
                db=object(), header_usr_seq=None, query_usr_seq="77", query_usr=None
            )
        assert error.value.status_code == 403, office


def test_a_branch_user_cannot_read_another_office():
    """열어 준 것은 '자기 지사'뿐이다. 남의 지사를 요청하면 막는다."""
    access = {"usr_seq": 77, "office_id": "20", "view_all_offices": False}
    assert fee_basis._scoped_office(access, "20") == "20"
    with pytest.raises(HTTPException) as error:
        fee_basis._scoped_office(access, "10")
    assert error.value.status_code == 403


def test_fee_basis_accepts_hq_user(monkeypatch):
    monkeypatch.setattr(
        fee_basis.UserContextService,
        "_resolve",
        lambda self, value: {
            "usr_seq": int(value), "office_id": "10",
            "menu_permissions": {"feeBasis": True},
        },
    )
    access = fee_basis._require_hq_user(
        db=object(), header_usr_seq="77", query_usr_seq=None, query_usr=None
    )
    assert access["usr_seq"] == 77
