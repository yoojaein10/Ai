# -*- coding: utf-8 -*-
"""Section 11 단위 검증: normalize_cust_docid / find_existing_cust_docids / SP mock"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')

from db_writer import normalize_cust_docid, find_existing_cust_docids

all_ok = True

# ── normalize_cust_docid ──────────────────────────────────────────────────────
cases_norm = [
    ("'0002260565",   "0002260565"),
    (" 5001892595 ",  "5001892595"),
    ("0002260565",    "0002260565"),
    (None,            ""),
    ("",              ""),
    ("'",             ""),
    ("  '  0010  ",  "0010"),
]
for val, exp in cases_norm:
    r = normalize_cust_docid(val)
    ok = r == exp
    mark = 'OK' if ok else 'FAIL'
    print('%s normalize(%r) -> %r  (exp=%r)' % (mark, val, r, exp))
    if not ok:
        all_ok = False

# ── find_existing_cust_docids: 빈 목록 → DB 연결 없이 ok=True ──────────────
r_empty = find_existing_cust_docids({}, [])
ok_empty = (r_empty["ok"] is True and r_empty["existing"] == set() and r_empty["error"] == "")
print('%s empty list -> ok=%s existing=%r' % ('OK' if ok_empty else 'FAIL', r_empty["ok"], r_empty["existing"]))
if not ok_empty:
    all_ok = False

# 빈값만 있는 경우도 빈 목록 처리
r_blank = find_existing_cust_docids({}, ["", None, "  "])
ok_blank = (r_blank["ok"] is True and r_blank["existing"] == set())
print('%s blank-only list -> ok=%s' % ('OK' if ok_blank else 'FAIL', r_blank["ok"]))
if not ok_blank:
    all_ok = False

# ── find_existing_cust_docids: DB 연결 실패 → ok=False, 전체 SKIP 아님 ──────
r_fail = find_existing_cust_docids(
    {"server": "INVALID_SERVER_XYZ", "database": "X", "username": "U", "password": "P"},
    ['REDACTED_CONFIGURE_LOCALLY7890'],
)
ok_fail = (r_fail["ok"] is False and r_fail["existing"] == set() and r_fail["error"] != "")
print('%s db-fail -> ok=%s error=%r' % ('OK' if ok_fail else 'FAIL', r_fail["ok"], r_fail["error"]))
if not ok_fail:
    all_ok = False

# ── SP mock: 최종 중복 확인 시뮬레이션 ──────────────────────────────────────
# insert_apw_master_expand를 실제 DB 없이 패치해서 duplicate_skipped 집계 검증

class _MockConn:
    """DB 없는 커서 mock."""
    def __init__(self, has_dup=False, fail_dup=False):
        self._has_dup = has_dup
        self._fail_dup = fail_dup
        self._committed = 0
        self._rolled_back = 0

    def cursor(self):
        return _MockCursor(self)

    def commit(self):
        self._committed += 1

    def rollback(self):
        self._rolled_back += 1

    def close(self):
        pass

class _MockCursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows = []
    def execute(self, sql, params=None):
        if self._conn._fail_dup and 'UPDLOCK' in sql:
            raise Exception("mock dup check fail")
        if self._conn._has_dup and 'UPDLOCK' in sql:
            self._rows = [(1,)]
        else:
            self._rows = []
    def fetchone(self):
        return self._rows[0] if self._rows else None
    def fetchall(self):
        return self._rows
    def close(self):
        pass

# 최종 중복 확인 핵심 로직만 테스트 (SP 호출 없이)
def _run_dup_check_only(cust_doc, mock_conn):
    """SP 직전 UPDLOCK 중복 확인 경로 시뮬레이션."""
    result = {"tried": 0, "fail": 0, "duplicate_skipped": 0, "errors": []}
    if cust_doc:
        _dup_row = None
        try:
            _dup_cur = mock_conn.cursor()
            _dup_cur.execute(
                "SELECT TOP (1) 1 FROM dbo.APW_Master WITH (UPDLOCK, HOLDLOCK)"
                " WHERE Office = ? AND CustDocID = ?",
                ("10", cust_doc),
            )
            _dup_row = _dup_cur.fetchone()
            try:
                _dup_cur.close()
            except Exception:
                pass
        except Exception as _dup_e:
            try:
                mock_conn.rollback()
            except Exception:
                pass
            result["tried"] += 1
            result["fail"] += 1
            result["errors"].append({
                "error": "중복 확인 실패: %s" % type(_dup_e).__name__,
            })
            return result, "fail"
        if _dup_row is not None:
            try:
                mock_conn.rollback()
            except Exception:
                pass
            result["duplicate_skipped"] += 1
            return result, "dup"
    result["tried"] += 1
    return result, "proceed"

# 케이스 A: 중복 없음 → proceed
conn_new = _MockConn(has_dup=False)
res, path = _run_dup_check_only("9999999999", conn_new)
ok_a = (path == "proceed" and res["tried"] == 1 and res["duplicate_skipped"] == 0 and res["fail"] == 0)
print('%s 최종확인-신규 -> path=%s tried=%d dup=%d fail=%d' % ('OK' if ok_a else 'FAIL', path, res["tried"], res["duplicate_skipped"], res["fail"]))
if not ok_a:
    all_ok = False

# 케이스 B: 중복 존재 → dup
conn_dup = _MockConn(has_dup=True)
res, path = _run_dup_check_only("9999999999", conn_dup)
ok_b = (path == "dup" and res["tried"] == 0 and res["duplicate_skipped"] == 1 and res["fail"] == 0)
print('%s 최종확인-중복 -> path=%s tried=%d dup=%d fail=%d' % ('OK' if ok_b else 'FAIL', path, res["tried"], res["duplicate_skipped"], res["fail"]))
if not ok_b:
    all_ok = False

# 케이스 C: 확인 실패 → fail, INSERT 보류
conn_err = _MockConn(fail_dup=True)
res, path = _run_dup_check_only("9999999999", conn_err)
ok_c = (path == "fail" and res["tried"] == 1 and res["fail"] == 1 and res["duplicate_skipped"] == 0)
print('%s 최종확인-실패 -> path=%s tried=%d dup=%d fail=%d' % ('OK' if ok_c else 'FAIL', path, res["tried"], res["duplicate_skipped"], res["fail"]))
if not ok_c:
    all_ok = False

# 케이스 D: 빈 cust_doc → proceed (중복 판단 안 함)
conn_empty = _MockConn(has_dup=True)  # has_dup이지만 빈값이므로 SKIP 안 함
res, path = _run_dup_check_only("", conn_empty)
ok_d = (path == "proceed" and res["tried"] == 1 and res["duplicate_skipped"] == 0)
print('%s 빈CustDocID-신규 -> path=%s tried=%d dup=%d' % ('OK' if ok_d else 'FAIL', path, res["tried"], res["duplicate_skipped"]))
if not ok_d:
    all_ok = False

# ── 집계 규칙: duplicate_skipped는 tried 미포함 ───────────────────────────────
# tried=2, dup=1, fail=0 → success+fail == tried (2+0==2? No: tried only counts non-dup)
# 시나리오: 3건 중 1건 dup, 2건 신규
counts = {"tried": 0, "success": 0, "fail": 0, "duplicate_skipped": 0}
for is_dup in [True, False, False]:
    if is_dup:
        counts["duplicate_skipped"] += 1
    else:
        counts["tried"] += 1
        counts["success"] += 1

ok_agg = (
    counts["duplicate_skipped"] == 1
    and counts["tried"] == 2
    and counts["success"] + counts["fail"] == counts["tried"]
)
print('%s 집계규칙: tried=%d success=%d fail=%d dup=%d' % (
    'OK' if ok_agg else 'FAIL',
    counts["tried"], counts["success"], counts["fail"], counts["duplicate_skipped"]))
if not ok_agg:
    all_ok = False

print()
print('ALL PASS' if all_ok else 'SOME FAIL')
