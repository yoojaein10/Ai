from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.admin import (
    AdminCodeCreate,
    AdminCodeGroup,
    AdminCodeGroupsResponse,
    AdminCodeListResponse,
    AdminCodeOut,
    AdminCodeUpdate,
    AdminMenuListResponse,
    AdminMenuRow,
    AdminPasswordReset,
    AdminRoleCreate,
    AdminRoleListResponse,
    AdminRoleRow,
    AdminRoleUpdate,
    AdminSettingCreate,
    AdminSettingListResponse,
    AdminSettingOut,
    AdminSettingUpdate,
    AdminUserCreate,
    AdminUserListResponse,
    AdminUserRow,
    AdminUserUpdate,
)
from app.services import admin as svc

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Users ─────────────────────────────────────────────────


@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    keyword: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AdminUserListResponse:
    rows = svc.list_users(db, keyword, is_active)
    return AdminUserListResponse(
        total=len(rows),
        items=[AdminUserRow(**r) for r in rows],
    )


@router.post("/users", response_model=AdminUserRow, status_code=201)
def create_user(
    data: AdminUserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AdminUserRow:
    if db.query(User).filter(User.login_id == data.login_id).first():
        raise HTTPException(status_code=409, detail="로그인ID가 이미 존재합니다")
    user = svc.create_user(db, data)
    return AdminUserRow(**svc._user_to_row(user))


@router.patch("/users/{user_id}", response_model=AdminUserRow)
def update_user(
    user_id: int,
    data: AdminUserUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AdminUserRow:
    user = svc.update_user(db, user_id, data)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    return AdminUserRow(**svc._user_to_row(user))


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int,
    data: AdminPasswordReset,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    ok = svc.reset_password(db, user_id, data.new_password)
    if not ok:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    return {"ok": True}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> dict:
    if current.id == user_id:
        raise HTTPException(status_code=400, detail="본인 계정은 삭제할 수 없습니다")
    ok, msg = svc.delete_user(db, user_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


# ── Roles ─────────────────────────────────────────────────


@router.get("/roles", response_model=AdminRoleListResponse)
def list_roles(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AdminRoleListResponse:
    rows = svc.list_roles(db)
    return AdminRoleListResponse(
        total=len(rows),
        items=[AdminRoleRow(**r) for r in rows],
    )


@router.post("/roles", response_model=AdminRoleRow, status_code=201)
def create_role(
    data: AdminRoleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AdminRoleRow:
    from app.db.models import Role

    if db.query(Role).filter(Role.code == data.code).first():
        raise HTTPException(status_code=409, detail="권한코드가 이미 존재합니다")
    role = svc.create_role(db, data)
    return AdminRoleRow(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        user_count=0,
        menu_ids=[rm.menu_id for rm in role.menus],
    )


@router.patch("/roles/{role_id}", response_model=AdminRoleRow)
def update_role(
    role_id: int,
    data: AdminRoleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AdminRoleRow:
    role = svc.update_role(db, role_id, data)
    if role is None:
        raise HTTPException(status_code=404, detail="권한을 찾을 수 없습니다")
    from app.db.models import UserRole

    user_count = db.query(UserRole).filter(UserRole.role_id == role_id).count()
    return AdminRoleRow(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        user_count=user_count,
        menu_ids=[rm.menu_id for rm in role.menus],
    )


@router.delete("/roles/{role_id}")
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    ok, msg = svc.delete_role(db, role_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.get("/menus", response_model=AdminMenuListResponse)
def list_menus(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AdminMenuListResponse:
    menus = svc.list_menus(db)
    return AdminMenuListResponse(
        total=len(menus),
        items=[AdminMenuRow.model_validate(m) for m in menus],
    )


# ── Codes ─────────────────────────────────────────────────


@router.get("/codes/groups", response_model=AdminCodeGroupsResponse)
def list_code_groups(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AdminCodeGroupsResponse:
    groups = svc.list_code_groups(db)
    return AdminCodeGroupsResponse(groups=[AdminCodeGroup(**g) for g in groups])


@router.get("/codes", response_model=AdminCodeListResponse)
def list_codes(
    group_code: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    keyword: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AdminCodeListResponse:
    codes = svc.list_codes(db, group_code, is_active, keyword)
    return AdminCodeListResponse(
        total=len(codes),
        items=[AdminCodeOut.model_validate(c) for c in codes],
    )


@router.post("/codes", response_model=AdminCodeOut, status_code=201)
def create_code(
    data: AdminCodeCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AdminCodeOut:
    from app.db.models import Code

    exists = (
        db.query(Code)
        .filter(Code.group_code == data.group_code, Code.code == data.code)
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="이미 존재하는 코드입니다")
    code = svc.create_code(db, data)
    return AdminCodeOut.model_validate(code)


@router.patch("/codes/{code_id}", response_model=AdminCodeOut)
def update_code(
    code_id: int,
    data: AdminCodeUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AdminCodeOut:
    code = svc.update_code(db, code_id, data)
    if code is None:
        raise HTTPException(status_code=404, detail="코드를 찾을 수 없습니다")
    return AdminCodeOut.model_validate(code)


@router.delete("/codes/{code_id}")
def delete_code(
    code_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    ok, msg = svc.delete_code(db, code_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


# ── Settings ──────────────────────────────────────────────


@router.get("/settings", response_model=AdminSettingListResponse)
def list_settings(
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AdminSettingListResponse:
    settings = svc.list_settings(db, category)
    return AdminSettingListResponse(
        total=len(settings),
        items=[AdminSettingOut.model_validate(s) for s in settings],
    )


@router.post("/settings", response_model=AdminSettingOut, status_code=201)
def create_setting(
    data: AdminSettingCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AdminSettingOut:
    from app.db.models import Setting

    if db.query(Setting).filter(Setting.key == data.key).first():
        raise HTTPException(status_code=409, detail="키가 이미 존재합니다")
    setting = svc.create_setting(db, data)
    return AdminSettingOut.model_validate(setting)


@router.patch("/settings/{setting_id}", response_model=AdminSettingOut)
def update_setting(
    setting_id: int,
    data: AdminSettingUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> AdminSettingOut:
    setting = svc.update_setting(db, setting_id, data)
    if setting is None:
        raise HTTPException(status_code=404, detail="설정을 찾을 수 없거나 편집 불가")
    return AdminSettingOut.model_validate(setting)


@router.delete("/settings/{setting_id}")
def delete_setting(
    setting_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    ok, msg = svc.delete_setting(db, setting_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}
