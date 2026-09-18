"""
알림(Notification) 생성 및 발송 서비스.

- 수동 일정 (is_daou_noti_enabled=True): 1일 전 09:00 알림 1건
- 외부 동기화 일정 (카카오/구글): 7일/3일/1일 전 09:00 알림 3건
- APScheduler가 매분 send_at <= NOW AND sent=0 감시하여 발송
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 외부 동기화 일정의 알림 일수 (D-7, D-3, D-1)
SYNC_NOTI_DAYS = [7, 3, 1]
# 수동 일정의 알림 일수 (D-1)
MANUAL_NOTI_DAYS = [1]
# 알림 발송 시각 (09:00)
NOTI_HOUR = 9


def _calc_send_at(event_start_dt: datetime, days_before: int) -> datetime:
    """일정 시작일 기준 N일 전 09:00 시각 계산"""
    send_date = event_start_dt.date() - timedelta(days=days_before)
    return datetime(send_date.year, send_date.month, send_date.day, NOTI_HOUR, 0, 0)


def _is_valid_send_at(send_at: datetime) -> bool:
    """발송 시점이 유효한지 확인 (이미 지난 시점은 제외)"""
    return send_at > datetime.now()


class NotificationService:

    @staticmethod
    def create_manual_notifications(cursor, event_id: int, event: dict) -> int:
        """수동 생성 일정에 대한 알림 행 생성.

        is_daou_noti_enabled=True인 경우만 호출.
        참석자 + 생성자 본인에게 1일 전 09:00 알림 1건씩 생성.
        """
        start_dt = datetime.fromisoformat(str(event["start_dt"]))
        attendee_ids = _get_event_attendee_ids(cursor, event_id)
        # 생성자도 알림 대상에 포함
        creator_id = event["creator_id"]
        target_ids = set(attendee_ids) | {creator_id}

        count = 0
        for days in MANUAL_NOTI_DAYS:
            send_at = _calc_send_at(start_dt, days)
            if not _is_valid_send_at(send_at):
                logger.info("알림 시점이 이미 지남 (D-%d, send_at=%s) → 건너뜀", days, send_at)
                continue
            for apwid in target_ids:
                _insert_notification(cursor, apwid, event_id, "manual", send_at)
                count += 1

        logger.info("수동 일정 알림 %d건 생성 (event_id=%d)", count, event_id)
        return count

    @staticmethod
    def create_sync_notifications(cursor, event_id: int, start_dt_str: str, target_apwids: list) -> int:
        """외부 동기화 일정(카카오/구글)에 대한 알림 행 생성.

        7일/3일/1일 전 09:00 알림 3건씩 생성.
        """
        start_dt = datetime.fromisoformat(str(start_dt_str))
        count = 0
        for days in SYNC_NOTI_DAYS:
            send_at = _calc_send_at(start_dt, days)
            if not _is_valid_send_at(send_at):
                continue
            for apwid in target_apwids:
                _insert_notification(cursor, apwid, event_id, "sync", send_at)
                count += 1

        logger.info("동기화 일정 알림 %d건 생성 (event_id=%d)", count, event_id)
        return count

    @staticmethod
    def refresh_notifications_for_event(cursor, event_id: int, event: dict) -> int:
        """일정 수정 시 미발송 알림을 삭제하고 재생성.

        이미 sent=1인 알림은 유지.
        """
        # 미발송 알림 삭제
        cursor.execute(
            "DELETE FROM YJI_CalendarNotifications WHERE event_id = ? AND sent = 0",
            (event_id,),
        )
        deleted = cursor.rowcount
        logger.info("기존 미발송 알림 %d건 삭제 (event_id=%d)", deleted, event_id)

        # 소스에 따라 재생성
        source = event.get("source")
        if source in ("kakao", "google"):
            target_ids = _get_event_attendee_ids(cursor, event_id)
            target_ids.append(event["creator_id"])
            return NotificationService.create_sync_notifications(
                cursor, event_id, event["start_dt"], target_ids,
            )
        elif event.get("is_daou_noti_enabled"):
            return NotificationService.create_manual_notifications(cursor, event_id, event)

        return 0

    @staticmethod
    def delete_notifications_for_event(cursor, event_id: int) -> int:
        """일정 삭제 시 미발송 알림 제거"""
        cursor.execute(
            "DELETE FROM YJI_CalendarNotifications WHERE event_id = ? AND sent = 0",
            (event_id,),
        )
        return cursor.rowcount


def _get_event_attendee_ids(cursor, event_id: int) -> list:
    """이벤트 참석자 사번 목록 조회"""
    cursor.execute(
        "SELECT apwid FROM YJI_CalendarAttendees WHERE event_id = ?",
        (event_id,),
    )
    return [row.apwid for row in cursor.fetchall()]


def _insert_notification(cursor, apwid: int, event_id: int, noti_type: str, send_at: datetime):
    """알림 행 1건 삽입 (중복 방지: 같은 event_id + apwid + send_at이면 건너뜀)"""
    cursor.execute(
        """
        IF NOT EXISTS (
            SELECT 1 FROM YJI_CalendarNotifications
            WHERE event_id = ? AND apwid = ? AND send_at = ?
        )
        INSERT INTO YJI_CalendarNotifications (apwid, event_id, noti_type, send_at, sent)
        VALUES (?, ?, ?, ?, 0)
        """,
        (event_id, apwid, send_at, apwid, event_id, noti_type, send_at),
    )
