"""MOA 로그인 — usr 파라미터 없이 접속했을 때 APWorks 계정으로 본인 확인.

TMWCMN_USR_BAC_INFO.PSWD 대조. 재직자 674명 기준 형식 분포(2026-07-22 실측):
64자리 hex(SHA-256 추정) 646명 / base64형 27명 / 평문 1명.
해시 생성 방식(대소문자·솔트)이 문서화되어 있지 않아 후보 변형을 모두 대조한다.
"""

import hashlib
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.auth_token import issue as issue_token


class AuthError(ValueError):
    pass


def password_hash_candidates(usr_id: str, password: str) -> "list[str]":
    """PSWD 해시 방식이 미확인이라 가능한 변형(SHA-256)을 모두 만든다."""
    variants = [
        password,
        password.upper(),
        password.lower(),
        f"{usr_id}{password}",
        f"{password}{usr_id}",
    ]
    result: "list[str]" = []
    for variant in variants:
        digest = hashlib.sha256(variant.encode("utf-8")).hexdigest()
        if digest not in result:
            result.append(digest)
    return result


def verify_password_hash(usr_id: str, password: str, stored: str) -> bool:
    stored = (stored or "").strip()
    if not stored:
        return False
    if stored.lower() in password_hash_candidates(usr_id, password):
        return True
    return stored == password  # 평문 저장 계정(레거시) 호환


def _source_database() -> str:
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return database


def login(db: Session, usr_id: str, password: str) -> "dict[str, Any]":
    """아이디·비밀번호 확인 후 사용자 정보 반환. 실패 사유는 노출하지 않는다."""
    usr_id = usr_id.strip()
    if not usr_id or not password:
        raise AuthError("아이디와 비밀번호를 입력하세요.")
    database = _source_database()
    # USR_ID는 재입사 등으로 중복될 수 있어 재직자 행 전체를 놓고 비밀번호로 판별한다
    rows = db.execute(
        text(
            f"""
            SELECT USR_SEQ AS usr_seq, RTRIM(USR_ID) AS usr_id,
                   RTRIM(EMP) AS emp_name, RTRIM(PSWD) AS pswd
            FROM [{database}].dbo.TMWCMN_USR_BAC_INFO
            WHERE USR_ID = CAST(:usr_id AS varchar(50))
              AND USE_YN = 'Y' AND RTRM_FL = '0'
            """
        ),
        {"usr_id": usr_id},
    ).mappings().all()
    for row in rows:
        if verify_password_hash(usr_id, password, row["pswd"] or ""):
            return {
                "usr_seq": row["usr_seq"],
                "usr_id": row["usr_id"],
                "emp_name": row["emp_name"],
                # 비밀번호를 맞혔다는 증표. 화면이 보관했다가 권한을 바꿀 때
                # X-MOA-AUTH 로 함께 보낸다 (app/services/auth_token.py).
                "auth_token": issue_token(int(row["usr_seq"])),
            }
    raise AuthError("아이디 또는 비밀번호가 올바르지 않습니다.")
