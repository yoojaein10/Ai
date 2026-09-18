"NH 다호수(동일 필지 다호수) 파싱 회귀 테스트\nPDF: C:\\Users\\PUBLIC_USER\\Desktop\\5001897261_20260624_145849.pdf\n기대값: Ho=101, hoetc='102, 107, 201호', Dong='B동', SAN=1, BUN1=0020, BUN2=0000\n"
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

from pdf_parser import _extract_nh_multiunit_hoetc
from db_writer import parse_building_detail, _parse_address, _format_bun, build_representative_address

PASS = 0; FAIL = 0

def check(label, got, expected):
    global PASS, FAIL
    if got == expected:
        print(f"  [OK] {label}: {got!r}")
        PASS += 1
    else:
        print(f"  [FAIL] {label}: got={got!r}  expected={expected!r}")
        FAIL += 1

# ── 1. _extract_nh_multiunit_hoetc 단위 테스트 ─────────────────────────────────
print("=== 1. _extract_nh_multiunit_hoetc 단위 테스트 ===")

# 4개 물건내역 블록 시뮬레이션 (PDF에서 추출한 실제 데이터)
_MOCK_LINES = [
    "▣물건내역", "물건", "정보", "일련번호", "1", "우편번호주소",
    "서울 도봉구 쌍문동  20 B동 102호",
    "물건종류", "집합상가", "소유자", "정보",
    "▣물건내역", "물건", "정보", "일련번호", "2", "우편번호주소",
    "서울 도봉구 쌍문동  20 B동 201호",
    "물건종류", "집합상가", "소유자", "정보",
    "▣물건내역", "물건", "정보", "일련번호", "3", "우편번호주소",
    "서울 도봉구 쌍문동  20 B동 101호",
    "물건종류", "집합상가", "소유자", "정보",
    "▣물건내역", "물건", "정보", "일련번호", "4", "우편번호주소",
    "서울 도봉구 쌍문동  20 107호",
    "물건종류", "집합상가", "소유자", "정보",
]

mu = _extract_nh_multiunit_hoetc(_MOCK_LINES)
if mu is None:
    print("  [FAIL] _extract_nh_multiunit_hoetc returned None")
    FAIL += 1
else:
    check("raw_addrs 개수", len(mu["raw_addrs"]), 4)
    check("primary_addr", mu["primary_addr"], "서울 도봉구 쌍문동  20 B동 101호")
    check("primary_ho",   mu["primary_ho"],   "101")
    check("dong",         mu["dong"],          "B동")
    check("hoetc",        mu["hoetc"],         "102, 107, 201호")

# 2개 블록만 있는 경우
_TWO_LINES = [
    "▣물건내역", "물건", "정보", "일련번호", "1", "우편번호주소",
    "서울 서초구 서초동 100 A동 301호",
    "물건종류", "아파트",
    "▣물건내역", "물건", "정보", "일련번호", "2", "우편번호주소",
    "서울 서초구 서초동 100 A동 302호",
    "물건종류", "아파트",
]
mu2 = _extract_nh_multiunit_hoetc(_TWO_LINES)
if mu2 is None:
    print("  [FAIL] 2개 블록 테스트 — None 반환")
    FAIL += 1
else:
    check("2블록 primary_ho", mu2["primary_ho"], "301")
    check("2블록 hoetc",      mu2["hoetc"],      "302호")
    check("2블록 dong",       mu2["dong"],        "A동")

# 블록이 1개인 경우 → None
_ONE_LINES = [
    "▣물건내역", "물건", "정보", "일련번호", "1", "우편번호주소",
    "서울 서초구 서초동 100 A동 301호",
]
mu1 = _extract_nh_multiunit_hoetc(_ONE_LINES)
check("1블록 → None", mu1, None)

# 다른 필지(lot 다름)인 경우 → None
_DIFF_LOT = [
    "▣물건내역", "물건", "정보", "일련번호", "1", "우편번호주소",
    "서울 서초구 서초동 100 A동 301호",
    "물건종류", "아파트",
    "▣물건내역", "물건", "정보", "일련번호", "2", "우편번호주소",
    "서울 서초구 서초동 200 A동 302호",  # lot=200 (다름)
    "물건종류", "아파트",
]
mu_diff = _extract_nh_multiunit_hoetc(_DIFF_LOT)
check("다른 lot → None", mu_diff, None)

print()

# ── 2. parse_bank24_pdf 통합 테스트 ────────────────────────────────────────────
PDF_PATH = 'C:\\Users\\PUBLIC_USER\\Desktop\\5001897261_20260624_145849.pdf'
if not os.path.exists(PDF_PATH):
    print(f"=== 2. PDF 통합 테스트 SKIP (파일 없음: {PDF_PATH}) ===")
else:
    print("=== 2. parse_bank24_pdf 통합 테스트 ===")
    from pdf_parser import parse_bank24_pdf
    p = parse_bank24_pdf(PDF_PATH)

    check("처리상태",       p.get("처리상태"), "성공")
    check("은행",           p.get("은행"),     "농협은행")
    check("addresses 개수", len(p.get("addresses", [])), 1)
    check("addresses[0]",   p.get("addresses", [""])[0], "서울 도봉구 쌍문동  20 B동 101호")
    check("pdf_소재지 101호 포함", "101호" in (p.get("pdf_소재지") or ""), True)
    check("pdf_우편번호주소 101호", "101호" in (p.get("pdf_우편번호주소") or ""), True)
    check("DB 대표호수",    p.get("DB 대표호수"), "101")
    check("DB hoetc",       p.get("DB hoetc"),    "102, 107, 201호")

    print()
    print("=== 3. db_writer 매핑 시뮬레이션 ===")
    rep_addr, addr_for_db, addr_count = build_representative_address(p)
    check("rep_addr 101호",   "101호" in (rep_addr or ""), True)
    check("addr_count",        addr_count, 1)

    parsed_addr = _parse_address(rep_addr) if rep_addr else {}
    bld = parse_building_detail(rep_addr) if rep_addr else {}
    check("SAN",    parsed_addr.get("San"),                         1)
    check("BUN1",   _format_bun(parsed_addr.get("Bun1", "")),       "0020")
    check("BUN2",   _format_bun(parsed_addr.get("Bun2", "")),       "0000")
    check("Dong",   bld.get("dong", ""),                             "B동")
    check("Floor",  bld.get("floor", ""),                            "")

    sp_ho = (p.get("DB 대표호수") or "").strip() or bld.get("ho", "")
    if sp_ho.endswith("호"): sp_ho = sp_ho[:-1].strip()
    check("SP Ho",  sp_ho, "101")
    check("SP hoetc", p.get("DB hoetc"), "102, 107, 201호")

print()
print(f"결과: PASS={PASS}  FAIL={FAIL}")
if FAIL == 0:
    print("ALL UNIT TESTS PASS")
    sys.exit(0)
else:
    print("SOME TESTS FAILED")
    sys.exit(1)
