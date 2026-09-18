# -*- coding: utf-8 -*-
"""주소 구조화/길이/인코딩 테스트."""
import unittest

import address_mapper as am


class TestStructure(unittest.TestCase):
    def test_multi_lot_operating_format(self):
        sa = am.structure_address(
            "서울 영등포구 당산동3가 322, 323, 324번지 케레스")
        self.assertEqual((sa.bun1, sa.bun2), ("0322", "0000"))
        self.assertEqual(sa.building, "323324")
        self.assertEqual(sa.addr_etc, "1")

    def test_repeated_base_lot_operating_format(self):
        sa = am.structure_address(
            "서울특별시 도봉구 도봉동 일반 617-21 617-21,22,23,28")
        self.assertEqual(sa.building, "617-22,617-23,617-28")
        self.assertEqual(sa.addr_etc, "1")

    def test_trailing_unit_without_ho_suffix(self):
        sa = am.structure_address(
            "경기도 부천시 원미구 심곡동 일반 456-11 더로얄아파트 902")
        self.assertEqual(sa.building, "더로얄아파트 902호")
        self.assertEqual(sa.ho, "902")

    def test_floor_label_is_not_building_name(self):
        sa = am.structure_address(
            "서울 성북구 정릉동 일반 508-67 제3층 제301호")
        self.assertEqual(sa.building, "제3층 301호")
        self.assertEqual(sa.building_nm, "")
    def test_compact_building_floor_unit(self):
        sa = am.structure_address(
            "서울특별시 샘플구 샘플동 일반 10-1 샘플센터지하2층제비203호")
        self.assertEqual(sa.building_nm, "샘플센터")
        self.assertEqual(sa.building, "샘플센터 지하2층 비203호")
        self.assertEqual((sa.dong, sa.ho), ("비", "203"))

    def test_comma_additional_sub_lots(self):
        sa = am.structure_address("경기도 김포시 월곶면 개곡리 812-20,32,45")
        self.assertEqual((sa.bun1, sa.bun2), ("0812", "0020"))
        self.assertEqual(sa.building, "-32,-45")
        self.assertEqual(sa.addr_etc, "1")

    def test_short_sido_is_normalized_for_db(self):
        self.assertEqual(
            am.structure_address("서울 관악구 봉천동 일반 10-2").admin_addr,
            "서울특별시 관악구 봉천동")
        self.assertEqual(
            am.structure_address("인천 서해구 경서동 일반 20-3").admin_addr,
            "인천광역시 서해구 경서동")

    def test_explicit_building_dong_ho_are_preserved(self):
        sa = am.structure_address(
            "경기 하남시 풍산동 565 샘플아파트 2505동 2103호")
        self.assertEqual(sa.building_nm, "샘플아파트")
        self.assertEqual(sa.dong, "2505")
        self.assertEqual(sa.ho, "2103")
        self.assertEqual(sa.building, "샘플아파트 2505동 2103호")

    def test_hyphenated_ho_and_floor_are_preserved(self):
        sa = am.structure_address(
            "서울특별시 영등포구 문래동5가 1 문래대림아파트 제101동 제1층 제102-2호")
        self.assertEqual(sa.admin_addr, "서울특별시 영등포구 문래동5가")
        self.assertEqual((sa.bun1, sa.bun2), ("0001", "0000"))
        self.assertEqual(sa.building_nm, "문래대림아파트")
        self.assertEqual(sa.dong, "101")
        self.assertEqual(sa.ho, "102-2")
        self.assertEqual(sa.building, "문래대림아파트 101동 제1층 102-2호")

    def test_multi_alpha_ho_is_preserved(self):
        sa = am.structure_address(
            "서울특별시 영등포구 양평동1가 243-1 F401호, F402호")
        self.assertEqual(sa.admin_addr, "서울특별시 영등포구 양평동1가")
        self.assertEqual((sa.bun1, sa.bun2), ("0243", "0001"))
        self.assertEqual(sa.ho, "F401,F402")
        self.assertEqual(sa.building, "F401,F402호")

    def test_ho_range_is_preserved(self):
        sa = am.structure_address(
            "서울 영등포구 양평동5가 1-1 아이에스비즈타워 제 18층 1801호~1809호")
        self.assertEqual(sa.ho, "1801~1809")
        self.assertIn("1801~1809호", sa.building)

    def test_duplicate_base_then_san_extra_lots(self):
        sa = am.structure_address(
            "경기도 파주시 문산읍 선유리 일반 201-10 201-10, 산2-1, 6")
        self.assertEqual((sa.bun1, sa.bun2), ("0201", "0010"))
        self.assertEqual(sa.building, "산2-1,6")

    def test_basic_ilban(self):
        sa = am.structure_address("서울특별시 강남구 역삼동 일반 100-1 샘플빌딩")
        self.assertEqual(sa.admin_addr, "서울특별시 강남구 역삼동")
        self.assertEqual(sa.san, "1")
        self.assertEqual(sa.bun1, "0100")
        self.assertEqual(sa.bun2, "0001")
        self.assertEqual(sa.building_nm, "샘플빌딩")

    def test_duplicate_lot_before_ilban_is_removed_from_addr(self):
        sa = am.structure_address(
            "서울특별시 강동구 고덕동 233-4 일반 233-4")
        self.assertEqual(sa.admin_addr, "서울특별시 강동구 고덕동")
        self.assertEqual((sa.bun1, sa.bun2), ("0233", "0004"))

    def test_san(self):
        sa = am.structure_address("강원 평창군 봉평면 무이리 산 286-3")
        self.assertEqual(sa.san, "2")
        self.assertEqual(sa.bun1, "0286")
        self.assertEqual(sa.bun2, "0003")

    def test_no_marker_with_suffix(self):
        sa = am.structure_address("서울특별시 강북구 수유동 229-18외 1필지 샘플타워 제13층 제1303호")
        self.assertEqual(sa.admin_addr, "서울특별시 강북구 수유동")
        self.assertEqual(sa.bun1, "0229")
        self.assertEqual(sa.bun2, "0018")
        self.assertEqual(sa.ho, "1303")
        self.assertTrue(sa.addr_etc)  # 외 1필지 → 다필지

    def test_no_subbun(self):
        sa = am.structure_address("경기도 의왕시 오전동 일반 849-")
        self.assertEqual(sa.bun1, "0849")
        self.assertEqual(sa.bun2, "0000")

    def test_bun_padding_is_four_chars(self):
        sa = am.structure_address("서울특별시 중구 오장동 일반 90-5")
        self.assertEqual(len(sa.bun1), 4)
        self.assertEqual(len(sa.bun2), 4)
        self.assertEqual(sa.bun1, "0090")


class TestAddrLength(unittest.TestCase):
    def test_provisional_under_limit(self):
        r = am.validate_addr_length("서울특별시 강남구 역삼동", max_len=40)
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], "provisional")

    def test_provisional_over_limit_fails(self):
        r = am.validate_addr_length("가" * 41, max_len=40)
        self.assertFalse(r["ok"])

    def test_codec_byte_length(self):
        # CP949 에서 한글은 2바이트
        r = am.validate_addr_length("가" * 21, max_len=40, codec="cp949")
        self.assertEqual(r["byte_len"], 42)
        self.assertFalse(r["ok"])  # 42 > 40, 조용히 자르지 않음

    def test_encoding_unmappable_char_fails(self):
        # cp949 로 인코딩 불가한 문자
        r = am.validate_addr_length("𠮷", max_len=40, codec="cp949")
        self.assertFalse(r["ok"])
        self.assertIn("인코딩", r["reason"])


class TestRegHistAllowlist(unittest.TestCase):
    def test_rejects_unknown_table(self):
        with self.assertRaises(ValueError):
            am.lookup_reghist(None, "서울 강남구", table="EVIL; DROP TABLE x")


if __name__ == "__main__":
    unittest.main()
