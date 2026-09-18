# -*- coding: utf-8 -*-
import unittest

import config
import tabletop_save as S


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn; self.description = None; self._rows = []
    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        if "@@SERVERNAME" in sql:
            self._rows = [("TEST-SRV", "TEST-DB")]
        elif "sys.parameters" in sql:
            names = S.sp_spec.INPUT_PARAM_NAMES + [p.name for p in S.sp_spec.OUTPUT_PARAM_SPECS]
            self._rows = [("@" + n,) for n in names]
        else:
            self.description = [("NewMasterID",), ("NewSEQ",)]
            self._rows = [("SYNTH-ID", 1)]
        return self
    def fetchone(self): return self._rows.pop(0) if self._rows else None
    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows
    def nextset(self): return False


class FakeConn:
    def __init__(self):
        self.executed = []; self.committed = False; self.rolled_back = False; self.closed = False
    def cursor(self): return FakeCursor(self)
    def commit(self): self.committed = True
    def rollback(self): self.rolled_back = True
    def close(self): self.closed = True


def app_cfg():
    app = config.AppConfig()
    app.db = config.DbConfig(enabled=True, server="TEST-SRV", database="TEST-DB",
                             username='REDACTED_CONFIGURE_LOCALLY', password='REDACTED_CONFIGURE_LOCALLY',
                             lookup_server="LOOKUP-SRV")
    return app


