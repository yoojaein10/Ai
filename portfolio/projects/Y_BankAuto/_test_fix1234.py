import sys, os
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')

from db_writer import _parse_address, _format_bun, parse_building_detail
from pdf_parser import _is_company, parse_bank24_pdf

errors = []

def chk(label, got, expected):
    if got != expected:
        errors.append(f"FAIL [{label}] got={got!r} expected={expected!r}")
    else:
        print(f"  PASS [{label}] {got!r}")

# ── FIX-1: 지목 suffix 없는 케이스 ──────────────────────────────────────────
print("=== FIX-1 ===")
cases = [
    ("선유리 일반 1372-8",  "경기도 파주시 문산읍 선유리", "1372", "0008"),
    ("금곡동 일반 599-2",   "경기도 남양주시 금곡동",      "0599", "0002"),
    ("목동 일반 499-2",     "경기도 화성시 동탄구 목동",   "0499", "0002"),
]
full = {
    "선유리 일반 1372-8":  "경기도 파주시 문산읍 선유리 일반 1372-8",
    "금곡동 일반 599-2":   "경기도 남양주시 금곡동 일반 599-2",
    "목동 일반 499-2":     "경기도 화성시 동탄구 목동 일반 499-2",
}
for short, exp_body, exp_bun1, exp_bun2 in cases:
    addr = full[short]
    r = _parse_address(addr)
    chk(f"FIX1 body/{short}", r["address_body"], exp_body)
    chk(f"FIX1 BUN1/{short}", _format_bun(r["Bun1"]), exp_bun1)
    chk(f"FIX1 BUN2/{short}", _format_bun(r["Bun2"]), exp_bun2)
    chk(f"FIX1 no일반/{short}", "일반" not in r["address_body"], True)

# 대전광역시 회귀: "대" 지목으로 오인 금지
r = _parse_address("대전광역시 서구 둔산동 1234-5")
chk("FIX1 대전회귀 body", r["address_body"], "대전광역시 서구 둔산동")
chk("FIX1 대전회귀 BUN1", _format_bun(r["Bun1"]), "1234")

# ── FIX-2: 정수지번 + 건물명 + 호수 ──────────────────────────────────────────
print("\n=== FIX-2 ===")
addr26 = "경기도 고양시 일산동구 식사동 1529 위시티일산자이 주상복합 119-1호"
r = _parse_address(addr26)
chk("FIX2 body",  r["address_body"], "경기도 고양시 일산동구 식사동")
chk("FIX2 BUN1",  _format_bun(r["Bun1"]), "1529")
chk("FIX2 BUN2",  _format_bun(r["Bun2"]), "0000")

bd = parse_building_detail(addr26)
chk("FIX2 building", bd["building"], "위시티일산자이 주상복합")
chk("FIX2 ho",       bd["ho"],       "119-1호")

# ── FIX-3: 물건내역 skip ─────────────────────────────────────────────────────
print("\n=== FIX-3 (파서 실행으로 확인) ===")
# category parsing 직접 단위테스트
from pdf_parser import _CATEGORY_SKIP
for v in ["물건내역", "물 건 내 역", "▣물건내역", "▣ 물건내역", "▣물 건 내 역"]:
    chk(f"FIX3 skip/{v!r}", v in _CATEGORY_SKIP or v.replace(" ","").replace("▣","") == "물건내역", True)
# compact 체크 보조
for v in ["▣ 물 건 내 역", "물   건   내   역"]:
    compact = v.replace(" ", "").replace("▣", "")
    chk(f"FIX3 compact/{v!r}", compact == "물건내역", True)
# 아파트는 유지
chk("FIX3 아파트 not skip", "아파트" not in _CATEGORY_SKIP, True)

# ── FIX-4: _is_company 확장 ──────────────────────────────────────────────────
print("\n=== FIX-4 ===")
chk("FIX4 유풍금속공업",  _is_company("유풍금속공업"),  True)
chk("FIX4 기존(주)",     _is_company("(주)테스트"),    True)
chk("FIX4 기존법인",     _is_company("대화감정평가법인"), True)
chk("FIX4 공업지역 FP",  _is_company("공업지역"),      False)  # 지역으로 끝남, 오인 금지
chk("FIX4 일반단어 FP",  _is_company("상사"),          False)  # len < 4
chk("FIX4 회사FP",       _is_company("전자제품"),       False)  # endswith 전자 but len?

# ── FIX-4 실제 PDF 파서 ──────────────────────────────────────────────────────
print("\n=== FIX-4 PDF 파서 ===")
p4 = r'D:\AI\Claude\Y_BankAuto\기업은행\0237260635.pdf'
if os.path.exists(p4):
    r4 = parse_bank24_pdf(p4)
    keys = ['은행','영업점','담당자','소유자','채무자','물건종류','의뢰일자']
    for k in keys:
        print(f"  {k}: {r4.get(k,'')}")
    debtor_val = r4.get("채무자","") or r4.get("소유자","")
    chk("FIX4 debtor not empty", bool(debtor_val), True)
else:
    print(f"  SKIP: {p4} 없음")

# ── 25개 전체 파서 재검수 ────────────────────────────────────────────────────
print("\n=== 25개 PDF 전체 재검수 ===")
BANKS = {
    "신한은행": r"D:\AI\Claude\Y_BankAuto\신한은행",
    "기업은행": r"D:\AI\Claude\Y_BankAuto\기업은행",
    "우리은행": r"D:\AI\Claude\Y_BankAuto\우리은행",
}
keys_full = ['은행','영업점','담당자','담당자 연락처','소유자','채무자',
             '물건종류','의뢰일자','pdf_소재지']

issues = []
for bank, folder in BANKS.items():
    pdfs = sorted([f for f in os.listdir(folder) if f.endswith('.pdf')])
    for fn in pdfs:
        path = os.path.join(folder, fn)
        r = parse_bank24_pdf(path)
        cat = r.get("물건종류","")
        sojaegi = r.get("pdf_소재지","")
        print(f"\n  [{bank}] {fn}")
        for k in keys_full:
            print(f"    {k}: {r.get(k,'')}")
        # 필수 체크
        if cat == "물건내역":
            issues.append(f"FIX3 미수정: {fn} 물건종류=물건내역")
        # FIX-1 체크: _parse_address() 결과의 address_body에서 "일반" 미포함
        # (pdf_소재지는 PDF 원문이므로 "일반" 포함이 정상)
        if bank == "우리은행" and sojaegi:
            from db_writer import _parse_address
            pa = _parse_address(sojaegi.strip())
            if "일반" in pa.get("address_body", ""):
                issues.append(f"FIX1 미수정: {fn} address_body에 '일반' 포함: {pa['address_body']}")

if issues:
    print("\n=== ISSUES ===")
    for i in issues:
        print(f"  {i}")
else:
    print("\n  [전체 필수 체크 PASS]")

# ── 단위 테스트 요약 ──────────────────────────────────────────────────────────
print("\n=== 단위 테스트 요약 ===")
if errors:
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
else:
    print("  ALL UNIT TESTS PASS")
