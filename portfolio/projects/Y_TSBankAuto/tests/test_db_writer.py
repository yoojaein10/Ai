# -*- coding: utf-8 -*-
"""SP 래퍼/파라미터/가드 테스트 (fake DB)."""
import os
import unittest

import address_mapper
import config
import parsers
import pipeline
import ts_db_writer as W
from tests import _fakes

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f]


def _params_for(fixture):
    pr = pipeline.prepare(_load(fixture))
    assert pr.eligible, pr.reasons
    return pr.params, pr.model


class TestParamAssembly(unittest.TestCase):
    def test_keys_and_order(self):
        params, _ = _params_for("woori_synth.txt")
        self.assertEqual(list(params.keys()), W.INPUT_PARAM_NAMES)
        self.assertEqual(len(W.params_in_order(params)), len(W.EXEC_BIND_PARAM_NAMES))

    def test_fixed_values(self):
        params, _ = _params_for("woori_synth.txt")
        self.assertIsNone(params["MasterID"])
        self.assertEqual(params["Office"], "10")
        self.assertEqual(params["AppCode"], "300611")
        self.assertEqual(params["Jun_Master"], 0)
        self.assertEqual(params["Score"], 1)

    def test_hfdocid_is_woori_only(self):
        for fn in ("woori_synth.txt", "kookmin_synth.txt", "saemaeul_synth.txt",
                   "ibk_synth.txt", "nonghyup_synth.txt", "suhyup_synth.txt"):
            params, model = _params_for(fn)
            expected = model.request_no if model.bank == "우리은행" else None
            self.assertEqual(params["HFDocid"], expected, fn)

    def test_internal_fields_null(self):
        params, _ = _params_for("woori_synth.txt")
        for k in ("DongHo", "CustID", "Reg_Charge", "Consult_Charge", "Manager",
                  "Guid", "Category", "Pyoung", "DocID",
                  "AdjPrice", "MinPrice", "MaxPrice",
                  "HFOwnername", "HFOwnerPhone", "HFOwnerTel", "HFWorkYN", "HFGubun"):
            self.assertIsNone(params[k], k)
        self.assertEqual(params["CustFAX"], "온")

    def test_pii_not_in_params(self):
        params, model = _params_for("woori_synth.txt")
        # debtor/owner/owner_phone 값이 어떤 파라미터에도 들어가면 안 됨
        pii = {model.debtor, model.owner, model.owner_phone} - {""}
        for v in params.values():
            if isinstance(v, str):
                for p in pii:
                    self.assertNotIn(p, v)

    def test_reg_eub_null_this_round(self):
        params, _ = _params_for("woori_synth.txt")
        self.assertIsNone(params["Reg"])
        self.assertIsNone(params["Eub"])

    def test_reg_datetime_uses_db_getdate(self):
        params, _ = _params_for("woori_synth.txt")
        self.assertIsNone(params["Reg_DateTime"])
        self.assertIn("GETDATE()", W.build_wrapper_sql())


class TestWrapperSql(unittest.TestCase):
    def test_placeholder_count(self):
        sql = W.build_wrapper_sql()
        self.assertEqual(W.count_placeholders(sql), len(W.EXEC_BIND_PARAM_NAMES))

    def test_output_clause(self):
        sql = W.build_wrapper_sql()
        self.assertIn("@NewMasterID=@OutMasterID OUTPUT", sql)
        self.assertIn("@NewSEQ=@OutSEQ OUTPUT", sql)
        self.assertIn("@OutMasterID AS NewMasterID", sql)
        self.assertIn("@OutSEQ AS NewSEQ", sql)
        self.assertIn(W.SP_NAME, sql)

    def test_no_data_inserted_in_sql(self):
        # 데이터값이 SQL 문자열에 직접 들어가지 않는다(전부 ?)
        sql = W.build_wrapper_sql()
        self.assertNotIn("300611", sql)
        self.assertNotIn("샘플", sql)


