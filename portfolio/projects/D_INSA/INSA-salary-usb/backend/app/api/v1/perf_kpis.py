from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas.perf_kpi import PerfKpiCreate, PerfKpiResponse, PerfKpiUpdate
from app.services.perf_kpi import (
    create_kpi,
    delete_kpi,
    get_kpi,
    list_kpis,
    update_kpi,
)

router = APIRouter(prefix="/eval/perf/kpis", tags=["eval-perf-kpis"])


@router.get("", response_model=list[PerfKpiResponse])
def list_perf_kpis(
    round_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_kpis(db, round_id)


@router.post("", response_model=PerfKpiResponse, status_code=status.HTTP_201_CREATED)
def create_perf_kpi(
    body: PerfKpiCreate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        return create_kpi(db, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/{kpi_id}", response_model=PerfKpiResponse)
def update_perf_kpi(
    kpi_id: int,
    body: PerfKpiUpdate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        return update_kpi(db, kpi_id, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{kpi_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_perf_kpi(
    kpi_id: int,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        delete_kpi(db, kpi_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{kpi_id}", response_model=PerfKpiResponse)
def get_perf_kpi(
    kpi_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    kpi = get_kpi(db, kpi_id)
    if kpi is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="KPI not found")
    return kpi
