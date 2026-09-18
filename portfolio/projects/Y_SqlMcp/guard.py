# -*- coding: utf-8 -*-
"""
guard.py — SQL 검열 계층 (코드 레벨 안전장치). 표준 라이브러리만 사용.

규칙:
  1) 한 번에 한 문장만 허용 (세미콜론 다중문장 차단 → 인젝션 방지)
  2) DDL/위험 명령 전면 차단 (DROP/ALTER/TRUNCATE/CREATE/GRANT/EXEC/MERGE/USE/DBCC ...)
     → SELECT / INSERT / UPDATE / DELETE (CRUD) 만 허용
  3) 저장 프로시저(sp_/xp_) 호출 차단
  4) 쿼리가 건드리는 모든 테이블이 화이트리스트(settings.ini의 allow_tables)에 있어야 통과.
     화이트리스트가 비어 있으면 어떤 테이블도 통과 못 함(= 초기엔 전부 거부).

분석은 '주석 제거 + 문자열 리터럴 제거'한 사본(c1)에서 수행하고,
실제 실행에는 '주석만 제거한' 원본(c0)을 사용한다(문자열 값 보존).
"""

import re

WRITE = {"INSERT", "UPDATE", "DELETE"}
FORBIDDEN = {
    "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE",
    "EXEC", "EXECUTE", "MERGE", "USE", "CALL", "BACKUP",
    "RESTORE", "SHUTDOWN", "DBCC", "RENAME", "DENY",
}

_KW_RE = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|"
    r"REVOKE|EXEC|EXECUTE|MERGE|USE|CALL|BACKUP|RESTORE|SHUTDOWN|DBCC|"
    r"RENAME|DENY)\b",
    re.IGNORECASE,
)

# FROM / JOIN / INTO / UPDATE 뒤의 테이블 식별자(스키마.테이블, db.스키마.테이블 포함)
_TABLE_RE = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE)\s+"
    r"((?:\[[^\]]+\]|\"[^\"]+\"|[A-Za-z_#][\w$#]*)"
    r"(?:\s*\.\s*(?:\[[^\]]+\]|\"[^\"]+\"|[A-Za-z_#][\w$#]*)){0,2})",
    re.IGNORECASE,
)


class SqlError(Exception):
    """검열에 걸린 SQL. 사용자에게 사유를 그대로 보여준다."""
    pass


def _strip_comments(sql):
    s = re.sub(r"/\*.*?\*/", " ", sql or "", flags=re.DOTALL)  # 블록 주석
    s = re.sub(r"--[^\n]*", " ", s)                              # 라인 주석
    return s


def _strip_strings(s):
    # 작은따옴표 문자열(''escape 포함)을 빈 문자열로 치환
    return re.sub(r"'(?:[^']|'')*'", "''", s)


def _depth_at(s, pos):
    seg = s[:pos]
    return seg.count("(") - seg.count(")")


def classify(sql):
    """
    SQL을 검열하고 종류를 판정한다.
    반환: ('select' | 'write', cleaned_sql)  ← cleaned_sql은 실행용(주석만 제거)
    위반 시 SqlError 발생.
    """
    c0 = _strip_comments(sql).strip()
    if not c0:
        raise SqlError("빈 SQL입니다.")
    c1 = _strip_strings(c0)

    # 1) 다중 문장 차단
    statements = [s for s in c1.split(";") if s.strip()]
    if len(statements) > 1:
        raise SqlError("여러 문장을 한 번에 실행할 수 없습니다. 한 문장만 보내세요.")

    # 2) 금지 키워드가 하나라도 있으면 차단
    keywords = [m.group(1).upper() for m in _KW_RE.finditer(c1)]
    for k in keywords:
        if k in FORBIDDEN:
            raise SqlError(
                "허용되지 않는 명령(%s)입니다. CRUD(SELECT/INSERT/UPDATE/DELETE)만 가능합니다." % k
            )

    # 3) 저장 프로시저 차단
    if re.search(r"\b(?:sp_|xp_)\w+", c1, re.IGNORECASE):
        raise SqlError("저장 프로시저(sp_/xp_) 호출은 허용되지 않습니다.")

    # 4) 괄호 깊이 0에서 처음 나오는 명령 키워드 = 주 명령 (WITH CTE/서브쿼리 대응)
    main = None
    for m in _KW_RE.finditer(c1):
        if _depth_at(c1, m.start()) == 0:
            main = m.group(1).upper()
            break
    if main is None:
        raise SqlError("지원하지 않는 SQL입니다. SELECT/INSERT/UPDATE/DELETE만 가능합니다.")

    if main in WRITE:
        return "write", c0
    if main == "SELECT":
        return "select", c0
    raise SqlError("지원하지 않는 SQL입니다. SELECT/INSERT/UPDATE/DELETE만 가능합니다.")


def _norm(name):
    """식별자를 (전체이름, 베이스테이블명) 소문자 튜플로 정규화."""
    parts = [p.strip().strip('[]"').strip() for p in name.split(".")]
    full = ".".join(parts).lower()
    base = parts[-1].lower()
    return full, base


# CTE 정의명 (WITH c AS ( ... )) — 실제 테이블이 아니므로 화이트리스트 검사에서 제외
_CTE_RE = re.compile(r"\b([A-Za-z_#][\w$#]*)\s+AS\s*\(", re.IGNORECASE)


def _cte_names(analyzed):
    return {m.group(1).lower() for m in _CTE_RE.finditer(analyzed)}


def extract_tables(cleaned):
    """쿼리가 참조하는 테이블 집합 {(full, base), ...}."""
    analyzed = _strip_strings(cleaned)
    found = set()
    for m in _TABLE_RE.finditer(analyzed):
        found.add(_norm(m.group(1)))
    return found


def check_allowed(cleaned, kind, allowed):
    """
    참조 테이블이 모두 화이트리스트에 있는지 검증. 위반 시 SqlError.
    allowed: settings.ini에서 읽은 허용 테이블명 리스트.
    """
    allowed_l = {a.lower() for a in allowed}
    analyzed = _strip_strings(cleaned)
    cte = _cte_names(analyzed)
    tabs = {(full, base) for (full, base) in extract_tables(cleaned)
            if base not in cte}

    if not tabs:
        # 테이블 없는 SELECT (예: SELECT GETDATE(), CTE만 참조) 는 무해 → 허용.
        if kind == "write":
            raise SqlError("대상 테이블을 인식할 수 없어 거부했습니다.")
        return

    offending = [
        full for (full, base) in tabs
        if full not in allowed_l and base not in allowed_l
    ]
    if offending:
        requested = ", ".join(sorted({b for _, b in tabs}))
        if not allowed_l:
            raise SqlError(
                "허용된 테이블이 없습니다. settings.ini의 allow_tables에 "
                "테이블을 먼저 등록하세요. (요청 테이블: %s)" % requested
            )
        raise SqlError(
            "화이트리스트에 없는 테이블입니다: %s" % ", ".join(sorted(set(offending)))
        )
