# -*- coding: utf-8 -*-
"""읽기 전용 검증 단계 설정/자격증명 (지시 §1, §4, §16).

- 자격증명은 전용 환경변수 4종에서만 받는다(keyring/INI/기존파일/CLI 우회 금지).
  하나라도 없으면 fail-closed. 값은 조회 즉시 사용하고 보관하지 않는다.
- allowlist 는 접속 환경변수와 독립된 비시크릿 설정에서 로드하며,
  시작 시 1회 로드·검증한 불변 객체로 사용한다(TOCTOU 방지: 검증 중 재읽기 없음).
- 실 DB 통합시험 스위치는 자격증명이 아니며 별도 매직값이 정확할 때만 활성.

이 모듈은 자격증명/서버명/연결 문자열을 반환값 repr·로그·예외에 담지 않는다.
"""
from __future__ import annotations

import configparser
import ipaddress
import os
import re
from dataclasses import dataclass, field

# 자격증명 전용 환경변수 (시크릿)
ENV_DB_SERVER = "YTS_DB_SERVER"
ENV_DB_NAME = "YTS_DB_NAME"
ENV_DB_USER = "YTS_DB_USER"
ENV_DB_PASSWORD = "YTS_DB_PASSWORD"
CREDENTIAL_ENV_VARS = (ENV_DB_SERVER, ENV_DB_NAME, ENV_DB_USER, ENV_DB_PASSWORD)

# 실 DB 읽기 전용 통합시험 스위치 (자격증명 아님)
ENV_INTEGRATION = "YTS_ENABLE_READONLY_INTEGRATION"
INTEGRATION_MAGIC = "I_UNDERSTAND_READONLY_DB_ACCESS"

# allowlist CIDR 하한 (지나치게 넓은 범위 거부)
_MIN_PREFIX_V4 = 24
_MIN_PREFIX_V6 = 64

_PLACEHOLDER_TOKENS = frozenset({
    "", "your_db_server_host", "your_db_name", "your_server_identity",
    "your_db_server", "changeme", "example", "placeholder", "todo", "none",
    "null", "localhost.example", "server.example.local",
})
_WILDCARD_CHARS = ("*", "%", "?")


class ReadOnlyConfigError(Exception):
    """읽기 전용 설정/자격증명/allowlist 로딩·검증 실패 (fail-closed)."""


class PreflightError(Exception):
    """다이얼 전 사전 검증 실패 — 자격증명을 네트워크로 보내기 전에 중단."""


# ───────────────────────────── 자격증명 (env 전용) ─────────────────────────────
@dataclass
class Credentials:
    """조회 즉시 사용 후 폐기 대상. repr 로 값을 노출하지 않는다."""
    server: str
    database: str
    user: str
    password: str

    def __repr__(self) -> str:   # 값 노출 금지
        return "Credentials(server=<set>, database=<set>, user=<set>, password=<set>)"

    def clear(self) -> None:
        """best-effort 참조 해제(완전 삭제를 보장한다고 주장하지 않는다)."""
        self.server = self.database = self.user = self.password = ""


def load_credentials(environ: dict | None = None) -> Credentials:
    """전용 환경변수 4종에서만 자격증명 로드. 하나라도 없으면 fail-closed.

    keyring/INI/기존 파일/CLI 우회 없음. 빈 값/공백만 있는 값도 거부.
    """
    env = os.environ if environ is None else environ
    missing = [name for name in CREDENTIAL_ENV_VARS if not (env.get(name) or "").strip()]
    if missing:
        # 어떤 변수가 없는지 이름만 (값은 절대 표시하지 않음)
        raise ReadOnlyConfigError(
            "자격증명 환경변수 누락(fail-closed): " + ", ".join(missing))
    return Credentials(
        server=env[ENV_DB_SERVER].strip(),
        database=env[ENV_DB_NAME].strip(),
        user=env[ENV_DB_USER].strip(),
        password=env[ENV_DB_PASSWORD],   # 비밀번호는 strip 하지 않는다
    )


def integration_enabled(environ: dict | None = None) -> bool:
    """실 DB 읽기 전용 통합시험 스위치가 정확한 매직값인지."""
    env = os.environ if environ is None else environ
    return env.get(ENV_INTEGRATION, "") == INTEGRATION_MAGIC


def child_env_without_db_secrets(environ: dict | None = None) -> dict:
    """자식 프로세스(PDF worker/테스트)에 넘길, DB 시크릿을 제거한 환경 사본.

    자격증명 4종과 통합시험 스위치를 제거한다. 원본 os.environ 은 변경하지 않는다.
    """
    env = dict(os.environ if environ is None else environ)
    for name in (*CREDENTIAL_ENV_VARS, ENV_INTEGRATION):
        env.pop(name, None)
    return env


