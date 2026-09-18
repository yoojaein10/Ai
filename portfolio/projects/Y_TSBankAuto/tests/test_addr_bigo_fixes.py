# -*- coding: utf-8 -*-
"""다필지(본번-부번 전체형) Building + ToJiBIGO 이름 접두 제거 검증."""
import unittest

import address_mapper as am
import sp_spec


class TestCommaFullLots(unittest.TestCase):
    def test_same_bon_additional_lot(self):
        # '395-17,395-30' → 주지번 395-17, 추가필지 -30, 다필지 플래그
        s = am.structure_address("경기 광주시 곤지암읍 봉현리 395-17,395-30")
        self.assertEqual(s.bun1, "0395")
        self.assertEqual(s.bun2, "0017")
        self.assertEqual(s.building, "-30")
        self.assertEqual(s.addr_etc, "1")

    def test_multiple_same_bon(self):
        s = am.structure_address("서울 강남구 역삼동 100-1,100-2,100-5")
        self.assertEqual(s.bun1, "0100")
        self.assertEqual(s.bun2, "0001")
        self.assertEqual(s.building, "-2,-5")
        self.assertEqual(s.addr_etc, "1")

    def test_different_bon_kept_full(self):
        s = am.structure_address("서울 강남구 역삼동 100-1,200-5")
        self.assertEqual(s.building, "200-5")
        self.assertEqual(s.addr_etc, "1")

    def test_single_lot_no_building(self):
        # 다필지 아님 → Building 없음(회귀 방지)
        s = am.structure_address("경기 광주시 곤지암읍 봉현리 395-17")
        self.assertEqual(s.building, "")
        self.assertEqual(s.addr_etc, "")


class TestStripBigoName(unittest.TestCase):
    def test_strips_leading_name(self):
        self.assertEqual(sp_spec.strip_bigo_leading_name("이영준. 매매예정"), "매매예정")
        self.assertEqual(sp_spec.strip_bigo_leading_name("홍길동.매매예정"), "매매예정")

    def test_keeps_when_no_name_prefix(self):
        self.assertEqual(sp_spec.strip_bigo_leading_name("매매예정"), "매매예정")
        # 숫자 접두는 이름 아님 → 유지
        self.assertEqual(sp_spec.strip_bigo_leading_name("2025. 재감정"), "2025. 재감정")

    def test_empty_and_none(self):
        self.assertEqual(sp_spec.strip_bigo_leading_name(""), "")
        self.assertIsNone(sp_spec.strip_bigo_leading_name(None))


if __name__ == "__main__":
    unittest.main()
