"""업무실적 기재사항 저장·복원.

설계 원칙 — 보수기준 점검(fee_basis) 의견 저장에서 터졌던 세 가지를 구조적으로 막는다.

(a) 빈 값 부활: excluded 를 3상태로 저장한다(행 없음 / 'Y' / 'N'). 화면에 내려줄 때도
    NOTE_EXCLUDED 를 None|True|False 로 자동기본값과 분리해 보낸다. `저장값 or 자동값`
    같은 falsy 병합을 쓰면 '일부러 포함'이 자동기본값(제외)으로 되살아난다.
    빈 사유는 지우지 않는다 — 사유를 비운 것도 결정이다. 행 삭제는 None 을 명시적으로
    보냈을 때만 한다(화면의 '자동값으로 되돌리기').

(b) 409 막다른길: 낙관적 잠금 토큰을 만들지 않는다. 저장은 자연키 per-doc upsert 이고
    사전 조건 검사가 없어서 409 를 낼 코드 경로 자체가 없다. 원천 금액이 바뀐 것은
    amount_fingerprint 로 표시만 하고(NOTE_STALE) 저장·전송을 막지 않는다.

(c) decisions_json 초기화: 사람 입력을 산출물과 같은 행·같은 JSON 칸에 두지 않는다.
    감정서 1건 = 1행이라 '통째 교체' 연산이 존재하지 않는다.
"""

import hashlib
import re
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.work_report_note import MAX_MEMO, MAX_REASON, WorkReportNote

DOC_ID_RE = re.compile(r"^[0-9A-Za-z-]{1,30}$")

# 사유 입력 제안(화면 datalist). 강제 목록이 아니라 힌트다 — 컬럼은 자유 문자열이라
# 나중에 코드 체계를 도입해도 스키마 변경 없이 값만 정규화하면 된다.
REASON_SUGGESTIONS = (
    "중복보고",
    "실비만 입금",
    "타지사 이관",
    "취소·반려",
    "차기 반월 보고",
)


class NoteStoreError(RuntimeError):
    """기재사항 저장소에 접근하지 못했다(테이블 없음·연결 실패 등)."""


def amount_fingerprint(row: dict[str, Any]) -> str:
    """저장 시점의 금액 지문. 원천이 바뀌었는지 표시하는 용도로만 쓴다."""
    raw = f"{row.get('GAMGA') or ''}|{row.get('SUSU') or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _row_to_dict(note: WorkReportNote) -> dict[str, Any]:
    return {
        "excluded": note.excluded == "Y",
        "reason": note.reason or "",
        "memo": note.memo or "",
        "amount_fingerprint": note.amount_fingerprint,
        "last_basis": note.last_basis,
        "updated_by": note.updated_by,
        "updated_by_name": note.updated_by_name,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
    }


def load_notes(
    db: Session, *, office_code: str, year: int, month: int, half: str
) -> dict[str, dict[str, Any]]:
    """(지사, 년, 월, 반월)의 기재사항 전체. 감정서번호 -> 값."""
    try:
        rows = db.execute(
            select(WorkReportNote).where(
                WorkReportNote.office_code == office_code,
                WorkReportNote.period_year == year,
                WorkReportNote.period_month == month,
                WorkReportNote.half == half,
            )
        ).scalars().all()
    except SQLAlchemyError as error:
        raise NoteStoreError(str(error)) from error
    return {note.doc_id: _row_to_dict(note) for note in rows}


def apply_notes_to_rows(
    rows: list[dict[str, Any]], notes: dict[str, dict[str, Any]]
) -> None:
    """조회 결과 행에 기재사항을 얹는다. 행을 걸러내지는 않는다.

    서버가 저장값으로 행을 미리 빼버리면 담당자가 그 감정서를 다시 포함시킬 경로가
    사라진다. 실제로 제외되는 목록은 지금처럼 화면 체크박스에서 온 exclude 쿼리다.
    """
    for row in rows:
        doc_id = str(row.get("ID_NUM") or "").strip()
        note = notes.get(doc_id)
        if not note:
            row["NOTE_EXCLUDED"] = None  # 손대지 않음 — 화면이 자동기본값을 쓴다
            row["NOTE_REASON"] = ""
            row["NOTE_MEMO"] = ""
            row["NOTE_STALE"] = False
            row["NOTE_UPDATED_BY"] = None
            continue
        row["NOTE_EXCLUDED"] = note["excluded"]
        row["NOTE_REASON"] = note["reason"]
        row["NOTE_MEMO"] = note["memo"]
        saved = note.get("amount_fingerprint")
        row["NOTE_STALE"] = bool(saved) and saved != amount_fingerprint(row)
        row["NOTE_UPDATED_BY"] = note.get("updated_by_name")


