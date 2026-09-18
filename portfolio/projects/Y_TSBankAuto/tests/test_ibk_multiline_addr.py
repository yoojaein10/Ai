# -*- coding: utf-8 -*-
"""기업은행: 소재지 라벨이 값과 분리된 표 셀 레이아웃 복원 + 다중 호 범위 축약.

실 Bank24 출력 PDF는 긴 주소가 줄바꿈되면 추출 순서가
값(앞줄) → '소 재 지'(라벨) → 값(뒷줄) 로 나온다(합성 데이터로 재현).
"""
import unittest

import address_mapper as am
from parsers import ibk


class TestMultiHoRange(unittest.TestCase):
    def test_comma_ho_list_collapses_to_range(self):
        # 'B동 231호, 232호, 233호, 234호' → 동=B, 호=231~234, 다세대 플래그
        s = am.structure_address(
            "경기 고양시 덕양구 향동동 580 센터빌딩 B동 231호, 232호, 233호, 234호")
        self.assertEqual(s.bun1, "0580")
        self.assertEqual(s.dong, "B")
        self.assertEqual(s.ho, "231~234")
        self.assertEqual(s.addr_etc, "1")
        self.assertTrue(s.building.endswith("231~234호"))

    def test_unsorted_ho_uses_min_max(self):
        s = am.structure_address("서울 강남구 역삼동 100 타워 501호, 505호, 503호")
        self.assertEqual(s.ho, "501~505")
        self.assertEqual(s.addr_etc, "1")

    def test_single_ho_unchanged(self):
        # 회귀 방지: 호가 하나면 범위/플래그를 만들지 않는다.
        s = am.structure_address("서울 강남구 역삼동 100 타워 501호")
        self.assertEqual(s.ho, "501")
        self.assertEqual(s.addr_etc, "")


class TestSplitLabelReconstruction(unittest.TestCase):
    # 값(앞줄) → 라벨 → 값(뒷줄) 순으로 추출된 합성 라인(실 PII 아님).
    LINES = [
        "탁상자문의뢰서",
        '의뢰기관: 기업은행            의뢰번호: 010-0000-0000           자문번호:',
        "▣의뢰내역",
        "기본    소 속    (주)샘플감정평가법인 본사",
        "물건종류   아파트형공장            평가사명",
        "우편번호      10546",
        "경기 고양시 덕양구 향동동 580 센터빌딩 B동 231호, 232호, 233호,",
        "소 재 지",
        "234호",
        "새주소코드",
        "물건",
        "정보",
        "새주소(소재지)",
        "채무자    샘플 유한책임회사         소유자    샘플 유한책임회사",
        "담당자명   최재현               의뢰일자      20260714",
        "영 업 점   안양                대표번호      0314433973",
        "휴대폰                      내선번호      310",
        "참고사항   샘플 감정평가사님 상담건입니다.",
    ]

    def test_address_reconstructed_across_label(self):
        m = ibk.parse(self.LINES)
        self.assertEqual(len(m.addresses), 1)
        addr = m.addresses[0]
        # 앞줄 + 뒷줄 이어붙임(라벨 줄 제외)
        self.assertIn("경기 고양시 덕양구 향동동 580", addr)
        self.assertIn("231호", addr)
        self.assertIn("234호", addr)
        self.assertNotIn("소 재 지", addr)
        # 다른 필드도 정상 파싱되는지(회귀 방지)
        self.assertEqual(m.request_no, '010-0000-0000')
        self.assertEqual(m.request_datetime, "2026-07-14")
        self.assertEqual(m.branch, "안양지점")

    def test_same_line_still_works(self):
        # 라벨+값이 같은 줄인 기존 형식은 그대로 동작해야 한다(회귀 방지).
        lines = list(self.LINES)
        lines[6] = "다른내용"
        lines[7] = "소 재 지   경기 샘플시 샘플읍 샘플리 400-4"
        lines[8] = "다음줄"
        m = ibk.parse(lines)
        self.assertEqual(len(m.addresses), 1)
        self.assertIn("샘플리 400-4", m.addresses[0])


if __name__ == "__main__":
    unittest.main()
