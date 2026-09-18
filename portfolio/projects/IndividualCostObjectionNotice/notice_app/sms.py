from __future__ import annotations

import re

import pyodbc


class SmsError(RuntimeError):
    pass


def normalize_mobile_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if not digits.startswith("01") or len(digits) not in (10, 11):
        raise ValueError("수신 전화번호 형식이 올바르지 않습니다.")
    return digits


def normalize_sender_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if not 8 <= len(digits) <= 12:
        raise ValueError("발신번호 형식이 올바르지 않습니다.")
    return digits


def mask_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) < 7:
        return "***"
    return digits[:3] + "****" + digits[-4:]


def _odbc_escape(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


def _safe_database_name(value: str) -> str:
    if not value or not value.replace("_", "").isalnum():
        raise ValueError("수신자 DB 이름이 올바르지 않습니다.")
    return value


class SmsClient:
    def __init__(
        self,
        *,
        server: str,
        database: str,
        username: str,
        password: str,
        driver: str,
        encrypt: str,
        trust_server_certificate: str,
        call_from: str,
        connection_timeout_seconds: int,
        query_timeout_seconds: int,
    ) -> None:
        self.call_from = normalize_sender_phone(call_from)
        self.query_timeout_seconds = query_timeout_seconds
        connection_string = ";".join(
            (
                "DRIVER=" + _odbc_escape(driver),
                "SERVER=" + _odbc_escape(server),
                "DATABASE=" + _odbc_escape(database),
                "UID=" + _odbc_escape(username),
                "PWD=" + _odbc_escape(password),
                "Encrypt=" + encrypt,
                "TrustServerCertificate=" + trust_server_certificate,
            )
        )
        try:
            self.connection = pyodbc.connect(
                connection_string,
                timeout=connection_timeout_seconds,
                autocommit=False,
            )
            self.connection.timeout = query_timeout_seconds
        except pyodbc.Error as exc:
            raise SmsError("문자 DB 연결에 실패했습니다.") from exc

    @staticmethod
    def _validate_text(subject: str, body: str) -> None:
        try:
            subject_length = len(subject.encode("cp949"))
            body_length = len(body.encode("cp949"))
        except UnicodeEncodeError as exc:
            raise SmsError("문자 DB에서 지원하지 않는 문자가 포함되어 있습니다.") from exc
        if not subject or subject_length > 40:
            raise SmsError("문자 제목은 CP949 기준 1~40바이트여야 합니다.")
        if not body or body_length > 2000:
            raise SmsError("문자 본문은 CP949 기준 1~2000바이트여야 합니다.")

    def send_mms(self, recipient: str, subject: str, body: str) -> None:
        recipient = normalize_mobile_phone(recipient)
        self._validate_text(subject, body)
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                EXEC dbo.MMS_SEND
                    @FILE_CNT=?, @MMS_BODY=?, @MMS_SUBJECT=?,
                    @FILE_TYPE1=?, @FILE_NAME1=?, @SERVICE_DEP1=?,
                    @CALL_TO=?, @CALL_FROM=?
                """,
                1,
                body,
                subject,
                "",
                "",
                "",
                recipient,
                self.call_from,
            )
            self.connection.commit()
        except pyodbc.Error as exc:
            self.connection.rollback()
            raise SmsError("MMS_SEND 실행에 실패했습니다.") from exc
        finally:
            cursor.close()

    def load_recipient_phones(
        self,
        source_database: str,
        departments: tuple[str, ...],
    ) -> tuple[str, ...]:
        source_database = _safe_database_name(source_database)
        if not departments:
            raise ValueError("운영 발송 부서가 설정되지 않았습니다.")
        placeholders = ", ".join("?" for _ in departments)
        query = f"""
            SELECT DISTINCT LTRIM(RTRIM(Uptel)) AS phone
            FROM [{source_database}].dbo.Seat_UserInfo
            WHERE LOWER(LTRIM(RTRIM(Dept_Nm))) IN ({placeholders})
              AND Uptel IS NOT NULL
              AND LTRIM(RTRIM(Uptel)) <> ''
        """
        cursor = self.connection.cursor()
        try:
            rows = cursor.execute(query, *departments).fetchall()
        except pyodbc.Error as exc:
            raise SmsError("Seat_UserInfo 수신번호 조회에 실패했습니다.") from exc
        finally:
            cursor.close()

        phones: set[str] = set()
        for row in rows:
            try:
                phones.add(normalize_mobile_phone(str(row[0])))
            except ValueError:
                continue
        return tuple(sorted(phones))

    def close(self) -> None:
        self.connection.close()