class TestTabletopSave(unittest.TestCase):
    def test_nonghyup_reg_lookup_falls_back_to_address2_and_rewrites_addr_fields(self):
        class Item:
            params = {name: None for name in S.sp_spec.INPUT_PARAM_NAMES}
            custname = "\ub18d\ud611\uc740\ud589 \uc0d8\ud50c\uc9c0\uc810"
            class structured:
                admin_addr = "ADDR1"
            class model:
                bank = "\ub18d\ud611\uc740\ud589"
                branch = "\uc0d8\ud50c\uc9c0\uc810"
                remarks = ""
                addresses = ["A1"]
                fallback_addresses = ["A2"]
                extra_units = []
                request_no = "SYNTH"

        class Fallback:
            san = "1"
            admin_addr = "ADDR2"
            bun1 = "0565"
            bun2 = "0000"
            building = "\ubbf8\uc0ac\uac15\ubcc0\uc544\ub780\ud2f0\uc6c0 2505\ub3d9 2103\ud638"
            building_nm = "\ubbf8\uc0ac\uac15\ubcc0\uc544\ub780\ud2f0\uc6c0"
            dong = "2505"
            ho = "2103"
            addr_etc = ""

        old_reg = S._lookup_reg_eub_ybankauto
        old_struct = S.address_mapper.structure_address
        old_customer = S.ro_lookups.lookup_customer
        old_exact = S.ro_lookups.lookup_customer_exact
        try:
            S._lookup_reg_eub_ybankauto = (
                lambda _cur, admin: {"Reg": "41450", "Eub": "11000"}
                if admin == "ADDR2" else None
            )
            S.address_mapper.structure_address = lambda raw: Fallback()
            class Result:
                _raw_selected = {"CustID": "008753"}
                status = S.ro_lookups.SINGLE
            S.ro_lookups.lookup_customer_exact = lambda *_: Result()
            S.ro_lookups.lookup_customer = lambda *_: Result()
            params = S._enrich_from_db(object(), Item())
        finally:
            S._lookup_reg_eub_ybankauto = old_reg
            S.address_mapper.structure_address = old_struct
            S.ro_lookups.lookup_customer_exact = old_exact
            S.ro_lookups.lookup_customer = old_customer

        self.assertEqual(params["Reg"], "41450")
        self.assertEqual(params["Eub"], "11000")
        self.assertEqual(params["Addr"], "ADDR2")
        self.assertEqual(params["BUN1"], "0565")
        self.assertEqual(params["Building_Nm"], "\ubbf8\uc0ac\uac15\ubcc0\uc544\ub780\ud2f0\uc6c0")

    def test_missing_customer_is_saved_as_null(self):
        class Item:
            params = {name: None for name in S.sp_spec.INPUT_PARAM_NAMES}
            custname = "샘플새마을금고 지점"
            class structured:
                admin_addr = "서울특별시 샘플구 샘플동"
            class model:
                bank = "새마을금고"
                branch = "샘플 지점"
                remarks = ""
                addresses = []
                extra_units = []
                request_no = "SYNTH"

        old_reg = S._lookup_reg_eub_ybankauto
        old_customer = S.ro_lookups.lookup_customer
        old_exact = S.ro_lookups.lookup_customer_exact
        try:
            S._lookup_reg_eub_ybankauto = lambda *_: {"Reg": "R", "Eub": "E"}
            missing = S.ro_lookups.LookupResult(S.ro_lookups.NO_RESULT, 0)
            S.ro_lookups.lookup_customer_exact = lambda *_: missing
            S.ro_lookups.lookup_customer = lambda *_: missing
            params = S._enrich_from_db(object(), Item())
        finally:
            S._lookup_reg_eub_ybankauto = old_reg
            S.ro_lookups.lookup_customer_exact = old_exact
            S.ro_lookups.lookup_customer = old_customer
        self.assertIsNone(params["CustID"])

    def test_contiguous_units_become_range_without_dongho_override(self):
        class Item:
            params = {name: None for name in S.sp_spec.INPUT_PARAM_NAMES}
            custname = "국민은행 샘플지점"
            class structured:
                admin_addr = "서울특별시 샘플구 샘플동"
            class model:
                bank = "국민은행"
                branch = "샘플지점"
                remarks = ""
                addresses = ["제606호", "제607호", "제608호"]
                extra_units = []
                request_no = "SYNTH"

        old_reg = S._lookup_reg_eub_ybankauto
        old_customer = S.ro_lookups.lookup_customer
        old_exact = S.ro_lookups.lookup_customer_exact
        try:
            S._lookup_reg_eub_ybankauto = lambda *_: {"Reg": "R", "Eub": "E"}
            class Result:
                _raw_selected = {"CustID": "C"}
                status = S.ro_lookups.SINGLE
            S.ro_lookups.lookup_customer_exact = lambda *_: Result()
            S.ro_lookups.lookup_customer = lambda *_: Result()
            params = S._enrich_from_db(object(), Item())
        finally:
            S._lookup_reg_eub_ybankauto = old_reg
            S.ro_lookups.lookup_customer_exact = old_exact
            S.ro_lookups.lookup_customer = old_customer
        self.assertEqual(params["Building"], "606호~608호")
        self.assertIsNone(params["DongHo"])
        self.assertEqual(params["Dong"], "606")

    def test_alpha_multi_ho_preserves_structured_building_and_ho(self):
        class Item:
            params = {name: None for name in S.sp_spec.INPUT_PARAM_NAMES}
            params.update({"Building": "F401,F402\ud638", "Ho": "F401,F402"})
            custname = "\uae30\uc5c5\uc740\ud589 \ud64d\ub300\uc5ed\uc9c0\uc810"
            class structured:
                admin_addr = "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uc601\ub4f1\ud3ec\uad6c \uc591\ud3c9\ub3d91\uac00"
            class model:
                bank = "\uae30\uc5c5\uc740\ud589"
                branch = "\ud64d\ub300\uc5ed\uc9c0\uc810"
                remarks = ""
                addresses = ["\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uc601\ub4f1\ud3ec\uad6c \uc591\ud3c9\ub3d91\uac00 243-1 F401\ud638, F402\ud638"]
                extra_units = []
                request_no = "SYNTH"

        old_reg = S._lookup_reg_eub_ybankauto
        old_customer = S.ro_lookups.lookup_customer
        old_exact = S.ro_lookups.lookup_customer_exact
        try:
            S._lookup_reg_eub_ybankauto = lambda *_: {"Reg": "R", "Eub": "E"}
            class Result:
                _raw_selected = {"CustID": "C"}
                status = S.ro_lookups.SINGLE
            S.ro_lookups.lookup_customer_exact = lambda *_: Result()
            S.ro_lookups.lookup_customer = lambda *_: Result()
            params = S._enrich_from_db(object(), Item())
        finally:
            S._lookup_reg_eub_ybankauto = old_reg
            S.ro_lookups.lookup_customer_exact = old_exact
            S.ro_lookups.lookup_customer = old_customer
        self.assertEqual(params["Building"], "F401,F402\ud638")
        self.assertEqual(params["Ho"], "F401,F402")

    def test_ibk_ho_range_preserves_range_and_building_name(self):
        class Item:
            params = {name: None for name in S.sp_spec.INPUT_PARAM_NAMES}
            params.update({
                "Building": "\uc544\uc774\uc5d0\uc2a4\ube44\uc988\ud0c0\uc6cc \uc81c \uc81c18\uce35 1801~1809\ud638",
                "Building_Nm": "\uc544\uc774\uc5d0\uc2a4\ube44\uc988\ud0c0\uc6cc \uc81c",
                "Ho": "1801~1809",
            })
            custname = "\uae30\uc5c5\uc740\ud589 \uad6c\ub85c\ub3d9\uc9c0\uc810"
            class structured:
                admin_addr = "\uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uc601\ub4f1\ud3ec\uad6c \uc591\ud3c9\ub3d95\uac00"
            class model:
                bank = "\uae30\uc5c5\uc740\ud589"
                branch = "\uad6c\ub85c\ub3d9\uc9c0\uc810"
                remarks = ""
                addresses = ["\uc11c\uc6b8 \uc601\ub4f1\ud3ec\uad6c \uc591\ud3c9\ub3d95\uac00 1-1 \uc544\uc774\uc5d0\uc2a4\ube44\uc988\ud0c0\uc6cc \uc81c 18\uce35 1801\ud638~1809\ud638"]
                extra_units = []
                request_no = "SYNTH"

        old_reg = S._lookup_reg_eub_ybankauto
        old_customer = S.ro_lookups.lookup_customer
        old_exact = S.ro_lookups.lookup_customer_exact
        try:
            S._lookup_reg_eub_ybankauto = lambda *_: {"Reg": "R", "Eub": "E"}
            class Result:
                _raw_selected = {"CustID": "C"}
                status = S.ro_lookups.SINGLE
            S.ro_lookups.lookup_customer_exact = lambda *_: Result()
            S.ro_lookups.lookup_customer = lambda *_: Result()
            params = S._enrich_from_db(object(), Item())
        finally:
            S._lookup_reg_eub_ybankauto = old_reg
            S.ro_lookups.lookup_customer_exact = old_exact
            S.ro_lookups.lookup_customer = old_customer
        self.assertEqual(params["Building"], "\uc544\uc774\uc5d0\uc2a4\ube44\uc988\ud0c0\uc6cc \uc81c 1801~1809\ud638")
        self.assertEqual(params["Ho"], "1801~1809")

    def test_imbank_prefixed_units_preserved_from_remark(self):
        class Item:
            params = {name: None for name in S.sp_spec.INPUT_PARAM_NAMES}
            params.update({
                "Building": "\ud2b8\ub9ac\uc544\uce20 \uc81c9\uce35 \uc528914\ud638",
                "Building_Nm": "\ud2b8\ub9ac\uc544\uce20",
                "Dong": "9\uce35",
                "Ho": "\uc528914",
                "ToJiBIGO": "\uc815\ubcf4 \uc81c\uc528916\ud638 \ud3ec\ud568\ud558\uc5ec \uac10\uc815 \ubc14\ub78d\ub2c8\ub2e4",
            })
            custname = "\uc544\uc774\uc5e0\ubc45\ud06c PRM\uac15\ub0a82\uc13c\ud130"
            class structured:
                admin_addr = "\uacbd\uae30\ub3c4 \uad70\ud3ec\uc2dc \ub2f9\ub3d9"
            class model:
                bank = "\uc544\uc774\uc5e0\ubc45\ud06c"
                branch = "PRM\uac15\ub0a82\uc13c\ud130"
                remarks = "\uc815\ubcf4 \uc81c\uc528916\ud638 \ud3ec\ud568\ud558\uc5ec \uac10\uc815 \ubc14\ub78d\ub2c8\ub2e4"
                addresses = ["\uacbd\uae30\ub3c4 \uad70\ud3ec\uc2dc \ub2f9\ub3d9 \uc77c\ubc18 1046 \ud2b8\ub9ac\uc544\uce20 \uc81c9\uce35 \uc81c\uc528914\ud638"]
                extra_units = []
                request_no = "KAP"

        old_reg = S._lookup_reg_eub_ybankauto
        old_customer = S.ro_lookups.lookup_customer
        old_exact = S.ro_lookups.lookup_customer_exact
        try:
            S._lookup_reg_eub_ybankauto = lambda *_: {"Reg": "R", "Eub": "E"}
            class Result:
                _raw_selected = {"CustID": "C"}
                status = S.ro_lookups.SINGLE
            S.ro_lookups.lookup_customer_exact = lambda *_: Result()
            S.ro_lookups.lookup_customer = lambda *_: Result()
            params = S._enrich_from_db(object(), Item())
        finally:
            S._lookup_reg_eub_ybankauto = old_reg
            S.ro_lookups.lookup_customer_exact = old_exact
            S.ro_lookups.lookup_customer = old_customer
        self.assertEqual(params["Building"], "\ud2b8\ub9ac\uc544\uce20  \uc528914,\uc528916\ud638")
        self.assertEqual(params["Ho"], "\uc528914,\uc528916")
        self.assertIsNone(params["Dong"])

    def test_woori_shifted_multi_units_match_operating_format(self):
        class Item:
            params = {name: None for name in S.sp_spec.INPUT_PARAM_NAMES}
            params.update({"CustName": "우리은행", "CustFAX": "온",
                           "Building": "문정역SKV 219,220 218동 1호",
                           "Building_Nm": "문정역SKV 219,220",
                           "Dong": "218", "Ho": "1"})
            custname = "우리은행"
            class structured:
                admin_addr = "서울특별시 송파구 문정동"
                dong = "218"
                ho = "1"
            class model:
                bank = "우리은행"
                branch = "우리은행"
                remarks = "긴급신청건"
                addresses = ["서울특별시 송파구 문정동 일반 642-3 218동 1호, 문정역SKV ,219,220"]
                extra_units = []
                request_no = "T1"

        old_reg = S._lookup_reg_eub_ybankauto
        old_customer = S.ro_lookups.lookup_customer
        old_exact = S.ro_lookups.lookup_customer_exact
        try:
            S._lookup_reg_eub_ybankauto = lambda *_: {"Reg": "R", "Eub": "E"}
            class Result:
                _raw_selected = {"CustID": "C"}
                status = S.ro_lookups.SINGLE
            S.ro_lookups.lookup_customer_exact = lambda *_: Result()
            S.ro_lookups.lookup_customer = lambda *_: Result()
            params = S._enrich_from_db(object(), Item())
        finally:
            S._lookup_reg_eub_ybankauto = old_reg
            S.ro_lookups.lookup_customer_exact = old_exact
            S.ro_lookups.lookup_customer = old_customer
        self.assertEqual(params["Building"], "218,219,220호")
        self.assertEqual(params["Ho"], "218219220")
        self.assertIsNone(params["Dong"])
        self.assertIsNone(params["Building_Nm"])
        self.assertIsNone(params["DongHo"])
        self.assertEqual(params["CustFAX"], "온")
        self.assertEqual(params["HFDocid"], "T1")

    def test_empty_batch_rejected(self):
        with self.assertRaises(S.SaveError):
            S.save_pdf_batch([], app_cfg(), allowed_roots=["."])

    def test_two_items_commit_once(self):
        conn = FakeConn(); lookup_conn = FakeConn(); params = [{"x": 1}, {"x": 2}]
        old_prepare, old_enrich, old_next = S.prepare_pdfs, S._enrich_from_db, S._next_reg_charge
        old_sql, old_order = S.sp_spec.build_wrapper_sql, S.sp_spec.params_in_order
        try:
            S.prepare_pdfs = lambda paths, roots: params
            S._enrich_from_db = lambda cur, p: p
            charges = iter((899, 1729))
            S._next_reg_charge = lambda cur: next(charges)
            S.sp_spec.build_wrapper_sql = lambda: 'EXEC REDACTED_CONFIGURE_LOCALLY ?'
            S.sp_spec.params_in_order = lambda p: [p["x"]]
            res = S.save_pdf_batch(["a", "b"], app_cfg(), allowed_roots=["."],
                                   connector=lambda *_a, **_k: conn,
                                   lookup_connector=lambda *_a, **_k: lookup_conn)
        finally:
            S.prepare_pdfs, S._enrich_from_db, S._next_reg_charge = old_prepare, old_enrich, old_next
            S.sp_spec.build_wrapper_sql, S.sp_spec.params_in_order = old_sql, old_order
        self.assertEqual(res.count, 2)
        self.assertTrue(conn.committed); self.assertFalse(conn.rolled_back); self.assertTrue(conn.closed)
        self.assertTrue(lookup_conn.rolled_back); self.assertTrue(lookup_conn.closed)

    def test_target_mismatch_rolls_back(self):
        conn = FakeConn(); app = app_cfg(); app.db.database = "OTHER"
        old_prepare = S.prepare_pdfs
        try:
            S.prepare_pdfs = lambda paths, roots: [{"x": 1}]
            with self.assertRaises(S.SaveError):
                S.save_pdf_batch(["a"], app, allowed_roots=["."],
                                 connector=lambda *_a, **_k: conn)
        finally:
            S.prepare_pdfs = old_prepare
        self.assertTrue(conn.rolled_back); self.assertFalse(conn.committed)


if __name__ == "__main__":
    unittest.main()
