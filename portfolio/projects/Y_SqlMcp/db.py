# -*- coding: utf-8 -*-
'\ndb.py — settings.ini 다중 프로파일 + pyodbc 연결.\n\nsettings.ini 구조:\n  [general]\n  default_profile = apworksdw\n\n  [profile.apworksdw]\n  server = 192.0.2.10\n  port = 1433\n  database = apworksdw\n  username = dh\n  password = ****\n  driver = ODBC Driver 17 for SQL Server\n  trust_server_certificate = true\n  timeout = 10\n  allow_tables = TABLE_A, TABLE_B      ; 비우면 전부 거부\n\n새 서버/DB는 [profile.<이름>] 섹션만 추가하면 코드 수정 없이 늘어난다.\n'

import os
import configparser
import pyodbc

BASE = os.path.dirname(os.path.abspath(__file__))
INI = os.path.join(BASE, "settings.ini")


def _cfg():
    cp = configparser.ConfigParser()
    if not os.path.exists(INI):
        raise FileNotFoundError("settings.ini 가 없습니다: %s" % INI)
    cp.read(INI, encoding="utf-8")
    return cp


def list_profiles():
    """등록된 프로파일 이름 목록."""
    cp = _cfg()
    return [s.split(".", 1)[1] for s in cp.sections()
            if s.lower().startswith("profile.")]


def default_profile():
    """기본 프로파일. [general] default_profile 우선, 없으면 첫 프로파일."""
    cp = _cfg()
    if cp.has_section("general") and cp.has_option("general", "default_profile"):
        name = cp.get("general", "default_profile").strip()
        if name:
            return name
    profs = list_profiles()
    if not profs:
        raise ValueError("settings.ini에 등록된 프로파일이 없습니다.")
    return profs[0]


def _section(profile):
    """프로파일 섹션을 대소문자 무관하게 찾는다."""
    cp = _cfg()
    target = ("profile.%s" % profile).lower()
    for s in cp.sections():
        if s.lower() == target:
            return cp[s]
    raise ValueError("프로파일 '%s' 을(를) settings.ini에서 찾을 수 없습니다." % profile)


def allowed_tables(profile):
    """해당 프로파일의 허용 테이블 리스트 (비어있으면 [])."""
    sec = _section(profile)
    raw = sec.get("allow_tables", "") or ""
    return [t.strip() for t in raw.split(",") if t.strip()]


def _bool(sec, key, default=False):
    val = sec.get(key, str(default)).strip().lower()
    return val in ("1", "true", "yes", "on")


def _conn_str(sec):
    driver = sec.get("driver", "ODBC Driver 17 for SQL Server")
    server = sec.get("server", "")
    port = sec.get("port", "1433")
    parts = [
        "DRIVER={%s}" % driver,
        "SERVER=%s,%s" % (server, port),
        "DATABASE=%s" % sec.get("database", ""),
        "UID=%s" % sec.get("username", ""),
        "PWD=%s" % sec.get("password", ""),
    ]
    if _bool(sec, "trust_server_certificate", True):
        parts.append("TrustServerCertificate=yes")
    if _bool(sec, "encrypt", False):
        parts.append("Encrypt=yes")
    return ";".join(parts) + ";"


def connect(profile, autocommit=False):
    """프로파일로 pyodbc 연결을 연다."""
    sec = _section(profile)
    timeout = int(sec.get("timeout", "10") or "10")
    return pyodbc.connect(_conn_str(sec), autocommit=autocommit, timeout=timeout)