class TestExecuteFakeDb(unittest.TestCase):
    def test_output_received_and_drained(self):
        params, _ = _params_for("woori_synth.txt")
        conn = _fakes.make_sp_output_conn("01-20260101-777", 42, with_noise=True)
        res = W.execute_sp(conn, params, rollback_test=True)
        self.assertEqual(res["output"]["NewMasterID"], "01-20260101-777")
        self.assertEqual(res["output"]["NewSEQ"], 42)
        self.assertTrue(conn.rolled_back)
        self.assertFalse(conn.committed)
        self.assertEqual(res["placeholder_count"], len(W.EXEC_BIND_PARAM_NAMES))

    def test_placeholder_param_count_match(self):
        params, _ = _params_for("kookmin_synth.txt")
        conn = _fakes.make_sp_output_conn()
        # FakeCursor.execute 가 placeholder != params 면 AssertionError
        W.execute_sp(conn, params)
        sql, sent = conn.cursor().executed[0] if False else (None, None)  # noqa
        # 직접 검증
        self.assertEqual(W.count_placeholders(W.build_wrapper_sql()),
                         len(W.params_in_order(params)))

    def test_output_found_after_noise(self):
        conn = _fakes.make_sp_output_conn("X", 1, with_noise=True)
        cur = conn.cursor()
        cur.execute(W.build_wrapper_sql(), W.params_in_order(_params_for("ibk_synth.txt")[0]))
        out = W.fetch_output_and_drain(cur)
        self.assertEqual(out["NewMasterID"], "X")


class TestCommitGuards(unittest.TestCase):
    def _full_ctx(self, **over):
        base = dict(
            rollback_test=False,
            env_allow_commit=True,
            gui_phrase=W.GUI_COMMIT_PHRASE,
            server="SRV", database="DB",
            allowlist=config.Allowlist(servers=("SRV",), databases=("DB",)),
            target_count=3, target_count_confirmed=True,
            dup_check_passed=True, audit_log_pii_free=True,
            metadata_verified=True,
        )
        base.update(over)
        return W.CommitContext(**base)

    def test_metadata_source_allows_full_guard(self):
        ok, fails = W.check_commit_guards(self._full_ctx())
        self.assertTrue(ok)
        self.assertEqual(fails, [])

    def test_single_flag_insufficient(self):
        # env 만 통과시키고 나머지는 기본(불충족)
        ctx = self._full_ctx(rollback_test=True, gui_phrase="", target_count=0,
                             target_count_confirmed=False, dup_check_passed=False,
                             audit_log_pii_free=False, metadata_verified=False,
                             allowlist=config.Allowlist())
        ok, fails = W.check_commit_guards(ctx)
        self.assertFalse(ok)
        self.assertGreater(len(fails), 1)

    def test_commit_with_guards_commits_when_all_pass(self):
        params, _ = _params_for("woori_synth.txt")
        conn = _fakes.make_sp_output_conn()
        result = W.commit_with_guards(conn, params, self._full_ctx())
        self.assertTrue(result["committed"])
        self.assertTrue(conn.committed)

    def test_allowlist_mismatch(self):
        ctx = self._full_ctx(server="EVIL")
        ok, fails = W.check_commit_guards(ctx)
        self.assertFalse(ok)
        self.assertTrue(any("allowlist" in f for f in fails))


class TestConnString(unittest.TestCase):
    def test_security_defaults_and_masking(self):
        db = config.DbConfig(server="h", port="1433", database="d",
                             driver="ODBC Driver 18 for SQL Server",
                             encrypt="yes", trust_server_certificate="false")
        cs = W.build_connection_string(db, "user", "pass")
        self.assertIn("Encrypt=yes", cs)
        self.assertIn("TrustServerCertificate=no", cs)
        import security
        self.assertEqual(security.mask_connection_string(cs), "[BLOCKED connection-string]")


if __name__ == "__main__":
    unittest.main()