# ───────────────────────────── allowlist (비시크릿, 불변) ─────────────────────────────
def _looks_like_placeholder(value: str) -> bool:
    v = (value or "").strip().strip("\"'").lower()
    if v in _PLACEHOLDER_TOKENS:
        return True
    if v.startswith("your") or v.startswith("<") or v.startswith("${") or v.startswith("%"):
        return True
    if any(w in v for w in _WILDCARD_CHARS):
        return True
    return False


def _reject_broad_ip(entry: str) -> ipaddress._BaseNetwork:
    """IP/CIDR 문자열을 파싱하고 지나치게 넓은 범위/미지정 주소를 거부."""
    try:
        net = ipaddress.ip_network(entry, strict=False)
    except ValueError as e:
        raise ReadOnlyConfigError(f"allowlist IP 형식 오류: {entry!r}") from e
    if net.network_address.is_unspecified or int(net.network_address) == 0:
        raise ReadOnlyConfigError(f"미지정 IP 금지: {entry!r}")
    minp = _MIN_PREFIX_V4 if net.version == 4 else _MIN_PREFIX_V6
    if net.prefixlen < minp:
        raise ReadOnlyConfigError(f"지나치게 넓은 CIDR 금지: {entry!r}")
    return net


@dataclass(frozen=True)
class ReadOnlyAllowlist:
    """4종 독립 allowlist (지시 §4). 불변 객체.

    - connect_hosts: 연결 전 허용 hostname/IP (정확 일치)
    - connect_ips: DNS 해석 결과 검증용 허용 IP/CIDR
    - server_identities: 연결 후 DB 가 반환하는 서버 식별값
    - databases: 연결 후 허용 DB명
    """
    connect_hosts: tuple[str, ...] = ()
    connect_ips: tuple[str, ...] = ()
    server_identities: tuple[str, ...] = ()
    databases: tuple[str, ...] = ()
    verify_dns: bool = False
    _ip_nets: tuple = field(default=(), repr=False)

    def host_allowed(self, host: str) -> bool:
        h = (host or "").strip().lower()
        if not h:
            return False
        return any(h == c.strip().lower() for c in self.connect_hosts)

    def server_identity_ok(self, identity: str) -> bool:
        s = (identity or "").strip()
        return bool(s) and any(s == c.strip() for c in self.server_identities)

    def database_ok(self, name: str) -> bool:
        s = (name or "").strip()
        return bool(s) and any(s == c.strip() for c in self.databases)

    def ip_allowed(self, ip: str) -> bool:
        try:
            addr = ipaddress.ip_address((ip or "").strip())
        except ValueError:
            return False
        return any(addr in net for net in self._ip_nets)


def _split_csv(v: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in (v or "").split(",") if x.strip())


def load_allowlist(ini_path: str) -> ReadOnlyAllowlist:
    """settings.ini 의 [ro_allowlist] 에서 불변 allowlist 를 1회 로드·검증.

    placeholder/빈 값/wildcard/넓은 CIDR 을 거부한다. 접속 환경변수를 기대값으로
    재사용하지 않는다(파일에서만 읽는다). 검증 중 파일을 다시 읽지 않는다(TOCTOU 방지).
    """
    cfg = configparser.ConfigParser()
    cfg.optionxform = str
    read = cfg.read(ini_path, encoding="utf-8")
    if not read:
        raise ReadOnlyConfigError(f"설정 파일을 읽을 수 없음: {ini_path}")
    if not cfg.has_section("ro_allowlist"):
        raise ReadOnlyConfigError("[ro_allowlist] 섹션 없음 (fail-closed)")
    sec = cfg["ro_allowlist"]

    connect_hosts = _split_csv(sec.get("connect_hosts", ""))
    connect_ips = _split_csv(sec.get("connect_ips", ""))
    server_identities = _split_csv(sec.get("server_identities", ""))
    databases = _split_csv(sec.get("databases", ""))
    verify_dns = str(sec.get("verify_dns", "false")).strip().lower() in ("1", "true", "yes", "on")

    if not connect_hosts:
        raise ReadOnlyConfigError("connect_hosts 비어 있음")
    if not server_identities:
        raise ReadOnlyConfigError("server_identities 비어 있음")
    if not databases:
        raise ReadOnlyConfigError("databases 비어 있음")

    for label, items in (("connect_hosts", connect_hosts),
                         ("server_identities", server_identities),
                         ("databases", databases)):
        for it in items:
            if _looks_like_placeholder(it):
                raise ReadOnlyConfigError(f"{label} placeholder/wildcard 금지: {it!r}")

    ip_nets = []
    for it in connect_ips:
        if _looks_like_placeholder(it):
            raise ReadOnlyConfigError(f"connect_ips placeholder/wildcard 금지: {it!r}")
        ip_nets.append(_reject_broad_ip(it))

    if verify_dns and not connect_ips:
        raise ReadOnlyConfigError("verify_dns=true 이면 connect_ips 가 필요")

    return ReadOnlyAllowlist(
        connect_hosts=connect_hosts,
        connect_ips=connect_ips,
        server_identities=server_identities,
        databases=databases,
        verify_dns=verify_dns,
        _ip_nets=tuple(ip_nets),
    )


