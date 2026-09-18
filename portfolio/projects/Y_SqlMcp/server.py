#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — 로컬 SQL MCP 서버 (사내망 MSSQL 조회/작업용).

데스크톱 Claude가 stdio로 띄우는 백그라운드 서버. 화면(GUI) 없음.

제공 도구:
  - list_profiles()                : 등록된 DB 프로파일 목록
  - test_connection(profile)       : 접속 확인
  - list_allowed_tables(profile)   : 화이트리스트(허용 테이블) 표시
  - describe_table(table, profile) : 테이블 컬럼 구조 (화이트리스트 내)
  - run_select(sql, profile)       : SELECT 조회 (바로 실행)
  - run_write(sql, profile, confirm): INSERT/UPDATE/DELETE
        confirm=False(기본) → 영향 행수만 미리보고 변경은 안 함(롤백)
        confirm=True        → 실제 반영(커밋)

안전장치는 guard.py(검열)와 settings.ini(화이트리스트)에서 강제된다.
"""

import os
import datetime

from mcp.server.fastmcp import FastMCP

import db
import guard

BASE = os.path.dirname(os.path.abspath(__file__))
LOGDIR = os.path.join(BASE, "logs")
os.makedirs(LOGDIR, exist_ok=True)
LOGFILE = os.path.join(LOGDIR, "sqlmcp.log")

MAX_ROWS = 200  # 조회 결과 표시 상한

mcp = FastMCP("sqlmcp")


def _log(kind, profile, sql, extra=""):
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write("%s\t%s\t%s\t%s\t%s\n" % (
                datetime.datetime.now().isoformat(timespec="seconds"),
                kind, profile, extra, (sql or "").strip().replace("\n", " ")))
    except Exception:
        pass


def _prof(profile):
    p = (profile or "").strip()
    return p if p else db.default_profile()


def _format_rows(cols, rows, profile):
    if not cols:
        return "(반환 컬럼 없음)"
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    if not rows:
        return "조회 결과 0건 (프로파일: %s)" % profile

    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = []
    for r in rows:
        vals = []
        for v in r:
            if v is None:
                vals.append("")
            else:
                vals.append(str(v).replace("\n", " ").replace("|", "\\|"))
        body.append("| " + " | ".join(vals) + " |")

    out = "조회 %d건 (프로파일: %s)\n\n%s\n%s\n%s" % (
        len(rows), profile, header, sep, "\n".join(body))
    if truncated:
        out += "\n\n… %d건까지만 표시했습니다. 조건을 더 좁혀 조회하세요." % MAX_ROWS
    return out


@mcp.tool()
def list_profiles() -> str:
    """등록된 DB 프로파일(서버/DB) 목록과 기본 프로파일을 보여준다."""
    try:
        profs = db.list_profiles()
        if not profs:
            return "등록된 프로파일이 없습니다. settings.ini에 [profile.<이름>] 섹션을 추가하세요."
        dflt = db.default_profile()
        lines = []
        for p in profs:
            tabs = db.allowed_tables(p)
            tag = " (기본)" if p == dflt else ""
            tcount = "%d개 테이블 허용" % len(tabs) if tabs else "허용 테이블 없음(전부 거부)"
            lines.append("- %s%s — %s" % (p, tag, tcount))
        return "프로파일 목록:\n" + "\n".join(lines)
    except Exception as e:
        return "❌ %s" % e


@mcp.tool()
def test_connection(profile: str = "") -> str:
    """지정 프로파일로 DB 접속이 되는지 확인한다."""
    p = _prof(profile)
    try:
        cn = db.connect(p, autocommit=True)
        cur = cn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cn.close()
        _log("TEST", p, "SELECT 1", "ok")
        return "✅ 접속 성공 (프로파일: %s)" % p
    except Exception as e:
        _log("TEST-ERR", p, "SELECT 1", str(e))
        return "❌ 접속 실패 (프로파일: %s): %s" % (p, e)


@mcp.tool()
def list_allowed_tables(profile: str = "") -> str:
    """해당 프로파일에서 조회/작업이 허용된 테이블 목록을 보여준다."""
    p = _prof(profile)
    try:
        tabs = db.allowed_tables(p)
        if not tabs:
            return ("프로파일 '%s' 에 허용된 테이블이 없습니다. "
                    "settings.ini의 allow_tables에 테이블명을 추가하세요." % p)
        return "허용 테이블 (프로파일: %s):\n%s" % (
            p, "\n".join("- %s" % t for t in tabs))
    except Exception as e:
        return "❌ %s" % e


@mcp.tool()
def describe_table(table: str, profile: str = "") -> str:
    """테이블의 컬럼 구조를 보여준다. (화이트리스트에 있는 테이블만)"""
    p = _prof(profile)
    name = (table or "").strip()
    if not name:
        return "❌ 테이블명을 입력하세요."
    base = name.split(".")[-1].strip().strip('[]"')
    allowed = {a.lower() for a in db.allowed_tables(p)}
    if base.lower() not in allowed and name.lower() not in allowed:
        return "❌ 화이트리스트에 없는 테이블입니다: %s" % name
    sql = (
        "SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE "
        "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION"
    )
    try:
        cn = db.connect(p, autocommit=True)
        cur = cn.cursor()
        cur.execute(sql, base)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        cn.close()
        if not rows:
            return "테이블 '%s' 의 컬럼 정보를 찾을 수 없습니다 (이름/권한 확인)." % name
        _log("DESCRIBE", p, name, "cols=%d" % len(rows))
        return _format_rows(cols, rows, p)
    except Exception as e:
        _log("DESCRIBE-ERR", p, name, str(e))
        return "❌ DB 오류: %s" % e


@mcp.tool()
def run_select(sql: str, profile: str = "") -> str:
    """사내 DB에서 SELECT 조회를 실행한다 (읽기 전용, 바로 실행).

    - SELECT 외 명령은 거부된다.
    - 참조 테이블이 화이트리스트(settings.ini allow_tables)에 있어야 한다.
    """
    p = _prof(profile)
    try:
        kind, cleaned = guard.classify(sql)
        if kind != "select":
            return "❌ 이 도구는 SELECT 전용입니다. 쓰기는 run_write를 사용하세요."
        guard.check_allowed(cleaned, kind, db.allowed_tables(p))
    except guard.SqlError as e:
        return "❌ %s" % e

    try:
        cn = db.connect(p, autocommit=True)
        cur = cn.cursor()
        cur.execute(cleaned)
        cols = [c[0] for c in cur.description] if cur.description else []
        rows = cur.fetchmany(MAX_ROWS + 1)
        cn.close()
    except Exception as e:
        _log("SELECT-ERR", p, sql, str(e))
        return "❌ DB 오류: %s" % e

    _log("SELECT", p, sql, "rows=%d" % min(len(rows), MAX_ROWS))
    return _format_rows(cols, rows, p)


@mcp.tool()
def run_write(sql: str, profile: str = "", confirm: bool = False) -> str:
    """INSERT/UPDATE/DELETE 를 실행한다.

    안전 절차(2단계):
      1) confirm=False (기본): 쿼리를 트랜잭션 안에서 실행해 '영향 행수'만 확인하고
         즉시 롤백한다. 실제 데이터는 변경되지 않는다. → 사용자에게 SQL과 행수를 보여줄 것.
      2) 사용자가 승인하면 confirm=True 로 다시 호출 → 커밋(실제 반영).

    - SELECT/DDL/저장프로시저는 거부된다.
    - 참조 테이블이 화이트리스트에 있어야 한다.
    """
    p = _prof(profile)
    try:
        kind, cleaned = guard.classify(sql)
        if kind != "write":
            return "❌ 이 도구는 INSERT/UPDATE/DELETE 전용입니다. 조회는 run_select를 사용하세요."
        guard.check_allowed(cleaned, kind, db.allowed_tables(p))
    except guard.SqlError as e:
        return "❌ %s" % e

    cn = None
    try:
        cn = db.connect(p, autocommit=False)
        cur = cn.cursor()
        cur.execute(cleaned)
        affected = cur.rowcount
        if confirm:
            cn.commit()
            cn.close()
            _log("WRITE-COMMIT", p, sql, "rows=%d" % affected)
            return "✅ 실행 완료 — %d개 행이 변경되었습니다. (프로파일: %s)" % (affected, p)
        else:
            cn.rollback()
            cn.close()
            _log("WRITE-PREVIEW", p, sql, "rows=%d" % affected)
            return (
                "🔎 미리보기 (아직 반영되지 않았습니다)\n"
                "이 쿼리는 약 %d개 행에 영향을 줍니다.\n"
                "프로파일: %s\n"
                "SQL: %s\n\n"
                "실제로 반영하려면 사용자 승인 후 confirm=true 로 다시 호출하세요."
                % (affected, p, cleaned)
            )
    except Exception as e:
        try:
            if cn:
                cn.rollback()
                cn.close()
        except Exception:
            pass
        _log("WRITE-ERR", p, sql, str(e))
        return "❌ DB 오류 (반영되지 않음): %s" % e


if __name__ == "__main__":
    mcp.run()
