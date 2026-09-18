# -*- coding: utf-8 -*-
"""테스트용 fake DB/UI 및 호출 가드 (S18).

- FakeCursor/FakeConnection: 실제 pyodbc 없이 SP 래퍼 placeholder/OUTPUT 검증.
- install_isolation_guards(): 실제 pyodbc.connect/네트워크 호출 시 테스트 실패.
"""
from __future__ import annotations


class FakeCursor:
    """스크립트된 결과셋을 제공하는 fake 커서.

    result_sets: [{"description": [(name,...)] | None, "rows": [tuple,...]}]
    """

    def __init__(self, conn, result_sets):
        self.conn = conn
        self._sets = list(result_sets)
        self._idx = 0
        self._row_i = 0
        self.executed = []        # [(sql, params)]
        self.description = self._sets[0]["description"] if self._sets else None

    def execute(self, sql, params=None):
        params = list(params or [])
        nq = sql.count("?")
        assert nq == len(params), f"placeholder({nq}) != params({len(params)})"
        self.conn.execute_count += 1
        # 데이터 값이 SQL 에 삽입되지 않았는지(바인딩 전용) 검증
        assert "EXEC" in sql or "SELECT" in sql
        self.executed.append((sql, params))
        self._idx = 0
        self._row_i = 0
        self.description = self._sets[0]["description"] if self._sets else None
        return self

    def _cur(self):
        return self._sets[self._idx] if self._idx < len(self._sets) else None

    def fetchone(self):
        cur = self._cur()
        if not cur:
            return None
        rows = cur["rows"]
        if self._row_i < len(rows):
            r = rows[self._row_i]
            self._row_i += 1
            return r
        return None

    def fetchall(self):
        cur = self._cur()
        if not cur:
            return []
        rows = cur["rows"][self._row_i:]
        self._row_i = len(cur["rows"])
        return rows

    def nextset(self):
        if self._idx + 1 < len(self._sets):
            self._idx += 1
            self._row_i = 0
            self.description = self._sets[self._idx]["description"]
            return True
        return False


class FakeConnection:
    def __init__(self, result_sets):
        self._sets = result_sets
        self.execute_count = 0
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return FakeCursor(self, self._sets)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def make_sp_output_conn(new_master_id="01-20260629-999", new_seq=12345,
                        with_noise=True):
    """SP 호출을 모사하는 fake 연결.

    SP 본문(설명 없는 셋) → (선택) 잡음 셋 → OUTPUT SELECT 셋 순으로 nextset.
    """
    sets = [{"description": None, "rows": []}]
    if with_noise:
        sets.append({"description": [("other",)], "rows": [("x",)]})
    sets.append({
        "description": [("NewMasterID",), ("NewSEQ",)],
        "rows": [(new_master_id, new_seq)],
    })
    return FakeConnection(sets)


class FakeRoCursor:
    """읽기 전용 고정 쿼리 전용 fake 커서.

    등록된 SELECT 또는 세션 SET 문만 허용한다. 미등록/미허용 SQL 을 받으면
    AssertionError 로 실패한다(지시 §8: fake cursor 도 미등록 SQL 거부).
    scripted: {op_id: [row tuple, ...]}
    """

    def __init__(self, conn):
        import ro_query
        self.conn = conn
        self.executed = []          # [(op_or_set, param_count)]
        self._rows = []
        self._i = 0
        self._sql_to_op = {q.sql: op for op, q in _ro_registry_items()}
        self._set_stmts = set(ro_query.SESSION_SETUP_STATEMENTS)

    def execute(self, sql, params=()):
        params = list(params or [])
        if sql in self._set_stmts:
            assert len(params) == 0, "SET 문에 바인딩 금지"
            self.executed.append((sql, 0))
            self._rows = []
            self._i = 0
            return self
        op = self._sql_to_op.get(sql)
        assert op is not None, "미등록/미허용 SQL 실행 시도"
        assert sql.count("?") == len(params), "placeholder != params"
        self.executed.append((op, len(params)))
        self._rows = list(self.conn.scripted.get(op, []))
        self._i = 0
        return self

    def fetchmany(self, n):
        rows = self._rows[self._i:self._i + n]
        self._i += len(rows)
        return rows

    def fetchall(self):
        rows = self._rows[self._i:]
        self._i = len(self._rows)
        return rows

    def fetchone(self):
        if self._i < len(self._rows):
            r = self._rows[self._i]
            self._i += 1
            return r
        return None


