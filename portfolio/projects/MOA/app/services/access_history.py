"""권한 변경을 한 줄씩 남긴다.

쓰는 쪽이 지켜야 할 것 하나: **이력 실패가 본 작업을 막으면 안 된다.**
권한을 못 바꾸는 것보다 이력이 한 줄 비는 편이 낫다 — 이력 표가 아직 없는
환경(운영 반영 전)에서도 권한 화면은 돌아야 한다. 그래서 record() 는 어떤
예외도 밖으로 내보내지 않고, 대신 로그에 남긴다.

다만 **삼키는 자리를 여기 한 곳으로 모은다.** 호출하는 쪽마다 try/except 를
흩어 두면 어디가 조용히 실패하는지 알 수 없게 된다.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.access_change import AccessChange

logger = logging.getLogger(__name__)


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return json.dumps({"_unserializable": str(value)}, ensure_ascii=False)


def record(
    db: Session,
    *,
    target_kind: str,
    target_key: str | int,
    action: str,
    before: Any = None,
    after: Any = None,
    target_label: str | None = None,
    actor_usr_seq: int | None = None,
    requested_by_usr_seq: int | None = None,
    reason: str | None = None,
    status: str = "applied",
) -> None:
    """변경 한 줄을 쌓는다. **commit 하지 않는다** — 부르는 쪽 트랜잭션에 얹힌다.

    같은 트랜잭션에 얹는 이유: 권한은 바뀌었는데 이력만 빠지거나 그 반대가
    되면 이력을 믿을 수 없다. 둘이 함께 커밋되거나 함께 없어야 한다.

    requested_by_usr_seq 를 안 주면 actor 와 같다고 본다 — 관리자가 직접 바꾼
    경우다. 신청 흐름이 붙으면 그때 둘이 갈린다.
    """
    row = AccessChange(
        target_kind=target_kind,
        target_key=str(target_key)[:120],
        target_label=(target_label or None) and str(target_label)[:120],
        action=action,
        status=status,
        before_json=_dump(before),
        after_json=_dump(after),
        actor_usr_seq=actor_usr_seq,
        requested_by_usr_seq=(
            actor_usr_seq if requested_by_usr_seq is None else requested_by_usr_seq
        ),
        reason=(reason or None) and str(reason)[:400],
    )
    # **세이브포인트 안에서 쓴다.** 그냥 flush 하면, 표가 없는 환경에서 실패가
    # 바깥 트랜잭션까지 더럽혀 뒤따르는 commit 이 통째로 깨진다 — 이력 한 줄
    # 때문에 권한 저장이 실패하는 것이다(2026-08-16 시험 19개가 그렇게 깨졌다).
    # 세이브포인트는 실패해도 그 지점까지만 되돌리고 본 작업은 살려 둔다.
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except SQLAlchemyError as exc:
        logger.warning("권한 변경 이력을 남기지 못했습니다 (%s %s): %s",
                       target_kind, target_key, exc)
        # 세이브포인트가 이미 되돌렸으므로 세션은 깨끗하다. 본 작업은 계속된다.
        if row in db:
            db.expunge(row)


def history(
    db: Session, *, target_kind: str | None = None, target_key: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """이력을 최근 순으로 읽는다. 화면이 '이 사람/이 묶음이 언제부터' 를 보여 줄 때."""
    from sqlalchemy import select  # noqa: PLC0415

    try:
        stmt = select(AccessChange).order_by(AccessChange.change_id.desc()).limit(limit)
        if target_kind:
            stmt = stmt.where(AccessChange.target_kind == target_kind)
        if target_key:
            stmt = stmt.where(AccessChange.target_key == str(target_key))
        rows = db.scalars(stmt).all()
    except SQLAlchemyError:
        return []          # 표가 아직 없다 — 화면은 '이력 없음'으로 뜬다
    return [
        {
            "change_id": row.change_id,
            "target_kind": row.target_kind,
            "target_key": row.target_key,
            "target_label": row.target_label,
            "action": row.action,
            "status": row.status,
            "before": json.loads(row.before_json) if row.before_json else None,
            "after": json.loads(row.after_json) if row.after_json else None,
            "actor_usr_seq": row.actor_usr_seq,
            "requested_by_usr_seq": row.requested_by_usr_seq,
            "reason": row.reason,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
