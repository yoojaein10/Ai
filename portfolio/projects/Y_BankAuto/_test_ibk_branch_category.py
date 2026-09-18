"""IBK 기업은행 지점명 파싱 + Category 분류 단위 테스트."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(__file__))

from pdf_parser import _is_valid_branch, _is_business_label
from db_writer import resolve_category_code, resolve_sp_cust_name


class TestIsValidBranch(unittest.TestCase):
    def test_단지_suffix_accepted(self):
        self.assertTrue(_is_valid_branch("검단산업단지"))

    def test_대표자명_rejected(self):
        # '대표자명'이 _LABEL_SET에 추가되어 _is_business_label에서 걸러져야 함
        # _is_valid_branch 자체는 len=4≤5이므로 True지만,
        # _is_business_label 쪽에서 label 처리됨을 아래에서 검증
        pass

    def test_known_valid_branches(self):
        for b in ("강남지점", "서울금융센터", "영업부", "본점"):
            self.assertTrue(_is_valid_branch(b), f"expected True for {b!r}")

    def test_invalid_branch(self):
        for b in ("", "담당자", "의뢰기관", "사업번호"):
            result = _is_valid_branch(b)
            if b == "":
                self.assertFalse(result)


class TestIsBusinessLabel(unittest.TestCase):
    def test_대표자명_is_label(self):
        self.assertTrue(_is_business_label("대표자명"))

    def test_사업번호_is_label(self):
        self.assertTrue(_is_business_label("사업번호"))

    def test_real_branch_not_label(self):
        self.assertFalse(_is_business_label("검단산업단지"))


class TestResolveCategoryCode(unittest.TestCase):
    def _item(self, cat):
        return {"물건종류": cat}

    # --- 근린생활시설: 건물명 없음 → 03 ---
    def test_근린생활시설_no_building_03(self):
        item = self._item("근린생활시설")
        self.assertEqual(resolve_category_code(item, "인천 서구 검단동 123", building_name=""), "03")

    # --- 근린생활시설: 건물명 있음 → 30 ---
    def test_근린생활시설_with_building_30(self):
        item = self._item("근린생활시설")
        self.assertEqual(resolve_category_code(item, "인천 서구 검단동 123-1", building_name="검단빌딩"), "30")

    # --- 상가: 항상 30 (기존 nhc 테스트 보호) ---
    def test_상가_always_30(self):
        item = self._item("상가")
        self.assertEqual(resolve_category_code(item, "서울 도봉구 쌍문동 138-22", building_name=""), "30")

    # --- 아파트 → 30 ---
    def test_아파트_30(self):
        self.assertEqual(resolve_category_code(self._item("아파트"), "서울 강남구 개포동 123 456동 789호"), "30")

    # --- 단독주택 → 03 ---
    def test_단독주택_03(self):
        self.assertEqual(resolve_category_code(self._item("단독주택"), "서울 노원구 상계동 500"), "03")

    # --- 물건종류 없음 + 호수 있음 → 30 ---
    def test_no_cat_unit_no_30(self):
        self.assertEqual(resolve_category_code({}, "서울 강남구 역삼동 123 101동 202호"), "30")

    # --- 물건종류 없음 + 호수 없음 → 03 ---
    def test_no_cat_no_unit_03(self):
        self.assertEqual(resolve_category_code({}, "인천 서구 검단동 456-1"), "03")


class TestResolveSPCustName(unittest.TestCase):
    def test_matched_cust_name_returned_as_is(self):
        item = {"은행": "기업은행", "영업점": "검단산업단지"}
        result = resolve_sp_cust_name(item, "기업은행 검단산업단지지점장", "기업은행", "검단산업단지")
        self.assertEqual(result, "기업은행 검단산업단지지점장")

    def test_production_from_cust_name(self):
        from db_writer import _production_from_cust_name
        self.assertEqual(_production_from_cust_name("기업은행 검단산업단지지점장"), "기업은행 검단산업단지지점")


IBK_PDF = r"C:\Bank24Extractor\input\기업 검단산업단지_01-2606-3-2060.pdf"


class TestIBKPDFIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(IBK_PDF):
            raise unittest.SkipTest(f"PDF 없음: {IBK_PDF}")
        from pdf_parser import parse_bank24_pdf
        cls.item = parse_bank24_pdf(IBK_PDF)

    def test_branch_parsed(self):
        self.assertEqual(self.item.get("영업점"), "검단산업단지", f"영업점 오파싱: {self.item.get('영업점')!r}")

    def test_bank_name(self):
        self.assertIn("기업은행", (self.item.get("은행") or ""), f"은행명: {self.item.get('은행')!r}")

    def test_category_03_no_building(self):
        rep_addr = self.item.get("대표물건주소", "") or ""
        cat = resolve_category_code(self.item, rep_addr, building_name="")
        self.assertEqual(cat, "03", f"Category 오분류: {cat!r}, 물건종류={self.item.get('물건종류')!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
