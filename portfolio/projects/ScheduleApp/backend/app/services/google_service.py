"""
카카오 톡캘린더 ICS 동기화 서비스.
ICS URL에서 일정을 파싱하여 DB에 저장.
"""
import logging
import re
import urllib.request
from datetime import datetime, timedelta

from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

KAKAO_ICS_URL = "https://calendar-ics.kakao.com/2mXV5fMDwdlRylBTwedJNGyo2-vRpkl3WPHRv1gkV_4/talk.ics"
KAKAO_DEFAULT_COLOR = "#51CF66"  # 부서 공개 기본 초록색 (dept)

# 동기화 일정에 자동 참석자로 등록할 부서 코드 목록
ATTENDEE_DEPTS = ["ju", "jip", "sim", "gam"]


def _fetch_kakao_ics_events(year: int = None) -> list:
    """카카오 ICS URL에서 이벤트 파싱"""
    try:
        req = urllib.request.Request(KAKAO_ICS_URL)
        with urllib.request.urlopen(req, timeout=15) as resp:
            ics_text = resp.read().decode("utf-8")
    except Exception as e:
        logger.error("카카오 ICS 가져오기 실패: %s", e)
        return []

    # 오늘 날짜부터만 가져오기
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    events = []
    vevent_blocks = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", ics_text, re.DOTALL)

    for block in vevent_blocks:
        ev = {}
        for line in block.strip().splitlines():
            line = line.strip()
            if line.startswith("SUMMARY:"):
                ev["summary"] = line[len("SUMMARY:"):]
            elif line.startswith("UID:"):
                ev["uid"] = line[len("UID:"):]
            elif line.startswith("DESCRIPTION:"):
                ev["description"] = line[len("DESCRIPTION:"):]
            elif line.startswith("LOCATION:"):
                ev["location"] = line[len("LOCATION:"):]
            elif line.startswith("DTSTART;VALUE=DATE:"):
                ev["start_date"] = line[len("DTSTART;VALUE=DATE:"):]
                ev["is_all_day"] = True
            elif line.startswith("DTSTART:"):
                ev["start_dt"] = line[len("DTSTART:"):]
                ev["is_all_day"] = False
            elif line.startswith("DTEND;VALUE=DATE:"):
                ev["end_date"] = line[len("DTEND;VALUE=DATE:"):]
            elif line.startswith("DTEND:"):
                ev["end_dt"] = line[len("DTEND:"):]

        if not ev.get("uid"):
            continue

        # 시간 파싱
        try:
            if ev.get("is_all_day"):
                start = datetime.strptime(ev["start_date"], "%Y%m%d")
                end_raw = ev.get("end_date", ev["start_date"])
                end = datetime.strptime(end_raw, "%Y%m%d") - timedelta(days=1)
                start_str = start.strftime("%Y-%m-%d 00:00:00")
                end_str = end.strftime("%Y-%m-%d 00:00:00")
            else:
                start = datetime.strptime(ev["start_dt"], "%Y%m%dT%H%M%SZ")
                end = datetime.strptime(ev.get("end_dt", ev["start_dt"]), "%Y%m%dT%H%M%SZ")
                # UTC → KST (+9)
                start = start + timedelta(hours=9)
                end = end + timedelta(hours=9)
                start_str = start.strftime("%Y-%m-%d %H:%M:%S")
                end_str = end.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, KeyError) as e:
            logger.warning("카카오 ICS 시간 파싱 실패: %s - %s", ev.get("uid"), e)
            continue

        # 오늘 이전 일정 제외
        if start < today:
            continue

        events.append({
            "uid": ev["uid"],
            "summary": ev.get("summary", "(제목 없음)"),
            "description": ev.get("description", ""),
            "location": ev.get("location", ""),
            "start_str": start_str,
            "end_str": end_str,
            "is_all_day": ev.get("is_all_day", False),
        })

    logger.info("카카오 ICS 파싱 완료: %d건", len(events))
    return events


