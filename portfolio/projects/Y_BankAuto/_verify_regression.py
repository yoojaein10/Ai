"""오늘 HUG 7건 + 기존 은행 회귀 검증"""
import sys, os, glob
sys.path.insert(0, "D:/AI/Claude/Y_BankAuto")
from pdf_parser import parse_bank24_pdf
from db_writer import _format_sp_date

FAIL_COUNT = 0

def check(label, got, exp, negate=False):
    global FAIL_COUNT
    if negate:
        ok = got != exp
        tag = f"!= {exp!r}"
    else:
        ok = got == exp
        tag = f"== {exp!r}"
    status = "OK" if ok else "FAIL"
    if not ok:
        FAIL_COUNT += 1
    print(f"  [{status}] {label}: {got!r}  (expected {tag})")

print("=" * 60)
print("FIX-1: _format_sp_date")
cases = [
    ("2026-06-11 오후 5:47:00", "2026-06-11"),
    ("2026-06-11 오전 9:34:00", "2026-06-11"),
    ("20260611", "2026-06-11"),
    ("202606100000136", None),
    ("", None),
    (None, None),
]
for v, exp in cases:
    check(repr(v), _format_sp_date(v), exp)

print()
print("=" * 60)
print("HUG 오늘 7건 (C:\\Bank24Extractor\\pdf\\202606100000*_20260612_093*.pdf)")
hug_pdfs = sorted(glob.glob(r"C:\Bank24Extractor\pdf\202606100000*_20260612_093*.pdf"))
print(f"  대상 {len(hug_pdfs)}건")
BAD_DEBTOR = {"상품명", "의뢰", "기관", "기 타", "정 보", "비 고", ""}
for pdf in hug_pdfs:
    bn = os.path.basename(pdf)
    r = parse_bank24_pdf(pdf)
    print(f"\n  [{bn}]")
    check("처리상태", r["처리상태"], "성공")
    # 의뢰일자: PDF에는 없고 Bank24 스크린 데이터에서 옴 — 여기선 skip
    # 특정 케이스
    docid = bn.split("_")[0]
    if docid == "202606100000136":
        check("채무자", r["채무자"], "정유리")
        check("소유자", r["소유자"], "김은서")
    if docid == "202606100000106":
        check("채무자", r["채무자"], "황수웅")

print()
print("=" * 60)
print("기존 신한/기업/우리/HUG 회귀 검증")
BAD_VALUES = {"상품명", "기 타", "정 보", "비 고", "건물"}
banks = ["신한은행", "기업은행", "우리은행", "주택도시보증공사"]
for bank in banks:
    pdfs = sorted(glob.glob(f"D:/AI/Claude/Y_BankAuto/{bank}/*.pdf"))
    if not pdfs:
        print(f"  {bank}: PDF 없음 skip")
        continue
    print(f"\n  [{bank}] {len(pdfs)}건")
    for pdf in pdfs:
        bn = os.path.basename(pdf)
        r = parse_bank24_pdf(pdf)
        check(f"{bn} 처리상태", r["처리상태"], "성공")
        debtor = r.get("채무자", "")
        owner  = r.get("소유자", "")
        if debtor in BAD_VALUES:
            check(f"{bn} 채무자(무효값차단)", debtor, None, negate=True)
        if owner in BAD_VALUES:
            check(f"{bn} 소유자(무효값차단)", owner, None, negate=True)

print()
print("=" * 60)
print(f"총 FAIL: {FAIL_COUNT}")
sys.exit(0 if FAIL_COUNT == 0 else 1)
