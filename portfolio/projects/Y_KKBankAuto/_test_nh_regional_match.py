# -*- coding: utf-8 -*-
"""농협중앙회 지역농협 거래처 매칭 회귀 테스트 (mock DB, 합성 데이터 전용).

- 실제 DB/Bank24/API/네트워크 연결 없음(소켓 연결 차단 fixture 포함).
- 쓰기(UPDATE/INSERT/DELETE/MERGE/DDL/EXEC/COMMIT)는 mock에서 즉시 실패로 차단.
- 실제 농협명·CustCode·거래처 목록을 하드코딩하지 않고 합성 인물/지점명만 사용.
단독 pytest 프로세스로 실행.
"""
import re
import socket

import pytest

import db_writer as dw


# ── 네트워크 차단 (실제 연결 발생 시 즉시 실패) ──────────────────────────────
@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("real network connection attempted in test")
    monkeypatch.setattr(socket.socket, "connect", _boom)
    # pyodbc.connect 는 각 테스트에서 명시적으로 mock; 기본은 차단
    monkeypatch.setattr(dw.pyodbc, "connect",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("real pyodbc.connect attempted")))


# ── mock DB ──────────────────────────────────────────────────────────────────
_WRITE_RE = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE)\b", re.I)


def _like_to_regex(pattern: str, escaped: bool):
    """SQL Server LIKE 패턴 → 정규식 (ESCAPE '\\' 여부 반영).

    escaped=True면 \\%, \\_, \\[, \\], \\\\ 를 리터럴로 처리(와일드카드 아님).
    """
    rx, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if escaped and ch == "\\" and i + 1 < len(pattern):
            rx.append(re.escape(pattern[i + 1])); i += 2; continue
        if ch == "%":
            rx.append(".*"); i += 1
        elif ch == "_":
            rx.append("."); i += 1
        else:
            rx.append(re.escape(ch)); i += 1
    return re.compile("^" + "".join(rx) + "$", re.S)


class MockCursor:
    def __init__(self, conn):
        self.conn = conn
        self._result = []

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        up = sql.upper().strip()
        if up.startswith("EXEC") or "SP_I_APW_MASTER_EXPAND" in up:
            raise AssertionError("SP EXEC attempted during test")
        if _WRITE_RE.search(sql):
            raise AssertionError(f"write DML/DDL attempted: {up[:16]}")
        self._result = self.conn.handle_select(sql, params)
        return self

    def fetchall(self):
        return list(self._result)

    def fetchone(self):
        return self._result[0] if self._result else None

    def nextset(self):
        return False

    def close(self):
        pass


class MockConn:
    def __init__(self, customers=None, reg_rows=None):
        # customers: list of (CustID, CustName, Active) — Office '11' 가정
        self.customers = list(customers or [])
        self.reg_rows = list(reg_rows or [])
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return MockCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass

    def handle_select(self, sql, params):
        up = sql.upper()
        if "APW_CUSTOMER" in up:
            p = list(params or [])
            escaped = r"ESCAPE '\'" in sql
            active_required = "ACTIVE='Y'" in up.replace(" ", "")
            # CustName 술어를 순서대로(=, LIKE) 추출해 파라미터와 AND 결합
            preds = re.findall(r"CUSTNAME\s*(=|LIKE)", up)

            def match(cust):
                _cid, cname, active = cust
                cname = cname or ""
                if active_required and (active or "") != "Y":
                    return False
                for op, val in zip(preds, p):
                    if op == "=":
                        if cname != val:
                            return False
                    else:
                        if not _like_to_regex(val, escaped).match(cname):
                            return False
                return True

            return [c for c in self.customers if match(c)]
        # RegHist 등은 매칭 없음
        return []


# ════════════════════════════════════════════════════════════════════════════
# 정규화 규칙
# ════════════════════════════════════════════════════════════════════════════
def test_normalize_basic_transform():
    assert dw.normalize_nonghyup_office_name("모현농협 능원지점") == "모현농업협동조합 능원지점"


