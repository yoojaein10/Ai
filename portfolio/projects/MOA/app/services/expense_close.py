"""실비 종결 처리 — 입금현황 우클릭 '실비 처리' (2026-09-01 사용자 결정).

실비만 받고 끝나는 건(취하·반려 등)은 상태 처리도 안 된 경우가 많아 재무팀만
안다. 그래서 자동 감지 대신 사람이 누른다. 처리하면 그 시점 수금액이 감정서의
최종 매출(기준액)이 되어 완납으로 끝나고, 미수금현황에서 빠지며, 배분 초안도
안 만든다. APWorks의 여비·기타실비 필드와는 무관하다.

되돌리기: 해제는 삭제가 아니라 released_* 를 채운다 — 판정만 바꾸는 꼬리표라
해제하면 모든 화면이 즉시 원래 판정으로 돌아가고, 누가 언제 처리·해제했는지
이력이 남는다.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.expense_close import ExpenseClose


class ExpenseCloseError(ValueError):
    pass


def active_close(db: Session, doc_id: str) -> "ExpenseClose | None":
    return db.scalars(
        select(ExpenseClose).where(
            ExpenseClose.doc_id == doc_id,
            ExpenseClose.released_at.is_(None),
        )
    ).first()


def _paid_amount(db: Session, doc_id: str) -> float:
    """이 감정서의 현재 수금액 — 입금현황 화면과 같은 식(_PAID).

    확정 금액이 화면의 수금액과 다르면 사용자가 혼란스럽다. 스코프판 CTE 로
    이 감정서 하나만 정산해 같은 값을 낸다.
    """
    from app.services.receivables import _PAID, _settle_cte, _source_view

    scoped = _settle_cte("SELECT CAST(:doc AS VARCHAR(500)) AS doc_id")
    paid = db.execute(
        text(
            scoped
            + f"SELECT {_PAID} AS paid "
            f"FROM dbo.a10_receivable_summary b "
            f"LEFT JOIN {_source_view()} a ON a.DocID = b.doc_id "
            "LEFT JOIN settle s ON s.doc_id = b.doc_id "
            "LEFT JOIN tax_doc t ON t.doc_id = b.doc_id "
            "LEFT JOIN dbo.a10_expense_close ec "
            "  ON ec.doc_id = b.doc_id AND ec.released_at IS NULL "
            "WHERE b.doc_id = CAST(:doc AS VARCHAR(500))"
        ),
        {"doc": doc_id},
    ).scalar()
    return float(paid or 0)


def mark(db: Session, doc_id: str, usr_seq: int) -> "dict[str, Any]":
    doc_id = str(doc_id or "").strip()
    if not doc_id:
        raise ExpenseCloseError("감정서번호가 비어 있습니다.")
    if active_close(db, doc_id) is not None:
        raise ExpenseCloseError("이미 실비 처리된 감정서입니다.")
    paid = _paid_amount(db, doc_id)
    # 입금이 아예 없는 건은 실비 처리 대상이 아니다 (2026-09-01 사용자 요구 —
    # 화면에서도 비활성이지만 서버가 최종 관문이다).
    if paid <= 0:
        raise ExpenseCloseError("입금이 없는 감정서는 실비 처리할 수 없습니다.")
    row = ExpenseClose(
        doc_id=doc_id,
        closed_amount=Decimal(str(round(paid, 4))),
        closed_by=usr_seq,
        closed_at=datetime.now(),
    )
    db.add(row)
    db.commit()
    return {"doc_id": doc_id, "closed_amount": paid}


def release(db: Session, doc_id: str, usr_seq: int) -> "dict[str, Any]":
    row = active_close(db, str(doc_id or "").strip())
    if row is None:
        raise ExpenseCloseError("실비 처리된 기록이 없는 감정서입니다.")
    row.released_by = usr_seq
    row.released_at = datetime.now()
    db.commit()
    return {"doc_id": row.doc_id}
