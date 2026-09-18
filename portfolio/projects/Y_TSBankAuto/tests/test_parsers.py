# -*- coding: utf-8 -*-
"""은행별 파서 테스트 (합성 fixture 사용)."""
import os
import unittest

import parsers
import pipeline
from parsers import base

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f]


class TestBankDetect(unittest.TestCase):
    def test_detect_all(self):
        cases = {
            "woori_synth.txt": "우리은행",
            "kookmin_synth.txt": "국민은행",
            "saemaeul_synth.txt": "새마을금고",
            "ibk_synth.txt": "기업은행",
            "hana_synth.txt": "하나은행",
            "nonghyup_synth.txt": "농협은행",
            "suhyup_synth.txt": "수협은행",
        }
        for fn, bank in cases.items():
            self.assertEqual(base.detect_bank(load(fn)), bank, fn)

    def test_title_does_not_decide_bank(self):
        # 국민 문서 제목은 담보감정평가의뢰서지만 은행은 헤더로 판별
        lines = load("kookmin_synth.txt")
        self.assertIn("담보감정평가의뢰서", lines[0])
        self.assertEqual(base.detect_bank(lines), "국민은행")


class TestWoori(unittest.TestCase):
    def test_fields(self):
        m = parsers.parse_request(load("woori_synth.txt"))
        self.assertEqual(m.bank, "우리은행")
        self.assertEqual(m.request_no, "T999999999")
        self.assertEqual(m.branch, "샘플금융센터")
        self.assertEqual(m.staff_name, "홍길동")
        self.assertTrue(m.branch_phone)
        self.assertEqual(m.extension, "100")
        self.assertEqual(len(m.addresses), 1)
        self.assertEqual(parsers.build_custname(m), "우리은행 샘플금융센터")

    def test_pii_captured_in_model_only(self):
        m = parsers.parse_request(load("woori_synth.txt"))
        # debtor/owner 는 모델엔 있으나 safe_log_dict 엔 없어야 한다
        self.assertNotIn("debtor", m.safe_log_dict())
        self.assertNotIn("owner", m.safe_log_dict())

    def test_blank_branch_excluded(self):
        # 2026-07-28 규칙: 영업점 공란은 우리은행 포함 전 은행에서 저장 제외.
        # (구 동작: 기본 거래처 "우리은행"으로 접수 — 실측 T260714135 로 폐지 확정)
        lines = load("woori_synth.txt")
        idx = next(i for i, line in enumerate(lines)
                   if "영 업 점" in line or base.nospace(line).startswith("영업점"))
        lines[idx] = "영 업 점                 담당자명   홍길동"
        with self.assertRaises(parsers.ExcludedRequest) as ctx:
            parsers.parse_request(lines)
        self.assertEqual(ctx.exception.code, "EXCLUDED_NO_BRANCH")

    def test_multiline_remark_before_label_is_preserved(self):
        lines = [
            "탁상자문의뢰서",
            "의뢰기관: 우리은행 의뢰번호: T260705652",
            "의뢰일자 2026-07-10 오후 2:27:53",
            "영 업 점   본점영업부             담당자명   정석철",
            "전화번호 02-2002-5248",
            "현재 임야이나 인허가 통해 지목 변경 예정입니다. 감안하여 담보 탁상가액 산정",
            "참고사항",
            "부탁드립니다.",
            "물건내역",
            "물건종류 임야",
            "주 소    경기도 파주시 문산읍 선유리 일반 201-10 201-10, 산2-1, 6",
        ]
        m = parsers.parse_request(lines)
        self.assertEqual(
            m.remarks,
            "현재 임야이나 인허가 통해 지목 변경 예정입니다. 감안하여 담보 탁상가액 산정 부탁드립니다.",
        )

    def test_remark_wraps_around_label_line(self):
        # 라벨 줄에 값이 있으면서 앞/뒤 줄로도 이어지는 다호 합산 의뢰 양식.
        # (실제 T260707161: 라벨줄만 취해 앞줄 201~403호·뒷줄 부탁드립니다 를 잃던 버그)
        lines = [
            "탁상자문의뢰서",
            "의뢰기관: 우리은행 의뢰번호: T260707161",
            "의뢰일자 2026-07-14",
            "영 업 점   여의도지점             담당자명   김혜민",
            "전화번호 02- 785-7100",
            "내선번호 513",
            "201호, 202호, 403호,",
            "참고사항     501호, 601호 합산한 값 부탁드립니다., 502호에 대해서만 개별 값",
            "부탁드립니다.",
            "물건내역",
            "주 소    서울특별시 강서구 화곡동 일반 24-490 크리스탈빌 1 201",
        ]
        m = parsers.parse_request(lines)
        self.assertEqual(
            m.remarks,
            "201호, 202호, 403호, 501호, 601호 합산한 값 부탁드립니다., "
            "502호에 대해서만 개별 값 부탁드립니다.",
        )


