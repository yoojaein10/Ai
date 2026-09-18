"""
Schedule (Event) service.
Uses direct SQL against YJI_CalendarEvents, YJI_CalendarAttendees tables.
Visibility-based access control (company/dept/personal).
"""
import logging

from app.exceptions import (
    NotFoundException,
    ForbiddenException,
    ConflictException,
)
from app.models.schedule import row_to_event, row_to_attendee
from app.services.user_service import UserService

logger = logging.getLogger(__name__)


class ScheduleService:

    _IW_SCHEDULE_EXCLUDE   = ("탁상", "업무부장")          # 공통 제외 gubun
    _IW_SCHEDULE_NPL_GRADES = ("총무이사", "국장")          # NPL 열람 허용 직급
    _IW_SCHEDULE_WIDE_DEPTS = ["su", "pg1", "pg2", "pu1", "pu2", "pu3", "jae", "ch", "jun"]
    _IW_SCHEDULE_COLOR = "#C084FC"

    @staticmethod
    def _get_iw_schedule_access(cursor, empno: int) -> tuple:
        """empno 권한에 따라 (조회가능 부서 목록, 직급) 반환."""
        cursor.execute(
            "SELECT Dept_Nm, Ugrade FROM [apworksdw].dbo.seat_Userinfo WHERE Apwid = ?",
            (empno,),
        )
        row = cursor.fetchone()
        if not row:
            return [], ""
        dept  = (row.Dept_Nm or "").strip()
        grade = (row.Ugrade  or "").strip()
        wide  = list(ScheduleService._IW_SCHEDULE_WIDE_DEPTS)
        if grade == "국장":
            return wide, grade
        if grade == "총무이사":
            return ["so"] + wide, grade
        if dept == "ch" and grade == "팀장":
            return ["so"] + wide, grade
        if empno in (3023, 4079, 4140):
            return ["pg1", "pg2", "su"], grade
        return ([dept] if dept else []), grade

    @staticmethod
    def _get_iw_schedule_events(cursor, empno: int, start: str, end: str) -> list:
        """APW_IW_SCHEDULE에서 권한 범위 내 일정을 CalendarEvent 형태 dict 목록으로 반환."""
        depts, grade = ScheduleService._get_iw_schedule_access(cursor, empno)
        if not depts:
            return []

        can_see_npl = grade in ScheduleService._IW_SCHEDULE_NPL_GRADES
        exclude     = list(ScheduleService._IW_SCHEDULE_EXCLUDE)
        if not can_see_npl:
            exclude.append("NPL")

        ph         = ",".join(["?"] * len(depts))
        ex_ph      = ",".join(["?"] * len(exclude))
        start_date = start[:10]
        end_date   = end[:10]
        DB         = "[apworksdw].dbo"

        cursor.execute(
            f"""
            SELECT s.name, s.date, s.gubun, s.Bigo, u.Dept_Nm
            FROM {DB}.APW_IW_SCHEDULE s
            JOIN {DB}.seat_Userinfo u
                ON LTRIM(RTRIM(s.name)) = LTRIM(RTRIM(u.Uname))
            WHERE s.date >= ? AND s.date < ?
              AND u.Dept_Nm IN ({ph})
              AND LTRIM(RTRIM(ISNULL(s.gubun, ''))) != ''
              AND LTRIM(RTRIM(s.gubun)) NOT IN ({ex_ph})
            ORDER BY s.date, s.name
            """,
            [start_date, end_date] + depts + exclude,
        )

        result = []
        for i, row in enumerate(cursor.fetchall()):
            name     = (row.name    or "").strip()
            date_str = str(row.date)[:10]
            gubun    = (row.gubun   or "").strip()
            bigo     = (row.Bigo    or "").strip() if row.Bigo else ""
            dept     = (row.Dept_Nm or "").strip()

            title = f"{name} {gubun}({bigo})" if bigo else f"{name} {gubun}"

            result.append({
                "event_id":             -(i + 1),
                "creator_id":           0,
                "title":                title,
                "description":          None,
                "location":             None,
                "event_color":          ScheduleService._IW_SCHEDULE_COLOR,
                "event_icon":           None,
                "start_dt":             f"{date_str} 00:00:00",
                "end_dt":               f"{date_str} 23:59:59",
                "is_all_day":           True,
                "visibility":           "dept",
                "dept_code":            dept,
                "repeat_rule":          None,
                "repeat_end_dt":        None,
                "is_daou_noti_enabled": False,
                "version":              0,
                "created_at":           None,
                "updated_at":           None,
                "creator_name":         name,
                "source":               "iw_schedule",
            })

        return result

    @staticmethod
    def get_events(cursor, empno: int, start: str, end: str, visibility: str = None) -> list:
        """
        기간별 이벤트 조회.
        visibility 기반 필터링:
          - company: 모두 볼 수 있음
          - dept: 해당 부서만
          - personal: 본인만 (creator_id = empno)
        추가로 본인이 참석자인 일정도 포함.
        APW_IW_SCHEDULE 일정도 권한 범위 내에서 합쳐서 반환.
        """
        user_dept = UserService.get_user_dept(cursor, empno)

        sql = """
            SELECT DISTINCT e.*, u.Uname AS creator_name
            FROM YJI_CalendarEvents e
            LEFT JOIN [apworksdw].dbo.seat_Userinfo u ON u.Apwid = e.creator_id
            LEFT JOIN YJI_CalendarAttendees a ON a.event_id = e.event_id AND a.apwid = ?
            WHERE e.is_deleted = 0
              AND e.start_dt < ?
              AND e.end_dt > ?
              AND (
                  e.visibility = 'company'
                  OR (e.visibility = 'dept' AND e.dept_code = ?)
                  OR (e.visibility = 'personal' AND e.creator_id = ?)
                  OR a.apwid IS NOT NULL
                  OR e.creator_id = ?
              )
        """
        params = [empno, end, start, user_dept, empno, empno]

        if visibility:
            sql += " AND e.visibility = ?"
            params.append(visibility)

        sql += " ORDER BY e.start_dt ASC"

        cursor.execute(sql, params)
        events = [row_to_event(row) for row in cursor.fetchall()]

        iw_events = ScheduleService._get_iw_schedule_events(cursor, empno, start, end)
        events.extend(iw_events)

        return events

    @staticmethod
    def get_team_events(cursor, empno: int, start: str, end: str) -> list:
        """pg1/pg2 팀 전체 이벤트 조회. empno가 pg1/pg2 소속이어야 함."""
        cursor.execute(
            "SELECT Dept_Nm FROM [apworksdw].dbo.seat_Userinfo WHERE Apwid = ?",
            (empno,),
        )
        row = cursor.fetchone()
        if not row:
            raise NotFoundException("사용자를 찾을 수 없습니다.")
        dept = (row.Dept_Nm or "").strip()
        if dept not in ("pg1", "pg2"):
            raise ForbiddenException("팀 일정은 pg1/pg2 팀원만 조회할 수 있습니다.")

        cursor.execute(
            """
            SELECT e.*, u.Uname AS owner_name, u.Apwid AS owner_empno
            FROM YJI_CalendarEvents e
            JOIN [apworksdw].dbo.seat_Userinfo u ON u.Apwid = e.creator_id
            WHERE e.is_deleted = 0
              AND e.start_dt < ?
              AND e.end_dt > ?
              AND u.Dept_Nm IN ('pg1', 'pg2')
            ORDER BY e.start_dt ASC
            """,
            (end, start),
        )
        events = []
        for r in cursor.fetchall():
            event = row_to_event(r)
            event["owner_name"]   = (r.owner_name or "").strip() if r.owner_name else None
            event["owner_empno"]  = int(r.owner_empno) if r.owner_empno else None
            event["creator_name"] = event["owner_name"]
            event["is_mine"]      = (event["creator_id"] == empno)
            events.append(event)
        return events

    @staticmethod
    def get_event_detail(cursor, event_id: int, empno: int) -> dict:
        """이벤트 상세 조회 (참석자 포함)"""
        cursor.execute(
            "SELECT e.*, u.Uname AS creator_name "
            "FROM YJI_CalendarEvents e "
            "LEFT JOIN [apworksdw].dbo.seat_Userinfo u ON u.Apwid = e.creator_id "
            "WHERE e.event_id = ? AND e.is_deleted = 0",
            (event_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise NotFoundException(f"일정을 찾을 수 없습니다. (event_id={event_id})")

        event = row_to_event(row)

        # 접근 권한 확인
        user_dept = UserService.get_user_dept(cursor, empno)
        has_access = (
            event["visibility"] == "company"
            or (event["visibility"] == "dept" and event["dept_code"] == user_dept)
            or event["creator_id"] == empno
        )

        if not has_access:
            # 참석자인지 확인
            cursor.execute(
                "SELECT 1 FROM YJI_CalendarAttendees WHERE event_id = ? AND apwid = ?",
                (event_id, empno),
            )
            if cursor.fetchone() is None:
                raise ForbiddenException("이 일정에 대한 접근 권한이 없습니다.")

        # 참석자 목록
        cursor.execute(
            "SELECT a.event_id, a.apwid, a.status, a.responded_at, "
            "u.Uname, u.Dept_Nm "
            "FROM YJI_CalendarAttendees a "
            "JOIN [apworksdw].dbo.seat_Userinfo u ON u.Apwid = a.apwid "
            "WHERE a.event_id = ?",
            (event_id,),
        )
        event["attendees"] = [row_to_attendee(r) for r in cursor.fetchall()]
        return event

    @staticmethod
    def create_event(cursor, empno: int, body) -> dict:
        """이벤트 생성"""
        cursor.execute(
            """
            INSERT INTO YJI_CalendarEvents
                (creator_id, title, description, location, event_color, event_icon,
                 start_dt, end_dt, is_all_day, visibility, dept_code,
                 repeat_rule, repeat_end_dt, is_daou_noti_enabled)
            OUTPUT INSERTED.*
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                empno,
                body.title,
                body.description,
                body.location,
                body.event_color,
                body.event_icon,
                body.start_dt,
                body.end_dt,
                1 if body.is_all_day else 0,
                body.visibility,
                body.dept_code,
                body.repeat_rule,
                body.repeat_end_dt,
                1 if getattr(body, "is_daou_noti_enabled", False) else 0,
            ),
        )
        event_row = cursor.fetchone()
        if event_row is None:
            raise NotFoundException("일정 생성에 실패했습니다.")

        event = row_to_event(event_row)
        event_id = event["event_id"]

        # 참석자 추가
        attendees = body.attendee_ids or []
        for apwid in attendees:
            if apwid == empno:
                continue  # 생성자 자신은 건너뜀
            cursor.execute(
                "INSERT INTO YJI_CalendarAttendees (event_id, apwid, status) VALUES (?, ?, 'pending')",
                (event_id, apwid),
            )

        # creator_name 추가
        cursor.execute(
            "SELECT Uname FROM [apworksdw].dbo.seat_Userinfo WHERE Apwid = ?",
            (empno,),
        )
        creator_row = cursor.fetchone()
        event["creator_name"] = creator_row.Uname if creator_row else None
        event["attendees"] = []

        return event

    @staticmethod
    def update_event(cursor, event_id: int, empno: int, body) -> dict:
        """이벤트 수정 (낙관적 잠금)"""
        cursor.execute(
            "SELECT * FROM YJI_CalendarEvents WHERE event_id = ? AND is_deleted = 0",
            (event_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise NotFoundException(f"일정을 찾을 수 없습니다. (event_id={event_id})")

        # 권한: 생성자만 수정 가능
        if row.creator_id != empno:
            raise ForbiddenException("일정 생성자만 수정할 수 있습니다.")

        # 낙관적 잠금
        if row.version != body.version:
            raise ConflictException(
                f"버전 충돌: 기대 버전 {body.version}, 현재 버전 {row.version}"
            )

        # 동적 UPDATE 구문 생성
        fields = []
        values = []
        updatable = {
            "title": body.title,
            "description": body.description,
            "location": body.location,
            "event_color": body.event_color,
            "event_icon": body.event_icon,
            "start_dt": body.start_dt,
            "end_dt": body.end_dt,
            "is_all_day": body.is_all_day,
            "visibility": body.visibility,
            "dept_code": body.dept_code,
            "repeat_rule": body.repeat_rule,
            "repeat_end_dt": body.repeat_end_dt,
            "is_daou_noti_enabled": body.is_daou_noti_enabled,
        }

        for key, val in updatable.items():
            if val is not None:
                if key in ("is_all_day", "is_daou_noti_enabled"):
                    val = 1 if val else 0
                fields.append(f"{key} = ?")
                values.append(val)

        fields.append("version = version + 1")
        fields.append("updated_at = GETDATE()")

        values.extend([body.version, event_id])

        cursor.execute(
            f"""
            UPDATE YJI_CalendarEvents
            SET {', '.join(fields)}
            OUTPUT INSERTED.*
            WHERE version = ? AND event_id = ? AND is_deleted = 0
            """,
            values,
        )
        updated_row = cursor.fetchone()
        if updated_row is None:
            raise ConflictException("동시 수정으로 인해 업데이트에 실패했습니다.")

        event = row_to_event(updated_row)

        # 참석자 업데이트 (attendee_ids가 전달된 경우)
        if body.attendee_ids is not None:
            # 기존 참석자 삭제
            cursor.execute(
                "DELETE FROM YJI_CalendarAttendees WHERE event_id = ?",
                (event_id,),
            )
            # 새 참석자 추가
            for apwid in body.attendee_ids:
                if apwid == empno:
                    continue
                cursor.execute(
                    "INSERT INTO YJI_CalendarAttendees (event_id, apwid, status) VALUES (?, ?, 'pending')",
                    (event_id, apwid),
                )

        # creator_name 추가
        cursor.execute(
            "SELECT Uname FROM [apworksdw].dbo.seat_Userinfo WHERE Apwid = ?",
            (empno,),
        )
        creator_row = cursor.fetchone()
        event["creator_name"] = creator_row.Uname if creator_row else None

        return event

    @staticmethod
    def get_timeline(cursor, date: str) -> list:
        """날짜별 리소스 타임라인 - 전 부서 사원별 출장/휴가/일반 일정"""
        from app.services.user_service import DEPT_NAMES

        TIMELINE_DEPTS = ["so", "su", "pg1", "pg2", "pu1", "pu2", "pu3", "jun", "ch", "jae"]
        TIMELINE_DEPT_ORDER = {d: i + 1 for i, d in enumerate(TIMELINE_DEPTS)}

        # 1. 타임라인 대상 사원 전체 조회
        placeholders = ",".join(["?"] * len(TIMELINE_DEPTS))
        cursor.execute(
            f"""
            SELECT Apwid, Uname, Dept_Nm
            FROM [apworksdw].dbo.seat_Userinfo
            WHERE Dept_Nm IN ({placeholders})
              AND Udtel IS NOT NULL AND Udtel != ''
            ORDER BY Uname
            """,
            TIMELINE_DEPTS,
        )
        user_rows = cursor.fetchall()
        if not user_rows:
            return []

        user_map: dict = {}
        for r in user_rows:
            apwid = int(r.Apwid)
            user_map[apwid] = {
                "apwid": apwid,
                "name": r.Uname,
                "dept_code": r.Dept_Nm,
                "events": [],
            }

        # 2. 해당 날짜의 이벤트 조회 (company/dept visibility)
        cursor.execute(
            """
            SELECT e.event_id, e.creator_id, e.title, e.event_color,
                   e.event_icon, e.start_dt, e.end_dt, e.is_all_day
            FROM YJI_CalendarEvents e
            WHERE e.is_deleted = 0
              AND e.start_dt < ?
              AND e.end_dt > ?
              AND e.visibility IN ('company', 'dept')
            """,
            (f"{date} 23:59:59", f"{date} 00:00:00"),
        )
        event_rows = cursor.fetchall()

        # 3. 이벤트별 참석자 조회 (한번에)
        attendees_map: dict = {}
        if event_rows:
            event_ids = [e.event_id for e in event_rows]
            ph2 = ",".join(["?"] * len(event_ids))
            cursor.execute(
                f"SELECT event_id, apwid FROM YJI_CalendarAttendees WHERE event_id IN ({ph2})",
                event_ids,
            )
            for row in cursor.fetchall():
                attendees_map.setdefault(row.event_id, []).append(int(row.apwid))

        # 4. 이벤트 타입 분류 및 사원 매핑
        def classify(title: str) -> str:
            if "출장" in (title or ""):
                return "출장"
            if any(k in (title or "") for k in ["휴가", "반차", "연차", "병가"]):
                return "휴가"
            return "일반"

        for ev in event_rows:
            event_data = {
                "event_id": ev.event_id,
                "title": ev.title,
                "event_type": classify(ev.title),
                "event_color": ev.event_color,
                "event_icon": ev.event_icon,
                "start_dt": str(ev.start_dt),
                "end_dt": str(ev.end_dt),
                "is_all_day": bool(ev.is_all_day),
            }
            creator_id = int(ev.creator_id) if ev.creator_id else None

            if creator_id and creator_id in user_map:
                user_map[creator_id]["events"].append(event_data)

            for att_apwid in attendees_map.get(ev.event_id, []):
                if att_apwid in user_map and att_apwid != creator_id:
                    user_map[att_apwid]["events"].append(event_data)

        # 5. 부서별 그룹핑 & 정렬
        dept_map: dict = {}
        for apwid, user_data in user_map.items():
            code = user_data["dept_code"]
            if code not in dept_map:
                dept_map[code] = {
                    "dept_code": code,
                    "dept_name": DEPT_NAMES.get(code, code),
                    "sort_order": TIMELINE_DEPT_ORDER.get(code, 99),
                    "users": [],
                }
            dept_map[code]["users"].append(user_data)

        for dept in dept_map.values():
            dept["users"].sort(key=lambda u: u["name"])

        return sorted(dept_map.values(), key=lambda d: d["sort_order"])

    @staticmethod
    def delete_event(cursor, event_id: int, empno: int) -> None:
        """이벤트 삭제 (soft delete)"""
        cursor.execute(
            "SELECT creator_id FROM YJI_CalendarEvents WHERE event_id = ? AND is_deleted = 0",
            (event_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise NotFoundException(f"일정을 찾을 수 없습니다. (event_id={event_id})")

        if row.creator_id != empno:
            raise ForbiddenException("일정 생성자만 삭제할 수 있습니다.")

        cursor.execute(
            "UPDATE YJI_CalendarEvents SET is_deleted = 1, updated_at = GETDATE() WHERE event_id = ?",
            (event_id,),
        )

