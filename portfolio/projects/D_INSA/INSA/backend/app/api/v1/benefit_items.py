from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.benefit import (
    BenefitItemCreate,
    BenefitItemListResponse,
    BenefitItemOut,
    BenefitItemUpdate,
)
from app.services import benefit_item as svc

router = APIRouter(prefix="/benefits/items", tags=["benefits"])


@router.get("", response_model=BenefitItemListResponse)
def list_items(
    keyword: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BenefitItemListResponse:
    items = svc.list_items(db, keyword, category, is_active)
    return BenefitItemListResponse(
        total=len(items),
        items=[BenefitItemOut.model_validate(x) for x in items],
    )


@router.post("", response_model=BenefitItemOut, status_code=201)
def create_item(
    data: BenefitItemCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BenefitItemOut:
    if svc.get_item_by_code(db, data.code):
        raise HTTPException(status_code=409, detail="항목코드가 이미 존재합니다")
    item = svc.create_item(db, data)
    return BenefitItemOut.model_validate(item)


@router.patch("/{item_id}", response_model=BenefitItemOut)
def update_item(
    item_id: int,
    data: BenefitItemUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> BenefitItemOut:
    item = svc.update_item(db, item_id, data)
    if item is None:
        raise HTTPException(status_code=404, detail="항목을 찾을 수 없습니다")
    return BenefitItemOut.model_validate(item)


@router.delete("/{item_id}")
def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    ok, msg = svc.delete_item(db, item_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}
