"""일계표 대사(bankReconcile) 개인 예외 — 이일우(813)·장세희(1171)에게만 켠다.

메뉴 키는 어떤 묶음(role)에도 넣지 않는다. 권한관리 화면에서도 켜고 끌 수 있고,
여기서는 기존 개인 예외를 지우지 않고 bankReconcile 만 더한다(변경 이력 기록).

  python -m scripts.seed_bank_reconcile_access --dry-run
  python -m scripts.seed_bank_reconcile_access
"""

import argparse

from app.database import get_session_factory
from app.models.access_policy import AccessPolicy
from app.services.access_policy import _menu_overrides
from app.services.permissions import save_access_policy

MENU_KEY = "bankReconcile"
ALLOWED = [(813, "이일우"), (1171, "장세희")]      # 2026-08-26 사용자 지정
REQUESTER = 813
MEMO = "일계표 대사 개인 예외 (2026-08-26, 이일우·장세희만)"


def _flag(value: "str | None") -> "bool | None":
    return None if value is None else value == "Y"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with get_session_factory()() as db:
        for usr_seq, name in ALLOWED:
            row = db.get(AccessPolicy, usr_seq)
            current = _menu_overrides(row.menu_overrides_json) if row else {}
            merged = {**current, MENU_KEY: True}
            state = "없음" if row is None else f"active={row.active} overrides={current}"
            print(f"{name}({usr_seq}): 현재 {state} → {merged}")
            if args.dry_run:
                continue
            save_access_policy(
                db, usr_seq=usr_seq, requester_usr_seq=REQUESTER,
                view_all_offices=_flag(row.view_all_offices_override if row else None),
                view_other_users=_flag(row.view_other_users_override if row else None),
                menu_overrides=merged, active=True, memo=MEMO,
            )
            print(f"  저장됨: {name}")


if __name__ == "__main__":
    main()
