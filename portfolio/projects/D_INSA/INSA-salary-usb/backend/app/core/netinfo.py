"""서버 자신의 LAN IP.

루프백(127.0.0.1)으로 들어온 요청은 정의상 서버가 돌고 있는 이 PC에서 온 것이다.
IP 기반 판정(연봉 금고 좌석 규칙 등)에서는 그 PC의 실제 LAN IP로 봐야 한다 —
같은 PC에서 localhost로 접속했느냐 LAN 주소로 접속했느냐에 따라 결과가 달라지면 안 된다.
"""
import socket
from functools import lru_cache
from typing import Optional

from app.core.config import settings


@lru_cache(maxsize=1)
def local_lan_ip() -> Optional[str]:
    """기본 라우트 인터페이스의 IPv4. 설정 SERVER_LAN_IP가 있으면 그것을 우선한다."""
    if settings.SERVER_LAN_IP:
        return settings.SERVER_LAN_IP
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # UDP connect는 패킷을 보내지 않고 라우팅만 결정한다.
            s.connect(('192.0.2.10', 1))
            return s.getsockname()[0]
    except OSError:
        return None
