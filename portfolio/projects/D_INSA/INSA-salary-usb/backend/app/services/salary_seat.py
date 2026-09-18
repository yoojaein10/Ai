"""연봉 금고 좌석 IP 매핑 — APW SEAT_USERINFO 조회.

규칙: 로그인 ID(APWID)로 좌석 행을 찾고, 담당자 PC IP는
``SALARY_SEAT_IP_PREFIX + UID`` 여야 한다. 읽기 전용이며 필요한 컬럼만 조회한다
(SEAT_USERINFO에는 PWD 등 민감 컬럼이 있으므로 ``SELECT *`` 금지).
"""
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings


def lookup_seat_uid(apw_db: Optional[Session], login_id: str) -> Optional[int]:
    """APWID가 login_id인 좌석의 UID. 없거나 조회 불가면 None.

    예외는 삼키지 않고 그대로 올린다 — 호출자가 fail-closed로 처리한다.
    """
    if apw_db is None:
        return None
    row = apw_db.execute(
        text("SELECT TOP 1 UID FROM dbo.SEAT_USERINFO WHERE APWID = :login_id"),
        {"login_id": login_id},
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def expected_ip_for_uid(uid: int) -> str:
    return f"{settings.SALARY_SEAT_IP_PREFIX}{uid}"
