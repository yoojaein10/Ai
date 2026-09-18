from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import EvalAiReport, User
from app.db.session import get_db
from app.schemas.eval_ai_report import (
    AiReportDetail,
    AiReportHistoryItem,
    AiReportListItem,
    GenerateBatchResponse,
    GenerateRequest,
)
from app.services.ai_eval_report_service import (
    BatchInProgressError,
    generate_batch,
    generate_one_report,
    list_reports_for_round,
)

router = APIRouter(prefix="/eval/ai-reports", tags=["eval-ai-report"])


@router.post(
    "/generate",
    response_model=GenerateBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_batch_route(
    payload: GenerateRequest,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        summary = generate_batch(db, payload.round_id, generated_by=current_user.id)
    except BatchInProgressError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return GenerateBatchResponse(**summary)


@router.post("/generate/{employee_id}", response_model=AiReportDetail)
def generate_one_route(
    employee_id: int,
    payload: GenerateRequest,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        report = generate_one_report(
            db, payload.round_id, employee_id, generated_by=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return AiReportDetail.model_validate(report)


@router.get("", response_model=list[AiReportListItem])
def list_route(
    round_id: int = Query(...),
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    return list_reports_for_round(db, round_id)


@router.get("/{report_id}", response_model=AiReportDetail)
def detail_route(
    report_id: int,
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    report = db.query(EvalAiReport).filter(EvalAiReport.id == report_id).first()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    return AiReportDetail.model_validate(report)


@router.get(
    "/employees/{employee_id}/history",
    response_model=list[AiReportHistoryItem],
)
def history_route(
    employee_id: int,
    round_id: int = Query(...),
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(EvalAiReport)
        .filter(
            EvalAiReport.round_id == round_id,
            EvalAiReport.employee_id == employee_id,
        )
        .order_by(desc(EvalAiReport.version))
        .all()
    )
    return [AiReportHistoryItem.model_validate(r) for r in rows]


@router.get(
    "/employees/{employee_id}/versions/{version}",
    response_model=AiReportDetail,
)
def version_detail_route(
    employee_id: int,
    version: int,
    round_id: int = Query(...),
    _: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    report = (
        db.query(EvalAiReport)
        .filter(
            EvalAiReport.round_id == round_id,
            EvalAiReport.employee_id == employee_id,
            EvalAiReport.version == version,
        )
        .first()
    )
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version not found")
    return AiReportDetail.model_validate(report)
