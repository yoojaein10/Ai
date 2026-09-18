from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import BenefitHealth, Department, Employee, User
from app.db.session import get_db
from app.schemas.benefit import (
    BenefitHealthCreate,
    BenefitHealthListResponse,
    BenefitHealthOut,
    BenefitHealthUpdate,
    UploadResult,
)
from app.services import benefit_health as svc

router = APIRouter(prefix="/benefits/health", tags=["benefits"])


@router.get("", response_model=BenefitHealthListResponse)
def list_health(
    year: Optional[int] = Query(None, ge=2000, le=2100),
    employee_id: Optional[int] = Query(None),
    result: Optional[str] = Query(None),
    recheck_only: bool = Query(False),
    keyword: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BenefitHealthListResponse:
    items = svc.list_health(db, year, employee_id, result, recheck_only, keyword)
    return BenefitHealthListResponse(total=len(items), items=items)


def _enrich(db: Session, rec_id: int) -> BenefitHealthOut:
    row = (
        db.query(BenefitHealth, Employee, Department)
        .outerjoin(Employee, BenefitHealth.employee_id == Employee.id)
        .outerjoin(Department, Employee.dept_id == Department.id)
        .filter(BenefitHealth.id == rec_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다")
    rec, emp, dept = row
    return svc._to_out(rec, emp, dept.name if dept else None)


@router.post("", response_model=BenefitHealthOut, status_code=201)
def create_health(
    data: BenefitHealthCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BenefitHealthOut:
    rec = svc.create_health(db, data)
    return _enrich(db, rec.id)


@router.patch("/{rec_id}", response_model=BenefitHealthOut)
def update_health(
    rec_id: int,
    data: BenefitHealthUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BenefitHealthOut:
    rec = svc.update_health(db, rec_id, data)
    if rec is None:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다")
    return _enrich(db, rec.id)


@router.delete("/{rec_id}")
def delete_health(
    rec_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    if not svc.delete_health(db, rec_id):
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다")
    return {"ok": True}


@router.post("/upload", response_model=UploadResult)
async def upload_health(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> UploadResult:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="xlsx 파일만 업로드 가능합니다")
    content = await file.read()
    return svc.upload_health(db, content)
