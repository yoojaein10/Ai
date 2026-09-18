# -*- coding: utf-8 -*-
"""RegHist/Customer 읽기 전용 조회 테스트 (fake cursor). 지시 §12, §13, §14."""
import unittest

import ro_lookups as L
import ro_pipeline as P
from tests import _fakes


# RegHist row: REG, EUB, NAME, AS1, AS2, AS3, AS4
def _reg_row(reg="R100", eub="E1", name="리이름"):
    return (reg, eub, name, "서울특별시", "강남구", "역삼동", "")


# Customer row: CustID, CustName, Active
def _cust_row(cid="C001", name="우리은행 강남지점", active="Y"):
    return (cid, name, active)


def _cur(scripted):
    return _fakes.make_ro_conn(scripted).cursor()


class TestRegHist(unittest.TestCase):
    def test_invalid_short(self):
        res = L.lookup_reghist(_cur({}), "서")
        self.assertEqual(res.status, L.INVALID_ADDRESS)

    def test_wildcard_only_rejected(self):
        res = L.lookup_reghist(_cur({}), "%% __")
        self.assertEqual(res.status, L.INVALID_ADDRESS)

    def test_no_result(self):
        res = L.lookup_reghist(_cur({"LOOKUP_REGHIST": []}), "서울특별시 강남구")
        self.assertEqual(res.status, L.NO_RESULT)

    def test_single(self):
        res = L.lookup_reghist(_cur({"LOOKUP_REGHIST": [_reg_row()]}),
                               "서울특별시 강남구")
        self.assertEqual(res.status, L.SINGLE)
        self.assertEqual(res._raw_selected, {"Reg": "R100", "Eub": "E1"})
        # DTO 는 마스킹만
        self.assertNotIn("R100", repr(res.dtos[0]))

    def test_multiple(self):
        rows = [_reg_row("R1"), _reg_row("R2")]
        res = L.lookup_reghist(_cur({"LOOKUP_REGHIST": rows}), "서울특별시 강남구")
        self.assertEqual(res.status, L.MULTIPLE)
        self.assertIsNone(res._raw_selected)   # 임의 선택 금지

    def test_too_many(self):
        rows = [_reg_row(f"R{i}") for i in range(L.ro_query.REGHIST_TOP)]
        res = L.lookup_reghist(_cur({"LOOKUP_REGHIST": rows}), "서울특별시 강남구")
        self.assertEqual(res.status, L.TOO_MANY)