def load_saved_list(
    db: Session, *, office_code: str, year: int, month: int, half: str
) -> list[str]:
    """저장된 작업 목록의 감정서번호. 없으면 빈 목록.

    이 목록이 비어 있지 않으면 화면은 자동선택 대신 이걸 그대로 복원한다(A안).
    기준(접수/전례/매출)은 키에 없다 — 기재사항과 같은 규칙으로, 한 반월의 제출
    목록은 하나다.
    """
    try:
        rows = db.execute(
            select(WorkReportNote.doc_id).where(
                WorkReportNote.office_code == office_code,
                WorkReportNote.period_year == year,
                WorkReportNote.period_month == month,
                WorkReportNote.half == half,
                WorkReportNote.in_list == "Y",
            ).order_by(WorkReportNote.doc_id)
        ).scalars().all()
    except SQLAlchemyError as error:
        raise NoteStoreError(str(error)) from error
    return [str(doc) for doc in rows]


def save_list(
    db: Session,
    *,
    office_code: str,
    year: int,
    month: int,
    half: str,
    basis: str | None,
    rows: list[dict[str, Any]],
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """화면의 목록 전체를 저장한다 — 멤버십(in_list) + 체크(excluded) + 사유.

    rows: [{doc_id, excluded, reason, memo?}] — 화면에 떠 있는 전 행.
    목록에서 빠진 감정서는 in_list='N' 으로 되돌린다(기재사항 자체는 지운다 —
    목록에 없는 사유는 화면에서 볼 길이 없어 남겨두면 고아 행이 된다).

    save_notes 와 달리 '건드린 것만'이 아니라 전 행을 쓴다. 중간에 끊겨도 마지막
    저장 시점 그대로 돌아오게 하는 것이 목적이다(2026-09-07).
    """
    now = datetime.now()
    usr_seq = None
    usr_name = None
    if user:
        try:
            usr_seq = int(user.get("usr_seq")) if user.get("usr_seq") is not None else None
        except (TypeError, ValueError):
            usr_seq = None
        usr_name = (user.get("emp_name") or user.get("usr_id") or None)

    rejected: list[dict[str, str]] = []
    keep: set[str] = set()
    try:
        for row in rows:
            doc_id = str(row.get("doc_id") or "").strip()
            if not DOC_ID_RE.match(doc_id):
                rejected.append({
                    "doc_id": doc_id, "code": "BAD_DOC_ID",
                    "message": "감정서번호 형식이 올바르지 않습니다.",
                })
                continue
            try:
                reason = _clean_text(row.get("reason"), MAX_REASON, "사유")
                memo = _clean_text(row.get("memo"), MAX_MEMO, "메모")
            except ValueError as error:
                rejected.append({"doc_id": doc_id, "code": "TOO_LONG", "message": str(error)})
                continue
            key = dict(
                office_code=office_code, period_year=year,
                period_month=month, half=half, doc_id=doc_id,
            )
            note = db.get(WorkReportNote, tuple(key.values()))
            if note is None:
                note = WorkReportNote(**key)
                db.add(note)
            note.in_list = "Y"
            note.excluded = "Y" if row.get("excluded") else "N"
            note.reason = reason
            note.memo = memo
            note.last_basis = basis
            note.updated_by = usr_seq
            note.updated_by_name = usr_name
            note.updated_at = now
            keep.add(doc_id)

        # 목록에서 빠진 건 정리 — 저장된 적 있으나 이번 목록에 없는 행을 지운다.
        stale = db.execute(
            select(WorkReportNote).where(
                WorkReportNote.office_code == office_code,
                WorkReportNote.period_year == year,
                WorkReportNote.period_month == month,
                WorkReportNote.half == half,
            )
        ).scalars().all()
        removed = 0
        for note in stale:
            if note.doc_id not in keep:
                db.delete(note)
                removed += 1
        db.commit()
    except SQLAlchemyError as error:
        db.rollback()
        raise NoteStoreError(str(error)) from error

    return {
        "saved_count": len(keep),
        "removed_count": removed,
        "rejected": rejected,
        "saved_at": now.isoformat(),
        "saved_by": usr_name,
    }


def saved_list_meta(
    db: Session, *, office_code: str, year: int, month: int, half: str
) -> dict[str, Any]:
    """저장본 표시용 정보 — 언제·누가 저장했고 몇 건인지."""
    try:
        rows = db.execute(
            select(WorkReportNote).where(
                WorkReportNote.office_code == office_code,
                WorkReportNote.period_year == year,
                WorkReportNote.period_month == month,
                WorkReportNote.half == half,
                WorkReportNote.in_list == "Y",
            )
        ).scalars().all()
    except SQLAlchemyError as error:
        raise NoteStoreError(str(error)) from error
    if not rows:
        return {"count": 0, "saved_at": None, "saved_by": None}
    latest = max(rows, key=lambda note: note.updated_at or datetime.min)
    return {
        "count": len(rows),
        "saved_at": latest.updated_at.isoformat() if latest.updated_at else None,
        "saved_by": latest.updated_by_name,
    }


def _clean_text(value: Any, limit: int, field: str) -> str:
    text = "" if value is None else str(value).strip()
    if len(text) > limit:
        raise ValueError(f"{field}는 {limit}자를 넘을 수 없습니다.")
    return text


def save_notes(
    db: Session,
    *,
    office_code: str,
    year: int,
    month: int,
    half: str,
    basis: str | None,
    notes: dict[str, Any],
    rows_by_doc: dict[str, dict[str, Any]] | None = None,
    user: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """감정서별 기재사항을 저장한다. 값이 None 이면 그 감정서의 행을 지운다.

    검증 실패는 감정서 단위로 격리한다 — 한 건이 잘못됐다고 나머지를 버리지 않는다.
    '현재 목록에 있는지'로는 막지 않는다. 수기 추가(extra_doc_ids)로 자동목록 밖
    감정서를 넣는 것이 이 화면의 정상 동작이라 목록 기반 검증은 성립하지 않는다.
    """
    saved_count = 0
    deleted_count = 0
    rejected: list[dict[str, str]] = []
    now = datetime.now()
    usr_seq = None
    usr_name = None
    if user:
        try:
            usr_seq = int(user.get("usr_seq")) if user.get("usr_seq") is not None else None
        except (TypeError, ValueError):
            usr_seq = None
        # UserContextService._resolve 가 돌려주는 이름 키는 emp_name 이다
        # (TMWCMN_USR_BAC_INFO.EMP). usr_nm/name 으로 찾으면 항상 비어 있다.
        usr_name = (user.get("emp_name") or user.get("usr_id") or None)

    for raw_doc, payload in notes.items():
        doc_id = str(raw_doc or "").strip()
        if not DOC_ID_RE.match(doc_id):
            rejected.append({
                "doc_id": doc_id, "code": "BAD_DOC_ID",
                "message": "감정서번호 형식이 올바르지 않습니다.",
            })
            continue
        key = dict(
            office_code=office_code, period_year=year,
            period_month=month, half=half, doc_id=doc_id,
        )
        try:
            if payload is None:
                result = db.execute(
                    delete(WorkReportNote).where(
                        WorkReportNote.office_code == office_code,
                        WorkReportNote.period_year == year,
                        WorkReportNote.period_month == month,
                        WorkReportNote.half == half,
                        WorkReportNote.doc_id == doc_id,
                    )
                )
                deleted_count += int(result.rowcount or 0)
                continue

            reason = _clean_text(payload.get("reason"), MAX_REASON, "사유")
            memo = _clean_text(payload.get("memo"), MAX_MEMO, "메모")
            excluded = "Y" if payload.get("excluded") else "N"
            fingerprint = None
            if rows_by_doc and doc_id in rows_by_doc:
                fingerprint = amount_fingerprint(rows_by_doc[doc_id])

            note = db.get(WorkReportNote, tuple(key.values()))
            if note is None:
                note = WorkReportNote(**key)
                db.add(note)
            note.excluded = excluded
            note.reason = reason
            note.memo = memo
            if fingerprint:
                note.amount_fingerprint = fingerprint
            note.last_basis = basis
            note.updated_by = usr_seq
            note.updated_by_name = usr_name
            note.updated_at = now
            saved_count += 1
        except ValueError as error:
            rejected.append({"doc_id": doc_id, "code": "TOO_LONG", "message": str(error)})
        except SQLAlchemyError as error:
            db.rollback()
            raise NoteStoreError(str(error)) from error

    try:
        db.commit()
    except SQLAlchemyError as error:
        db.rollback()
        raise NoteStoreError(str(error)) from error

    return {
        "saved_count": saved_count,
        "deleted_count": deleted_count,
        "rejected": rejected,
        "notes": load_notes(
            db, office_code=office_code, year=year, month=month, half=half
        ),
    }
