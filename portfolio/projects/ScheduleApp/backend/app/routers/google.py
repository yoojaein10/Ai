"""
Calendar ICS sync router.
"""
import logging
from fastapi import APIRouter, Depends, Query, HTTPException

from app.database import get_db
from app.schemas import ApiResponse
from app.services.google_service import GoogleService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/google", tags=["calendar-sync"])


@router.post("/sync-ics", response_model=ApiResponse)
def sync_kakao_ics(
    empno: int = Query(..., description="사번"),
    cursor=Depends(get_db),
):
    """카카오 ICS URL로 톡캘린더 동기화 (인증 불필요)"""
    try:
        result = GoogleService.sync_kakao_ics(cursor, empno)
    except ValueError as e:
        logger.error("카카오 ICS 동기화 오류 (empno=%s): %s", empno, e)
        raise HTTPException(status_code=400, detail=str(e))
    return ApiResponse(
        data=result,
        message=f"카카오 동기화 완료 ({result['created']}건 추가, {result['updated']}건 수정, {result['deleted']}건 삭제)",
    )
