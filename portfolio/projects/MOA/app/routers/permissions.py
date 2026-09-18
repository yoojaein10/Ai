"""권한부여 API — 본사 사용자만 조작할 수 있다."""

import logging

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Annotated

from app.database import get_db
from app.dependencies import (
    AccessContext,
    require_menu,
    require_menu_write,
    require_same_requester,
)
from app.schemas.common import ApiResponse
from app.services.permissions import (
    PermissionError_,
    get_user_policy,
    grant_permission,
    list_offices,
    list_permissions,
    organization_preview,
    revoke_permission,
    save_access_policy,
    search_employees,
)
from app.services.access_policy import MENU_KEYS, office_available_menus
from app.services.access_roles import (
    LockoutError,
    personal_override_usr_seqs,
    all_user_assignments,
    RoleError,
    assign_department,
    assign_user,
    delete_role,
    department_assignments,
    list_roles,
    save_role,
)
from app.services.users import UserContextError, UserContextService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/permissions", tags=["permissions"])


class GrantRequest(BaseModel):
    requester_usr_seq: int
    usr_id: str = Field(min_length=1, max_length=50)
    memo: str | None = Field(default=None, max_length=200)


class RevokeRequest(BaseModel):
    requester_usr_seq: int


class UserPolicyUpdateRequest(BaseModel):
    requester_usr_seq: int
    view_all_offices: bool | None = None
    view_other_users: bool | None = None
    menu_overrides: dict[str, bool] = Field(default_factory=dict)
    active: bool = True
    memo: str | None = Field(default=None, max_length=200)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    response = ApiResponse(success=False, code=code, message=message, data=None)
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))


def _check_admin(db: Session, usr_seq: int) -> JSONResponse | None:
    """권한 관리는 본사 소속 재직자만 가능하다."""
    try:
        context = UserContextService(db)._resolve(str(usr_seq))
    except UserContextError as exc:
        return _error(status.HTTP_403_FORBIDDEN, exc.code, str(exc))
    if context["office_id"] != "10":
        return _error(
            status.HTTP_403_FORBIDDEN, "NOT_HEAD_OFFICE", "권한부여는 본사만 가능합니다."
        )
    return None


@router.get("", response_model=ApiResponse)
def get_permissions(
    db: Session = Depends(get_db),
    _access: AccessContext = Depends(require_menu("permissionManage")),
) -> ApiResponse:
    # 지사 관리자에게 전사 명단을 보여 줄 이유가 없다 — 부여·회수는 이미 지사
    # 경계로 막혀 있는데 조회만 전사였다(2026-08-17 전수조사). 같은 라우터의
    # /organization-preview·/departments 와 잣대를 맞춘다.
    items = list_permissions(db)
    if str(_access.get("office_id")) != "10":
        mine = _branch_member_usr_ids(db, str(_access.get("office_id")))
        items = [row for row in items
                 if mine is None or str(row.get("usr_id", "")).strip() in mine]
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={"items": items, "count": len(items)},
    )


@router.get("/employees", response_model=ApiResponse)
def get_employees(
    q: Annotated[str, Query(min_length=1, max_length=30)],
    db: Session = Depends(get_db),
    _access: AccessContext = Depends(require_menu("permissionManage")),
) -> ApiResponse:
    items = search_employees(db, q)
    # 이름으로 남의 지사 재직자를 훑을 수 있었다 — 같은 화면의 다른 조회는
    # 전부 자기 지사로 좁혀 놨는데 여기만 잣대가 달랐다(2026-08-17 전수조사).
    if str(_access.get("office_id")) != "10":
        items = [row for row in items
                 if str(row.get("office_id")) == str(_access.get("office_id"))]
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={"items": items, "count": len(items)},
    )


@router.get("/organization-preview", response_model=ApiResponse)
def get_organization_preview(
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("permissionManage")),
) -> ApiResponse:
    visible_office_id = None if access["office_id"] == "10" else str(access["office_id"])
    data = organization_preview(db, visible_office_id=visible_office_id)
    return ApiResponse(
        success=True, code="0000", message="조회 완료", data=data,
    )


