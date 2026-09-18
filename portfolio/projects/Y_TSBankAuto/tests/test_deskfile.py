# -*- coding: utf-8 -*-
import datetime
import os
import tempfile
import unittest

import config
import deskfile as D
import sp_spec


class FakeCursor:
    def __init__(self, conn, existing_rows):
        self.conn = conn
        self._existing = existing_rows
        self._rows = []

    def execute(self, sql, params=None):
        if isinstance(params, (str, bytes)):
            params = [params]
        params = list(params or [])
        assert sql.count("?") == len(params), "placeholder/param mismatch"
        self.conn.executed.append((sql, params))
        if "@@SERVERNAME" in sql:
            self._rows = [("TEST-SRV", "TEST-DB")]
        elif "sys.parameters" in sql:
            names = sp_spec.INPUT_PARAM_NAMES + [p.name for p in sp_spec.OUTPUT_PARAM_SPECS]
            self._rows = [("@" + n,) for n in names]
        elif sql == D.SQL_SELECT_ROW:
            self._rows = list(self._existing)
        else:
            if self.conn.fail_sp:
                raise RuntimeError("SP_FAIL")
            self._rows = []
        return self

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def nextset(self):
        return False


class FakeConn:
    def __init__(self, existing_rows=(), fail_sp=False):
        self.executed = []
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self._existing = existing_rows
        self.fail_sp = fail_sp

    def cursor(self):
        return FakeCursor(self, self._existing)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def app_cfg():
    app = config.AppConfig()
    app.db = config.DbConfig(enabled=True, server="TEST-SRV", database="TEST-DB",
                             username='REDACTED_CONFIGURE_LOCALLY', password='REDACTED_CONFIGURE_LOCALLY',
                             lookup_server="LOOKUP-SRV")
    return app


class TestDeskFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "DESK")
        os.makedirs(self.root)
        self.pdf = os.path.join(self.tmp.name, "src.pdf")
        with open(self.pdf, "wb") as f:
            f.write(b"%PDF-1.4 synthetic")
        self.now = datetime.datetime(2026, 9, 9, 10, 0, 0)

    def tearDown(self):
        self.tmp.cleanup()

    def _connector(self, conn):
        def connector(cs, **kw):
            return conn
        return connector

    def test_insert_when_no_row(self):
        conn = FakeConn()
        out = {"NewMasterID": "01-20260909-039", "RegCharge": 1729}
        status, code = D.register(out, self.pdf, app_cfg(), connector=self._connector(conn),
                                  root=self.root, now=self.now)
        self.assertEqual((status, code), ("Y", ""))
        dst = os.path.join(self.root, "01-20260909-039-1.pdf")
        self.assertTrue(os.path.isfile(dst))
        sql, params = conn.executed[-1]
        self.assertEqual(sql, D.SQL_INSERT)
        self.assertEqual(params, ["01-20260909-039", os.path.abspath(dst), self.now, "김유진", 1])
        self.assertTrue(conn.committed)
        self.assertTrue(conn.closed)

    def test_update_when_row_exists_without_file1(self):
        conn = FakeConn(existing_rows=[(None,)])
        out = {"NewMasterID": "01-20260909-040", "RegCharge": 899}
        status, _ = D.register(out, self.pdf, app_cfg(), connector=self._connector(conn),
                               root=self.root, now=self.now)
        self.assertEqual(status, "Y")
        sql, params = conn.executed[-1]
        self.assertEqual(sql, D.SQL_UPDATE)
        self.assertEqual(params[3], "양혜지")

    def test_skip_when_row_has_file1(self):
        conn = FakeConn(existing_rows=[(r"\\server\data1\DESK\x-1.jpg",)])
        out = {"NewMasterID": "01-20260909-041", "RegCharge": 899}
        status, code = D.register(out, self.pdf, app_cfg(), connector=self._connector(conn),
                                  root=self.root, now=self.now)
        self.assertEqual((status, code), ("S", "DESK_ROW_HAS_FILE1"))
        self.assertFalse(os.path.exists(os.path.join(self.root, "01-20260909-041-1.pdf")))
        self.assertFalse(conn.committed)
        self.assertFalse(any(sql in (D.SQL_INSERT, D.SQL_UPDATE) for sql, _ in conn.executed))

    def test_skip_when_file_exists_no_suffix_no_db(self):
        dst = os.path.join(self.root, "01-20260909-042-1.pdf")
        with open(dst, "wb") as f:
            f.write(b"old")
        conn = FakeConn()
        out = {"NewMasterID": "01-20260909-042"}
        status, code = D.register(out, self.pdf, app_cfg(), connector=self._connector(conn),
                                  root=self.root, now=self.now)
        self.assertEqual((status, code), ("S", "DESK_FILE_EXISTS"))
        self.assertEqual(conn.executed, [])
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), b"old")
        self.assertEqual(os.listdir(self.root), ["01-20260909-042-1.pdf"])

    def test_sp_failure_removes_copied_file(self):
        conn = FakeConn(fail_sp=True)
        out = {"NewMasterID": "01-20260909-043", "RegCharge": 1729}
        status, code = D.register(out, self.pdf, app_cfg(), connector=self._connector(conn),
                                  root=self.root, now=self.now)
        self.assertEqual(status, "N")
        self.assertEqual(code, "RuntimeError")
        self.assertFalse(os.path.exists(os.path.join(self.root, "01-20260909-043-1.pdf")))
        self.assertTrue(conn.rolled_back)
        self.assertFalse(conn.committed)

    def test_invalid_master_id_skips_without_touching_anything(self):
        conn = FakeConn()
        for bad in ("", "SYNTH-ID", "../01-20260909-001", "01-20260909-001-1"):
            status, code = D.register({"NewMasterID": bad}, self.pdf, app_cfg(),
                                      connector=self._connector(conn), root=self.root)
            self.assertEqual((status, code), ("S", "DOCID_INVALID"), bad)
        self.assertEqual(conn.executed, [])
        self.assertEqual(os.listdir(self.root), [])

    def test_db_target_mismatch_removes_file(self):
        conn = FakeConn()
        app = app_cfg()
        app.db.database = "OTHER-DB"
        out = {"NewMasterID": "01-20260909-044"}
        status, code = D.register(out, self.pdf, app, connector=self._connector(conn),
                                  root=self.root, now=self.now)
        self.assertEqual((status, code), ("N", "DB_TARGET_MISMATCH"))
        self.assertEqual(os.listdir(self.root), [])

    def test_upman_mapping_and_alternation(self):
        self.assertEqual(D.upman_for({"RegCharge": 899}), "양혜지")
        self.assertEqual(D.upman_for({"RegCharge": "1729"}), "김유진")
        a = D.upman_for({"RegCharge": None})
        b = D.upman_for({})
        self.assertEqual({a, b}, {"양혜지", "김유진"})

    def test_dest_path_is_fixed_under_root(self):
        p = D.dest_path("01-20260909-045", self.root)
        self.assertEqual(os.path.basename(p), "01-20260909-045-1.pdf")
        self.assertEqual(os.path.dirname(p), os.path.abspath(self.root))
        with self.assertRaises(D.DeskFileError):
            D.dest_path("..\\evil", self.root)


if __name__ == "__main__":
    unittest.main()
