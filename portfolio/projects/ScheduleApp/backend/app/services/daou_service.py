"""
Daou Office 알림톡 발송 서비스.
별도 로그인 없이 clientId / clientSecret / Bearer token 헤더로 직접 호출.
"""
import logging
from datetime import datetime
import httpx

from app.config import settings
from app.exceptions import NotFoundException, AppException

logger = logging.getLogger(__name__)

DAOU_API_URL = "https://gw.dhapp.co.kr/api/chat/pubsubs/external"


def format_alimtalk_message(event: dict) -> str:
    """일정 정보를 알림톡 문구로 변환"""
    DOW_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
    start_dt = datetime.fromisoformat(str(event["start_dt"]))
    date_str = start_dt.strftime("%Y-%m-%d") + " " + DOW_KR[start_dt.weekday()]
    title = event["title"]

    if event.get("is_all_day"):
        time_line = "종일"
    else:
        start_time = start_dt.strftime("%H:%M")
        end_time = datetime.fromisoformat(str(event["end_dt"])).strftime("%H:%M")
        time_line = f"{start_time} ~ {end_time}"

    return (
        f"[일정 등록 알림]\n"
        f"일시: {date_str}\n"
        f"{time_line}\n"
        f"일정: [{title}]\n"
        f"위 일정이 등록되었습니다.\n"
        f"확인 부탁드립니다"
    )



def get_target_login_id(cursor, empno: int) -> str:
    """[apworksdw].dbo.YJI_GroupUser 테이블에서 empno 기준 로그인ID 조회 (User_Seq 또는 User_ID에 사번 존재)"""
    cursor.execute(
        """SELECT User_Seq, User_ID FROM [apworksdw].dbo.YJI_GroupUser
           WHERE User_Seq = CAST(? AS NVARCHAR) OR User_ID = CAST(? AS NVARCHAR)""",
        (empno, empno),
    )
    row = cursor.fetchone()
    if row is None:
        raise NotFoundException(f"[apworksdw].dbo.YJI_GroupUser에서 사번 {empno}에 해당하는 사용자를 찾을 수 없습니다.")
    # 사번이 User_Seq에 있으면 User_ID가 로그인ID, 반대면 User_Seq가 로그인ID
    if row.User_Seq.isdigit():
        return row.User_ID
    return row.User_Seq


def get_user_ids_for_attendees(cursor, attendee_ids: list) -> list:
    """참석자 사번 목록 → [apworksdw].dbo.YJI_GroupUser User_ID 목록 반환 (매핑 안되는 사람은 제외)"""
    if not attendee_ids:
        return []
    placeholders = ",".join(["CAST(? AS NVARCHAR)"] * len(attendee_ids))
    cursor.execute(
        f"SELECT User_ID FROM [apworksdw].dbo.YJI_GroupUser WHERE User_Seq IN ({placeholders})",
        attendee_ids,
    )
    return [row.User_ID for row in cursor.fetchall()]


