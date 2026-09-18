"""
Users router - Seat_UserInfo 조회 전용.
"""
import logging
import os

from fastapi import APIRouter, Depends, Query

from app.database import get_db
from app.schemas import ApiResponse
from app.services.user_service import UserService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])

_EMPNO_FILE = r"C:\ProgramData\ScheduleApp\current_empno.txt"


@router.get("/current-empno", response_model=ApiResponse)
def get_current_empno():
    """로컬에 저장된 사번 반환 (EXE 실행 인자로 저장된 값)"""
    try:
        if os.path.isfile(_EMPNO_FILE):
            with open(_EMPNO_FILE, "r", encoding="utf-8-sig") as f:  # BOM 자동 처리
                val = int(f.read().strip())
            return ApiResponse(data={"empno": val})
    except (ValueError, OSError):
        pass
    return ApiResponse(data={"empno": None})


@router.get("/me", response_model=ApiResponse)
def get_me(
    empno: int = Query(..., description="사번"),
    cursor=Depends(get_db),
):
    """현재 사용자 정보 (Seat_UserInfo)"""
    user = UserService.get_user_by_empno(cursor, empno)
    return ApiResponse(data=user)


@router.get("/search", response_model=ApiResponse)
def search_users(
    q: str = Query("", description="이름 검색어"),
    cursor=Depends(get_db),
):
    """참석자 검색 (이름으로)"""
    users = UserService.search_users(cursor, q)
    return ApiResponse(data=users)


@router.get("/by-department", response_model=ApiResponse)
def get_users_by_department(
    cursor=Depends(get_db),
):
    """부서별 사용자 트리 조회 (트리뷰용)"""
    try:
        tree = UserService.get_users_by_department(cursor)
        return ApiResponse(data=tree)
    except Exception as e:
        logger.error("부서별 사용자 조회 실패: %s", e, exc_info=True)
        raise


@router.get("/departments", response_model=ApiResponse)
def get_departments(
    cursor=Depends(get_db),
):
    """부서 목록 (그룹 필터용)"""
    departments = UserService.get_departments(cursor)
    return ApiResponse(data=departments)
