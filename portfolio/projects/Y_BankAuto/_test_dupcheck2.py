# -*- coding: utf-8 -*-
"""Section 7 mock 검증: UPDLOCK 위치 이동 후 6가지 시나리오."""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')

# ─── Mock 인프라 ──────────────────────────────────────────────────────────────
class _MockCursor:
    def __init__(self, conn, dup_hit=False, dup_raise=False, sp_raise=False):
        self._conn = conn
        self._dup_hit   = dup_hit
        self._dup_raise = dup_raise
        self._sp_raise  = sp_raise
        self._rows = []
    def execute(self, sql, params=None):
        self._conn._calls.append(("execute", sql[:40]))
        if "UPDLOCK" in sql:
            if self._dup_raise:
                raise Exception("mock dup error")
            self._rows = [(1,)] if self._dup_hit else []
        elif "SP_I_APW" in sql or "_SP_EXPAND" in sql:
            if self._sp_raise:
                raise Exception("mock sp error")
            self._rows = [(9001, "D9001", 1, 1)]
        else:
            self._rows = [(1,)]   # men_gbn UPDATE 등
    def fetchone(self):
        return self._rows[0] if self._rows else None
    def fetchall(self):
        return self._rows
    def fetchmany(self, size=1):
        return self._rows[:size]
    def nextset(self):
        return False
    def close(self):
        self._conn._calls.append(("close",))


class _MockConn:
    def __init__(self, dup_hit=False, dup_raise=False, sp_raise=False):
        self._dup_hit   = dup_hit
        self._dup_raise = dup_raise
        self._sp_raise  = sp_raise
        self._calls     = []
        self.commits    = 0
        self.rollbacks  = 0
    def cursor(self):
        return _MockCursor(self,
            dup_hit=self._dup_hit,
            dup_raise=self._dup_raise,
            sp_raise=self._sp_raise,
        )
    def commit(self):
        self._calls.append(("commit",))
        self.commits += 1
    def rollback(self):
        self._calls.append(("rollback",))
        self.rollbacks += 1
    def close(self):
        pass


# ─── 핵심 경로 시뮬레이터 ────────────────────────────────────────────────────
# insert_apw_master_expand의 한 item 처리 경로를 직접 재현한다.
# addr_count, param_ok, cust_doc으로 진입 경로를 제어한다.

def _run_item(conn, cust_doc, addr_count=1, param_ok=True):
    """반환: result dict, 이벤트 목록"""
    from db_writer import normalize_cust_docid
    import re

    result = {"tried": 0, "success": 0, "fail": 0, "duplicate_skipped": 0, "errors": []}
    events = []

    # ① 소재지 없음
    if addr_count == 0:
        try:
            conn.rollback()
        except Exception:
            pass
        result["tried"] += 1
        result["fail"] += 1
        result["errors"].append({"error": "소재지 없음"})
        events.append("addr_fail")
        return result, events

    # ② 파라미터 검증 실패
    if not param_ok:
        try:
            conn.rollback()
        except Exception:
            pass
        result["tried"] += 1
        result["fail"] += 1
        result["errors"].append({"error": "placeholder 불일치"})
        events.append("param_fail")
        return result, events

    # ③ 중복 확인
    duplicate_exists = False
    if cust_doc:
        _dup_cur = None
        try:
            _dup_cur = conn.cursor()
            _dup_cur.execute(
                "SELECT TOP (1) 1 FROM dbo.APW_Master WITH (UPDLOCK, HOLDLOCK)"
                " WHERE Office = ? AND CustDocID = ?",
                ("10", cust_doc),
            )
            duplicate_exists = _dup_cur.fetchone() is not None
            events.append("dup_select")
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            result["tried"] += 1
            result["fail"] += 1
            result["errors"].append({"error": "중복 확인 실패: %s" % type(e).__name__})
            events.append("dup_check_fail")
            return result, events
        finally:
            if _dup_cur is not None:
                try:
                    _dup_cur.close()
                except Exception:
                    pass

    if duplicate_exists:
        try:
            conn.rollback()
        except Exception:
            pass
        result["duplicate_skipped"] += 1
        events.append("dup_skip")
        return result, events

    result["tried"] += 1

    # ④ SP 호출
    try:
        _sp_cur = conn.cursor()
        _sp_cur.execute("SP_I_APW mock", [])
        row = _sp_cur.fetchone()
        events.append("sp_execute")
        conn.commit()
        events.append("commit")
        result["success"] += 1
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        result["fail"] += 1
        events.append("sp_fail")

    return result, events


all_ok = True

def chk(label, cond):
    global all_ok
    mark = 'OK' if cond else 'FAIL'
    print('%s %s' % (mark, label))
    if not cond:
        all_ok = False