class TestKookmin(unittest.TestCase):
    def test_address_from_object_region_not_tax(self):
        m = parsers.parse_request(load("kookmin_synth.txt"))
        # 세금계산서 주소(중구 세종대로)가 아니라 물건 주소(마포구 합정동)
        self.assertTrue(m.addresses)
        self.assertIn("합정동", m.addresses[0])
        self.assertNotIn("세종대로", m.addresses[0])

    def test_custname(self):
        m = parsers.parse_request(load("kookmin_synth.txt"))
        self.assertEqual(parsers.build_custname(m), "국민은행 샘플종합금융센터")

    def test_phone_on_separate_row(self):
        lines = load("kookmin_synth.txt")
        manager = next(i for i, line in enumerate(lines) if line.startswith("담당자명"))
        lines[manager] = "담당자명   홍길동"
        lines.insert(manager + 1, "전화번호   0200000000")
        m = parsers.parse_request(lines)
        self.assertEqual(m.branch_phone, "0200000000")


class TestSaemaeul(unittest.TestCase):
    def test_split_address(self):
        m = parsers.parse_request(load("saemaeul_synth.txt"))
        self.assertTrue(m.addresses)
        self.assertIn("샘플동", m.addresses[0])

    def test_custname_normalized(self):
        m = parsers.parse_request(load("saemaeul_synth.txt"))
        self.assertEqual(parsers.build_custname(m), "샘플새마을금고 본점")

    def test_stacked_gita_bigo_jeongbo_remark(self):
        # 비고가 세로 라벨 "기 타 / 비 고 / 정 보"에 분리돼 들어가는 양식.
        # (실제 10000000000017136756: 비고 줄은 빈 라벨이고 값은 기타·정보 줄에 있음)
        lines = [
            "탁상자문의뢰서",
            "새마을금고",
            "의뢰기관:                 의뢰번호: 10000000000017136756",
            "▣의뢰내역",
            "금 고    화성 본점",
            "금고 담당자명  천성민              금고 전화번호    031-227-7008",
            "의뢰일자      2026-07-14 오후 4:16:00",
            "기 타                    F1003, F1005 (5개호실)(상가,판매시설)",
            "비 고",
            "정 보           탁감 부탁드립니다. (10층 아니라 1층입니다)",
            "▣물건정보",
            "번 호       1                 물건종류    토지+건물",
            "정보           경기도 안산시 단원구 고잔동 일반 539-10 고잔동 1003호",
            "세부주소",
        ]
        m = parsers.parse_request(lines)
        self.assertEqual(
            m.remarks,
            "F1003, F1005 (5개호실)(상가,판매시설) 탁감 부탁드립니다. (10층 아니라 1층입니다)",
        )
        # 물건정보의 "정 보 <주소>" 라인을 비고로 오인하지 않아야 한다.
        self.assertNotIn("경기도", m.remarks)

    def test_empty_branch_excluded(self):
        # 실제 10000000000017138561: '금 고' 라벨만 있고 값 칸이 비어 영업점 미상.
        # 2026-07-28 규칙: 영업점 미상 건은 저장하지 않고 EXCLUDED_NO_BRANCH 로 제외.
        lines = [
            "탁상자문의뢰서",
            "새마을금고",
            "의뢰기관:                 의뢰번호: 10000000000017138561",
            "▣의뢰내역",
            "기 본    소 속    (주)대화감정평가법인 본사",
            "금 고",
            "금고 담당자명  최윤정              금고 전화번호    02-418-8478",
            "의뢰일자      2026-07-15 오전 11:33:00",
            "비 고    오피스텔 담보대출, 방이지점 02-418-8478 회신",
            "▣물건정보",
            "번 호       1                 물건종류    토지+건물",
            "세부주소       경기도 남양주시 별내동 일반 995- 별내동 103동 1505호",
        ]
        with self.assertRaises(parsers.ExcludedRequest) as ctx:
            parsers.parse_request(lines)
        self.assertEqual(ctx.exception.code, "EXCLUDED_NO_BRANCH")

    def test_present_branch_not_excluded(self):
        # 금고명이 정상적으로 같은 줄에 있으면 제외 미발동(회귀 방지).
        m = parsers.parse_request(load("saemaeul_synth.txt"))
        self.assertEqual(m.branch, "샘플 본점")


