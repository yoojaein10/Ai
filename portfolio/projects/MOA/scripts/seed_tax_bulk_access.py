"""계산서 일괄발급(taxBulk) 메뉴를 본사 권한 묶음에 넣는다 (2026-08-27).

대상 = 카드전표(cardVouchers)가 이미 든 활성 본사 묶음 — 같은 사람들(본사 재무팀·전산정보팀·관리자)이
쓰는 화면이라 같은 묶음에 얹는다. 묶음 저장은 서비스(save_role)를 거쳐 변경 이력과 가드를 그대로 탄다.
권한 관리 화면에서도 켜고 끌 수 있다.

  python -m scripts.seed_tax_bulk_access            # 미리보기
  python -m scripts.seed_tax_bulk_access --apply    # 실제 반영
"""

import argparse
import json

from sqlalchemy import select

from app.database import get_session_factory
from app.models.access_role import AccessRole
from app.services.access_roles import save_role

MENU_KEY = "taxBulk"
ANCHOR_KEY = "cardVouchers"
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
            if ANCHOR_KEY not in keys:
                continue
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
            print(f"   저장 완료")
        if not args.apply:
            print("미리보기만 했습니다. 반영하려면 --apply")


if __name__ == "__main__":
    main()