def test_normalize_no_double_transform():
    assert dw.normalize_nonghyup_office_name("모현농업협동조합 능원지점") == "모현농업협동조합 능원지점"


def test_normalize_does_not_touch_nonghyup_bank():
    assert dw.normalize_nonghyup_office_name("농협은행 강남지점") == "농협은행 강남지점"
    assert dw.normalize_nonghyup_office_name("NH농협은행 강남지점") == "NH농협은행 강남지점"


def test_normalize_standalone_and_internal_nonghyup_not_changed():
    # 앞에 한글이 없는(독립) '농협' 또는 문장 내부 '농협'은 변환하지 않음
    assert dw.normalize_nonghyup_office_name("농협 방문 예정") == "농협 방문 예정"


def test_normalize_whitespace_normalized():
    assert dw.normalize_nonghyup_office_name("  모현농협   능원지점  ") == "모현농업협동조합 능원지점"


@pytest.mark.parametrize("bad", ["", "   ", "a\x00b", "a\r\nb", "a\x1bb", "x" * 201])
def test_normalize_failclosed_inputs(bad):
    assert dw.normalize_nonghyup_office_name(bad) is None


# ════════════════════════════════════════════════════════════════════════════
# LIKE 이스케이프
# ════════════════════════════════════════════════════════════════════════════
def test_like_escape_order_and_chars():
    assert dw._like_escape(r"a\b") == r"a\\b"           # escape 문자 먼저
    assert dw._like_escape("100%_[x]") == r"100\%\_\[x\]"


# ════════════════════════════════════════════════════════════════════════════
# 후보 우선순위 / fail-closed / fallback 금지
# ════════════════════════════════════════════════════════════════════════════
def test_exact_transformed_match():
    conn = MockConn([("C1", "모현농업협동조합 능원지점", "Y")])
    r = dw.lookup_cust_code(conn, "농협중앙회", "모현농협 능원지점")
    assert r["matched"] and r["CustCode"] == "C1"
    assert r["CustName"] == "모현농업협동조합 능원지점"
    assert r["method"] == "nh_regional_exact_transformed"


def test_original_match_when_no_transformed():
    conn = MockConn([("C2", "모현농협 능원지점", "Y")])
    r = dw.lookup_cust_code(conn, "농협중앙회", "모현농협 능원지점")
    assert r["matched"] and r["CustCode"] == "C2"
    assert r["method"] == "nh_regional_exact_original"


def test_partial_match_transformed():
    conn = MockConn([("C3", "[본소]모현농업협동조합 능원지점(대출)", "Y")])
    r = dw.lookup_cust_code(conn, "농협중앙회", "모현농협 능원지점")
    assert r["matched"] and r["CustCode"] == "C3"
    assert r["method"] == "nh_regional_partial_transformed"


def test_failclosed_when_no_candidate():
    # 다른 농협중앙회 지점만 존재 → 매칭 실패, 빈 값(다른 지점 선택 금지)
    conn = MockConn([("C9", "농협중앙회 서천지점", "Y")])
    r = dw.lookup_cust_code(conn, "농협중앙회", "모현농협 능원지점")
    assert r["matched"] is False and r["CustCode"] == "" and r["CustName"] == ""


def test_no_bank_only_fallback_pattern_used():
    conn = MockConn([("C9", "농협중앙회 서천지점", "Y")])
    dw.lookup_cust_code(conn, "농협중앙회", "모현농협 능원지점")
    # '농협중앙회%' 형태의 bank_only LIKE 파라미터가 사용되지 않아야 함
    for _sql, params in conn.executed:
        for p in (params or []):
            assert p != "농협중앙회%"
            assert not (isinstance(p, str) and p.startswith("농협중앙회") and p.endswith("%")
                        and "능원" not in p and "모현" not in p)


def test_seocheon_mismatch_prevented():
    conn = MockConn([
        ("C9", "농협중앙회 서천지점", "Y"),
        ("C1", "모현농업협동조합 능원지점", "Y"),
    ])
    r = dw.lookup_cust_code(conn, "농협중앙회", "모현농협 능원지점")
    assert r["CustName"] == "모현농업협동조합 능원지점"   # 서천지점으로 가지 않음