class TestIbk(unittest.TestCase):
    def test_date_only(self):
        m = parsers.parse_request(load("ibk_synth.txt"))
        self.assertEqual(m.request_datetime, "2026-01-01")
        self.assertTrue(m.request_date_only)

    def test_branch_suffix(self):
        m = parsers.parse_request(load("ibk_synth.txt"))
        self.assertEqual(parsers.build_custname(m), "기업은행 샘플지점")

    def test_representative_number_is_cust_phone(self):
        m = parsers.parse_request(load("ibk_synth.txt"))
        self.assertEqual(m.branch_phone, "0310000000")


class TestHana(unittest.TestCase):
    def test_fields(self):
        lines = [
            "탁상자문의뢰서",
            "KEB하나은행",
            "의뢰기관:                 의뢰번호: 202607000154       자문번호  01-20260702-080",
            "▣의뢰내역",
            "채무자    성 명     샘플법인             전화번호",
            "영 업 점   샘플금융센터            담당자명   샘플담당",
            "의뢰일자      2026-07-02 오후 1:03:32      전화번호      0200000000",
            "기 타",
            '의뢰부동산 : 샘플상가 204호~207호 총4개호 자가사용중. 담당자 :샘플사용자 차장 0200000000 (110)',
            "▣물건정보",
            "물건종류   분양상가              소 유 자",
            "소 재 지   서울특별시 마포구 샘플동 490 샘플상가 제몰동 204호",
        ]
        m = parsers.parse_request(lines)
        self.assertEqual(m.bank, "하나은행")
        self.assertEqual(m.request_no, "202607000154")
        self.assertEqual(m.request_datetime, "2026-07-02 13:03:32")
        self.assertEqual(m.branch, "샘플금융센터")
        self.assertEqual(m.staff_name, "샘플담당")
        self.assertEqual(m.branch_phone, "0200000000")
        self.assertEqual(m.extension, "110")
        self.assertEqual(m.property_type, "분양상가")
        self.assertIn("204호~207호", m.remarks)
        self.assertIn("샘플상가", m.addresses[0])
        self.assertEqual(parsers.build_custname(m), "하나은행 샘플금융센터")

    def test_sample_pdfs_are_eligible_when_present(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "하나은행"))
        if not os.path.isdir(root):
            self.skipTest("하나은행 샘플 폴더 없음")
        for name in ("1.pdf", "2.pdf", "3.pdf", "4.pdf", "5.pdf", "6.pdf"):
            path = os.path.join(root, name)
            lines = base.extract_lines(path, allowed_roots=[root])
            pr = pipeline.prepare(lines)
            self.assertTrue(pr.eligible, f"{name}: {pr.reasons}")
            self.assertEqual(pr.model.bank, "하나은행")
            self.assertTrue(pr.model.request_no)
            self.assertTrue(pr.model.addresses)


class TestNewBankPdfSamples(unittest.TestCase):
    def _sample_root(self, folder):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", folder))

    def _assert_pdf_samples(self, folder, bank, count):
        root = self._sample_root(folder)
        if not os.path.isdir(root):
            self.skipTest(f"{folder} 샘플 폴더 없음")
        for idx in range(1, count + 1):
            path = os.path.join(root, f"{idx}.pdf")
            lines = base.extract_lines(path, allowed_roots=[root])
            pr = pipeline.prepare(lines)
            self.assertTrue(pr.eligible, f"{folder}/{idx}.pdf: {pr.reasons}")
            self.assertEqual(pr.model.bank, bank)
            self.assertTrue(pr.model.request_no)
            self.assertTrue(pr.model.branch)
            self.assertTrue(pr.model.addresses)

    def test_shinhan_sample_pdf(self):
        self._assert_pdf_samples("신한은행", "신한은행", 1)

    def test_nhcentral_sample_pdfs(self):
        self._assert_pdf_samples("농협중앙회", "농협중앙회", 5)

    def test_forest_sample_pdfs(self):
        self._assert_pdf_samples("산림조합", "산림조합중앙회", 3)

    def test_nhcentral_custname_uses_branch(self):
        from models import RequestModel
        m = RequestModel(bank="농협중앙회", branch="서울원예농협 마장동지점")
        self.assertEqual(parsers.build_custname(m), "서울원예농협 마장동지점")

    def test_forest_custname_uses_branch(self):
        from models import RequestModel
        m = RequestModel(bank="산림조합중앙회", branch="청도군산림조합")
        self.assertEqual(parsers.build_custname(m), "청도군산림조합")