# ─── 시나리오 1: 중복 존재 ──────────────────────────────────────────────────
conn1 = _MockConn(dup_hit=True)
r1, ev1 = _run_item(conn1, 'REDACTED_CONFIGURE_LOCALLY7890')
print('\n[시나리오1] 중복 존재')
chk('SP 호출 0회',            "sp_execute" not in ev1)
chk('rollback 1회',           conn1.rollbacks == 1)
chk('tried=0',                r1["tried"] == 0)
chk('success=0',              r1["success"] == 0)
chk('fail=0',                 r1["fail"] == 0)
chk('duplicate_skipped=1',    r1["duplicate_skipped"] == 1)
chk('success+fail==tried',    r1["success"] + r1["fail"] == r1["tried"])

# ─── 시나리오 2: 신규 ───────────────────────────────────────────────────────
conn2 = _MockConn(dup_hit=False)
r2, ev2 = _run_item(conn2, "9999999999")
print('\n[시나리오2] 신규')
chk('dup SELECT 실행',        "dup_select" in ev2)
chk('SP 호출 1회',            "sp_execute" in ev2)
chk('commit 1회',             conn2.commits == 1)
chk('dup SELECT → SP 순서',   ev2.index("dup_select") < ev2.index("sp_execute"))
chk('tried=1',                r2["tried"] == 1)
chk('success=1',              r2["success"] == 1)
chk('fail=0',                 r2["fail"] == 0)
chk('duplicate_skipped=0',    r2["duplicate_skipped"] == 0)
chk('success+fail==tried',    r2["success"] + r2["fail"] == r2["tried"])

# ─── 시나리오 3: 중복 확인 오류 ─────────────────────────────────────────────
conn3 = _MockConn(dup_raise=True)
r3, ev3 = _run_item(conn3, "1111111111")
print('\n[시나리오3] 중복 확인 오류')
chk('SP 호출 0회',            "sp_execute" not in ev3)
chk('rollback 1회',           conn3.rollbacks == 1)
chk('tried=1',                r3["tried"] == 1)
chk('success=0',              r3["success"] == 0)
chk('fail=1',                 r3["fail"] == 1)
chk('duplicate_skipped=0',    r3["duplicate_skipped"] == 0)
chk('errors 예외타입만',      r3["errors"] and "Exception" in r3["errors"][0]["error"])
chk('success+fail==tried',    r3["success"] + r3["fail"] == r3["tried"])

# ─── 시나리오 4: 소재지 없음 ────────────────────────────────────────────────
conn4 = _MockConn()
r4, ev4 = _run_item(conn4, "2222222222", addr_count=0)
print('\n[시나리오4] 소재지 없음')
chk('dup SELECT 0회',         "dup_select" not in ev4)
chk('SP 호출 0회',            "sp_execute" not in ev4)
chk('rollback 호출',          conn4.rollbacks >= 1)
chk('tried=1',                r4["tried"] == 1)
chk('fail=1',                 r4["fail"] == 1)
chk('duplicate_skipped=0',    r4["duplicate_skipped"] == 0)
chk('success+fail==tried',    r4["success"] + r4["fail"] == r4["tried"])

# ─── 시나리오 5: SP 파라미터 107개 불일치 ───────────────────────────────────
conn5 = _MockConn()
r5, ev5 = _run_item(conn5, "3333333333", param_ok=False)
print('\n[시나리오5] SP 파라미터 불일치')
chk('dup SELECT 0회',         "dup_select" not in ev5)
chk('SP 호출 0회',            "sp_execute" not in ev5)
chk('rollback 호출',          conn5.rollbacks >= 1)
chk('tried=1',                r5["tried"] == 1)
chk('fail=1',                 r5["fail"] == 1)
chk('duplicate_skipped=0',    r5["duplicate_skipped"] == 0)
chk('success+fail==tried',    r5["success"] + r5["fail"] == r5["tried"])

# ─── 시나리오 6: 빈 CustDocID ───────────────────────────────────────────────
conn6 = _MockConn(dup_hit=True)   # dup_hit이지만 빈값이므로 SELECT 안 해야 함
r6, ev6 = _run_item(conn6, "")
print('\n[시나리오6] 빈 CustDocID')
chk('dup SELECT 0회',         "dup_select" not in ev6)
chk('SP 호출 1회',            "sp_execute" in ev6)
chk('tried=1',                r6["tried"] == 1)
chk('success=1',              r6["success"] == 1)
chk('duplicate_skipped=0',    r6["duplicate_skipped"] == 0)
chk('success+fail==tried',    r6["success"] + r6["fail"] == r6["tried"])

# ─── 공통: 신규 건 중복 SELECT와 SP는 동일 connection 사용 ─────────────────
print('\n[공통] 신규 건 동일 connection 확인')
conn2b = _MockConn(dup_hit=False)
r2b, ev2b = _run_item(conn2b, "8888888888")
chk('dup SELECT → SP → commit 순서',
    ev2b == ["dup_select", "sp_execute", "commit"])

print()
print('ALL PASS' if all_ok else 'SOME FAIL')