async def send_alimtalk(target_login_id: str, message: str) -> dict:
    """다우오피스 알림톡 발송 (로그인 -> 쿠키 -> form-urlencoded 발송)"""
    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
        # 1단계: 로그인 → 세션 쿠키 발급
        login_resp = await client.post(
            settings.DAOU_LOGIN_URL,
            json={
                "username": settings.DAOU_USERNAME,
                "password": settings.DAOU_PASSWORD,
                "locale": "ko",
            },
            headers={"Content-Type": "application/json"},
        )
        logger.info("다우 로그인 응답 [%s]: %s", login_resp.status_code, login_resp.text)

        if login_resp.status_code not in (200, 201):
            raise AppException(
                status_code=502,
                detail=f"다우 로그인 실패 (HTTP {login_resp.status_code}): {login_resp.text}",
            )

        # 2단계: 쿠키로 메시지 발송 (form-urlencoded)
        send_resp = await client.post(
            settings.DAOU_SEND_URL,
            data={
                "targetLoginId": target_login_id,
                "message": message,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        logger.info("다우 발송 응답 [%s]: %s", send_resp.status_code, send_resp.text)

        if send_resp.status_code not in (200, 201):
            raise AppException(
                status_code=502,
                detail=f"다우 발송 실패 (HTTP {send_resp.status_code}): {send_resp.text}",
            )

        return send_resp.json() if send_resp.text else {"result": "ok"}


def send_alimtalk_to_attendees_sync(event_id: int, attendee_apwids: list, message: str) -> None:
    """참석자 전원에게 알림톡 발송 후 DB 업데이트 (동기 버전, 별도 스레드에서 실행)

    핵심: 이 함수는 create_event 트랜잭션 커밋 후 별도 스레드에서 실행됨.
    따라서 DB 락 충돌 없음.
    """
    if not attendee_apwids:
        return

    from app.database import get_connection

    # apwid → 로그인ID 매핑 (User_Seq 또는 User_ID에 사번이 있을 수 있음)
    conn = get_connection()
    cursor = conn.cursor()
    try:
        placeholders = ",".join(["CAST(? AS NVARCHAR)"] * len(attendee_apwids))
        cursor.execute(
            f"""SELECT User_Seq, User_ID FROM [apworksdw].dbo.YJI_GroupUser
                WHERE User_Seq IN ({placeholders}) OR User_ID IN ({placeholders})""",
            attendee_apwids + attendee_apwids,
        )
        apwid_to_login = {}
        rows = cursor.fetchall()
        logger.info("[apworksdw].dbo.YJI_GroupUser 조회 결과 %d건 (입력 apwids=%s)", len(rows), attendee_apwids)
        for r in rows:
            logger.info("  Row: User_Seq=%s, User_ID=%s", r.User_Seq, r.User_ID)
            if r.User_Seq.isdigit():
                # User_Seq에 사번, User_ID에 로그인ID
                apwid_to_login[int(r.User_Seq)] = r.User_ID
            elif r.User_ID.isdigit():
                # User_ID에 사번, User_Seq에 로그인ID
                apwid_to_login[int(r.User_ID)] = r.User_Seq
        logger.info("apwid_to_login 매핑: %s", apwid_to_login)
    finally:
        cursor.close()
        conn.close()

    if not apwid_to_login:
        return

    # 1) HTTP 호출: 로그인 + 발송 (동기 httpx)
    results: dict[int, bool] = {}
    with httpx.Client(timeout=10.0, verify=False) as client:
        # 로그인 1회
        try:
            login_resp = client.post(
                settings.DAOU_LOGIN_URL,
                json={"username": settings.DAOU_USERNAME, "password": settings.DAOU_PASSWORD, "locale": "ko"},
                headers={"Content-Type": "application/json"},
            )
        except Exception as e:
            logger.error("다우 로그인 요청 실패: %s", e)
            return

        if login_resp.status_code not in (200, 201):
            logger.error("다우 로그인 실패: %s %s", login_resp.status_code, login_resp.text)
            return

        # 참석자별 발송 (결과만 수집)
        for apwid, user_id in apwid_to_login.items():
            try:
                send_resp = client.post(
                    settings.DAOU_SEND_URL,
                    data={"targetLoginId": user_id, "message": message},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                results[apwid] = send_resp.status_code in (200, 201)
                logger.info("알림톡 [%s/%s] → %s", user_id, apwid, send_resp.status_code)
            except Exception as e:
                results[apwid] = False
                logger.error("알림톡 발송 오류 [%s]: %s", user_id, e)

    # 2) DB 업데이트: HTTP 완료 후 한번에
    if not results:
        return

    conn = get_connection()
    cursor = conn.cursor()
    try:
        for apwid, success in results.items():
            cursor.execute(
                """
                UPDATE YJI_CalendarAttendees
                SET alimtalk_sent = ?, alimtalk_sent_at = GETDATE()
                WHERE event_id = ? AND apwid = ?
                """,
                ("Y" if success else "N", event_id, apwid),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("알림톡 DB 업데이트 오류: %s", e)
    finally:
        cursor.close()
        conn.close()
