"""로그인 증표(서명 토큰) 만들기·검증하기.

왜 있나 (2026-08-16 진단)
    지금 서버는 **숫자 하나를 그대로 믿는다.** get_current_access 가
    X-MOA-USR-SEQ 헤더(또는 ?usr_seq=)의 값을 isdigit() 만 보고 그 사람으로
    친다. 로그인은 비밀번호를 확인하지만 그 결과로 아무것도 발급하지 않는다.
    docs/APWORKS_LAUNCH.md 도 스스로 '인증이 아니라 식별' 이라고 적어 두었다.

    조회만 있을 때는 감수할 만한 거래였다. 그런데 권한 화면이 붙으면서 이
    헤더로 열리는 것이 '남의 실적 조회'에서 **'전사 권한 쓰기'** 로 바뀌었다.
    누구든 재무팀 usr_seq 를 넣으면 부서 묶음을 갈아치울 수 있다.

무엇을 하나
    로그인에 성공하면 HMAC 로 서명한 짧은 증표를 준다. 서버는 그 서명이 맞을
    때만 '이 사람이 비밀번호를 아는 사람' 이라고 인정한다.

무엇을 **안** 하나
    EXE 런처는 비밀번호 없이 ?usr= 만 넘긴다(APWorks 가 이미 확인했다는 전제).
    그 경로를 여기서 끊으면 전 사원이 프로그램을 못 연다. 그래서 이 모듈은
    증표를 **더한다**. 무엇을 증표로만 허용할지는 dependencies.py 가 정하고,
    지금은 '권한을 바꾸는 일' 에만 요구한다 — 조회는 종전대로 둔다.
    EXE 손잡이를 어떻게 신뢰할지는 APWorks 쪽과 함께 정해야 하는 별도 문제다.

비밀키
    AUTH_TOKEN_SECRET 을 .env 에 둔다. 없으면 서버가 뜰 때마다 임시 키를 만들어
    쓰는데, 그러면 **재기동할 때마다 모두 다시 로그인**해야 한다 — 운영에서는
    반드시 지정한다. 없다고 죽이지는 않는다(개발·시험이 막히므로).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time

from app.config import get_settings

logger = logging.getLogger(__name__)

# 증표가 살아 있는 시간. 하루 일과보다 넉넉히 잡되, 흘린 증표가 영원히 살지는
# 않게 한다. 만료되면 화면이 다시 로그인을 띄운다.
TOKEN_TTL_SECONDS = 12 * 60 * 60

_FALLBACK_SECRET: str | None = None


def _secret() -> str:
    global _FALLBACK_SECRET
    configured = getattr(get_settings(), "auth_token_secret", None)
    raw = configured.get_secret_value() if hasattr(configured, "get_secret_value") else configured
    if raw:
        return str(raw)
    if _FALLBACK_SECRET is None:
        _FALLBACK_SECRET = secrets.token_urlsafe(32)
        logger.warning(
            "AUTH_TOKEN_SECRET 이 없어 임시 키를 씁니다 — 서버를 다시 띄우면 "
            "모두 다시 로그인해야 합니다. 운영에서는 .env 에 지정하세요."
        )
    return _FALLBACK_SECRET


def _sign(payload: str) -> str:
    digest = hmac.new(_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256)
    return base64.urlsafe_b64encode(digest.digest()).decode("ascii").rstrip("=")


def issue(usr_seq: int, *, ttl: int = TOKEN_TTL_SECONDS, now: float | None = None) -> str:
    """'이 사람이 방금 비밀번호를 맞혔다' 는 증표. 형식은 `usr_seq.만료.서명`."""
    expires = int((now if now is not None else time.time()) + ttl)
    payload = f"{int(usr_seq)}.{expires}"
    return f"{payload}.{_sign(payload)}"


def verify(token: str | None, *, now: float | None = None) -> int | None:
    """증표가 맞으면 usr_seq, 아니면 None.

    **usr_seq 는 증표에서 꺼낸다.** 헤더에 따로 실려 온 숫자를 쓰면 서명한
    보람이 없다 — 증표는 A 것이고 헤더는 B 라고 적어 보내면 그만이다.
    """
    if not token:
        return None
    parts = str(token).split(".")
    if len(parts) != 3:
        return None
    raw_seq, raw_exp, signature = parts
    if not raw_seq.isdigit() or not raw_exp.isdigit():
        return None
    # 서명을 먼저 본다. 만료를 먼저 보면 위조 증표에도 '만료' 라고 답해 주게 되어
    # 형식이 맞는지 아닌지를 알려 주는 셈이 된다.
    if not hmac.compare_digest(_sign(f"{raw_seq}.{raw_exp}"), signature):
        return None
    if int(raw_exp) < int(now if now is not None else time.time()):
        return None
    return int(raw_seq)