@router.post("/grant", response_model=ApiResponse)
def grant(
    request: GrantRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("permissionManage")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    try:
        row = grant_permission(
            db, request.usr_id, request.memo,
            requester_usr_seq=int(access.get("usr_seq") or 0) or None,
            # 본사는 전 지사를, 지사는 자기 지사만. 옆칸 /users/role 과 같은 잣대다.
            visible_office_id=(
                None if str(access.get("office_id")) == "10"
                else str(access.get("office_id"))
            ),
        )
    except PermissionError_ as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "GRANT_FAILED", str(exc))
    return ApiResponse(
        success=True, code="0000",
        message=f"{row.usr_id}에게 전체지사 조회 권한을 부여했습니다.", data={"id": row.id},
    )


@router.post("/{permission_id}/revoke", response_model=ApiResponse)
def revoke(
    permission_id: int,
    request: RevokeRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("permissionManage")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    try:
        row = revoke_permission(
            db, permission_id,
            # 본사는 전 지사를, 지사는 자기 지사만 — grant 와 같은 경계.
            visible_office_id=(
                None if str(access.get("office_id")) == "10"
                else str(access.get("office_id"))
            ),
        )
    except PermissionError_ as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "REVOKE_FAILED", str(exc))
    return ApiResponse(
        success=True, code="0000",
        message=f"{row.usr_id}의 권한을 회수했습니다.", data=None,
    )


@router.get("/users/{usr_seq}", response_model=ApiResponse)
def get_user_policy_route(
    usr_seq: int,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("permissionManage")),
) -> ApiResponse | JSONResponse:
    try:
        data = get_user_policy(
            db,
            usr_seq=usr_seq,
            visible_office_id=(
                None if access["office_id"] == "10" else str(access["office_id"])
            ),
        )
    except PermissionError_ as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "POLICY_LOAD_FAILED", str(exc))
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.put("/users/{usr_seq}", response_model=ApiResponse)
def put_user_policy(
    usr_seq: int,
    request: UserPolicyUpdateRequest,
    db: Session = Depends(get_db),
    # 이건 개인 예외를 **저장**하는 쓰기다 — 나머지 쓰기 8개처럼 증표를 요구해야
    # 한다. 2026-08-16 증표 관문을 달 때 여기만 require_menu(읽기 가드)로 남아,
    # 화면의 주 저장 버튼(permissions-preview.js)이 증표 없이 통과했다. 서비스층
    # (save_access_policy)에 자기부여·마지막관리자 가드는 있었지만, 헤더 숫자
    # 하나만으로 남의 개인 예외를 갈아치우는 길이 이 한 곳에 열려 있었다.
    access: AccessContext = Depends(require_menu_write("permissionManage")),
) -> ApiResponse | JSONResponse:
    require_same_requester(access, request.requester_usr_seq)
    try:
        data = save_access_policy(
            db,
            usr_seq=usr_seq,
            requester_usr_seq=request.requester_usr_seq,
            view_all_offices=request.view_all_offices,
            view_other_users=request.view_other_users,
            menu_overrides=request.menu_overrides,
            active=request.active,
            memo=request.memo,
            visible_office_id=(
                None if access["office_id"] == "10" else str(access["office_id"])
            ),
        )
    except PermissionError_ as exc:
        return _error(status.HTTP_400_BAD_REQUEST, "POLICY_SAVE_FAILED", str(exc))
    return ApiResponse(
        success=True,
        code="0000",
        message="사용자 권한을 저장했습니다.",
        data=data,
    )


# ── 일괄권한(역할) ────────────────────────────────────────────────────────
#
# 2026-08-13 추가. 지금까지는 사람을 하나씩만 고칠 수 있었고 부서·직군 기본값은
# 코드에 박혀 있었다. 여기서 일괄권한을 만들고 부서·개인에 붙인다.
# 해석 순서는 access_policy.resolve_role 참고 — **개인이 부서를 이긴다.**
#
# 모든 엔드포인트가 permissionManage 메뉴를 요구한다. 권한을 바꾸는 화면이라
# 조회조차 아무나 열면 안 된다(누가 무슨 권한을 갖는지가 그대로 드러난다).