def test_multi_candidate_active_priority():
    conn = MockConn([
        ("C_N", "모현농업협동조합 능원지점", "N"),
        ("C_Y", "모현농업협동조합 능원지점", "Y"),
    ])
    r = dw.lookup_cust_code(conn, "농협중앙회", "모현농협 능원지점")
    assert r["CustCode"] == "C_Y" and r["multi"] is True


def test_already_coop_name_matches_original_path():
    conn = MockConn([("C1", "모현농업협동조합 능원지점", "Y")])
    r = dw.lookup_cust_code(conn, "농협중앙회", "모현농업협동조합 능원지점")
    assert r["matched"] and r["method"] == "nh_regional_exact_original"


@pytest.mark.parametrize("bad", ["", "   ", "x\x00y", "x\r\ny", "x\x1by", "지" * 201])
def test_lookup_failclosed_bad_branch(bad):
    conn = MockConn([("C1", "모현농업협동조합 능원지점", "Y")])
    r = dw.lookup_cust_code(conn, "농협중앙회", bad)
    assert r["matched"] is False and r["CustCode"] == ""


# ════════════════════════════════════════════════════════════════════════════
# LIKE 특수문자가 와일드카드로 동작하지 않음 + 파라미터 바인딩
# ════════════════════════════════════════════════════════════════════════════
def test_like_special_chars_not_wildcard():
    # 입력에 [ ] 등 특수문자 포함 — LIKE에서 이스케이프되어 리터럴로만 매칭.
    # exact는 실패하고 partial(LIKE)로만 매칭되도록 DB 이름을 더 길게 구성.
    conn = MockConn([
        ("A", "모현농업협동조합 능원X지점 센터", "Y"),   # [동]이 와일드카드였다면 오매칭 위험
        ("B", "모현농업협동조합 능원[동]지점 센터", "Y"),  # 리터럴 [동] 포함 — 정답
    ])
    r = dw.lookup_cust_code(conn, "농협중앙회", "모현농협 능원[동]지점")
    assert r["matched"] and r["CustCode"] == "B"      # 리터럴 매칭(A로 오매칭 아님)
    assert "partial" in r["method"]
    like = [(s, p) for s, p in conn.executed
            if "LIKE" in s.upper() and "APW_CUSTOMER" in s.upper()]
    assert like
    for s, p in like:
        assert r"ESCAPE '\'" in s                      # 명시적 ESCAPE 절
    # 파라미터에 [,] 가 이스케이프되어 전달됨(와일드카드 해석 방지)
    assert any((r"\[" in p[0] and r"\]" in p[0]) for _s, p in like)


def test_all_search_values_parameter_bound():
    conn = MockConn([("C1", "모현농업협동조합 능원지점", "Y")])
    branch = "모현농협 능원지점"
    dw.lookup_cust_code(conn, "농협중앙회", branch)
    assert conn.executed, "no query executed"
    for sql, params in conn.executed:
        assert "?" in sql                      # 파라미터 자리표시자 사용
        assert params is not None and len(params) >= 1
        # 합성 입력값이 SQL 문자열에 직접 포함되지 않음
        assert branch not in sql
        assert "모현" not in sql


# ════════════════════════════════════════════════════════════════════════════
# 다른 은행 회귀(일반 경로 미변경)
# ════════════════════════════════════════════════════════════════════════════
def test_other_bank_generic_path_unchanged():
    # 농협은행은 일반 경로 사용 — 정확 매칭 동작 유지
    conn = MockConn([("K1", "농협은행 강남지점", "Y")])
    r = dw.lookup_cust_code(conn, "농협은행", "강남지점")
    assert r["matched"] and r["CustCode"] == "K1"
    assert r["method"].startswith("exact")     # 일반 경로 method


