"""
Holidays router - APW_HOLIDAY 조회.
"""
import logging
from fastapi import APIRouter, Depends, Query
from app.database import get_db
from app.schemas import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/holidays", tags=["holidays"])


@router.get("", response_model=ApiResponse)
def get_holidays(
    start_date: str = Query(..., description="시작일 (YYYY-MM-DD)"),
    end_date: str = Query(..., description="종료일 (YYYY-MM-DD)"),
    cursor=Depends(get_db),
):
    """기간 내 공휴일 목록 반환 (apworksdw.dbo.APW_HOLIDAY)"""
    cursor.execute(
        """
        SELECT holiday, name
        FROM apworksdw.dbo.APW_HOLIDAY
        WHERE holiday >= ? AND holiday <= ?
        ORDER BY holiday
        """,
        start_date,
        end_date,
    )
    rows = cursor.fetchall()
    data = [{"date": row.holiday, "name": row.name} for row in rows]
    return ApiResponse(data=data)
