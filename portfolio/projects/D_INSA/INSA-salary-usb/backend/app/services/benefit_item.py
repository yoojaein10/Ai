from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import BenefitEvent, BenefitItem
from app.schemas.benefit import BenefitItemCreate, BenefitItemUpdate


def list_items(
    db: Session,
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> list[BenefitItem]:
    query = db.query(BenefitItem)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(BenefitItem.code.ilike(like), BenefitItem.name.ilike(like))
        )
    if category:
        query = query.filter(BenefitItem.category == category)
    if is_active is not None:
        query = query.filter(BenefitItem.is_active == is_active)
    return query.order_by(BenefitItem.category, BenefitItem.code).all()


def get_item(db: Session, item_id: int) -> Optional[BenefitItem]:
    return db.query(BenefitItem).filter(BenefitItem.id == item_id).first()


def get_item_by_code(db: Session, code: str) -> Optional[BenefitItem]:
    return db.query(BenefitItem).filter(BenefitItem.code == code).first()


def create_item(db: Session, data: BenefitItemCreate) -> BenefitItem:
    item = BenefitItem(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_item(
    db: Session, item_id: int, data: BenefitItemUpdate
) -> Optional[BenefitItem]:
    item = get_item(db, item_id)
    if item is None:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, item_id: int) -> tuple[bool, str]:
    item = get_item(db, item_id)
    if item is None:
        return False, "항목을 찾을 수 없습니다"
    used = db.query(BenefitEvent).filter(BenefitEvent.item_id == item_id).count()
    if used > 0:
        return False, f"연결된 이력 {used}건이 있어 삭제할 수 없습니다. 비활성화를 사용하세요."
    db.delete(item)
    db.commit()
    return True, "삭제되었습니다"
