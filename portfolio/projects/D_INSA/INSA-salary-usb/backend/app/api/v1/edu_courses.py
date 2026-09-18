from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.edu import (
    EduCourseCreate,
    EduCourseListResponse,
    EduCourseOut,
    EduCourseUpdate,
)
from app.services import edu_course as svc

router = APIRouter(prefix="/edu/courses", tags=["edu"])


@router.get("", response_model=EduCourseListResponse)
def list_courses(
    keyword: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> EduCourseListResponse:
    items = svc.list_courses(db, keyword, category, is_active)
    return EduCourseListResponse(
        total=len(items), items=[EduCourseOut.model_validate(x) for x in items]
    )


@router.post("", response_model=EduCourseOut, status_code=201)
def create_course(
    data: EduCourseCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> EduCourseOut:
    if svc.get_course_by_code(db, data.course_code):
        raise HTTPException(status_code=409, detail="과정코드가 이미 존재합니다")
    course = svc.create_course(db, data)
    return EduCourseOut.model_validate(course)


@router.patch("/{course_id}", response_model=EduCourseOut)
def update_course(
    course_id: int,
    data: EduCourseUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> EduCourseOut:
    course = svc.update_course(db, course_id, data)
    if course is None:
        raise HTTPException(status_code=404, detail="교육과정을 찾을 수 없습니다")
    return EduCourseOut.model_validate(course)


@router.delete("/{course_id}")
def delete_course(
    course_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    ok, msg = svc.delete_course(db, course_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}