class RoleSaveRequest(BaseModel):
    role_id: int | None = None
    name: str = Field(min_length=1, max_length=60)
    # 소속 — 이 일괄권한이 속한 곳(본사 '10' 또는 지사코드). 공용 없이 소속별로 따로.
    office_id: str = Field(default="10", max_length=10)
    menu_keys: list[str] = Field(default_factory=list)
    # None = '이 일괄권한은 이 플래그를 정하지 않는다' (아래 층이 그대로 산다)
    view_all_offices: bool | None = None
    view_other_users: bool | None = None
    memo: str | None = Field(default=None, max_length=200)
    # 이 일괄권한이 붙어 있는 부서 사람이 메뉴 0개가 될 때, 화면이 한 번 묻고 다시 보낸다.
    confirm_lockout: bool = False


class RoleDeleteRequest(BaseModel):
    # 쓰는 곳이 있는 일괄권한은 기본은 막힌다. 화면이 '각자 복사본으로 떼어낸 뒤 지웁니다'
    # 를 확인받으면 detach=True 로 다시 보낸다.
    detach: bool = False


class DeptAssignRequest(BaseModel):
    office_id: str = Field(min_length=1, max_length=10)
    department_name: str = Field(min_length=1, max_length=60)
    role_id: int | None = None      # None = 해제(코드 기본값으로 되돌림)
    # 이 부서 사람이 메뉴 0개가 되어 로그인 자체가 막힐 때, 화면이 한 번 물어보고
    # 다시 보낸다. 기본 False — 확인 없이는 진행하지 않는다.
    confirm_lockout: bool = False


class UserAssignRequest(BaseModel):
    usr_seq: int
    role_id: int | None = None
    # 이 사람이 메뉴 0개가 되면 409 로 한 번 묻고, 화면이 이 값을 켜서 다시 보낸다.
    confirm_lockout: bool = False


class DeptTarget(BaseModel):
    office_id: str = Field(min_length=1, max_length=10)
    department_name: str = Field(min_length=1, max_length=60)


class DeptBulkRequest(BaseModel):
    """부서 여러 개에 같은 일괄권한을 한 번에. role_id=None 은 일괄 해제."""

    role_id: int | None = None
    confirm_lockout: bool = False
    # 200개면 전 부서(123개)를 넉넉히 덮는다 — 그 이상은 잘못 만든 요청이다.
    targets: list[DeptTarget] = Field(min_length=1, max_length=200)


class UserBulkRequest(BaseModel):
    role_id: int | None = None
    confirm_lockout: bool = False
    usr_seqs: list[int] = Field(min_length=1, max_length=500)


def _role_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, LockoutError):
        # 고장이 아니라 '정말 할 거냐' 는 물음이다. 화면이 코드로 구분해서
        # 확인창을 띄우고 confirm_lockout=true 로 다시 보낸다.
        return _error(status.HTTP_409_CONFLICT, "ROLE_LOCKOUT_CONFIRM", str(exc))
    return _error(status.HTTP_400_BAD_REQUEST, "ROLE_SAVE_FAILED", str(exc))


@router.get("/roles", response_model=ApiResponse)
def get_roles(
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("permissionManage")),
) -> ApiResponse:
    """일괄권한 목록 — **로그인 소속의 것만**(공용 없는 지사별 일괄권한, 2026-08-18). 각 소속이
    자기 일괄권한만 만들고 본다. 소속은 로그인 계정으로 정해진다(office_id)."""
    office = str(access.get("office_id") or "10")
    items = list_roles(db, office_id=office)
    # 일괄권한 편집기에 소속 상한만 보낸다 — 지사는 지사 노출분(9)만, 본사는 전 메뉴(18).
    # 지사가 본사 전용 메뉴(매출입력·상여·카드전표 등)를 일괄권한에 담지 못하게(2026-08-19).
    avail = [k for k in MENU_KEYS if k in office_available_menus(office)]
    return ApiResponse(success=True, code="0000", message="조회 완료",
                       data={"items": items, "count": len(items),
                             "menu_keys": avail, "office_id": office})