class TestShinhan(unittest.TestCase):
    @staticmethod
    def _lines(branch_line):
        return [
            "탁상자문평가의뢰서",
            "의뢰기관: 신한은행 의뢰번호: 2026229585",
            "▣ 기본정보 ▣",
            "기본 소속 (주)샘플감정평가법인 본사",
            branch_line,
            "의뢰일자 2026-08-06 오전 11:47:09",
            "▣ 물건내역 ▣",
            "주소 서울특별시 영등포구 샘플동 일반 100-1",
        ]

    def test_branch_on_same_request_office_line(self):
        m = parsers.parse_request(self._lines(
            "의뢰점 영등포금융센터(1107) 담당자 홍길동 전화번호 0200000000"))
        self.assertEqual(m.branch, "영등포금융센터")
        self.assertEqual(parsers.build_custname(m), "신한은행 영등포금융센터")

    def test_legacy_branch_on_previous_line_is_preserved(self):
        lines = self._lines("의뢰점 담당자 홍길동 전화번호 0200000000")
        lines.insert(4, "샘플지점(1234)")
        m = parsers.parse_request(lines)
        self.assertEqual(m.branch, "샘플지점")


class TestImBankPdfSamples(unittest.TestCase):
    def test_imbank_sample_pdfs(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "IM뱅크"))
        if not os.path.isdir(root):
            self.skipTest("IM뱅크 샘플 폴더 없음")
        for name in ("1.pdf", "2.pdf"):
            path = os.path.join(root, name)
            lines = base.extract_lines(path, allowed_roots=[root])
            pr = pipeline.prepare(lines)
            self.assertTrue(pr.eligible, f"{name}: {pr.reasons}")
            self.assertEqual(pr.model.bank, "아이엠뱅크")
            self.assertTrue(pr.model.request_no.startswith("KAP"))
            self.assertTrue(pr.model.branch)
            self.assertTrue(pr.model.addresses)

    def test_imbank_custname_suffix(self):
        from models import RequestModel
        m = RequestModel(bank="아이엠뱅크", branch="수도권PRM센터")
        self.assertEqual(parsers.build_custname(m), "아이엠뱅크 수도권PRM센터")


class TestNonghyup(unittest.TestCase):
    def test_multi_unit_representative(self):
        m = parsers.parse_request(load("nonghyup_synth.txt"))
        self.assertGreaterEqual(len(m.addresses), 2)
        self.assertTrue(m.extra_units)  # 나머지 물건 병합 후보
        # 대표 = 첫 물건
        self.assertIn("1001", m.addresses[0])

    def test_address2_is_fallback_only(self):
        lines = load("nonghyup_synth.txt")
        lines = [line for line in lines
                 if not base.nospace(line).startswith(("주소1", "주소2"))]
        lines.append("주 소2   경기 샘플시 샘플동 일반 200-3 샘플아파트 101동 202호")
        m = parsers.parse_request(lines)
        self.assertIn("200-3", m.addresses[0])

        lines.append("주 소1   경기 샘플시 샘플동 일반 100-1 우선주소")
        m = parsers.parse_request(lines)
        self.assertIn("100-1", m.addresses[0])
        self.assertNotIn("200-3", m.addresses[0])


class TestSuhyup(unittest.TestCase):
    def test_spaced_cooperative_name_normalized(self):
        from models import RequestModel
        m = RequestModel(bank="수협은행",
                         branch="민물장어양식수산업협 동조합 문래역지점")
        self.assertEqual(parsers.build_custname(m),
                         "민물장어양식수협 문래역지점")

    def test_split_cooperative_name_normalized(self):
        from models import RequestModel
        m = RequestModel(bank="수협은행",
                         branch="냉동냉장수산업협동조 합 사직동지점")
        self.assertEqual(parsers.build_custname(m),
                         "냉동냉장수협 사직동지점")

    def test_branch_join_and_normalize(self):
        m = parsers.parse_request(load("suhyup_synth.txt"))
        self.assertEqual(parsers.build_custname(m), "통조림가공수협 샘플지점")

    def test_datetime_join(self):
        m = parsers.parse_request(load("suhyup_synth.txt"))
        self.assertEqual(m.request_datetime, "2026-01-01 11:00:00")

    def test_branch_on_same_line(self):
        lines = load("suhyup_synth.txt")
        idx = next(i for i, line in enumerate(lines) if line.startswith("의뢰점"))
        lines[idx] = "의뢰점 수협은행 샘플지점 담당자 홍길동 전화번호 020000000"
        m = parsers.parse_request(lines)
        self.assertEqual(m.branch, "수협은행 샘플지점")


