import sys, os
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from pdf_parser import _is_entity_name, parse_bank24_pdf

errors = []
def chk(label, got, expected):
    if got != expected:
        errors.append(f"FAIL [{label}] got={got!r} expected={expected!r}")
    else:
        print(f"  PASS [{label}]")

# ── _is_entity_name 단위 테스트 ──────────────────────────────────────────────
print("=== _is_entity_name 단위 테스트 ===")
for v in ["고강역신원아침도시퍼스티지", "한성모듈러(주)", "(주)알팩"]:
    chk(f"True: {v}", _is_entity_name(v), True)

for v in ["아파트", "물건내역", "전화번호", "의뢰일자",
          "11111111111111", "2026-06-10", "성명", "성   명",
          "임대차포함여부", "공부요청구분", "감정서발송지점"]:
    chk(f"False: {v!r}", _is_entity_name(v), False)

# ── 문제 PDF 검증 ────────────────────────────────────────────────────────────
print("\n=== 우리은행 2026060374.pdf ===")
r = parse_bank24_pdf(r'D:\AI\Claude\Y_BankAuto\우리은행\2026060374.pdf')
for k in ['은행','영업점','채무자','소유자','물건종류','의뢰일자','pdf_소재지']:
    print(f"  {k}: {r.get(k,'')}")
chk("채무자=고강역신원아침도시퍼스티지", r.get("채무자",""), "고강역신원아침도시퍼스티지")
chk("소유자=고강역신원아침도시퍼스티지", r.get("소유자",""), "고강역신원아침도시퍼스티지")
chk("물건종류=아파트", r.get("물건종류",""), "아파트")

# ── 25개 PDF 전체 회귀 ────────────────────────────────────────────────────────
print("\n=== 25개 PDF 회귀 ===")
BANKS = {
    "신한": r"D:\AI\Claude\Y_BankAuto\신한은행",
    "기업": r"D:\AI\Claude\Y_BankAuto\기업은행",
    "우리": r"D:\AI\Claude\Y_BankAuto\우리은행",
}
BAD_NAMES = {"아파트","물건내역","전화번호","의뢰일자","성명","성   명","소유자","채무자"}
issues = []
for bank, folder in BANKS.items():
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith('.pdf'): continue
        r = parse_bank24_pdf(os.path.join(folder, fn))
        d = r.get("채무자",""); o = r.get("소유자","")
        cat = r.get("물건종류","")
        print(f"  [{bank}] {fn}  채무자={d!r}  소유자={o!r}  물건종류={cat!r}")
        for val in [d, o]:
            if val in BAD_NAMES:
                issues.append(f"오추출 [{fn}] 채무자/소유자={val!r}")
        if cat == "물건내역":
            issues.append(f"FIX3 미반영 [{fn}] 물건종류=물건내역")

if issues:
    print("\n[ISSUES]")
    for i in issues: print(f"  {i}")

print("\n=== 단위 테스트 요약 ===")
if errors:
    for e in errors: print(f"  {e}")
    sys.exit(1)
else:
    print("  ALL UNIT TESTS PASS")
    if not issues:
        print("  ALL REGRESSION PASS")