def _branch_member_usr_ids(db: Session, office_id: str) -> "set[str] | None":
    """그 지사 구성원의 usr_id 집합. 못 읽으면 None — 부르는 쪽이 닫는다."""
    try:
        org = organization_preview(db, visible_office_id=office_id)
        return {
            str(emp["usr_id"]).strip()
            for office in org.get("offices") or []
            for dept in office.get("departments") or []
            for emp in dept.get("employees") or []
            if emp.get("usr_id")
        }
    except Exception:      # noqa: BLE001
        return None


def _head_office_only(access: AccessContext) -> "JSONResponse | None":
    """일괄권한 정의는 **전사 공용 자원**이라 본사만 만지게 한다 (2026-08-13 검수).

    일괄권한은 참조라 하나를 고치면 그걸 쓰는 부서·사람이 즉시 따라간다. 시드가
    본사 재무팀·전산정보팀을 '본사 전체메뉴' 하나에 묶으므로, 지사 관리자가 그
    일괄권한을 고치면 본사 두 부서의 권한이 통째로 바뀐다. permissionManage 는
    available 에 전원 열려 있어 지사 사용자도 개별 부여로 가질 수 있다.
    """
    if str(access.get("office_id")) != "10":
        return _error(status.HTTP_403_FORBIDDEN, "NOT_HEAD_OFFICE",
                      "일괄권한은 본사에서만 만들고 고칠 수 있습니다.")
    return None


@router.post("/roles", response_model=ApiResponse)
def post_role(
    request: RoleSaveRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("permissionManage")),
) -> ApiResponse | JSONResponse:
    """일괄권한을 만들거나 고친다(role_id 가 있으면 고치기). 본사 전용 잠금은 2026-08-18
    걷어냈다 — 각 소속(본사·지사)이 자기 일괄권한을 만든다. **소속은 로그인 계정으로
    강제**한다(요청값 무시): 지사 담당자가 로그인하면 자기 지사 일괄권한만 만들어진다."""
    office = str(access.get("office_id") or "10")
    try:
        data = save_role(
            db, role_id=request.role_id, name=request.name,
            menu_keys=request.menu_keys,
            view_all_offices=request.view_all_offices,
            view_other_users=request.view_other_users,
            memo=request.memo,
            office_id=office,
            updated_by_usr_seq=int(access.get("usr_seq") or 0) or None,
            confirm_lockout=request.confirm_lockout,
        )
    except (RoleError, LockoutError) as exc:
        return _role_error(exc)
    return ApiResponse(success=True, code="0000", message="저장 완료", data=data)


@router.post("/roles/{role_id}/delete", response_model=ApiResponse)
def post_role_delete(
    role_id: int,
    request: RoleDeleteRequest = RoleDeleteRequest(),
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("permissionManage")),
) -> ApiResponse | JSONResponse:
    """일괄권한을 지운다. 쓰는 곳이 있으면 기본은 막고, detach=True 면 쓰던 부서·사람을
    복사본으로 떼어낸 뒤 지운다. 본사 전용 잠금은 2026-08-18 걷어냈다 — 각 소속이 자기
    일괄권한을 지운다. 소속은 로그인 계정으로 검사해 남의 소속 건은 못 지운다."""
    office = str(access.get("office_id") or "10")
    try:
        data = delete_role(
            db, role_id, detach=request.detach,
            updated_by=int(access.get("usr_seq") or 0) or None,
            office_id=office,
        )
    except RoleError as exc:
        return _role_error(exc)
    return ApiResponse(success=True, code="0000", message="삭제 완료", data=data)