# ───────────────────────────── 서버 문자열 파싱 & 사전 검증 ─────────────────────────────
_HOSTPART_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class ServerTarget:
    host: str
    instance: str = ""
    port: str = ""
    is_ip: bool = False


def parse_server(server: str) -> ServerTarget:
    """YTS_DB_SERVER 문자열을 host/instance/port 로 명시적으로 파싱.

    지원: host, host,port, host\\instance, host\\instance,port,
          ipv4[,port], [ipv6][,port]. 제어문자/주입문자는 거부.
    """
    s = (server or "").strip()
    if not s:
        raise PreflightError("서버 문자열이 비어 있음")
    if any(ord(c) < 0x20 or c == "\x7f" for c in s) or "\x00" in s:
        raise PreflightError("서버 문자열에 제어문자 포함")

    port = ""
    host_inst = s
    # IPv6 brackets: [::1] or [::1],1433
    if s.startswith("["):
        end = s.find("]")
        if end == -1:
            raise PreflightError("IPv6 대괄호 미종결")
        host = s[1:end]
        rest = s[end + 1:]
        if rest.startswith(","):
            port = rest[1:]
        elif rest:
            raise PreflightError("IPv6 뒤 잘못된 형식")
        try:
            ipaddress.IPv6Address(host)
        except ValueError as e:
            raise PreflightError("IPv6 주소 형식 오류") from e
        _validate_port(port)
        return ServerTarget(host=host, port=port, is_ip=True)

    # 마지막 콤마로 포트 분리
    if "," in host_inst:
        host_inst, _, port = host_inst.rpartition(",")
        _validate_port(port)

    instance = ""
    host = host_inst
    if "\\" in host_inst:
        host, _, instance = host_inst.partition("\\")
        if not instance or "\\" in instance or not _HOSTPART_RE.match(instance):
            raise PreflightError("인스턴스명 형식 오류")

    host = host.strip()
    if not host:
        raise PreflightError("호스트가 비어 있음")

    is_ip = False
    try:
        ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        if not _HOSTPART_RE.match(host):
            raise PreflightError("호스트명 형식 오류")

    return ServerTarget(host=host, instance=instance, port=port, is_ip=is_ip)


def _validate_port(port: str) -> None:
    if port == "":
        return
    if not port.isdigit():
        raise PreflightError("포트 형식 오류")
    n = int(port)
    if not (1 <= n <= 65535):
        raise PreflightError("포트 범위 오류")


def preflight_check(server: str, allowlist: ReadOnlyAllowlist,
                    *, resolver=None) -> ServerTarget:
    """다이얼 전 사전 검증. 실패하면 자격증명 전송 전에 PreflightError.

    - YTS_DB_SERVER 의 host 가 connect_hosts 에 정확히 일치.
    - verify_dns=True 면 resolver 로 해석한 모든 IP 가 connect_ips 에 허용돼야 한다.
      해석 결과 검증이 불가능하면 중단(부분일치/suffix 비교 사용 안 함).
    """
    target = parse_server(server)
    if not allowlist.host_allowed(target.host):
        raise PreflightError("서버 host 가 connect_hosts 에 없음")

    if allowlist.verify_dns:
        if target.is_ip:
            if not allowlist.ip_allowed(target.host):
                raise PreflightError("IP literal 이 connect_ips 에 없음")
            return target
        if resolver is None:
            raise PreflightError("verify_dns=true 인데 resolver 미구성 — 중단")
        try:
            ips = list(resolver(target.host))
        except Exception as e:
            raise PreflightError("DNS 해석 실패") from e
        if not ips:
            raise PreflightError("DNS 해석 결과 없음")
        for ip in ips:
            if not allowlist.ip_allowed(ip):
                raise PreflightError("해석된 IP 중 미허용 존재")
    return target
