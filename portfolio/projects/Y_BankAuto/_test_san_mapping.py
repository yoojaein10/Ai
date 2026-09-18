# -*- coding: utf-8 -*-
"""산지번 SAN 매핑 규칙 단위 테스트.

규칙:
  일반 지번 → SAN = 1
  산 지번   → SAN = 2
  주소 없음/미파싱 기본값 → SAN = 1
"""
import sys, os, io, unittest

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(__file__))

from db_writer import _parse_address, _format_bun


class TestSanMapping(unittest.TestCase):

    def _chk(self, addr, san, bun1, bun2, label=""):
        r = _parse_address(addr)
        self.assertEqual(r["San"],  san,  f"SAN mismatch  [{label or addr!r}]: got {r['San']}")
        self.assertEqual(_format_bun(r["Bun1"]), bun1,
                         f"BUN1 mismatch [{label or addr!r}]: got {_format_bun(r['Bun1'])!r}")
        self.assertEqual(_format_bun(r["Bun2"]), bun2,
                         f"BUN2 mismatch [{label or addr!r}]: got {_format_bun(r['Bun2'])!r}")

    # ── 산지번 SAN=2 ────────────────────────────────────────────────────────
    def test_산지번_단순(self):
        self._chk("산69-6", 2, "0069", "0006", "산69-6")

    def test_산지번_공백포함(self):
        self._chk("산 69-6", 2, "0069", "0006", "산 69-6")

    def test_산지번_전체주소(self):
        self._chk("경기도 안산시 단원구 대부동동 산69-6",
                  2, "0069", "0006", "대부동동 산69-6 전체주소")

    def test_산지번_공백_전체주소(self):
        self._chk("경기도 안산시 단원구 대부동동 산 69-6",
                  2, "0069", "0006", "대부동동 산 69-6 전체주소")

    def test_산지번_정수(self):
        self._chk("정남면 산 220", 2, "0220", "0000", "산 220")

    def test_산지번_번지키워드(self):
        self._chk("정남면 산 220-5번지 건물명", 2, "0220", "0005", "산+번지")

    def test_산지번_외필지(self):
        self._chk("정남면 산193-1외 1필지", 2, "0193", "0001", "산+외필지")

    # ── 일반 지번 SAN=1 ─────────────────────────────────────────────────────
    def test_일반지번_하이픈(self):
        self._chk("107-65", 1, "0107", "0065", "107-65")

    def test_일반지번_정수(self):
        self._chk("쌍문동 20", 1, "0020", "0000", "쌍문동 20")

    def test_일반지번_동포함(self):
        self._chk("대부동동 69-6", 1, "0069", "0006", "대부동동 69-6")

    def test_일반지번_건물호수(self):
        self._chk("쌍문동 20 B동 101호", 1, "0020", "0000", "쌍문동+B동+호수")

    def test_일반지번_전체주소(self):
        self._chk("서울 도봉구 쌍문동 138-22", 1, "0138", "0022", "도봉구 쌍문동")

    def test_일반지번_번지키워드(self):
        self._chk("명일동 47-12번지 건물명", 1, "0047", "0012", "일반+번지")

    # ── 주소 없음/빈 문자열 → SAN=1 ─────────────────────────────────────────
    def test_빈문자열(self):
        r = _parse_address("")
        self.assertEqual(r["San"], 1, "빈 문자열 → San=1")

    def test_None_equivalent(self):
        # 실제 호출은 str로 들어오지만 빈 주소 기본값 검증
        r = _parse_address("  ")
        self.assertEqual(r["San"], 1, "공백만 있는 주소 → San=1")


class TestSanMappingNoSan0(unittest.TestCase):
    """_parse_address 반환값에 San=0이 절대 없어야 한다."""

    _SAMPLE_ADDRS = [
        "경기도 안산시 단원구 대부동동 산69-6",
        "산 69-6",
        "정남면 산 220-5번지",
        "정남면 산193-1외 1필지",
        "서울 도봉구 쌍문동 138-22",
        "명일동 47-12번지 건물명",
        "쌍문동 20 B동 101호",
        "대부동동 69-6",
        "",
        "산",
    ]

    def test_no_san_zero(self):
        for addr in self._SAMPLE_ADDRS:
            r = _parse_address(addr)
            self.assertNotEqual(r["San"], 0,
                                f"San=0 잔재 발견: addr={addr!r} → {r}")


# ── 문제 PDF 통합 테스트 ─────────────────────────────────────────────────────
PDF_PATH = 'C:\\Users\\PUBLIC_USER\\Documents\\DHAPPMessenger\\기업 반월mtv_01-2606-3-2072.pdf'


class TestIBKBanwolMtvIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(PDF_PATH):
            raise unittest.SkipTest(f"PDF 없음: {PDF_PATH}")
        from pdf_parser import parse_bank24_pdf
        from db_writer import build_representative_address
        cls.item = parse_bank24_pdf(PDF_PATH)
        cls.rep_addr, _, _ = build_representative_address(cls.item)

    def test_bank(self):
        self.assertIn("기업은행", self.item.get("은행", ""))

    def test_branch(self):
        self.assertIn("반월", self.item.get("영업점", ""))

    def test_san_bun(self):
        r = _parse_address(self.rep_addr)
        self.assertEqual(r["San"], 2,
                         f"SAN 오류: addr={self.rep_addr!r}, got San={r['San']}")
        self.assertEqual(_format_bun(r["Bun1"]), "0069",
                         f"BUN1 오류: {_format_bun(r['Bun1'])!r}")
        self.assertEqual(_format_bun(r["Bun2"]), "0006",
                         f"BUN2 오류: {_format_bun(r['Bun2'])!r}")

    def test_category(self):
        from db_writer import resolve_category_code
        cat = resolve_category_code(self.item, self.rep_addr)
        self.assertEqual(cat, "03", f"Category 오류: {cat!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
