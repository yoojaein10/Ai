# -*- coding: utf-8 -*-
"""오케스트레이터 전체 흐름 테스트 (fake). 지시 §10, §12."""
import inspect
import os
import shutil
import tempfile
import unittest

import bank24_adapter as A
from tests._fakes import FakeBank24Adapter
import bank24_automation as b24
import config
import orchestrator as O
import ro_config as C
import ro_lookups
import ts_db_writer as W
from tests import _fakes


def _scripted(*, target_srv="SRV01\\INST", write_perm=0,
              customer_rows=None, reghist_rows=None):
    meta = []
    pid = 0
    for s in W.INPUT_PARAM_SPECS:
        pid += 1
        meta.append((pid, "@" + s.name, 0, "varchar", 0, "varchar", 40, 0, 0))
    for s in W.OUTPUT_PARAM_SPECS:
        pid += 1
        meta.append((pid, "@" + s.name, 1, "int", 0, "int", 4, 10, 0))
    perms = (write_perm,) * 9 + (1, 1)   # 9 write perms, view_def, select
    return {
        "VERIFY_TARGET": [("appdb", target_srv, "INST", "lg", "usr", "lg")],
        "VERIFY_ROLES": [(0, 0, 0, 0, 0, 1)],
        "VERIFY_PERMISSIONS": [perms],
        "READ_SP_METADATA": meta,
        "LOOKUP_CUSTOMER": customer_rows if customer_rows is not None
        else [("C001", "우리은행 강남지점", "Y")],
        "LOOKUP_REGHIST": reghist_rows if reghist_rows is not None
        else [("R100", "E1", "리", "서울특별시", "강남구", "역삼동", "")],
    }


def _allowlist():
    return C.ReadOnlyAllowlist(connect_hosts=("h",),
                               server_identities=("SRV01\\INST",),
                               databases=("appdb",))


def _fake_parse(eligible=True, status="parsed"):
    def stage(path, roots, *, need_raw_keys):
        raw = {"bank": "우리은행", "branch": "강남",
               "admin_addr": "서울특별시 강남구"} if need_raw_keys else None
        return O.ParseOutcome(status, eligible,
                              {"status": status, "bank": "우리은행", "eligible": eligible,
                               "unit_count": 1, "multi_unit": False},
                              _raw_keys=raw)
    return stage


def _run(scripted=None, capture=None, **over):
    ad = FakeBank24Adapter()
    conn = _fakes.make_ro_conn(scripted if scripted is not None else _scripted())
    if capture is not None:
        capture["conn"] = conn
    root = tempfile.mkdtemp()
    try:
        kw = dict(adapter=ad, request_token="REQ-1", pdf_root=root, timestamp="20260701",
                  allowed_roots=[root], db_provider=lambda: conn, allowlist=_allowlist(),
                  parse_stage=_fake_parse())
        kw.update(over)
        return O.run(**kw)
    finally:
        shutil.rmtree(root, ignore_errors=True)


class TestFullFlow(unittest.TestCase):
    def test_order_and_statuses(self):
        rep = _run()
        step_names = [s[0] for s in rep.steps]
        # Bank24 → parse → DB 순서
        self.assertLess(step_names.index("download_pdf"), step_names.index("parse"))
        self.assertLess(step_names.index("parse"), step_names.index("db_post_verify"))
        self.assertEqual(rep.customer_status, ro_lookups.SINGLE)
        self.assertEqual(rep.reghist_status, ro_lookups.SINGLE)
        self.assertEqual(rep.duplicate_status, "undecidable")
        self.assertEqual(rep.metadata_status, "provisional")

    def test_never_commit_or_exec(self):
        rep = _run()
        self.assertFalse(rep.committed)
        self.assertFalse(rep.executed_sp)

    def test_rollback_close_all_paths(self):
        cap = {}
        _run(capture=cap)
        self.assertTrue(cap["conn"].rolled_back)
        self.assertTrue(cap["conn"].closed)


class TestFailClosed(unittest.TestCase):
    def test_step_failure_stops_chain(self):
        class BadAdapter(FakeBank24Adapter):
            def query_requests(self):
                raise b24.AutomationBlocked("boom")
        rep = O.run(adapter=BadAdapter(), request_token="REQ-1", pdf_root=".",
                    timestamp="t", allowed_roots=["."],
                    db_provider=lambda: _fakes.make_ro_conn(_scripted()),
                    allowlist=_allowlist(), parse_stage=_fake_parse())
        names = [s[0] for s in rep.steps]
        self.assertIn("bank24", names)
        self.assertNotIn("parse", names)
        self.assertNotIn("db_post_verify", names)

    def test_parse_fail_no_db_connect(self):
        db_called = {"n": 0}

        def provider():
            db_called["n"] += 1
            return _fakes.make_ro_conn(_scripted())
        rep = _run(db_provider=provider, parse_stage=_fake_parse(eligible=False,
                                                                status="ineligible"))
        self.assertFalse(rep.db_connected)
        self.assertEqual(db_called["n"], 0)   # 파싱 실패 시 DB 연결 미시도

    def test_no_db_during_parse(self):
        order = []

        def provider():
            order.append("db")
            return _fakes.make_ro_conn(_scripted())

        def stage(path, roots, *, need_raw_keys):
            self.assertNotIn("db", order)   # 파싱 시점에 DB 미연결
            order.append("parse")
            return _fake_parse()(path, roots, need_raw_keys=need_raw_keys)
        _run(db_provider=provider, parse_stage=stage)
        self.assertLess(order.index("parse"), order.index("db"))

    def test_gate_fail_skips_lookups(self):
        rep = _run(scripted=_scripted(write_perm=1))   # 쓰기 권한 → gate 닫힘
        self.assertIsNone(rep.customer_status)          # 조회 미실행
        self.assertEqual(rep.failed_step, "db_post_verify")

    def test_two_stage_no_db(self):
        ad = FakeBank24Adapter()
        root = tempfile.mkdtemp()
        try:
            rep = O.run(adapter=ad, request_token="REQ-1", pdf_root=root, timestamp="t",
                        allowed_roots=[root], parse_stage=_fake_parse())
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertFalse(rep.db_connected)
        names = [s[0] for s in rep.steps]
        self.assertIn("db_stage", names)


class TestSaveBlocked(unittest.TestCase):
    def test_save_stub_always_blocks(self):
        with self.assertRaises(O.SaveBlocked):
            O.save_to_db_stub({"any": "params"})


class TestNoWriteModule(unittest.TestCase):
    def test_orchestrator_no_write_imports(self):
        src = inspect.getsource(O)
        self.assertNotIn("import ts_db_writer", src)
        self.assertNotIn("execute_sp(", src)
        self.assertNotIn("commit_with_guards(", src)
        self.assertNotIn(".commit(", src)


if __name__ == "__main__":
    unittest.main()