class TestExcelRuleRegressions(unittest.TestCase):
    def test_nonghyup_address2_preserved_for_reg_fallback(self):
        lines = [
            "\ud0c1\uc0c1\uc790\ubb38\uc758\ub8b0\uc11c",
            "\uc758\ub8b0\uae30\uad00: \ub18d\ud611\uc740\ud589     \uc758\ub8b0\ubc88\ud638: 5001902347",
            "\uc758\ub8b0\uc77c\uc790 2026-07-08 \uc624\ud6c4 1:44:00",
            "\uc601\uc5c5\uc810 \ud654\uc591\uc9c0\uc810 \uc804\ud654\ubc88\ud638 0236797557",
            "\ub2f4\ub2f9\uc790 \uc774\ubba4\uc9c4",
            "\ubb3c\uac74\ub0b4\uc5ed",
            "\uc8fc \uc18c1 \uc11c\uc6b8\ud2b9\ubcc4\uc2dc \uc6a9\uc0b0\uad6c \uc6d0\ud6a8\ub85c2\uac00 17 601\ud638 \uc77c\ubc18 17-\uc5d0\ub370\ub974\ub098\uc778\uc6a9\uc0b0 601",
            "\uc8fc \uc18c2 \uc11c\uc6b8 \uc6a9\uc0b0\uad6c \uc6d0\ud6a8\ub85c2\uac00 17 \uc5d0\ub370\ub974\ub098\uc778\uc6a9\uc0b0 601\ud638",
        ]
        m = parsers.parse_request(lines)
        self.assertTrue(m.addresses)
        self.assertTrue(m.fallback_addresses)
        self.assertIn("601", m.addresses[0])
        self.assertIn("601", m.fallback_addresses[0])

    def test_suhyup_regional_fishery_coop_normalized(self):
        from models import RequestModel
        m = RequestModel(
            bank="\uc218\ud611\uc740\ud589",
            branch="\uc601\uad11\uad70\uc218\uc0b0\uc5c5\ud611\ub3d9\uc870\ud569 \uac15\ub0a8\uc5ed\uc0bc\uc9c0\uc810",
        )
        self.assertEqual(
            parsers.build_custname(m),
            "\uc601\uad11\uad70\uc218\ud611 \uac15\ub0a8\uc5ed\uc0bc\uc9c0\uc810",
        )

    def test_saemaeul_default_extension_two(self):
        m = parsers.parse_request(load("saemaeul_synth.txt"))
        self.assertEqual(pipeline.build_custcharge(m), "\ud64d\uae38\ub3d9/2")


class TestEligibility(unittest.TestCase):
    def test_korea_invest_savings_bank(self):
        lines = [
            "탁상자문의뢰서",
            "의뢰기관: 한국투자저축은행 의뢰번호: 00000000000001",
            "의뢰일자 2026-01-01 영 업 점 샘플지점",
            "담당자명 홍길동 전화번호 0200000000",
            "참고사항 샘플 비고",
            "일련번호 1 물건종류 대지",
            "기본주소 서울 강동구 성내동",
            "상세주소 100-2번지",
        ]
        m = parsers.parse_request(lines)
        self.assertEqual(m.bank, "한국투자저축은행")
        self.assertEqual(m.branch, "샘플지점")
        self.assertIn("일반 100-2", m.addresses[0])
        self.assertEqual(parsers.build_custname(m),
                         "한국투자저축은행 샘플지점")

    def test_all_fixtures_eligible(self):
        for fn in ("woori_synth.txt", "kookmin_synth.txt", "saemaeul_synth.txt",
                   "ibk_synth.txt", "nonghyup_synth.txt", "suhyup_synth.txt"):
            pr = pipeline.prepare(load(fn))
            self.assertTrue(pr.eligible, f"{fn}: {pr.reasons}")

    def test_missing_required_blocks(self):
        # 영업점은 있으나 의뢰일시/주소 누락 → 파싱은 되고 적격성에서 차단.
        lines = ["탁상자문의뢰서", "의뢰기관: 우리은행 의뢰번호: T1 자문번호: 01-1",
                 "영 업 점   본점영업부             담당자명   홍길동"]
        pr = pipeline.prepare(lines)
        self.assertFalse(pr.eligible)


if __name__ == "__main__":
    unittest.main()
