"""APWorks 사용자 컨텍스트 — 로그인 계정, 조직, 메뉴·데이터 범위와 접근 감사 로그.

실데이터 확인 결과(2026-07-20): USE_YN은 전 행 'Y', RTRM_FL은 '0'=재직/'1'=퇴사
(RTRM_FL='1'인 1,240명 중 1,210명이 RTRM_DAY 보유, '0'은 0명). 판정은 fail-closed:
정확히 USE_YN='Y'이고 RTRM_FL='0'인 경우만 허용한다.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.access_log import AccessLog
from app.services.access_policy import (
    identity_from_row,
    load_access_policy,
)
from app.services.office_lookup import active_offices, get_office


class UserContextError(LookupError):
    def __init__(self, code: str, message: str, office_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.office_id = office_id


class UserContextService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def context(self, usr_seq: str, client_ip: str | None) -> dict[str, Any]:
        try:
            data = self._resolve(usr_seq)
        except UserContextError as exc:
            self._log(usr_seq, exc.code, exc.office_id, client_ip, str(exc))
            raise
        # 성공 시에는 조회된 USR_ID로 남겨 감사 로그를 사람이 읽기 쉽게 한다.
        self._log(data["usr_id"], "OK", data["office_id"], client_ip, f"usr_seq={usr_seq}")
        return data

    def _resolve(self, usr_seq: str) -> dict[str, Any]:
        # APWorks가 넘기는 식별자는 USR_SEQ(int, 유일)다. USR_ID는 동명이인·재입사로
        # 중복될 수 있어 2026-07-21부터 USR_SEQ 기준으로 바꿨다.
        database = _source_database()
        row = self.db.execute(
            text(
                f"""
                SELECT TOP 1
                    u.USR_SEQ AS usr_seq,
                    RTRIM(u.USR_ID) AS usr_id,
                    RTRIM(u.EMP) AS emp_name,
                    RTRIM(u.OFFICE_ID) AS office_id,
                    RTRIM(u.USE_YN) AS use_yn,
                    RTRIM(u.RTRM_FL) AS rtrm_fl,
                    RTRIM(u.APPRAISAL_FL) AS appraisal_fl,
                    LOWER(RTRIM(s.Dept_Nm)) AS seat_dept,
                    NULLIF(LTRIM(RTRIM(d.CHRG_BIZ)), '') AS chrg_biz
                FROM [{database}].dbo.TMWCMN_USR_BAC_INFO u
                LEFT JOIN [{database}].dbo.TMWCMN_EMPT_DTL d
                    ON d.USR_SEQ = u.USR_SEQ
                OUTER APPLY (
                    SELECT TOP 1 s.Dept_Nm
                    FROM [{database}].dbo.Seat_userinfo s
                    WHERE RTRIM(s.APWID) = RTRIM(u.USR_ID)
                      AND RTRIM(u.OFFICE_ID) = '10'
                ) s
                WHERE u.USR_SEQ = :usr_seq
                """
            ),
            {"usr_seq": int(usr_seq)},
        ).mappings().first()
        if row is None:
            raise UserContextError("USER_NOT_FOUND", "등록되지 않은 사용자입니다.")
        office_id = row["office_id"]
        if row["use_yn"] != "Y":
            raise UserContextError("USER_INACTIVE", "사용 중지된 사용자입니다.", office_id)
        if row["rtrm_fl"] != "0":
            raise UserContextError("USER_RETIRED", "퇴사 처리된 사용자입니다.", office_id)
        office = get_office(self.db, office_id)
        if office is None:
            raise UserContextError(
                "OFFICE_NOT_MAPPED",
                f"소속 지사({office_id})가 A10BRIDGE에 등록되어 있지 않습니다.",
                office_id,
            )

        identity = identity_from_row(row)
        policy = load_access_policy(self.db, identity)
        # 레거시 허용명단(a10_access_allow) 폴백은 2026-08-18 걷어냈다 — 실측으로 여기
        # 걸리는 사람이 0명이었다(기존 명단 8명 전원 이미 묶음 보유). 권한은 이제 오로지
        # 묶음·개인 예외에서만 온다. 묶음 없으면 메뉴 0개 = 아래에서 명확히 로그인 거절.
        if not policy["menu_keys"]:
            # 열 수 있는 메뉴가 하나도 없으면 들여보내지 않고 분명히 거절한다.
            # 종전 허용명단 방식은 이 자리에서 ACCESS_DENIED 를 냈다. 메뉴 권한 방식으로
            # 바꾸면서 이 관문이 사라져, 권한 없는 사람이 빈 화면을 받게 되어 있었다.
            # 빈 화면은 고장으로 읽힌다 — 문의가 전산으로 온다.
            raise UserContextError(
                "ACCESS_DENIED", "이 프로그램 사용 권한이 없습니다.", office_id
            )
        view_all = policy["view_all_offices"]
        offices = active_offices(self.db) if view_all else [office]
        return {
            "usr_seq": row["usr_seq"],
            "usr_id": row["usr_id"],
            "emp_name": row["emp_name"],
            "office_id": office_id,
            "office_name": office.office_name,
            "docid_prefix": office.docid_prefix,
            "division_code": office.division_code,
            "department_code": identity.department_code,
            "department_name": identity.department_name,
            "employee_type": identity.employee_type,
            "is_appraiser": identity.is_appraiser,
            "view_all_offices": view_all,
            "view_other_users": policy["view_other_users"],
            "menu_permissions": policy["menu_permissions"],
            "menu_keys": policy["menu_keys"],
            "is_operations": policy["is_operations"],
            "is_branch_finance": policy["is_branch_finance"],
            "policy_source": policy["policy_source"],
            "offices": [
                {
                    "office_code": item.office_id,
                    "office_name": item.office_name,
                    "docid_prefix": item.docid_prefix,
                    "division_code": item.division_code,
                }
                for item in offices
            ],
        }

    def _log(
        self,
        usr_id: str,
        result: str,
        office_id: str | None,
        client_ip: str | None,
        detail: str | None,
    ) -> None:
        try:
            self.db.add(
                AccessLog(
                    usr_id=usr_id[:50],
                    action="EXE_LAUNCH",
                    result=result,
                    office_id=office_id,
                    client_ip=client_ip,
                    detail=detail[:400] if detail else None,
                )
            )
            self.db.commit()
        except Exception:
            # 감사 로그 실패가 컨텍스트 응답 자체를 막지 않도록 한다.
            self.db.rollback()


def _source_database() -> str:
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return database