class FakeRoConnection:
    """읽기 전용 fake 연결. rollback/close 만 기록. commit 은 호출 시 실패."""

    def __init__(self, scripted=None):
        self.scripted = dict(scripted or {})
        self.autocommit = False
        self.timeout = None
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return FakeRoCursor(self)

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True

    def commit(self):
        raise AssertionError("읽기 전용 경로에서 COMMIT 금지")


def _ro_registry_items():
    import ro_query
    return list(ro_query._REGISTRY.items())


def make_ro_conn(scripted=None):
    """op_id→rows 스크립트로 읽기 전용 fake 연결 생성."""
    return FakeRoConnection(scripted)


class FakeBank24Adapter:
    """테스트 전용 fake Bank24 adapter(제품 런타임에는 없음, §4/§57).

    실제 Bank24/네트워크 접근 없이 orchestrator·pdf 흐름을 합성 데이터로 시험한다.
    """

    is_fake = True

    def __init__(self, *, scripted_requests=None, pdf_bytes=None):
        import bank24_adapter
        self._requests = scripted_requests or [
            bank24_adapter.RequestSummary(
                request_token="REQ-1", bank_label="우리은행",
                branch_label="강남", masked_request_no="12****89"),
        ]
        self._pdf_bytes = pdf_bytes or (
            b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
        self.logged_in = False
        self.on_tabletop = False

    def launch_or_attach(self):
        return {"attached": True, "fake": True}

    def verify_login_screen(self):
        return {"login_screen": True, "fake": True}

    def login(self, credential_provider=None):
        self.logged_in = True
        return {"logged_in": True, "fake": True}

    def adopt_login_confirmed(self, main_win=None):
        # bank24_login_flow 가 확인한 메인 창을 채택(로그인 완료로 표시).
        self.logged_in = True
        return {"logged_in": True, "adopted": True}

    def select_tabletop_menu(self):
        import bank24_automation as b24
        if not self.logged_in:
            raise b24.AutomationBlocked("로그인 전 탁상 메뉴 선택 불가")
        self.on_tabletop = True
        return {"menu": "탁상", "fake": True}

    def query_requests(self) -> list:
        import bank24_automation as b24
        if not self.on_tabletop:
            raise b24.AutomationBlocked("탁상 메뉴 미선택 상태에서 조회 불가")
        return list(self._requests)

    def download_pdf(self, request_token: str, pdf_root: str, *, timestamp: str) -> str:
        import bank24_automation as b24
        import pdf_download
        if not any(r.request_token == request_token for r in self._requests):
            raise b24.AutomationBlocked("알 수 없는 의뢰 토큰")
        return pdf_download.save_pdf_bytes(self._pdf_bytes, pdf_root, timestamp=timestamp)


def install_isolation_guards():
    """실제 외부 호출을 차단(S18). 호출 시 AssertionError → 테스트 실패."""
    import urllib.request

    def _block_net(*a, **k):
        raise AssertionError("테스트 중 네트워크 호출 금지")

    urllib.request.urlopen = _block_net  # type: ignore

    try:
        import pyodbc

        def _block_connect(*a, **k):
            raise AssertionError("테스트 중 실제 pyodbc.connect 금지")

        pyodbc.connect = _block_connect  # type: ignore
    except Exception:
        pass

    try:
        import requests  # 설치돼 있으면 차단

        def _block_req(*a, **k):
            raise AssertionError("테스트 중 requests 호출 금지")

        for name in ("get", "post", "put", "delete", "request"):
            setattr(requests, name, _block_req)
    except Exception:
        pass

    # 실제 Bank24 실행 차단(§61): Bank24.exe 를 자식 프로세스로 띄우지 않는다.
    try:
        import subprocess
        _orig_popen = subprocess.Popen

        class _GuardedPopen(_orig_popen):
            def __init__(self, args, *a, **k):
                argv0 = args[0] if isinstance(args, (list, tuple)) and args else args
                if "bank24.exe" in str(argv0 or "").lower():
                    raise AssertionError("테스트 중 Bank24.exe 실행 금지")
                super().__init__(args, *a, **k)

        subprocess.Popen = _GuardedPopen
    except Exception:
        pass