@router.get("/departments", response_model=ApiResponse)
def get_departments(
    office_id: Annotated[str | None, Query(max_length=10)] = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("permissionManage")),
) -> ApiResponse:
    """부서 → 일괄권한 목록. 지사 사용자는 자기 지사만 본다."""
    scope = None if access["office_id"] == "10" else str(access["office_id"])
    items = department_assignments(db, office_id=scope or office_id)
    return ApiResponse(success=True, code="0000", message="조회 완료",
                       data={"items": items, "count": len(items)})


@router.post("/departments", response_model=ApiResponse)
def post_department(
    request: DeptAssignRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("permissionManage")),
) -> ApiResponse | JSONResponse:
    """부서 하나에 일괄권한을 붙인다(또는 해제). 그 부서 사람 전부가 한 번에 바뀐다."""
    if access["office_id"] != "10" and str(access["office_id"]) != request.office_id:
        return _error(status.HTTP_403_FORBIDDEN, "NOT_MY_OFFICE",
                      "다른 지사의 부서 권한은 바꿀 수 없습니다.")
    try:
        data = assign_department(
            db, office_id=request.office_id, department_name=request.department_name,
            role_id=request.role_id,
            updated_by_usr_seq=int(access.get("usr_seq") or 0) or None,
            confirm_lockout=request.confirm_lockout,
        )
    except (RoleError, LockoutError) as exc:
        return _role_error(exc)
    return ApiResponse(success=True, code="0000", message="저장 완료", data=data)


@router.post("/users/role", response_model=ApiResponse)
def post_user_role(
    request: UserAssignRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("permissionManage")),
) -> ApiResponse | JSONResponse:
    """사람 하나에 일괄권한을 붙인다(또는 해제). 부서 일괄권한을 이긴다.

    지사 경계를 반드시 확인한다 (2026-08-13 검수에서 이 엔드포인트만 빠져 있었다).
    같은 라우터의 나머지는 전부 막는데 여기만 안 막아, 지사 권한관리자가 본사
    직원의 권한을 통째로 갈아치울 수 있었다. usr_seq 만으로는 소속을 모르므로
    put_user_policy 와 같은 방식으로 대상의 identity 를 먼저 뽑아 비교한다.
    """
    visible = None if str(access.get("office_id")) == "10" else str(access.get("office_id"))
    try:
        data = assign_user(
            db, usr_seq=request.usr_seq, role_id=request.role_id,
            updated_by_usr_seq=int(access.get("usr_seq") or 0) or None,
            visible_office_id=visible,
            confirm_lockout=request.confirm_lockout,
        )
    except (RoleError, LockoutError) as exc:
        # LockoutError 는 RoleError 가 아니다 — 따로 안 잡으면 500 으로 샌다.
        return _role_error(exc)
    return ApiResponse(success=True, code="0000", message="저장 완료", data=data)


# 경로 주의: /users/{usr_seq} 가 먼저 등록돼 있어 /users/roles 로 두면
# "roles" 가 usr_seq 로 잡혀 422 가 난다(경로 그림자) — /roles 밑에 둔다.
@router.get("/roles/user-assignments", response_model=ApiResponse)
def get_user_roles(
    db: Session = Depends(get_db),
    _access: AccessContext = Depends(require_menu("permissionManage")),
) -> ApiResponse:
    """개인 → 일괄권한 배정. 일괄 적용 화면이 '누가 이 세트를 쓰나'를 미리 체크해
    그릴 때 쓴다. 지사 관리자는 자기 지사 구성원 것만 본다 — 같은 라우터의
    GET /departments 와 같은 잣대(2026-08-17 검증에서 전사 노출 지적)."""
    items = all_user_assignments(db)
    # 개인 예외도 함께 — 화면이 '이 사람은 부서 권한을 안 따라간다'를 그린다.
    # 왕복을 더 만들지 않는 이유: 둘은 늘 같이 쓰이고, 따로 오면 한쪽만 늦게
    # 도착해 표가 깜빡인다(2026-08-17 인사이동 표시).
    overrides = personal_override_usr_seqs(db)
    if str(_access.get("office_id")) != "10":
        try:
            org = organization_preview(
                db, visible_office_id=str(_access.get("office_id")))
            mine = {
                int(emp["usr_seq"])
                for office in org.get("offices") or []
                for dept in office.get("departments") or []
                for emp in dept.get("employees") or []
                if emp.get("usr_seq") is not None
            }
            items = [row for row in items if int(row["usr_seq"]) in mine]
            overrides = [seq for seq in overrides if int(seq) in mine]
        except Exception:   # noqa: BLE001 — 못 좁히면 안 보여 준다(닫히는 쪽)
            items = []
            overrides = []
    return ApiResponse(success=True, code="0000", message="조회 완료",
                       data={"items": items, "count": len(items),
                             "personal_overrides": overrides})


