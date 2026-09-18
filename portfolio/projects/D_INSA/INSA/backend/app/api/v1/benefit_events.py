from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import (
    BenefitEvent,
    BenefitItem,
    Department,
    Employee,
    User,
)
from app.db.session import get_apw_db, get_db
from app.schemas.benefit import (
    BenefitEventCreate,
    BenefitEventListResponse,
    BenefitEventOut,
    BenefitEventUpdate,
    UploadResult,
)
from app.services import benefit_event as svc

router = APIRouter(prefix="/benefits/events", tags=["benefits"])


@router.get("", response_model=BenefitEventListResponse)
def list_events(
    year: Optional[int] = Query(None, ge=2000, le=2100),
    employee_id: Optional[int] = Query(None),
    event_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    apw_db: Session = Depends(get_apw_db),
    _: User = Depends(get_current_user),
) -> BenefitEventListResponse:
    items = svc.list_events(db, apw_db, year, employee_id, event_type, keyword)
    return BenefitEventListResponse(total=len(items), items=items)


def _enrich(db: Session, apw_db: Session, event_id: int) -> BenefitEventOut:
    row = (
        db.query(BenefitEvent, Employee, Department, BenefitItem)
        .outerjoin(Employee, BenefitEvent.employee_id == Employee.id)
        .outerjoin(Department, Employee.dept_id == Department.id)
        .outerjoin(BenefitItem, BenefitEvent.item_id == BenefitItem.id)
        .filter(BenefitEvent.id == event_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="이력을 찾을 수 없습니다")
    ev, emp, dept, item = row
    linked = svc._find_linked_schedules(
        apw_db, emp.name_ko if emp else "", ev.event_date
    )
    return svc._to_out(ev, emp, dept.name if dept else None, item, linked)


@router.post("", response_model=BenefitEventOut, status_code=201)
def create_event(
    data: BenefitEventCreate,
    db: Session = Depends(get_db),
    apw_db: Session = Depends(get_apw_db),
    _: User = Depends(get_current_user),
) -> BenefitEventOut:
    ev = svc.create_event(db, data)
    return _enrich(db, apw_db, ev.id)


@router.patch("/{event_id}", response_model=BenefitEventOut)
def update_event(
    event_id: int,
    data: BenefitEventUpdate,
    db: Session = Depends(get_db),
    apw_db: Session = Depends(get_apw_db),
    _: User = Depends(get_current_user),
) -> BenefitEventOut:
    ev = svc.update_event(db, event_id, data)
    if ev is None:
        raise HTTPException(status_code=404, detail="이력을 찾을 수 없습니다")
    return _enrich(db, apw_db, ev.id)


@router.delete("/{event_id}")
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    if not svc.delete_event(db, event_id):
        raise HTTPException(status_code=404, detail="이력을 찾을 수 없습니다")
    return {"ok": True}


@router.post("/upload", response_model=UploadResult)
async def upload_events(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> UploadResult:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="xlsx 파일만 업로드 가능합니다")
    content = await file.read()
    return svc.upload_events(db, content)