class TestCustomer(unittest.TestCase):
    def test_exact_customer_name(self):
        res = L.lookup_customer_exact(
            _cur({"LOOKUP_CUSTOMER_EXACT": [_cust_row(name="샘플수협 지점")]}),
            "샘플수협 지점")
        self.assertEqual(res.status, L.SINGLE)
        self.assertEqual(res._raw_selected, {"CustID": "C001"})

    def test_woori_default_uses_exact_registered_query(self):
        res = L.lookup_customer(
            _cur({"LOOKUP_CUSTOMER_EXACT": [_cust_row(name="우리은행")]}),
            "우리은행", "우리은행")
        self.assertEqual(res.status, L.SINGLE)
        self.assertIsNotNone(res._raw_selected)

    def test_invalid(self):
        res = L.lookup_customer(_cur({}), "우", "")
        self.assertEqual(res.status, L.INVALID)

    def test_no_result(self):
        res = L.lookup_customer(_cur({"LOOKUP_CUSTOMER": []}), "우리은행", "강남")
        self.assertEqual(res.status, L.NO_RESULT)

    def test_single(self):
        res = L.lookup_customer(_cur({"LOOKUP_CUSTOMER": [_cust_row()]}),
                                "우리은행", "강남")
        self.assertEqual(res.status, L.SINGLE)
        self.assertEqual(res._raw_selected, {"CustID": "C001"})
        self.assertNotIn("C001", repr(res.dtos[0]))

    def test_multiple_ranked_not_autoselected(self):
        rows = [_cust_row("C1", "우리은행 강남중앙지점", "Y"),
                _cust_row("C2", "우리은행 강남지점", "Y")]
        res = L.lookup_customer(_cur({"LOOKUP_CUSTOMER": rows}), "우리은행", "강남")
        self.assertEqual(res.status, L.MULTIPLE)
        self.assertIsNone(res._raw_selected)
        # 랭킹은 결정적: 더 짧고 지점 포함하는 이름이 앞
        self.assertEqual(res.dtos[0].cust_name_masked,
                         L.security.mask_name("우리은행 강남지점"))

    def test_too_many(self):
        rows = [_cust_row(f"C{i}", f"우리은행 강남{i}지점") for i in range(L.ro_query.CUSTOMER_TOP)]
        res = L.lookup_customer(_cur({"LOOKUP_CUSTOMER": rows}), "우리은행", "강남")
        self.assertEqual(res.status, L.TOO_MANY)

    def test_branch_variants(self):
        self.assertEqual(L.branch_variants("강남"), ["강남", "강남지점"])
        self.assertEqual(L.branch_variants("강남지점"), ["강남지점"])

    def test_rank_active_first(self):
        rows = [_cust_row("C1", "우리은행 강남지점", "N"),
                _cust_row("C2", "우리은행 강남지점", "Y")]
        ranked = L.rank_customer_rows(rows, "우리은행", "강남")
        self.assertEqual(ranked[0][0], "C2")


class TestPipelineDecision(unittest.TestCase):
    def _single_cust(self):
        return L.lookup_customer(_cur({"LOOKUP_CUSTOMER": [_cust_row()]}), "우리은행", "강남")

    def _single_reg(self):
        return L.lookup_reghist(_cur({"LOOKUP_REGHIST": [_reg_row()]}), "서울특별시 강남구")

    def test_unpinned_blocks_even_if_lookups_ok(self):
        d = P.decide(customer=self._single_cust(), reghist=self._single_reg(),
                     metadata_verified=False)
        self.assertFalse(d["processable"])
        self.assertTrue(any("메타데이터" in r for r in d["reasons"]))
        self.assertFalse(d["execute_connected"])
        self.assertFalse(d["commit_connected"])

    def test_multiple_customer_blocks(self):
        rows = [_cust_row("C1"), _cust_row("C2", "우리은행 강남중앙지점")]
        cust = L.lookup_customer(_cur({"LOOKUP_CUSTOMER": rows}), "우리은행", "강남")
        d = P.decide(customer=cust, reghist=self._single_reg(), metadata_verified=True)
        self.assertFalse(d["processable"])

    def test_all_ok_dryrun_only(self):
        d = P.decide(customer=self._single_cust(), reghist=self._single_reg(),
                     metadata_verified=True)
        self.assertTrue(d["processable"])
        self.assertEqual(d["status"], P.PROCESSABLE_DRYRUN)
        self.assertFalse(d["execute_connected"])

    def test_reghist_no_result_allowed(self):
        reg = L.lookup_reghist(_cur({"LOOKUP_REGHIST": []}), "서울특별시 강남구")
        d = P.decide(customer=self._single_cust(), reghist=reg, metadata_verified=True)
        self.assertTrue(d["processable"])   # Reg/Eub 없이 진행 가능


class TestNoWritePathReference(unittest.TestCase):
    def test_ro_pipeline_has_no_execute_or_commit(self):
        import inspect
        src = inspect.getsource(P)
        # 쓰기 모듈을 import 하거나 실행/커밋 함수를 호출하지 않는다(문서 언급은 무관).
        self.assertNotIn("import ts_db_writer", src)
        self.assertNotIn("execute_sp(", src)
        self.assertNotIn("commit_with_guards(", src)
        self.assertFalse(hasattr(P, "ts_db_writer"))


if __name__ == "__main__":
    unittest.main()
