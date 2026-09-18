import sys
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from pdf_parser import parse_bank24_pdf

# ── BUG-1/3: 우리은행 NOEST_2026060374.pdf ──────────────────────────────────
print("=== NOEST_2026060374.pdf ===")
path = r'C:\Bank24Extractor\pdf\NOEST_2026060374.pdf'
r = parse_bank24_pdf(path)
keys = ['은행','영업점','담당자','담당자 연락처','소유자','채무자','물건종류','의뢰일자','pdf_소재지']
for k in keys:
    print(f"  {k}: {r.get(k, '')}")

assert r.get('소유자') != '아파트', f"BUG-1 미수정: 소유자={r.get('소유자')}"
assert r.get('물건종류') == '아파트', f"물건종류 오추출: {r.get('물건종류')}"
assert r.get('의뢰일자') == '2026-06-10', f"BUG-3 미수정: 의뢰일자={r.get('의뢰일자')}"
print("  [PASS] BUG-1 소유자!=아파트, BUG-3 의뢰일자=2026-06-10")

# ── 회귀: NOEST_2026171570.pdf ───────────────────────────────────────────────
import os
p2 = r'C:\Bank24Extractor\pdf\NOEST_2026171570.pdf'
if os.path.exists(p2):
    print("\n=== NOEST_2026171570.pdf ===")
    r2 = parse_bank24_pdf(p2)
    for k in keys:
        print(f"  {k}: {r2.get(k, '')}")
else:
    print(f"\n  SKIP (없음): {p2}")

# ── 회귀: 기업은행.pdf ────────────────────────────────────────────────────────
p3 = r'D:\AI\Claude\Y_BankAuto\기업은행.pdf'
if os.path.exists(p3):
    print("\n=== 기업은행.pdf ===")
    r3 = parse_bank24_pdf(p3)
    for k in keys:
        print(f"  {k}: {r3.get(k, '')}")
else:
    print(f"\n  SKIP (없음): {p3}")

# ── 회귀: 기존 신한은행 샘플들 ────────────────────────────────────────────────
for fn in [
    r'C:\Bank24Extractor\pdf\01-2605-3-1631._0311260760.pdf',
    r'C:\Bank24Extractor\pdf\01-2606-3-1853_2026171622.pdf',
]:
    if os.path.exists(fn):
        print(f"\n=== {os.path.basename(fn)} ===")
        rx = parse_bank24_pdf(fn)
        for k in keys:
            print(f"  {k}: {rx.get(k, '')}")
    else:
        print(f"\n  SKIP (없음): {fn}")

print("\n=== ALL DONE ===")