@router.post("/departments/bulk", response_model=ApiResponse)
def post_departments_bulk(
    request: DeptBulkRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("permissionManage")),
) -> ApiResponse | JSONResponse:
    """부서 여러 개에 같은 일괄권한을 한 번에 붙인다(또는 해제).

    일부러 **단건 서비스를 대상마다 그대로 부른다** — 일괄이라는 지름길에서
    가드(permissionManage 부서 금지·잠금 확인·이력)가 하나도 빠지면 안 된다.
    한 부서가 막혀도 나머지는 진행하고, 무엇이 어떻게 됐는지 전부 돌려준다.

    잠금 확인 흐름: 1차(confirm=false)에서 잠기는 부서는 적용하지 않고
    needs_confirm 으로 돌려준다 → 화면이 합계로 한 번 묻고 → 그 대상들만
    confirm=true 로 다시 보낸다. 확인 없이 부서 전원이 잠기는 일이 없다.
    """
    applied: "list[dict]" = []
    blocked: "list[dict]" = []
    needs_confirm: "list[dict]" = []
    # 조직도는 루프 동안 불변이다 — 한 번만 읽어 대상마다 재사용한다.
    # 안 그러면 잠금 검사(locked_out_count)가 대상마다 전사 스캔을 다시 해서
    # 부서 수십 개 일괄이 수십 초짜리 요청이 된다(2026-08-17 실측: 20개=20회).
    try:
        org_snapshot = organization_preview(db)
    except Exception:   # noqa: BLE001 — 못 읽으면 각자 읽는 종전 동작으로
        org_snapshot = None
    for target in request.targets:
        # 지사 관리자는 자기 지사만 — 단건 엔드포인트와 같은 잣대.
        if access["office_id"] != "10" and str(access["office_id"]) != target.office_id:
            blocked.append({"office_id": target.office_id,
                            "department_name": target.department_name,
                            "reason": "다른 지사의 부서 권한은 바꿀 수 없습니다."})
            continue
        try:
            assign_department(
                db, office_id=target.office_id,
                department_name=target.department_name,
                role_id=request.role_id,
                updated_by_usr_seq=int(access.get("usr_seq") or 0) or None,
                confirm_lockout=request.confirm_lockout,
                org=org_snapshot,
            )
            applied.append({"office_id": target.office_id,
                            "department_name": target.department_name})
        except LockoutError as exc:
            db.rollback()   # 서비스도 롤백하지만 이중 방어 — 다음 commit 에 못 묻게
            needs_confirm.append({"office_id": target.office_id,
                                  "department_name": target.department_name,
                                  "locked": exc.locked})
        except RoleError as exc:
            blocked.append({"office_id": target.office_id,
                            "department_name": target.department_name,
                            "reason": str(exc)})
        except Exception:   # noqa: BLE001
            # 예상 밖 예외 하나가 요청 전체를 500 으로 끊으면, 이미 커밋된
            # 앞 대상들을 화면이 알 길이 없다 — 부분 결과 보고가 이 API 의 계약이다.
            logger.exception("부서 일괄 적용 실패: %s %s",
                             target.office_id, target.department_name)
            db.rollback()
            blocked.append({"office_id": target.office_id,
                            "department_name": target.department_name,
                            "reason": "처리 중 오류가 났습니다. 전산정보팀에 알려 주세요."})
    return ApiResponse(
        success=True, code="0000",
        message=f"부서 {len(applied)}개 적용",
        data={"applied": applied, "blocked": blocked, "needs_confirm": needs_confirm},
    )