class GoogleService:

    @staticmethod
    def _get_multi_dept_empnos(cursor, dept_codes: list, exclude_empno: int) -> list:
        """여러 부서 코드로 사번 목록 조회 (생성자 제외, 중복 제거)"""
        if not dept_codes:
            return []
        placeholders = ",".join(["?"] * len(dept_codes))
        cursor.execute(
            f"SELECT Apwid FROM [apworksdw].dbo.seat_Userinfo "
            f"WHERE Dept_Nm IN ({placeholders}) AND Udtel IS NOT NULL AND Udtel != '' AND Dept_Nm != 'gy'",
            dept_codes,
        )
        return list({
            int(row.Apwid)
            for row in cursor.fetchall()
            if row.Apwid and int(row.Apwid) != exclude_empno
        })

    @staticmethod
    def sync_kakao_ics(cursor, empno: int, year: int = None) -> dict:
        """카카오 ICS URL에서 일정을 가져와 DB에 동기화"""
        kakao_events = _fetch_kakao_ics_events(year)
        logger.info("카카오 ICS 일정 %d건 수신 (empno=%s)", len(kakao_events), empno)

        dept_empnos = GoogleService._get_multi_dept_empnos(cursor, ATTENDEE_DEPTS, empno)
        logger.info("자동 참석자 %d명 (부서: %s)", len(dept_empnos), ATTENDEE_DEPTS)

        created = 0
        updated = 0

        for kev in kakao_events:
            kakao_id = kev["uid"]
            cursor.execute(
                "SELECT event_id FROM YJI_CalendarEvents "
                "WHERE kakao_event_id = ? AND creator_id = ? AND source = 'kakao' AND is_deleted = 0",
                (kakao_id, empno),
            )
            existing = cursor.fetchone()
            if existing:
                event_id = existing[0]
                cursor.execute(
                    "UPDATE YJI_CalendarEvents SET title = ?, description = ?, location = ?, "
                    "start_dt = ?, end_dt = ?, is_all_day = ?, event_color = ? WHERE event_id = ?",
                    (kev["summary"], kev["description"], kev["location"],
                     kev["start_str"], kev["end_str"], 1 if kev["is_all_day"] else 0,
                     KAKAO_DEFAULT_COLOR, event_id),
                )
                # 기존 일정에도 누락된 참석자 보충 (중복 방지)
                _ensure_attendees(cursor, event_id, dept_empnos)
                updated += 1
                continue

            cursor.execute(
                """
                INSERT INTO YJI_CalendarEvents
                    (creator_id, title, description, location,
                     event_color, start_dt, end_dt, is_all_day,
                     visibility, dept_code, source, kakao_event_id)
                OUTPUT INSERTED.event_id
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'dept', NULL, 'kakao', ?)
                """,
                (empno, kev["summary"], kev["description"], kev["location"],
                 KAKAO_DEFAULT_COLOR, kev["start_str"], kev["end_str"],
                 1 if kev["is_all_day"] else 0, kakao_id),
            )
            row = cursor.fetchone()
            if row:
                event_id = row[0]
                for apwid in dept_empnos:
                    cursor.execute(
                        "INSERT INTO YJI_CalendarAttendees (event_id, apwid, status) VALUES (?, ?, 'pending')",
                        (event_id, apwid),
                    )
                # 외부 동기화 일정 → 7일/3일/1일 전 알림 3건 자동 생성
                noti_targets = dept_empnos + [empno]
                NotificationService.create_sync_notifications(
                    cursor, event_id, kev["start_str"], noti_targets,
                )
                created += 1

        # 카카오에서 삭제된 일정 처리
        kakao_ids = {kev["uid"] for kev in kakao_events}
        cursor.execute(
            "SELECT event_id, kakao_event_id FROM YJI_CalendarEvents "
            "WHERE creator_id = ? AND source = 'kakao' AND is_deleted = 0",
            (empno,),
        )
        deleted = 0
        for row in cursor.fetchall():
            if row.kakao_event_id and row.kakao_event_id not in kakao_ids:
                cursor.execute(
                    "UPDATE YJI_CalendarEvents SET is_deleted = 1 WHERE event_id = ?",
                    (row.event_id,),
                )
                deleted += 1

        logger.info("카카오 ICS 동기화 완료: 생성 %d, 수정 %d, 삭제 %d", created, updated, deleted)
        return {"created": created, "updated": updated, "deleted": deleted, "total": len(kakao_events)}


def _ensure_attendees(cursor, event_id: int, apwid_list: list):
    """기존 일정에 누락된 참석자를 추가 (중복 방지)"""
    if not apwid_list:
        return
    cursor.execute(
        "SELECT apwid FROM YJI_CalendarAttendees WHERE event_id = ?",
        (event_id,),
    )
    existing_ids = {row.apwid for row in cursor.fetchall()}
    added = 0
    for apwid in apwid_list:
        if apwid not in existing_ids:
            cursor.execute(
                "INSERT INTO YJI_CalendarAttendees (event_id, apwid, status) VALUES (?, ?, 'pending')",
                (event_id, apwid),
            )
            added += 1
    if added > 0:
        logger.info("기존 일정(event_id=%d) 참석자 %d명 보충", event_id, added)
