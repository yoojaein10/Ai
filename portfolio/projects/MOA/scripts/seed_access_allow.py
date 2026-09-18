"""a10_access_allow 시드: 화면 접근 허용 명단.

이 명단에 활성 행이 있으면 명단 밖 사용자는 화면이 열리지 않는다.
재실행 가능(upsert). 명단을 통째로 끄려면 표를 비우거나 active='N'으로.

실행: python -m scripts.seed_access_allow
"""

from sqlalchemy import select

from app.database import get_session_factory
from app.models.access_allow import AccessAllow

# (USR_SEQ, 이름) — 2026-07-22 확정. 동명이인은 재직·소속 확인 후 결정.
# 박중현은 본사(4122), 유재인·임정미는 재직자 기준.
ALLOWED = [
    (813, "이일우"),
    (1260, "유재인"),
    (2012, "원동하"),
    (77, "김경희"),
    (1171, "장세희"),
    (1060, "임정미"),
    (429, "박중현"),
    (1996, "고정은"),
    # 신한은행 발송기한 관리(/desktop/shinhan-delay) 사용자 (2026-09-02).
    # 문(allowlist)만 연다 — 화면 자체는 shinhanDelay 개인 예외가 따로 막는다.
    (2013, "엄기원"),
]


def main() -> None:
    with get_session_factory()() as db:
        for usr_seq, name in ALLOWED:
            row = db.scalar(select(AccessAllow).where(AccessAllow.usr_seq == usr_seq))
            if row is None:
                db.add(AccessAllow(usr_seq=usr_seq, emp_name=name, active="Y"))
            else:
                row.emp_name = name
                row.active = "Y"
        db.commit()
        active = db.scalars(
            select(AccessAllow).where(AccessAllow.active == "Y").order_by(AccessAllow.emp_name)
        ).all()
    print(f"접근 허용 명단 {len(active)}명:")
    for row in active:
        print(f"  {row.emp_name} (USR_SEQ={row.usr_seq})")


if __name__ == "__main__":
    main()
