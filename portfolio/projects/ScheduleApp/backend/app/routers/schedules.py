"""
Schedule (Event) router.
All endpoints receive empno (employee number) as a query parameter.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.database import get_db, get_cursor_ctx
from app.schemas import ApiResponse
from app.schemas.schedule import EventCreate, EventUpdate
from app.services.schedule_service import ScheduleService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=ApiResponse)
def get_events(
    empno: int = Query(..., description="사번"),
    start: str = Query(..., description="시작일 (ISO format)"),
    end: str = Query(..., description="종료일 (ISO format)"),
    visibility: Optional[str] = Query(None, description="company|dept|personal"),
    cursor=Depends(get_db),
):
    """기간별 이벤트 조회 - empno 사용자가 볼 수 있는 일정"""
    events = ScheduleService.get_events(cursor, empno, start, end, visibility)
    return ApiResponse(data=events)


@router.post("", response_model=ApiResponse, status_code=201)
def create_event(
    body: EventCreate,
    empno: int = Query(..., description="사번"),
):
    """새 이벤트 생성 + D-1 정기알림 생성 (즉시 알림톡 발송 없음)"""
    with get_cursor_ctx() as cursor:
        event = ScheduleService.create_event(cursor, empno, body)
        if body.is_daou_noti_enabled:
            NotificationService.create_manual_notifications(cursor, event["event_id"], event)

    return ApiResponse(data=event, message="일정이 생성되었습니다.")


@router.get("/timeline", response_model=ApiResponse)
def get_timeline(
    date: str = Query(..., description="조회 날짜 (YYYY-MM-DD)"),
    cursor=Depends(get_db),
):
    """날짜별 리소스 타임라인 (관리자용) - 전 부서 사원별 출장/휴가/일반 일정"""
    result = ScheduleService.get_timeline(cursor, date)
    return ApiResponse(data=result)


@router.get("/team", response_model=ApiResponse)
def get_team_events(
    empno: int = Query(..., description="사번"),
    start: str = Query(..., description="시작일 (ISO format)"),
    end:   str = Query(..., description="종료일 (ISO format)"),
    cursor=Depends(get_db),
):
    """pg1/pg2 팀 전체 이벤트 조회"""
    events = ScheduleService.get_team_events(cursor, empno, start, end)
    return ApiResponse(data=events)


@router.get("/{event_id}", response_model=ApiResponse)
def get_event(
    event_id: int,
    empno: int = Query(..., description="사번"),
    cursor=Depends(get_db),
):
    """이벤트 상세 조회"""
    event = ScheduleService.get_event_detail(cursor, event_id, empno)
    return ApiResponse(data=event)


@router.put("/{event_id}", response_model=ApiResponse)
def update_event(
    event_id: int,
    body: EventUpdate,
    empno: int = Query(..., description="사번"),
):
    """이벤트 수정 (낙관적 잠금 적용) + D-1 정기알림 갱신"""
    with get_cursor_ctx() as cursor:
        event = ScheduleService.update_event(cursor, event_id, empno, body)
        NotificationService.refresh_notifications_for_event(cursor, event_id, event)

    return ApiResponse(data=event, message="일정이 수정되었습니다.")


@router.delete("/{event_id}", response_model=ApiResponse)
def delete_event(
    event_id: int,
    empno: int = Query(..., description="사번"),
):
    """이벤트 삭제 (soft delete) + 미발송 알림 제거"""
    with get_cursor_ctx() as cursor:
        ScheduleService.delete_event(cursor, event_id, empno)
        NotificationService.delete_notifications_for_event(cursor, event_id)
    return ApiResponse(message="일정이 삭제되었습니다.")
