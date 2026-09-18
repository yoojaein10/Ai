"""
User service - [apworksdw].dbo.seat_Userinfo 조회 전용.
"""
import logging

from app.exceptions import NotFoundException

logger = logging.getLogger(__name__)

# 부서 코드 -> 부서명 매핑
DEPT_NAMES = {
    "jip": "집행부",
    "sim": "심사부",
    "gam": "감사부",
    "ju": "주주평가사",
    "mp": "명예평가사",
    "yj": "예비주주평가사",
    "so": "소속평가사",
    "su": "수습평가사",
    "pg1": "평가1부",
    "pg2": "평가2부",
    "pu1": "업무1팀",
    "pu2": "업무2팀",
    "pu3": "업무3팀",
    "jun": "전산정보팀",
    "ch": "총무기획팀",
    "jae": "재무팀",
}

DEPT_ORDER = {
    "so": 1, "su": 2, "pg1": 3, "pg2": 4,
    "pu1": 5, "pu2": 6, "pu3": 7,
    "jun": 8, "ch": 9, "jae": 10,
    # 기타 (참석자 트리뷰용)
    "jip": 11, "sim": 12, "gam": 13, "ju": 14, "mp": 15, "yj": 16,
}


class UserService:
    @staticmethod
    def get_user_by_empno(cursor, empno: int) -> dict:
        """사번으로 사용자 정보 조회"""
        cursor.execute(
            "SELECT Apwid, Uname, Dept_Nm, Team_name, Udtel, Uptel, Ugrade "
            "FROM [apworksdw].dbo.seat_Userinfo WHERE Apwid = ?",
            (empno,),
        )
        row = cursor.fetchone()
        if not row:
            raise NotFoundException("사용자를 찾을 수 없습니다.")
        return {
            "apwid": int(row.Apwid) if row.Apwid else 0,
            "name": row.Uname,
            "dept_code": row.Dept_Nm,
            "dept_name": DEPT_NAMES.get(row.Dept_Nm, row.Dept_Nm),
            "team_name": row.Team_name,
            "phone_ext": row.Udtel,
            "phone": row.Uptel,
            "grade": (row.Ugrade or "").strip(),
        }

    @staticmethod
    def get_user_dept(cursor, empno: int) -> str:
        """사번으로 부서코드만 조회 (내부용)"""
        cursor.execute(
            "SELECT Dept_Nm FROM [apworksdw].dbo.seat_Userinfo WHERE Apwid = ?",
            (empno,),
        )
        row = cursor.fetchone()
        if not row:
            raise NotFoundException("사용자를 찾을 수 없습니다.")
        return row.Dept_Nm

    @staticmethod
    def search_users(cursor, query: str) -> list:
        """이름으로 사용자 검색 (재직 중인 사용자만)"""
        cursor.execute(
            "SELECT Apwid, Uname, Dept_Nm, Team_name "
            "FROM [apworksdw].dbo.seat_Userinfo "
            "WHERE Uname LIKE ? AND Udtel IS NOT NULL AND Udtel != '' AND Dept_Nm != 'gy' "
            "ORDER BY Uname",
            (f"%{query}%",),
        )
        return [
            {
                "apwid": int(r.Apwid) if r.Apwid else 0,
                "name": r.Uname,
                "dept_code": r.Dept_Nm,
                "dept_name": DEPT_NAMES.get(r.Dept_Nm, r.Dept_Nm),
                "team_name": r.Team_name,
            }
            for r in cursor.fetchall()
        ]

    @staticmethod
    def get_users_by_department(cursor) -> list:
        """부서별 사용자 목록 (트리뷰용)"""
        cursor.execute(
            "SELECT Apwid, Uname, Dept_Nm "
            "FROM [apworksdw].dbo.seat_Userinfo "
            "WHERE Udtel IS NOT NULL AND Udtel != '' AND Dept_Nm != 'gy' "
            "ORDER BY Uname"
        )

        dept_map = {}
        for row in cursor.fetchall():
            code = row.Dept_Nm
            if code not in DEPT_NAMES:
                continue
            if code not in dept_map:
                dept_map[code] = {
                    "dept_code": code,
                    "dept_name": DEPT_NAMES[code],
                    "sort_order": DEPT_ORDER.get(code, 99),
                    "users": [],
                }
            dept_map[code]["users"].append({
                "apwid": int(row.Apwid) if row.Apwid else 0,
                "name": row.Uname,
            })

        return sorted(dept_map.values(), key=lambda x: x["sort_order"])

    @staticmethod
    def get_departments(cursor) -> list:
        """부서 목록 + 부서별 사용자 수"""
        cursor.execute(
            "SELECT Dept_Nm, COUNT(*) as cnt "
            "FROM [apworksdw].dbo.seat_Userinfo "
            "WHERE Udtel IS NOT NULL AND Udtel != '' AND Dept_Nm != 'gy' "
            "GROUP BY Dept_Nm"
        )
        results = []
        for row in cursor.fetchall():
            code = row.Dept_Nm
            if code in DEPT_NAMES:
                results.append({
                    "dept_code": code,
                    "dept_name": DEPT_NAMES[code],
                    "member_count": row.cnt,
                    "sort_order": DEPT_ORDER.get(code, 99),
                })
        return sorted(results, key=lambda x: x["sort_order"])
