"""로그인 증표 — 만들기·검증·권한 쓰기 관문 (2026-08-16).

왜 있나
    서버가 **숫자 하나를 그대로 믿고 있었다.** get_current_access 가
    X-MOA-USR-SEQ 헤더 값을 isdigit() 만 보고 그 사람으로 쳤고, 로그인은
    비밀번호를 확인하고도 아무것도 발급하지 않았다.

    조회만 있을 때는 감수할 만한 거래였지만, 권한 화면이 붙으면서 이 헤더로
    열리는 것이 '남의 실적 조회'에서 **'전사 권한 쓰기'** 로 바뀌었다.
    누구든 재무팀 usr_seq 를 넣으면 부서 묶음을 갈아치울 수 있었다.

    EXE 런처는 비밀번호 없이 ?usr= 로 들어오므로 조회 경로는 그대로 두고,
    **바꾸는 API 에만** 증표를 요구한다.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base
from app.models.access_role import AccessDeptRole, AccessRole, AccessUserRole
from app.database import get_db
from app.dependencies import get_current_access
from app.main import app
from app.services import auth_token


def test_증표를_만들고_되읽는다():
    token = auth_token.issue(2012)
    assert auth_token.verify(token) == 2012


def test_서명이_틀리면_거절한다():
    token = auth_token.issue(2012)
    seq, exp, signature = token.split(".")
    # usr_seq 만 남의 것으로 바꿔치기 — 서명이 안 맞아야 한다.
    assert auth_token.verify(f"9999.{exp}.{signature}") is None
    # 서명을 한 글자 고친 것도.
    flipped = signature[:-1] + ("A" if signature[-1] != "A" else "B")
    assert auth_token.verify(f"{seq}.{exp}.{flipped}") is None


def test_만료되면_거절한다():
    past = time.time() - 10
    token = auth_token.issue(2012, ttl=1, now=past)
    assert auth_token.verify(token) is None
    # 아직 안 지났으면 통과한다 — 무조건 막는 게 아니다.
    assert auth_token.verify(auth_token.issue(2012)) == 2012


@pytest.mark.parametrize("bad", [None, "", "abc", "1.2", '192.0.2.10', "x.y.z"])
def test_모양이_이상하면_조용히_거절한다(bad):
    assert auth_token.verify(bad) is None


# ── 권한 쓰기 관문 ────────────────────────────────────────────────────────

def _access():
    return {
        "usr_seq": 2012, "usr_id": "tester", "emp_name": "원동하",
        "office_id": "10", "office_name": "본사",
        "view_all_offices": True, "view_other_users": True,
        "menu_permissions": {"permissionManage": True},
        "offices": [{"office_code": "10"}],
    }


@pytest.fixture()
def client():
    """묶음 표만 만든 인메모리 DB 위의 클라이언트.

    get_db 를 None 으로 두면 관문을 지난 뒤 서비스가 터져서, '막혔는지'와
    '터졌는지'를 구분할 수 없다 — 관문 시험이 엉뚱한 이유로 통과한다.
    """
    engine = create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        AccessRole.__table__, AccessDeptRole.__table__, AccessUserRole.__table__,
    ])
    session = sessionmaker(bind=engine, future=True)()
    app.dependency_overrides[get_current_access] = _access
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_증표_없이_권한을_바꾸려_하면_막는다(client):
    """이 시험이 이 변경의 전부다 — 헤더 숫자만으로는 못 바꾼다."""
    res = client.post("/api/permissions/roles", json={"name": "몰래", "menu_keys": []})
    assert res.status_code == 401, res.text
    assert res.json()["code"] == "AUTH_TOKEN_REQUIRED"


def test_남의_증표로는_못_바꾼다(client):
    """증표는 A 것이고 헤더에는 B 라고 적어 보내는 길을 막는다."""
    res = client.post(
        "/api/permissions/roles", json={"name": "몰래", "menu_keys": []},
        headers={"X-MOA-AUTH": auth_token.issue(9999)},
    )
    assert res.status_code == 401, res.text
    assert res.json()["code"] == "AUTH_TOKEN_MISMATCH"


def test_조회는_증표_없이도_된다(client):
    """EXE 런처는 비밀번호 없이 들어온다 — 조회까지 막으면 전 사원이 못 쓴다."""
    res = client.get("/api/permissions/roles")
    # 증표 관문에서 막히지 않았다는 것만 본다(DB 가 없어 다른 이유로는 실패할 수 있다).
    assert res.status_code != 401 or res.json().get("code") not in (
        "AUTH_TOKEN_REQUIRED", "AUTH_TOKEN_MISMATCH"
    ), res.text


def test_스위치를_끄면_종전대로_돈다(client, monkeypatch):
    """운영에서 문제가 생기면 되돌릴 손잡이가 있어야 한다.

    다만 기본값은 켬이다 — 끄면 주소를 아는 사람이 전사 권한을 갈아치울 수 있다.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_require_token_for_writes", False)
    res = client.post("/api/permissions/roles", json={"name": "몰래", "menu_keys": []})
    assert res.status_code != 401 or res.json().get("code") != "AUTH_TOKEN_REQUIRED"


def test_기본값은_켬이다():
    """끄는 것은 사람이 정하는 일이다 — 기본이 꺼져 있으면 아무도 모른 채 열린다."""
    assert get_settings().auth_require_token_for_writes is True


def test_로그인이_증표를_함께_준다():
    """발급이 빠지면 화면이 증표를 못 얻어 아무도 권한을 못 바꾼다."""
    import inspect

    from app.services import auth as auth_service

    source = inspect.getsource(auth_service.login)
    assert "auth_token" in source, "login 이 증표를 안 돌려준다"
