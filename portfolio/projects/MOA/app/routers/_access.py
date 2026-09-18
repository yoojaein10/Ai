"""공용 신원 확인 의존성.

app/routers/fee_basis.py 의 _require_hq_user 에서 **본사 전용 게이트만 뺀** 형태다.
fee_basis 쪽은 손대지 않는다 — tests/test_fee_basis_access.py 가 그 이름에 의존한다.

여기는 "누가 요청했는지"만 확인한다. 무엇을 할 수 있는지는 각 라우터가 정한다.
기재사항 저장은 '누가 적었는지'를 남겨야 하므로 신원이 필수다.
"""

import logging
from typing import Any

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.users import UserContextError, UserContextService

logger = logging.getLogger(__name__)


def require_user(
    db: Session = Depends(get_db),
    header_usr_seq: "str | None" = Header(None, alias="X-MOA-USR-SEQ"),
    query_usr_seq: "str | None" = Query(None, alias="usr_seq"),
    query_usr: "str | None" = Query(None, alias="usr"),
) -> dict[str, Any]:
    """요청자를 확인한다. 신원이 없거나 확인 불가면 막는다(권한 제한은 하지 않는다)."""
    raw = header_usr_seq or query_usr_seq or query_usr
    if not raw or not str(raw).isdigit():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자 확인이 필요합니다.",
        )
    try:
        return UserContextService(db)._resolve(str(raw))
    except (UserContextError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="사용자 권한을 확인할 수 없습니다.",
        ) from exc
