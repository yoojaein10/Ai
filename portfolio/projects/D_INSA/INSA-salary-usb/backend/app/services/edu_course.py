from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import EduCourse, EduRecord
from app.schemas.edu import EduCourseCreate, EduCourseUpdate


def list_courses(
    db: Session,
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> list[EduCourse]:
    query = db.query(EduCourse)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(EduCourse.course_code.ilike(like), EduCourse.course_name.ilike(like))
        )
    if category:
        query = query.filter(EduCourse.category == category)
    if is_active is not None:
        query = query.filter(EduCourse.is_active == is_active)
    return query.order_by(EduCourse.course_code).all()


def get_course(db: Session, course_id: int) -> Optional[EduCourse]:
    return db.query(EduCourse).filter(EduCourse.id == course_id).first()


def get_course_by_code(db: Session, code: str) -> Optional[EduCourse]:
    return db.query(EduCourse).filter(EduCourse.course_code == code).first()


def create_course(db: Session, data: EduCourseCreate) -> EduCourse:
    course = EduCourse(**data.model_dump())
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


def update_course(
    db: Session, course_id: int, data: EduCourseUpdate
) -> Optional[EduCourse]:
    course = get_course(db, course_id)
    if course is None:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(course, field, value)
    db.commit()
    db.refresh(course)
    return course


def delete_course(db: Session, course_id: int) -> tuple[bool, str]:
    course = get_course(db, course_id)
    if course is None:
        return False, "교육과정을 찾을 수 없습니다"

    used = db.query(EduRecord).filter(EduRecord.course_id == course_id).count()
    if used > 0:
        return False, f"이수 기록이 {used}건 있어 삭제할 수 없습니다. 비활성화를 사용하세요."

    db.delete(course)
    db.commit()
    return True, "삭제되었습니다"
