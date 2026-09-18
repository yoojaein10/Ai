from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.core.security import hash_password
from app.db.models import (
    Code,
    Department,
    Employee,
    Menu,
    Role,
    RoleMenu,
    Setting,
    User,
    UserRole,
)
from app.schemas.admin import (
    AdminCodeCreate,
    AdminCodeUpdate,
    AdminRoleCreate,
    AdminRoleUpdate,
    AdminSettingCreate,
    AdminSettingUpdate,
    AdminUserCreate,
    AdminUserUpdate,
)


# ── Users ─────────────────────────────────────────────────


def _user_to_row(user: User) -> dict:
    emp = user.employee
    dept_name = emp.department.name if emp and emp.department else None
    roles = [ur.role for ur in user.roles if ur.role is not None]
    return {
        "id": user.id,
        "login_id": user.login_id,
        "employee_id": user.employee_id,
        "emp_no": emp.emp_no if emp else None,
        "name_ko": emp.name_ko if emp else None,
        "dept_name": dept_name,
        "is_active": user.is_active,
        "role_codes": [r.code for r in roles],
        "role_names": [r.name for r in roles],
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def list_users(
    db: Session,
    keyword: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> list[dict]:
    query = (
        db.query(User)
        .options(
            joinedload(User.employee).joinedload(Employee.department),
            joinedload(User.roles).joinedload(UserRole.role),
        )
    )
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if keyword:
        like = f"%{keyword}%"
        query = query.outerjoin(Employee, User.employee_id == Employee.id).filter(
            or_(
                User.login_id.ilike(like),
                Employee.emp_no.ilike(like),
                Employee.name_ko.ilike(like),
            )
        )
    users = query.order_by(User.login_id).all()
    return [_user_to_row(u) for u in users]


def get_user(db: Session, user_id: int) -> Optional[User]:
    return (
        db.query(User)
        .options(
            joinedload(User.employee).joinedload(Employee.department),
            joinedload(User.roles).joinedload(UserRole.role),
        )
        .filter(User.id == user_id)
        .first()
    )


def create_user(db: Session, data: AdminUserCreate) -> User:
    user = User(
        login_id=data.login_id,
        password_hash=hash_password(data.password),
        employee_id=data.employee_id,
        is_active=data.is_active,
    )
    db.add(user)
    db.flush()
    for rid in data.role_ids:
        db.add(UserRole(user_id=user.id, role_id=rid))
    db.commit()
    return get_user(db, user.id)


def update_user(
    db: Session, user_id: int, data: AdminUserUpdate
) -> Optional[User]:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return None
    if data.employee_id is not None:
        user.employee_id = data.employee_id
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.role_ids is not None:
        db.query(UserRole).filter(UserRole.user_id == user_id).delete()
        for rid in data.role_ids:
            db.add(UserRole(user_id=user_id, role_id=rid))
    db.commit()
    return get_user(db, user_id)


def reset_password(db: Session, user_id: int, new_password: str) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return False
    user.password_hash = hash_password(new_password)
    db.commit()
    return True


def delete_user(db: Session, user_id: int) -> tuple[bool, str]:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return False, "사용자를 찾을 수 없습니다"
    db.query(UserRole).filter(UserRole.user_id == user_id).delete()
    db.delete(user)
    db.commit()
    return True, "삭제되었습니다"


# ── Roles ─────────────────────────────────────────────────


def _role_to_row(role: Role, user_count: int) -> dict:
    menu_ids = [rm.menu_id for rm in role.menus] if role.menus else []
    return {
        "id": role.id,
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "user_count": user_count,
        "menu_ids": menu_ids,
    }


def list_roles(db: Session) -> list[dict]:
    roles = (
        db.query(Role)
        .options(joinedload(Role.menus))
        .order_by(Role.id)
        .all()
    )
    counts: dict[int, int] = {}
    for (rid,) in db.query(UserRole.role_id).all():
        counts[rid] = counts.get(rid, 0) + 1
    return [_role_to_row(r, counts.get(r.id, 0)) for r in roles]


def get_role(db: Session, role_id: int) -> Optional[Role]:
    return (
        db.query(Role)
        .options(joinedload(Role.menus))
        .filter(Role.id == role_id)
        .first()
    )


def create_role(db: Session, data: AdminRoleCreate) -> Role:
    role = Role(code=data.code, name=data.name, description=data.description)
    db.add(role)
    db.flush()
    for mid in data.menu_ids:
        db.add(RoleMenu(role_id=role.id, menu_id=mid))
    db.commit()
    return get_role(db, role.id)


def update_role(
    db: Session, role_id: int, data: AdminRoleUpdate
) -> Optional[Role]:
    role = db.query(Role).filter(Role.id == role_id).first()
    if role is None:
        return None
    if data.name is not None:
        role.name = data.name
    if data.description is not None:
        role.description = data.description
    if data.menu_ids is not None:
        db.query(RoleMenu).filter(RoleMenu.role_id == role_id).delete()
        for mid in data.menu_ids:
            db.add(RoleMenu(role_id=role_id, menu_id=mid))
    db.commit()
    return get_role(db, role_id)


def delete_role(db: Session, role_id: int) -> tuple[bool, str]:
    role = db.query(Role).filter(Role.id == role_id).first()
    if role is None:
        return False, "권한을 찾을 수 없습니다"
    used = db.query(UserRole).filter(UserRole.role_id == role_id).count()
    if used > 0:
        return False, f"사용자 {used}명에 연결되어 있어 삭제할 수 없습니다"
    db.query(RoleMenu).filter(RoleMenu.role_id == role_id).delete()
    db.delete(role)
    db.commit()
    return True, "삭제되었습니다"


def list_menus(db: Session) -> list[Menu]:
    return db.query(Menu).order_by(Menu.sort_order, Menu.id).all()


# ── Codes ─────────────────────────────────────────────────


def list_code_groups(db: Session) -> list[dict]:
    rows = (
        db.query(Code.group_code, Code.group_name)
        .order_by(Code.group_code)
        .all()
    )
    seen: dict[str, dict] = {}
    for gc, gn in rows:
        if gc not in seen:
            seen[gc] = {"group_code": gc, "group_name": gn, "count": 0}
        seen[gc]["count"] += 1
        if gn and not seen[gc]["group_name"]:
            seen[gc]["group_name"] = gn
    return list(seen.values())


def list_codes(
    db: Session,
    group_code: Optional[str] = None,
    is_active: Optional[bool] = None,
    keyword: Optional[str] = None,
) -> list[Code]:
    query = db.query(Code)
    if group_code:
        query = query.filter(Code.group_code == group_code)
    if is_active is not None:
        query = query.filter(Code.is_active == is_active)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(or_(Code.code.ilike(like), Code.name.ilike(like)))
    return query.order_by(Code.group_code, Code.sort_order, Code.code).all()


def create_code(db: Session, data: AdminCodeCreate) -> Code:
    code = Code(**data.model_dump())
    db.add(code)
    db.commit()
    db.refresh(code)
    return code


def update_code(
    db: Session, code_id: int, data: AdminCodeUpdate
) -> Optional[Code]:
    code = db.query(Code).filter(Code.id == code_id).first()
    if code is None:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(code, field, value)
    db.commit()
    db.refresh(code)
    return code


def delete_code(db: Session, code_id: int) -> tuple[bool, str]:
    code = db.query(Code).filter(Code.id == code_id).first()
    if code is None:
        return False, "코드를 찾을 수 없습니다"
    db.delete(code)
    db.commit()
    return True, "삭제되었습니다"


# ── Settings ──────────────────────────────────────────────


def list_settings(
    db: Session, category: Optional[str] = None
) -> list[Setting]:
    query = db.query(Setting)
    if category:
        query = query.filter(Setting.category == category)
    return query.order_by(Setting.category, Setting.key).all()


def get_setting(db: Session, setting_id: int) -> Optional[Setting]:
    return db.query(Setting).filter(Setting.id == setting_id).first()


def create_setting(db: Session, data: AdminSettingCreate) -> Setting:
    setting = Setting(**data.model_dump())
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


def update_setting(
    db: Session, setting_id: int, data: AdminSettingUpdate
) -> Optional[Setting]:
    setting = get_setting(db, setting_id)
    if setting is None:
        return None
    if not setting.is_editable:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(setting, field, value)
    db.commit()
    db.refresh(setting)
    return setting


def delete_setting(db: Session, setting_id: int) -> tuple[bool, str]:
    setting = get_setting(db, setting_id)
    if setting is None:
        return False, "설정을 찾을 수 없습니다"
    if not setting.is_editable:
        return False, "편집할 수 없는 설정입니다"
    db.delete(setting)
    db.commit()
    return True, "삭제되었습니다"
