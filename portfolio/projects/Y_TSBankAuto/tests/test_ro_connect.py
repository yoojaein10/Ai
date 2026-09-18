# -*- coding: utf-8 -*-
"""읽기 전용 접속/트랜잭션 테스트 (DB 없이). 지시 §5, §6."""
import unittest

import ro_config as C
import ro_connect as N
import ro_query as Q
import security
from tests import _fakes


def _target(host="dbhost", instance="", port="1433", is_ip=False):
    return C.ServerTarget(host=host, instance=instance, port=port, is_ip=is_ip)


class TestConnString(unittest.TestCase):
    def test_security_defaults(self):
        # 현 환경 확정(§7): Driver 17 + Encrypt=yes + TSC=yes.
        cs = N.build_connection_string(_target(), "db", "user", "pw")
        self.assertIn("DRIVER={ODBC Driver 17 for SQL Server}", cs)
        self.assertIn("Encrypt=yes", cs)
        self.assertIn("TrustServerCertificate=yes", cs)
        self.assertIn("ApplicationIntent=ReadOnly", cs)
        self.assertIn("MARS_Connection=no", cs)
        self.assertIn("LoginTimeout=5", cs)

    def test_encrypt_forced_no_plaintext(self):
        # Encrypt=yes 강제(미암호화 접속 금지)
        cs = N.build_connection_string(_target(), "db", "user", "pw")
        self.assertNotIn("Encrypt=no", cs)
        self.assertNotIn("Encrypt=false", cs)

    def test_password_brace_escaped(self):
        cs = N.build_connection_string(_target(), "db", "user", "a}b")
        self.assertIn("PWD={a}}b}", cs)

    def test_masked_by_security(self):
        cs = N.build_connection_string(_target(), "db", "user", "pw")
        self.assertEqual(security.mask_connection_string(cs), "[BLOCKED connection-string]")

    def test_instance_and_port_assembled(self):
        cs = N.build_connection_string(_target(instance="INST", port="1533"),
                                       "db", "user", "pw")
        self.assertIn("SERVER=dbhost\\INST,1533", cs)

    def test_injection_rejected(self):
        with self.assertRaises(N.InjectionRejected):
            N.build_connection_string(_target(), "d;DROP", "user", "pw")
        with self.assertRaises(N.InjectionRejected):
            N.build_connection_string(_target(), "db", "u=v", "pw")
        with self.assertRaises(N.InjectionRejected):
            N.build_connection_string(_target(host="h\nx"), "db", "user", "pw")

    def test_password_control_char_rejected(self):
        with self.assertRaises(N.InjectionRejected):
            N.build_connection_string(_target(), "db", "user", "p\x00w")


class TestConnectGate(unittest.TestCase):
    def test_connect_blocked_without_switch(self):
        creds = C.Credentials("dbhost", "d", "u", "p")
        al = C.ReadOnlyAllowlist(connect_hosts=("dbhost",),
                                 server_identities=("SRV",), databases=("d",))
        with self.assertRaises(N.ConnectionBlocked):
            N.connect_readonly(creds, al, environ={})


class TestReadonlyTransaction(unittest.TestCase):
    def test_session_setup_and_rollback_close(self):
        conn = _fakes.make_ro_conn()
        with N.readonly_transaction(conn) as c:
            self.assertIs(c, conn)
        self.assertTrue(conn.rolled_back)
        self.assertTrue(conn.closed)
        self.assertFalse(conn.autocommit)

    def test_rollback_close_on_exception(self):
        conn = _fakes.make_ro_conn()
        with self.assertRaises(ValueError):
            with N.readonly_transaction(conn):
                raise ValueError("boom")
        self.assertTrue(conn.rolled_back)
        self.assertTrue(conn.closed)

    def test_stop_check_aborts(self):
        conn = _fakes.make_ro_conn()
        with self.assertRaises(N.ConnectionBlocked):
            with N.readonly_transaction(conn, stop_check=lambda: True):
                pass
        self.assertTrue(conn.rolled_back)
        self.assertTrue(conn.closed)

    def test_never_commits(self):
        conn = _fakes.make_ro_conn()
        with N.readonly_transaction(conn):
            pass
        # FakeRoConnection.commit 은 호출 시 AssertionError → 호출되지 않았음을 보장
        self.assertFalse(getattr(conn, "committed", False))

    def test_session_statements_applied(self):
        conn = _fakes.make_ro_conn()
        recorded = {}
        with N.readonly_transaction(conn) as c:
            cur = c.cursor()
            Q.apply_readonly_session(cur)
            recorded["ops"] = [e[0] for e in cur.executed]
        self.assertEqual(recorded["ops"], list(Q.SESSION_SETUP_STATEMENTS))


if __name__ == "__main__":
    unittest.main()
