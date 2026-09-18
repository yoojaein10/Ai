# -*- coding: utf-8 -*-
"""연결 후 대상/역할/권한 검증 평가 테스트. 지시 §4 사후, §9."""
import unittest

import ro_config as C
import ro_guards as G


def _al():
    return C.ReadOnlyAllowlist(
        connect_hosts=("h",), server_identities=("SRV01\\INST",), databases=("appdb",))


# VERIFY_TARGET: db_name, server_name, instance, login, db_user, orig_login
def _target_row(db="appdb", srv="SRV01\\INST"):
    return (db, srv, "INST", "login", "user", "login")


# VERIFY_ROLES: sysadmin, db_owner, db_datawriter, db_ddladmin, db_securityadmin, db_datareader
def _roles_row(*flags):
    return flags if flags else (0, 0, 0, 0, 0, 1)


# VERIFY_PERMISSIONS order (11): srv_control, srv_alter_login, db_insert, db_update,
# db_delete, db_execute, db_alter, db_control, db_take_ownership, db_view_def, db_select
def _perms_row(writes=0, view_def=1, select=1):
    return (writes, writes, writes, writes, writes, writes, writes, writes, writes,
            view_def, select)


class TestTarget(unittest.TestCase):
    def test_ok(self):
        ok, r = G.evaluate_target(_target_row(), _al())
        self.assertTrue(ok, r)

    def test_server_mismatch(self):
        ok, r = G.evaluate_target(_target_row(srv="OTHER"), _al())
        self.assertFalse(ok)
        self.assertTrue(any("서버" in x for x in r))

    def test_db_mismatch(self):
        ok, r = G.evaluate_target(_target_row(db="master"), _al())
        self.assertFalse(ok)

    def test_none_row(self):
        ok, r = G.evaluate_target(None, _al())
        self.assertFalse(ok)

    def test_no_raw_values_in_reasons(self):
        ok, r = G.evaluate_target(_target_row(srv="SECRETSRV"), _al())
        self.assertFalse(ok)
        self.assertFalse(any("SECRETSRV" in x for x in r))


class TestRoles(unittest.TestCase):
    def test_readonly_ok(self):
        ok, r = G.evaluate_roles(_roles_row())
        self.assertTrue(ok, r)

    def test_excessive_blocked(self):
        for i, name in enumerate(("sysadmin", "db_owner", "db_datawriter",
                                  "db_ddladmin", "db_securityadmin")):
            flags = [0, 0, 0, 0, 0, 1]
            flags[i] = 1
            ok, r = G.evaluate_roles(tuple(flags))
            self.assertFalse(ok, name)

    def test_null_undetermined_blocked(self):
        ok, r = G.evaluate_roles((None, 0, 0, 0, 0, 1))
        self.assertFalse(ok)
        self.assertTrue(any("확인 불가" in x for x in r))

    def test_wrong_type_blocked(self):
        ok, r = G.evaluate_roles(("yes", 0, 0, 0, 0, 1))
        self.assertFalse(ok)


class TestPermissions(unittest.TestCase):
    def test_readonly_ok(self):
        ok, r = G.evaluate_permissions(_perms_row())
        self.assertTrue(ok, r)

    def test_write_perm_blocked(self):
        ok, r = G.evaluate_permissions(_perms_row(writes=1))
        self.assertFalse(ok)
        self.assertTrue(any("쓰기/상승" in x for x in r))

    def test_null_blocked(self):
        row = list(_perms_row())
        row[2] = None  # db_insert NULL
        ok, r = G.evaluate_permissions(tuple(row))
        self.assertFalse(ok)

    def test_missing_read_perm_blocked(self):
        ok, r = G.evaluate_permissions(_perms_row(view_def=0))
        self.assertFalse(ok)
        self.assertTrue(any("읽기 권한 부족" in x for x in r))


class TestGate(unittest.TestCase):
    def test_all_ok(self):
        res = G.evaluate_gate(_target_row(), _roles_row(), _perms_row(), _al())
        self.assertTrue(res["gate_open"])

    def test_any_fail_closes_gate(self):
        res = G.evaluate_gate(_target_row(), _roles_row(1, 0, 0, 0, 0, 1),
                              _perms_row(), _al())
        self.assertFalse(res["gate_open"])
        self.assertTrue(res["reasons"])


if __name__ == "__main__":
    unittest.main()