@router.post("/users/role/bulk", response_model=ApiResponse)
def post_user_role_bulk(
    request: UserBulkRequest,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu_write("permissionManage")),
) -> ApiResponse | JSONResponse:
    """사람 여러 명에 같은 일괄권한을 한 번에. 자기부여 차단·지사 경계는 사람마다
    단건 서비스(assign_user)가 그대로 검사한다.

    잠금 확인은 부서 일괄과 같은 흐름이다(2026-08-17 추가): 1차에서 메뉴 0개가
    되는 사람은 적용하지 않고 needs_confirm 으로 돌려준다 → 화면이 합계로 한 번
    묻고 → 그 사람들만 confirm_lockout=true 로 다시 보낸다. 지사 사람에게 본사
    전용 메뉴만 든 일괄권한을 걸면 교집합이 전부 잘라내 0개가 되는데, 종전에는 그게
    조용히 커밋되어 다음 로그인부터 거절됐다.
    """
    visible = None if str(access.get("office_id")) == "10" else str(access.get("office_id"))
    applied: "list[int]" = []
    blocked: "list[dict]" = []
    needs_confirm: "list[dict]" = []
    # 유령 행 방지: 중복은 한 번으로 접고, 0·음수는 막고, 조직도가 읽히면
    # 실재하지 않는 usr_seq 도 막는다(2026-08-17 적대 검증 — 아무 숫자나 넣으면
    # 그대로 커밋되고 '성공'으로 보고됐다).
    known: "set[int] | None" = None
    try:
        org = organization_preview(db)
        known = {
            int(emp["usr_seq"])
            for office in org.get("offices") or []
            for dept in office.get("departments") or []
            for emp in dept.get("employees") or []
            if emp.get("usr_seq") is not None
        }
    except Exception:   # noqa: BLE001 — 조직도를 못 읽으면 이 검증만 접는다
        known = None
    for usr_seq in dict.fromkeys(int(x) for x in request.usr_seqs):
        if usr_seq <= 0:
            blocked.append({"usr_seq": usr_seq, "reason": "올바르지 않은 usr_seq 입니다."})
            continue
        if known is not None and usr_seq not in known:
            blocked.append({"usr_seq": usr_seq,
                            "reason": "조직도에 없는 사용자입니다."})
            continue
        try:
            assign_user(
                db, usr_seq=usr_seq, role_id=request.role_id,
                updated_by_usr_seq=int(access.get("usr_seq") or 0) or None,
                visible_office_id=visible,
                confirm_lockout=request.confirm_lockout,
            )
            applied.append(usr_seq)
        except LockoutError:
            # 부서 일괄과 같은 흐름 — 적용하지 않고 모아 돌려주면 화면이 합계로
            # 한 번 묻고, 그 사람들만 confirm=true 로 다시 보낸다.
            db.rollback()   # 서비스도 롤백하지만 이중 방어(다음 commit 에 묻지 않게)
            needs_confirm.append({"usr_seq": usr_seq, "locked": 1})
        except RoleError as exc:
            blocked.append({"usr_seq": usr_seq, "reason": str(exc)})
        except Exception:   # noqa: BLE001
            logger.exception("개인 일괄 적용 실패: %s", usr_seq)
            db.rollback()
            blocked.append({"usr_seq": usr_seq,
                            "reason": "처리 중 오류가 났습니다. 전산정보팀에 알려 주세요."})
    return ApiResponse(
        success=True, code="0000",
        message=f"개인 {len(applied)}명 적용",
        data={"applied": applied, "blocked": blocked, "needs_confirm": needs_confirm},
    )
