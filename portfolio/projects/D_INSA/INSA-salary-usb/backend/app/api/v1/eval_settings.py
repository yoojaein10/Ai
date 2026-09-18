from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas.eval_setting import EvalSettingResponse, EvalSettingUpsert
from app.services.eval_setting import get_setting_by_year, upsert_setting

router = APIRouter(prefix="/eval/settings", tags=["eval-settings"])


@router.get("", response_model=EvalSettingResponse | None)
def get_eval_setting(
    year: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_setting_by_year(db, year)


@router.put("", response_model=EvalSettingResponse)
def upsert_eval_setting(
    body: EvalSettingUpsert,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    return upsert_setting(db, body)
