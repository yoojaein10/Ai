# -*- coding: utf-8 -*-
"""Bank24 자격증명 조회 헬퍼 (지시 §9, §9-a).

원칙:
- 이 프로젝트 전용 keyring service 와 고정 lookup key 만 사용한다.
- 참조 프로젝트(Y_BankAuto)의 keyring service·key 를 읽거나 쓰지 않는다.
- GUI 런타임은 settings.ini에서 전달된 단일 자격증명 쌍을 사용한다.
- 항목이 없으면 fail-closed(CredentialError). 빈 값/익명 금지.
- 파일·소스·명령행·로그·GUI 에 원문을 저장·출력하지 않는다.
- 장수명 객체(adapter/GUI/오케스트레이터)에 비밀번호를 보관하지 않는다.
- 반환 객체는 즉시 사용하고 wipe() 로 best-effort 소거한다(문자열 불변 한계 명시).
- 확인문구/비밀번호 비교는 상수시간(hmac.compare_digest)으로 한다.

이번 단계에서는 실제 로그인에 사용하지 않는다(구조/게이트만 제공).
"""
from __future__ import annotations

import hmac
import os

# 이 프로젝트 전용 (참조 프로젝트와 분리)
KEYRING_SERVICE = "Y_TSBankAuto/Bank24"
KEY_USERNAME = "bank24_id"
KEY_PASSWORD = 'REDACTED_CONFIGURE_LOCALLY'

# 전용 환경변수 (config 와 동일 이름 사용; 시크릿)
ENV_USERNAME = "YTS_BANK24_ID"
ENV_PASSWORD = "YTS_BANK24_PASSWORD"

METHOD_KEYRING = "keyring"
METHOD_ENV = "env"
METHOD_INI = "ini"


class CredentialError(Exception):
    """자격증명 조회 실패(fail-closed). 원문/사유 상세는 담지 않는다."""


class Credential:
    """단수명 자격증명 홀더. 사용 즉시 wipe() 권장. 로그/repr 에 원문 미노출."""

    __slots__ = ("username", "_pw")

    def __init__(self, username: str, password: str):
        self.username = username
        self._pw = bytearray(password.encode("utf-8"))

    def password_bytes(self) -> bytearray:
        return self._pw

    def use_password(self):
        """비밀번호를 str 로 잠깐 노출(호출 즉시 사용). 반환값을 보관하지 말 것."""
        return self._pw.decode("utf-8")

    def wipe(self) -> None:
        for i in range(len(self._pw)):
            self._pw[i] = 0
        self._pw = bytearray()
        self.username = ""

    def __repr__(self) -> str:
        return "Credential(username=***, password=***)"

    __str__ = __repr__


def _from_keyring() -> tuple[str | None, str | None]:
    try:
        import keyring
    except Exception:
        raise CredentialError("keyring 미설치(선택 방식=keyring, fail-closed)")
    try:
        u = keyring.get_password(KEYRING_SERVICE, KEY_USERNAME)
        p = keyring.get_password(KEYRING_SERVICE, KEY_PASSWORD)
    except Exception:
        raise CredentialError("keyring 조회 오류(fail-closed)")
    return u, p


def _from_env(environ: dict) -> tuple[str | None, str | None]:
    return environ.get(ENV_USERNAME), environ.get(ENV_PASSWORD)


def load_credentials(method: str, *, environ: dict | None = None,
                     ini_username: str | None = None,
                     ini_password: str | None = None) -> Credential:
    """명시적으로 선택한 단일 방식으로만 조회. 자동 fallback 하지 않는다.

    method: "ini", "keyring" 또는 "env". 없거나 빈 값이면 CredentialError(fail-closed).
    """
    if method == METHOD_KEYRING:
        u, p = _from_keyring()
    elif method == METHOD_ENV:
        u, p = _from_env(environ if environ is not None else os.environ)
    elif method == METHOD_INI:
        u, p = ini_username, ini_password
    else:
        raise CredentialError("알 수 없는 자격증명 방식")
    if not u:
        raise CredentialError("자격증명 ID 없음(fail-closed)")
    if not p:
        raise CredentialError("자격증명 비밀번호 없음(빈/익명 금지, fail-closed)")
    return Credential(u, p)


def store_credentials(username: str, password: str) -> None:
    """keyring 등록만 허용. 파일 저장 없음. 빈 값 거부."""
    if not username or not password:
        raise CredentialError("빈 자격증명 저장 불가")
    try:
        import keyring
    except Exception:
        raise CredentialError("keyring 미설치로 저장 불가(파일 저장 금지)")
    keyring.set_password(KEYRING_SERVICE, KEY_USERNAME, username)
    keyring.set_password(KEYRING_SERVICE, KEY_PASSWORD, password)


def credentials_present(method: str, *, environ: dict | None = None) -> bool:
    """원문을 노출하지 않고 존재 여부만 확인(GUI 상태 표시용)."""
    try:
        c = load_credentials(method, environ=environ)
    except CredentialError:
        return False
    c.wipe()
    return True


def constant_time_equals(a: str, b: str) -> bool:
    """확인문구/비밀번호 상수시간 비교. 로그·예외에 값을 남기지 않는다."""
    try:
        return hmac.compare_digest((a or "").encode("utf-8"),
                                   (b or "").encode("utf-8"))
    except Exception:
        return False
