"""
APScheduler 기반 정기 알림 발송 스케줄러.

매분 YJI_CalendarNotifications 테이블을 감시하여
send_at <= 현재시각 AND sent=0 인 알림을 다우오피스 API로 발송.
"""
import logging

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.database import get_connection

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def _format_noti_message(event_row) -> str:
    """알림 발송용 메시지 포맷"""
    from datetime import datetime

    DOW_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

    start_dt = event_row.start_dt
    if isinstance(start_dt, str):
        start_dt = datetime.fromisoformat(start_dt)

    date_str = start_dt.strftime("%Y-%m-%d") + " " + DOW_KR[start_dt.weekday()]
    title = event_row.title

    if event_row.is_all_day:
        time_line = "종일"
    else:
        start_time = start_dt.strftime("%H:%M")
        end_dt = event_row.end_dt
        if isinstance(end_dt, str):
            end_dt = datetime.fromisoformat(end_dt)
        end_time = end_dt.strftime("%H:%M")
        time_line = f"{start_time} ~ {end_time}"

    return (
        f"[정기알림]\n"
        f"일시: {date_str}\n"
        f"{time_line}\n"
        f"일정: [{title}]\n"
        f"위 일정이 예정되어 있습니다.\n"
        f"확인 부탁드립니다"
    )


def _get_login_id(cursor, apwid: int) -> str | None:
    """apwid → 다우오피스 로그인ID 조회"""
    cursor.execute(
        """SELECT User_Seq, User_ID FROM [apworksdw].dbo.YJI_GroupUser
           WHERE User_Seq = CAST(? AS NVARCHAR) OR User_ID = CAST(? AS NVARCHAR)""",
        (apwid, apwid),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    if row.User_Seq.isdigit():
        return row.User_ID
    return row.User_Seq


def process_pending_notifications():
    """미발송 알림을 찾아 다우오피스 API로 발송하고 sent=1로 업데이트"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # send_at이 현재 시각 이전이고 sent=0인 알림 조회
        cursor.execute("""
            SELECT n.noti_id, n.apwid, n.event_id, n.noti_type, n.message,
                   e.title, e.start_dt, e.end_dt, e.is_all_day
            FROM YJI_CalendarNotifications n
            JOIN YJI_CalendarEvents e ON e.event_id = n.event_id AND e.is_deleted = 0
            WHERE n.sent = 0 AND n.send_at <= GETDATE()
            ORDER BY n.send_at ASC
        """)
        rows = cursor.fetchall()

        if not rows:
            return

        logger.info("정기알림 발송 대상 %d건 발견", len(rows))

        # 다우오피스 로그인 1회
        with httpx.Client(timeout=10.0, verify=False) as client:
            try:
                login_resp = client.post(
                    settings.DAOU_LOGIN_URL,
                    json={
                        "username": settings.DAOU_USERNAME,
                        "password": settings.DAOU_PASSWORD,
                        "locale": "ko",
                    },
                    headers={"Content-Type": "application/json"},
                )
            except Exception as e:
                logger.error("정기알림 다우 로그인 실패: %s", e)
                return

            if login_resp.status_code not in (200, 201):
                logger.error("정기알림 다우 로그인 실패: %s", login_resp.status_code)
                return

            for row in rows:
                noti_id = row.noti_id
                apwid = row.apwid

                # 로그인ID 조회
                login_id = _get_login_id(cursor, apwid)
                if not login_id:
                    logger.warning("정기알림 [noti_id=%d] apwid=%d 로그인ID 없음 → 건너뜀", noti_id, apwid)
                    _mark_sent(cursor, conn, noti_id)
                    continue

                # 메시지: 커스텀 message가 있으면 사용, 없으면 이벤트 기반 생성
                message = row.message if row.message else _format_noti_message(row)

                # 발송
                try:
                    send_resp = client.post(
                        settings.DAOU_SEND_URL,
                        data={"targetLoginId": login_id, "message": message},
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    success = send_resp.status_code in (200, 201)
                    logger.info(
                        "정기알림 발송 [noti_id=%d, %s/%d] → %s",
                        noti_id, login_id, apwid, send_resp.status_code,
                    )
                except Exception as e:
                    success = False
                    logger.error("정기알림 발송 오류 [noti_id=%d]: %s", noti_id, e)

                # sent=1 업데이트 (성공 여부와 관계없이 재시도 방지)
                _mark_sent(cursor, conn, noti_id)

    except Exception as e:
        logger.error("정기알림 스케줄러 오류: %s", e)
    finally:
        cursor.close()
        conn.close()


def _mark_sent(cursor, conn, noti_id: int):
    """알림을 발송 완료로 마킹"""
    try:
        cursor.execute(
            "UPDATE YJI_CalendarNotifications SET sent = 1 WHERE noti_id = ?",
            (noti_id,),
        )
        conn.commit()
    except Exception as e:
        logger.error("정기알림 sent 업데이트 실패 [noti_id=%d]: %s", noti_id, e)


def start_scheduler():
    """APScheduler 시작 — 매분 실행"""
    scheduler.add_job(
        process_pending_notifications,
        trigger=IntervalTrigger(minutes=1),
        id="process_pending_notifications",
        name="정기알림 발송",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("정기알림 스케줄러 시작 (매 1분 간격)")


def stop_scheduler():
    """APScheduler 종료"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("정기알림 스케줄러 종료")