def test_other_bank_bank_only_fallback_still_works():
    # 일반 은행은 기존 bank_only fallback 유지(농협중앙회만 금지)
    conn = MockConn([("H1", "하나은행 역삼지점", "Y")])
    r = dw.lookup_cust_code(conn, "하나은행", "없는지점")
    assert r["matched"] and r["CustCode"] == "H1"
    assert r["method"].startswith("bank_only")   # 일반 은행은 bank_only fallback 유지


# ════════════════════════════════════════════════════════════════════════════
# 직함 '장'은 매칭 성공 시에만
# ════════════════════════════════════════════════════════════════════════════
def test_title_suffix_only_on_matched():
    item = {"은행": "농협중앙회", "영업점": "모현농협 능원지점"}
    # 매칭 성공
    ok = dw.resolve_sp_cust_name(item, "모현농업협동조합 능원지점", "농협중앙회", "모현농협 능원지점")
    assert ok == "모현농업협동조합 능원지점장"
    # 매칭 실패 → 빈 값(직함 '장' 미생성)
    fail = dw.resolve_sp_cust_name(item, "", "농협중앙회", "모현농협 능원지점")
    assert fail == ""


# ════════════════════════════════════════════════════════════════════════════
# 실패 건에서 SP/INSERT/commit 미호출 (SP 경로 통합, 쓰기 0건)
# ════════════════════════════════════════════════════════════════════════════
def test_sp_path_skips_failed_nh_without_write(monkeypatch):
    conn = MockConn(customers=[("C9", "농협중앙회 서천지점", "Y")])  # 매칭 실패 유도
    monkeypatch.setattr(dw.pyodbc, "connect", lambda *a, **k: conn)

    item = {
        "은행": "농협중앙회",
        "영업점": "모현농협 능원지점",
        "처리상태": "성공",
        "의뢰번호": "SYN-0001",
        "pdf_소재지": "경기도 용인시 처인구 모현읍 능원리 100",
    }
    db_config = {"server": "x", "database": "y", "username": "u", "password": "p",
                 "driver": "ODBC Driver 17 for SQL Server"}
    result = dw.insert_apw_master_expand([item], db_config, log=None)

    assert result["success"] == 0
    assert result["fail"] >= 1
    assert conn.commits == 0                       # commit 0건
    # SP EXEC 미실행(실행됐다면 MockCursor가 AssertionError)
    assert not any("SP_I_APW_MASTER_EXPAND" in s.upper() for s, _ in conn.executed)
    # 실패 사유는 비식별(원문 영업점/CustName/CustCode 미포함), 참조는 해시
    errs = result["errors"]
    assert errs and all("모현" not in (e.get("error", "")) for e in errs)


def test_sp_path_matched_nh_reaches_dupcheck(monkeypatch):
    # 매칭 성공 시에는 skip 없이 진행(중복확인 SELECT까지 도달). SP는 중복으로 차단.
    conn = MockConn(customers=[("C1", "모현농업협동조합 능원지점", "Y")])
    # 중복 확인 SELECT가 1행 반환하도록 처리 → SP 호출 없이 DUP-SKIP
    orig_handle = conn.handle_select

    def handle(sql, params):
        if "APW_MASTER" in sql.upper() and "CUSTDOCID" in sql.upper():
            return [(1,)]     # 중복 존재
        return orig_handle(sql, params)

    conn.handle_select = handle
    monkeypatch.setattr(dw.pyodbc, "connect", lambda *a, **k: conn)

    item = {
        "은행": "농협중앙회", "영업점": "모현농협 능원지점", "처리상태": "성공",
        "의뢰번호": "SYN-0002",
        "pdf_소재지": "경기도 용인시 처인구 모현읍 능원리 100",
    }
    db_config = {"server": "x", "database": "y", "username": "u", "password": "p",
                 "driver": "ODBC Driver 17 for SQL Server"}
    result = dw.insert_apw_master_expand([item], db_config, log=None)
    # 매칭됐고 중복이라 SP/commit 없이 dup-skip (쓰기 0건)
    assert conn.commits == 0
    assert result["duplicate_skipped"] >= 1
    assert not any("SP_I_APW_MASTER_EXPAND" in s.upper() for s, _ in conn.executed)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
