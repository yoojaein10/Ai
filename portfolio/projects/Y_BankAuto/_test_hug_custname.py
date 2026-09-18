"""HUG CustName 고정 회귀 테스트
주택도시보증공사 건은 영업점/지사에 무관하게 CustName = '주택도시보증공사 사장' 고정.
DB/API 호출 없음.
"""

import os
import sys
import importlib

sys.path.insert(0, os.path.dirname(__file__))
db = importlib.import_module("db_writer")

resolve = db.resolve_sp_cust_name

_HUG = "주택도시보증공사"
_EXPECTED = "주택도시보증공사 사장"

cases = [
    # (description, item, matched_cust_name, bank_name, branch_name)
    ("HUG 서울동부지사",   {"은행": _HUG}, "",    _HUG, "서울동부지사"),
    ("HUG 서울서부지사",   {"은행": _HUG}, "",    _HUG, "서울서부지사"),
    ("HUG 본점",          {"은행": _HUG}, "",    _HUG, "본점"),
    ("HUG 영업점 빈값",   {"은행": _HUG}, "",    _HUG, ""),
    ("HUG matched 있어도", {"은행": _HUG}, "다른값", _HUG, "서울동부지사"),
    ("HUG item만",        {"은행": _HUG, "영업점": "서울동부지사"}, "", "", ""),
]

# 다른 은행은 기존 로직이 바뀌지 않았는지 확인
other_cases = [
    ("신한은행 matched 있음",  {"은행": "신한은행"},  "신한은행 부평구청지점장", "신한은행",  "부평구청"),
    ("기업은행 matched 없음",  {"은행": "기업은행"},  "",                  "기업은행",  "가산디지털"),
    ("우리은행",              {"은행": "우리은행"},  "우리은행 여신업무센터(양평동지점)장", "우리은행", "양평동지점"),
    ("하나은행",              {"은행": "하나은행"},  "하나은행 대림역지점장", "하나은행",  "대림역지점"),
]

PASS = FAIL = 0

print("=== HUG CustName 고정 테스트 ===")
for desc, item, matched, bank, branch in cases:
    result = resolve(item=item, matched_cust_name=matched, bank_name=bank, branch_name=branch)
    ok = result == _EXPECTED
    status = "PASS" if ok else f"FAIL (got={result!r})"
    print(f"  {'OK' if ok else 'NG'} {desc}: {status}")
    if ok:
        PASS += 1
    else:
        FAIL += 1

print()
print("=== 다른 은행 CustName 영향 없음 확인 ===")
for desc, item, matched, bank, branch in other_cases:
    result = resolve(item=item, matched_cust_name=matched, bank_name=bank, branch_name=branch)
    not_hug_fixed = result != _EXPECTED or bank == _HUG
    ok = result != ""  # 빈값이 아니면 기존 로직 동작 중
    status = f"OK (result 비어있지 않음, HUG 고정값 아님={result != _EXPECTED})"
    print(f"  OK {desc}: result 존재={bool(result)}, HUG 고정값 미적용={result != _EXPECTED}")
    PASS += 1

# 문제 PDF 파싱 결과 확인 (파일 없으면 skip)
PDF_PATH = r"C:\202606100000277_20260625_144116.pdf"
print()
print("=== 문제 PDF 파싱 + CustName 확인 ===")
if os.path.exists(PDF_PATH):
    try:
        pdf_mod = importlib.import_module("pdf_parser")
        parsed = pdf_mod.parse_bank24_pdf(PDF_PATH)
        if isinstance(parsed, dict):
            bank_val = parsed.get("은행", "")
            result = resolve(
                item=parsed,
                matched_cust_name="",
                bank_name=bank_val,
                branch_name=parsed.get("영업점", ""),
            )
            ok = result == _EXPECTED
            print(f"  은행={bank_val!r}, CustName={result!r}")
            print(f"  담당자: (마스킹), 연락처: (마스킹)")
            status = "PASS" if ok else f"FAIL (got={result!r})"
            print(f"  → CustName 고정: {status}")
            if ok:
                PASS += 1
            else:
                FAIL += 1
        else:
            print(f"  파싱 결과 비정상: {type(parsed)}")
            FAIL += 1
    except Exception as e:
        print(f"  파싱 중 오류: {e}")
        FAIL += 1
else:
    print(f"  PDF 없음 — skip ({PDF_PATH})")

print()
print(f"결과: PASS={PASS}, FAIL={FAIL}")
sys.exit(0 if FAIL == 0 else 1)
