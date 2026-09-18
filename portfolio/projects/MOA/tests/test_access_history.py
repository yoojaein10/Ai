"""권한 변경이 실제로 이력에 쌓이는지 (2026-08-16).

왜 있나
    2026-08-16 진단에서 권한 변경이 **아무 흔적도 안 남기고 있었다.**
    a10_access_log 5,499행이 전부 로그인이고 권한 변경은 한 줄도 없었다.
    묶음은 참조라 하나를 고치면 지사 여러 곳이 동시에 바뀌는데, 잘못 건드려도
    원래 무엇이었는지 되돌릴 근거가 없었다.

    이력은 '있는 줄 알았는데 없는' 것이 가장 나쁘다 — 사고가 난 뒤에야 안다.
    그래서 각 쓰기 경로마다 실제로 한 줄이 쌓이는지 여기서 확인한다.

    특히 before 를 함께 확인한다. after 만 남기면 '무엇이 되었나'는 알아도
    '무엇이었나'를 몰라 되돌릴 수 없다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.access_change import AccessChange
from app.models.access_role import AccessDeptRole, AccessRole, AccessUserRole
from app.services import access_history
from app.services.access_roles import (
    assign_department,
    assign_user,
    delete_role,
    save_role,
)


@pytest.fixture()
def db_session():
    """묶음 3표 + 이력 표를 만든 인메모리 DB.

    StaticPool 이 꼭 필요하다 — sqlite 인메모리는 연결마다 빈 DB 가 새로 생긴다.
    """
    engine = create_engine(
        "sqlite://", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        AccessRole.__table__, AccessDeptRole.__table__, AccessUserRole.__table__,
        AccessChange.__table__,
    ])
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


def _rows(db, kind=None):
    stmt = select(AccessChange).order_by(AccessChange.change_id)
    if kind:
        stmt = stmt.where(AccessChange.target_kind == kind)
    return db.scalars(stmt).all()


def _make(db, name, keys, actor=2012):
    return save_role(
        db, role_id=None, name=name, menu_keys=keys,
        view_all_offices=None, view_other_users=None, memo=None,
        updated_by_usr_seq=actor,
    )


def test_묶음을_만들고_고치면_before_와_after_가_남는다(db_session):
    role = _make(db_session, "집행부", ["appraisals"])
    created = _rows(db_session, "role")
    assert len(created) == 1
    assert created[0].action == "create"
    assert created[0].actor_usr_seq == 2012

    save_role(
        db_session, role_id=role["role_id"], name="집행부",
        menu_keys=["appraisals", "bonus"],
        view_all_offices=None, view_other_users=None, memo="상여 담당 추가",
        updated_by_usr_seq=2012,
    )
    rows = _rows(db_session, "role")
    assert len(rows) == 2
    last = rows[-1]
    assert last.action == "update"
    # 되돌리려면 before 가 있어야 한다 — 이게 이 표의 존재 이유다.
    import json
    assert json.loads(last.before_json)["menu_keys"] == ["appraisals"]
    assert json.loads(last.after_json)["menu_keys"] == ["appraisals", "bonus"]
    assert last.reason == "상여 담당 추가"


def test_부서와_개인_부여도_남는다(db_session):
    role = _make(db_session, "지사일반", ["appraisals"])
    assign_department(
        db_session, office_id="21", department_name="업무팀",
        role_id=role["role_id"], updated_by_usr_seq=2012,
    )
    assign_user(db_session, usr_seq=555, role_id=role["role_id"], updated_by_usr_seq=2012)

    dept = _rows(db_session, "dept_role")
    user = _rows(db_session, "user_role")
    assert len(dept) == 1 and dept[0].action == "assign"
    assert dept[0].target_key == "21|업무팀"
    assert len(user) == 1 and user[0].action == "assign"
    assert user[0].target_key == "555"

    # 해제도 남아야 한다 — 준 것만 남고 뗀 것이 안 남으면 이력이 아니다.
    assign_user(db_session, usr_seq=555, role_id=None, updated_by_usr_seq=2012)
    user = _rows(db_session, "user_role")
    assert len(user) == 2 and user[-1].action == "unassign"


def test_삭제도_남고_삭제된_내용이_보존된다(db_session):
    role = _make(db_session, "임시", ["appraisals", "payments"])
    delete_role(db_session, role["role_id"])
    rows = _rows(db_session, "role")
    assert rows[-1].action == "delete"
    import json
    # 지운 묶음이 무엇이었는지가 남아야 다시 만들 수 있다.
    assert json.loads(rows[-1].before_json)["menu_keys"] == ["appraisals", "payments"]


def test_요청자를_안_주면_행위자와_같다(db_session):
    """지금은 관리자가 직접 바꾸므로 둘이 같다.

    신청 흐름이 붙는 날 둘이 갈리고, 그때 결재선이 이 두 칸에서 읽힌다 —
    표를 새로 만들 필요가 없다.
    """
    _make(db_session, "일반", ["appraisals"], actor=2012)
    row = _rows(db_session, "role")[0]
    assert row.requested_by_usr_seq == row.actor_usr_seq == 2012
    assert row.status == "applied"


def test_이력_표가_없어도_권한_저장은_된다(db_session):
    """이력 한 줄 때문에 권한을 못 바꾸면 안 된다.

    세이브포인트로 감싸지 않으면 표 없는 환경에서 flush 실패가 바깥 트랜잭션까지
    더럽혀, 뒤따르는 commit 이 통째로 깨진다 — 실제로 그렇게 시험 19개가 깨졌다.
    """
    AccessChange.__table__.drop(db_session.get_bind())
    role = _make(db_session, "표없음", ["appraisals"])
    assert role["role_id"] > 0        # 이력은 못 남겨도 저장은 됐다
    saved = db_session.get(AccessRole, role["role_id"])
    assert saved is not None and saved.active == "Y"


def test_history_는_최근_순으로_읽고_표가_없으면_빈_목록이다(db_session):
    role = _make(db_session, "가", ["appraisals"])
    save_role(
        db_session, role_id=role["role_id"], name="가", menu_keys=["payments"],
        view_all_offices=None, view_other_users=None, memo=None, updated_by_usr_seq=2012,
    )
    got = access_history.history(db_session, target_kind="role")
    assert [r["action"] for r in got] == ["update", "create"]

    AccessChange.__table__.drop(db_session.get_bind())
    assert access_history.history(db_session) == []


def test_같은_배정_재전송은_이력을_또_쌓지_않는다(db_session):
    """확인 재전송이나 중복 클릭이 같은 내용의 이력을 반복해 쌓으면, '언제
    무엇이 바뀌었나'를 되짚는 이 표의 존재 이유가 흐려진다 — 같은 값은 no-op."""
    role = _make(db_session, "일반", ["appraisals"])
    for _ in range(3):
        assign_department(db_session, office_id="10", department_name="업무1팀",
                          role_id=role["role_id"], updated_by_usr_seq=2012)
    assert len(_rows(db_session, "dept_role")) == 1

    for _ in range(3):
        assign_user(db_session, usr_seq=555, role_id=role["role_id"],
                    updated_by_usr_seq=2012)
    assert len(_rows(db_session, "user_role")) == 1

    # 해제도 한 번만 남는다 — 이미 없는 것을 또 떼는 건 아무 일도 아니다.
    for _ in range(2):
        assign_user(db_session, usr_seq=555, role_id=None, updated_by_usr_seq=2012)
    assert [r.action for r in _rows(db_session, "user_role")] == ["assign", "unassign"]
