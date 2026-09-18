from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import Department, EduCourse, EduRecord, Employee, User
from app.db.session import get_db
from app.schemas.edu import (
    EduRecordCreate,
    EduRecordListResponse,
    EduRecordOut,
    EduRecordUpdate,
    EduRecordUploadResult,
)
from app.services import edu_record as svc

router = APIRouter(prefix="/edu/records", tags=["edu"])


@router.get("", response_model=EduRecordListResponse)
def list_records(
    year: Optional[int] = Query(None, ge=2000, le=2100),
    employee_id: Optional[int] = Query(None),
    course_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> EduRecordListResponse:
    items = svc.list_records(db, year, employee_id, course_id, category, keyword)
    return EduRecordListResponse(total=len(items), items=items)


def _enrich(db: Session, rec_id: int) -> EduRecordOut:
    row = (
        db.query(EduRecord, Employee, Department, EduCourse)
        .outerjoin(Employee, EduRecord.employee_id == Employee.id)
        .outerjoin(Department, Employee.dept_id == Department.id)
        .outerjoin(EduCourse, EduRecord.course_id == EduCourse.id)
        .filter(EduRecord.id == rec_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다")
    rec, emp, dept, course = row
    return svc._to_out(rec, emp, dept.name if dept else None, course)


@router.post("", response_model=EduRecordOut, status_code=201)
def create_record(
    data: EduRecordCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> EduRecordOut:
    rec = svc.create_record(db, data)
    return _enrich(db, rec.id)


@router.patch("/{record_id}", response_model=EduRecordOut)
def update_record(
    record_id: int,
    data: EduRecordUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> EduRecordOut:
    rec = svc.update_record(db, record_id, data)
    if rec is None:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다")
    return _enrich(db, rec.id)


@router.delete("/{record_id}")
def delete_record(
    record_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    if not svc.delete_record(db, record_id):
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다")
    return {"ok": True}


@router.post("/upload", response_model=EduRecordUploadResult)
async def upload_records(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> EduRecordUploadResult:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="xlsx 파일만 업로드 가능합니다")
    content = await file.read()
    return svc.upload_records(db, content)
