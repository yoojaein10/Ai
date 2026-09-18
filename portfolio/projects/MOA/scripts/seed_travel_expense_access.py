"""출장비(travelExpense) 메뉴를 본사 권한 묶음 전부에 넣는다 (2026-09-10).

델파이 출장비프로그램은 본사(Office 10) 전 직원이 열었다 — 조사자 54명이 적고 결재자 10명(APWorks
결재자 명단)이 결재한다. 그래서 활성 본사 묶음 전부에 얹는다. 지사 묶음은 손대지 않는다(델파이도 본사만).
묶음 저장은 서비스(save_role)를 거쳐 변경 이력과 가드를 그대로 탄다. 권한 관리 화면에서도 켜고 끌 수 있다.

  python -m scripts.seed_travel_expense_access            # 미리보기
  python -m scripts.seed_travel_expense_access --apply    # 실제 반영
"""

import argparse
import json

from sqlalchemy import select

from app.database import get_session_factory
from app.models.access_role import AccessRole
from app.services.access_roles import save_role

MENU_KEY = "travelExpense"
REQUESTER = 813   # 이일우 — 시드 실행자


def _flag(value: "str | None") -> "bool | None":
    return {"Y": True, "N": False}.get(str(value or "").strip().upper())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="실제로 저장 (없으면 미리보기)")
    args = parser.parse_args()
    with get_session_factory()() as db:
        roles = db.scalars(select(AccessRole).where(AccessRole.active == "Y", AccessRole.office_id == "10")).all()
        for role in roles:
            keys = list(json.loads(role.menu_keys_json or "[]"))
            if MENU_KEY in keys:
                print(f"{role.role_id} {role.name}: 이미 있음")
                continue
            print(f"{role.role_id} {role.name}: {len(keys)}개 → +{MENU_KEY}")
            if not args.apply:
                continue
            save_role(
                db, role_id=role.role_id, name=role.name, menu_keys=[*keys, MENU_KEY],
                view_all_offices=_flag(role.view_all_offices), view_other_users=_flag(role.view_other_users),
                memo=role.memo, updated_by_usr_seq=REQUESTER, office_id=role.office_id or "10",
            )
            print("   저장 완료")
        if not args.apply:
            print("미리보기만 했습니다. 반영하려면 --apply")


if __name__ == "__main__":
    main()
