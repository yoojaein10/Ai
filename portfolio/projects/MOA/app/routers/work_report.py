"""협회 업무실적 보고 API. 반월·기준으로 감정서를 뽑아 미리보기/엑셀 내보내기.

지사는 자기 지사(office_code)만 조회하도록 화면에서 코드를 고정한다.
"""

import logging
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import AccessContext, require_menu, resolve_office_scope
from app.schemas.common import ApiResponse
from app.services.excel_export import XLSX_MEDIA_TYPE
from app.services.kapa_submit import (
    KapaNotConfiguredError,
    KapaQueryError,
    fetch_registered_doc_ids,
    submit_work_report,
)
from app.services.work_report import Basis, Half, build_kapa_rows
from app.services.work_report_excel import build_work_report_xlsx
from app.services.work_report_missing import scan_missing
from app.services.work_report_import import extract_work_report_doc_ids
from app.services.work_report_note import (
    REASON_SUGGESTIONS,
    NoteStoreError,
    apply_notes_to_rows,
    load_notes,
    load_saved_list,
    save_list,
    save_notes,
    saved_list_meta,
)

router = APIRouter(prefix="/api/work-report", tags=["work-report"])

logger = logging.getLogger(__name__)

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _doc_list(value: str | None) -> list[str]:
    """콤마로 구분된 감정서번호 목록 파싱 (수기 추가/제외용)."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@router.post("/import", response_model=ApiResponse)
async def import_excel(
    file: UploadFile = File(...),
    # 파일을 받아 파싱하는 자리다. DB 를 읽지는 않지만 인증 없이 열어 둘 이유도
    # 없다 — 업무실적 메뉴를 쓰는 사람만 올린다 (2026-08-07 점검).
    _access: AccessContext = Depends(require_menu("workReport")),
) -> ApiResponse:
    """업무실적 엑셀에서 감정서번호만 읽어 수기 추가용 목록으로 반환한다."""
    filename = file.filename or ""
    if not filename.lower().endswith((".xls", ".xlsx")):
        return ApiResponse(
            success=False, code="BAD_FILE",
            message="엑셀 파일(.xls, .xlsx)만 올릴 수 있습니다.", data=None,
        )
    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(data) > _MAX_UPLOAD_BYTES:
        return ApiResponse(
            success=False, code="FILE_TOO_LARGE",
            message="엑셀 파일은 10MB 이하만 올릴 수 있습니다.", data=None,
        )
    try:
        docs = extract_work_report_doc_ids(data, filename)
    except Exception as error:
        return ApiResponse(
            success=False, code="BAD_FILE",
            message=f"엑셀 파일을 읽지 못했습니다: {error}", data=None,
        )
    if not docs:
        return ApiResponse(
            success=False, code="NO_DOCS",
            message="엑셀에서 감정서번호를 찾지 못했습니다.", data=None,
        )
    return ApiResponse(
        success=True, code="0000", message=f"감정서번호 {len(docs)}건을 불러왔습니다.",
        data={"doc_ids": docs, "count": len(docs), "filename": filename},
    )


@router.get("/preview", response_model=ApiResponse)
def preview(
    year: int,
    month: int,
    half: Half,
    basis: Basis,
    office_code: str = "10",
    extra: str | None = None,
    exclude: str | None = None,
    fresh: bool = False,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("workReport")),
) -> ApiResponse:
    """화면 미리보기용. 협회 컬럼과 행을 그대로 반환(수기 추가/제외 반영).

    저장된 작업 목록이 있으면 자동선택 대신 그것을 그대로 복원한다(2026-09-07 A안).
    fresh=true 면 저장본을 무시하고 원천에서 다시 뽑는다 — 저장된 체크·사유는
    감정서번호로 다시 얹히므로 결정은 남는다.
    """
    # 권한 범위 판정은 try 밖에서 — 아래 except가 403 격리 예외를 삼키지 않도록 한다.
    scoped_office = resolve_office_scope(access, office_code) or "10"
    saved_docs: list[str] = []
    if not fresh:
        try:
            saved_docs = load_saved_list(
                db, office_code=scoped_office, year=year, month=month, half=half
            )
        except NoteStoreError as error:
            logger.warning("저장 목록 조회 실패 (%s) — 자동선택으로 계속합니다.", error)
    try:
        data = build_kapa_rows(
            db, office_id=scoped_office,
            year=year, month=month, half=half, basis=basis,
            extra_doc_ids=_doc_list(extra), exclude_doc_ids=_doc_list(exclude),
            only_doc_ids=saved_docs or None,
        )
    except Exception as error:  # 원인 파악을 위해 실제 메시지를 화면에 돌려준다
        return ApiResponse(
            success=False, code="ERROR",
            message=f"{type(error).__name__}: {error}", data=None,
        )
    data["count"] = len(data.get("rows", []))
    data["restored"] = bool(saved_docs)

    # 저장된 기재사항 병합. 행을 걸러내지는 않는다 — 저장값은 체크박스 초기값으로만 쓴다.
    # 읽지 못하면 notes_loaded=False 로 알리고 화면이 편집을 잠근다. 못 읽은 채로
    # 저장을 허용하면 기존 결정을 덮어쓴다.
    try:
        notes = load_notes(
            db, office_code=office_code, year=year, month=month, half=half
        )
        apply_notes_to_rows(data["rows"], notes)
        data["notes_loaded"] = True
        data["note_count"] = len(notes)
    except NoteStoreError as error:
        logger.warning("기재사항 조회 실패 (%s) — 편집 잠금으로 계속합니다.", error)
        apply_notes_to_rows(data["rows"], {})
        data["notes_loaded"] = False
        data["note_count"] = 0
    data["reason_suggestions"] = list(REASON_SUGGESTIONS)
    # 저장본 표시(언제·누가·몇 건). 실패해도 미리보기는 계속한다.
    try:
        data["saved_list"] = saved_list_meta(
            db, office_code=scoped_office, year=year, month=month, half=half
        )
    except NoteStoreError:
        data["saved_list"] = {"count": 0, "saved_at": None, "saved_by": None}

    # 협회 등록 여부 병합 — 조회 실패해도 미리보기는 계속 (확인불가로 표시)
    try:
        registered = fetch_registered_doc_ids(data["appcode"], data["bungi"], data["month"])
        for row in data["rows"]:
            row["KAPA_REGISTERED"] = row.get("ID_NUM") in registered
        data["kapa_checked"] = True
        data["kapa_registered_count"] = sum(
            1 for row in data["rows"] if row["KAPA_REGISTERED"]
        )
    except Exception:
        for row in data["rows"]:
            row["KAPA_REGISTERED"] = None
        data["kapa_checked"] = False
        data["kapa_registered_count"] = None
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.get("/missing", response_model=ApiResponse)
def missing(
    basis: Basis,
    from_year: int,
    from_month: int,
    to_year: int,
    to_month: int,
    cur_year: int,
    cur_month: int,
    office_code: str = "10",
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("workReport")),
) -> ApiResponse:
    """기간(from~to)에 걸친 협회 미등록(누락) 건. 화면에서 골라 현재 회차에 수기 추가한다.

    협회 서버를 달마다 조회하므로 시간이 걸린다(범위 상한은 서비스가 강제). 협회 조회가
    실패하면 누락을 신뢰할 수 없어 그대로 오류로 돌려준다 — 전부 미등록으로 오인해
    잘못 추가·전송하는 것을 막는다.
    """
    scoped_office = resolve_office_scope(access, office_code) or "10"
    try:
        data = scan_missing(
            db, office_id=scoped_office, basis=basis,
            from_year=from_year, from_month=from_month,
            to_year=to_year, to_month=to_month,
            current_year=cur_year, current_month=cur_month,
        )
    except ValueError as error:
        return ApiResponse(success=False, code="BAD_RANGE", message=str(error), data=None)
    except (KapaQueryError, KapaNotConfiguredError) as error:
        return ApiResponse(
            success=False, code="KAPA_PROTECT",
            message=f"협회 등록 조회에 실패해 누락을 확인할 수 없습니다: {error}", data=None,
        )
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.get("/export.xlsx", response_model=None)
def export(
    year: int,
    month: int,
    half: Half,
    basis: Basis,
    office_code: str = "10",
    extra: str | None = None,
    exclude: str | None = None,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("workReport")),
) -> Response:
    """협회 업로드용 엑셀(.xlsx). 미리보기와 같은 조건으로 양식을 채워 내려준다."""
    scoped_office = resolve_office_scope(access, office_code) or "10"
    try:
        saved_docs = load_saved_list(
            db, office_code=scoped_office, year=year, month=month, half=half
        )
    except NoteStoreError as error:
        logger.warning("저장 목록 조회 실패 (%s) — 자동선택으로 계속합니다.", error)
        saved_docs = []
    result = build_kapa_rows(
        db, office_id=scoped_office,
        year=year, month=month, half=half, basis=basis,
        extra_doc_ids=_doc_list(extra), exclude_doc_ids=_doc_list(exclude),
        only_doc_ids=saved_docs or None,
    )
    filename = f"{year}.{month:02d}월업무실적보고_{half}_{office_code}.xlsx"
    return Response(
        content=build_work_report_xlsx(result),
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": (
                f"attachment; filename=work_report.xlsx; "
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.post("/submit", response_model=ApiResponse)
def submit(
    year: int,
    month: int,
    half: Half,
    basis: Basis,
    office_code: str = "10",
    extra: str | None = None,
    exclude: str | None = None,
    confirm: bool = False,
    fresh: bool = False,
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("workReport")),
) -> ApiResponse:
    """협회로 업무실적 전송. 안전을 위해 기본은 dry-run(미리보기)이고,
    confirm=true 일 때만 실제 전송한다(협회 프로덕션·호출이력 모니터링)."""
    # 화면이 보여주는 것과 같은 목록을 보낸다. 저장본이 있으면 그것을 그대로 쓴다 —
    # 예전엔 자동선택을 다시 돌려서, 화면 380건인데 접수기준 160건이 나갔다
    # (2026-09-07 본사 8월 하반). 목록을 저장해 둔 회차는 그게 결정이다.
    scoped_office = resolve_office_scope(access, office_code) or "10"
    saved_docs: list[str] = []
    if not fresh:
        try:
            saved_docs = load_saved_list(
                db, office_code=scoped_office, year=year, month=month, half=half
            )
        except NoteStoreError as error:
            logger.warning("저장 목록 조회 실패 (%s) — 자동선택으로 계속합니다.", error)
    try:
        result = build_kapa_rows(
            db, office_id=scoped_office,
            year=year, month=month, half=half, basis=basis,
            extra_doc_ids=_doc_list(extra), exclude_doc_ids=_doc_list(exclude),
            only_doc_ids=saved_docs or None,
        )
    except Exception as error:  # 미리보기와 같게 — 사유 없이 500 이 나지 않도록
        return ApiResponse(
            success=False, code="ERROR",
            message=f"전송할 목록을 만들지 못했습니다: {type(error).__name__}: {error}",
            data=None,
        )
    try:
        outcome = submit_work_report(result, dry_run=not confirm)
    except (KapaQueryError, KapaNotConfiguredError) as error:
        return ApiResponse(
            success=False, code="KAPA_PROTECT",
            message=str(error), data=None,
        )
    if outcome.get("success"):
        message = "전송 완료"
    elif outcome.get("dry_run"):
        message = "미리보기(dry-run)"
    else:
        message = f"전송 실패: {outcome.get('message')}"
        suspects = outcome.get("suspects") or []
        if suspects:
            sample = ", ".join(item["doc_id"] for item in suspects[:5])
            message += (
                f" · 거래처코드·감정가가 빈 {len(suspects)}건이 있습니다({sample}"
                f"{' 외' if len(suspects) > 5 else ''}). 원장을 채운 뒤 다시 보내세요."
            )
    return ApiResponse(success=True, code="0000", message=message, data=outcome)


class WorkReportListSave(BaseModel):
    """작업 저장 — 화면에 떠 있는 목록 전체(멤버십 + 체크 + 사유)."""

    rows: list[dict[str, Any]] = Field(default_factory=list)


@router.put("/list", response_model=ApiResponse)
def put_list(
    year: int,
    month: int,
    half: Half,
    office_code: str = "10",
    basis: Basis | None = None,
    payload: WorkReportListSave = Body(...),
    db: Session = Depends(get_db),
    access: AccessContext = Depends(require_menu("workReport")),
) -> ApiResponse:
    """작업 목록을 통째로 저장한다. 다시 열면 이 목록이 그대로 복원된다.

    화면의 전 행을 받는다('건드린 것만'이 아니다) — 중간에 끊겨도 마지막 저장
    시점으로 돌아오게 하는 것이 목적이다. 목록에서 빠진 감정서는 저장소에서도 지운다.
    """
    try:
        result = save_list(
            # 읽기와 같은 잣대로 소속을 강제한다(지사→본사 쓰기 구멍 방지).
            db, office_code=resolve_office_scope(access, office_code) or "10",
            year=year, month=month, half=half,
            basis=basis, rows=payload.rows, user=access,
        )
    except NoteStoreError as error:
        return ApiResponse(
            success=False, code="NOTE_STORE_UNAVAILABLE",
            message=f"작업 목록을 저장하지 못했습니다: {error}", data=None,
        )
    rejected = result.get("rejected") or []
    message = f"목록 {result['saved_count']}건 저장"
    if result["removed_count"]:
        message += f" · {result['removed_count']}건 목록에서 제거"
    if rejected:
        message += f" · {len(rejected)}건 거부"
    return ApiResponse(success=True, code="0000", message=message, data=result)


@router.get("/notes", response_model=ApiResponse)
def get_notes(
    year: int,
    month: int,
    half: Half,
    office_code: str = "10",
    db: Session = Depends(get_db),
    # 저장(PATCH)만 막고 읽기(GET)를 열어 두면 반쪽이다 — usr_seq 없이 아무나
    # office_code 만 바꿔 남의 지사 기재사항을 읽을 수 있었다 (2026-08-07 점검).
    access: AccessContext = Depends(require_menu("workReport")),
) -> ApiResponse:
    """(지사, 년, 월, 반월)의 저장된 기재사항. 기준(basis)과 무관하게 공유된다."""
    try:
        notes = load_notes(
            db,
            office_code=resolve_office_scope(access, office_code) or "10",
            year=year, month=month, half=half,
        )
    except NoteStoreError as error:
        return ApiResponse(
            success=False, code="NOTE_STORE_UNAVAILABLE",
            message=f"기재사항을 불러오지 못했습니다: {error}", data=None,
        )
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={"notes": notes, "count": len(notes),
              "reason_suggestions": list(REASON_SUGGESTIONS)},
    )


@router.patch("/notes", response_model=ApiResponse)
def patch_notes(
    year: int,
    month: int,
    half: Half,
    office_code: str = "10",
    basis: Basis | None = None,
    notes: dict[str, Any] = Body(..., embed=True),
    db: Session = Depends(get_db),
    # 상류(main)는 require_user 를 썼다 — 신원만 확인하고 권한은 안 막는다.
    # 이 브랜치는 메뉴 권한으로 막으므로 같은 잣대를 쓴다. 두 의존성이 돌려주는
    # 값은 같은 dict(UserContextService._resolve)라 save_notes(user=...) 는 그대로다.
    # 이렇게 두지 않으면 usr_seq 만 있으면 업무실적 메뉴가 없는 사람도 기재사항을
    # 쓸 수 있다 — 이 브랜치가 막으려는 바로 그 구멍이다.
    access: AccessContext = Depends(require_menu("workReport")),
) -> ApiResponse:
    """기재사항 저장. 값이 null 인 감정서는 행을 지운다(자동값으로 되돌리기).

    담당자가 실제로 건드린 감정서만 보내면 된다 — 목록 전체를 보낼 필요가 없고,
    보내지 않은 감정서의 저장값은 그대로 남는다.
    """
    if not isinstance(notes, dict):
        return ApiResponse(
            success=False, code="BAD_PAYLOAD",
            message="notes 는 감정서번호를 키로 하는 객체여야 합니다.", data=None,
        )
    try:
        result = save_notes(
            # 읽기(get_notes)와 **같은 잣대**로 소속을 강제한다. 안 그러면 지사 사용자가
            # office_code 만 '10'(기본값=본사)으로 바꿔 본사 기재사항을 지우거나 덮어썼다
            # (2026-08-19 감사에서 잡힌 지사→본사 쓰기 구멍). resolve_office_scope 가
            # 지사에겐 자기 지사로 강제하고, 전지사조회 없는 본사엔 '10' 을 준다.
            db, office_code=resolve_office_scope(access, office_code) or "10",
            year=year, month=month, half=half,
            basis=basis, notes=notes, user=access,
        )
    except NoteStoreError as error:
        return ApiResponse(
            success=False, code="NOTE_STORE_UNAVAILABLE",
            message=f"기재사항을 저장하지 못했습니다: {error}", data=None,
        )
    rejected = result.get("rejected") or []
    message = f"{result['saved_count']}건 저장"
    if result["deleted_count"]:
        message += f" · {result['deleted_count']}건 자동값으로 되돌림"
    if rejected:
        message += f" · {len(rejected)}건 거부"
    return ApiResponse(success=True, code="0000", message=message, data=result)
