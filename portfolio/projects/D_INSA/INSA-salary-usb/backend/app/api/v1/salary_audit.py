from datetime import datetime
import ipaddress
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.netinfo import local_lan_ip
from app.db.models import SalaryAccessLog, User
from app.db.session import get_db
from app.schemas.salary_audit import (
    AccessLogCreate,
    AccessLogListResponse,
    AccessLogRow,
)

router = APIRouter(prefix="/salary", tags=["salary"])


def normalize_ip(raw: Optional[str]) -> Optional[str]:
    'IPv4-mapped IPv6(::ffff:192.0.2.10)와 IPv6 루프백(::1)을 IPv4 표기로 맞춘다.\n\n    Node(Vite 프록시)·듀얼스택 nginx가 이런 형태로 넘기면 좌석 규칙·수동 허용의\n    문자열 비교가 전부 어긋난다.\n    '
    if not raw:
        return raw
    if raw == "::1":
        return "127.0.0.1"
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return raw  # 예: TestClient의 "testclient"
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return str(addr.ipv4_mapped)
    return str(addr)


def client_ip(request: Request) -> Optional[str]:
    """nginx 뒤에서도 실제 클라이언트 IP를 얻는다.

    uvicorn을 --proxy-headers로 띄우면 request.client.host가 이미
    X-Forwarded-For의 첫 값으로 치환되어 있다.

    루프백(127.0.0.1)은 서버가 돌고 있는 바로 이 PC에서 온 요청이므로 그 PC의
    LAN IP로 바꾼다 — 같은 PC에서 localhost로 접속했다고 IP 판정이 달라지면 안 된다.
    """
    ip = normalize_ip(request.client.host if request.client else None)
    if ip == "127.0.0.1":
        return local_lan_ip() or ip
    return ip


def log_access(
    db: Session,
    *,
    user_id: int,
    action: str,
    request: Request,
    target_user_id: Optional[int] = None,
    record_count: Optional[int] = None,
) -> SalaryAccessLog:
    """다른 라우터(IP 정책 등)에서도 재사용한다.

    커밋하지 않는다 — 트랜잭션 경계는 호출자의 몫이다. flush만으로
    row.id 등을 채워 반환하므로, 호출자는 이 호출을 자신의 트랜잭션
    (예: 정책 변경 저장)에 포함시켜 함께 커밋하거나 함께 롤백할 수 있다.
    """
    row = SalaryAccessLog(
        user_id=user_id,
        action=action,
        target_user_id=target_user_id,
        record_count=record_count,
        ip_address=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        occurred_at=datetime.now(),
    )
    db.add(row)
    db.flush()
    return row


@router.post(
    "/access-logs", response_model=AccessLogRow, status_code=status.HTTP_201_CREATED
)
def create_access_log(
    data: AccessLogCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
) -> AccessLogRow:
    if data.target_user_id is not None:
        exists = db.query(User).filter(User.id == data.target_user_id).first()
        if exists is None:
            raise HTTPException(status_code=400, detail="후임자를 찾을 수 없습니다")

    row = log_access(
        db,
        user_id=current_user.id,
        action=data.action,
        request=request,
        target_user_id=data.target_user_id,
        record_count=data.record_count,
    )
    db.commit()
    return AccessLogRow.model_validate(row)


@router.get("/access-logs", response_model=AccessLogListResponse)
def list_access_logs(
    user_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("SYSTEM_ADMIN")),
) -> AccessLogListResponse:
    query = db.query(SalaryAccessLog)
    if user_id is not None:
        query = query.filter(SalaryAccessLog.user_id == user_id)
    if action is not None:
        query = query.filter(SalaryAccessLog.action == action)

    total = query.count()
    rows = (
        query.order_by(desc(SalaryAccessLog.occurred_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    return AccessLogListResponse(
        items=[AccessLogRow.model_validate(r) for r in rows], total=total
    )
