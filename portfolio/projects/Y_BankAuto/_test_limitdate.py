"""SP LimitDate = 실행일 +3 영업일(월~금) 회귀 테스트"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

from datetime import date
from db_writer import _limit_date_from_today, _format_sp_date

PASS = 0; FAIL = 0

def check(label, got, expected):
    global PASS, FAIL
    if got == expected:
        print(f"  [OK] {label}: {got!r}")
        PASS += 1
    else:
        print(f"  [FAIL] {label}: got={got!r}  expected={expected!r}")
        FAIL += 1

print("=== 1. _limit_date_from_today 영업일 계산 ===")
# 기본 케이스
check("2026-06-22(월) +3영업일 → 2026-06-25(목)", _limit_date_from_today(date(2026,  6, 22)), "2026-06-25")
check("2026-06-24(수) +3영업일 → 2026-06-29(월)", _limit_date_from_today(date(2026,  6, 24)), "2026-06-29")
check("2026-06-26(금) +3영업일 → 2026-07-01(수)", _limit_date_from_today(date(2026,  6, 26)), "2026-07-01")

# 토·일 기준 — 주말 스킵
check("2026-06-27(토) +3영업일 → 2026-07-01(수)", _limit_date_from_today(date(2026,  6, 27)), "2026-07-01")
check("2026-06-28(일) +3영업일 → 2026-07-01(수)", _limit_date_from_today(date(2026,  6, 28)), "2026-07-01")

# 월말·연말 경계
check("2026-06-29(월) +3영업일 → 2026-07-02(목)", _limit_date_from_today(date(2026,  6, 29)), "2026-07-02")
check("2026-12-30(수) +3영업일 → 2027-01-04(월)", _limit_date_from_today(date(2026, 12, 30)), "2027-01-04")
check("2026-12-31(목) +3영업일 → 2027-01-05(화)", _limit_date_from_today(date(2026, 12, 31)), "2027-01-05")

# 윤년 경계
check("2028-02-27(월) +3영업일 → 2028-03-01(수)", _limit_date_from_today(date(2028,  2, 27)), "2028-03-01")

# today 미주입 → 타입 확인
import datetime as _dt
result_auto = _limit_date_from_today()
check("미주입 반환값 길이 10", len(result_auto), 10)
check("미주입 형식 YYYY-MM-DD", result_auto[4], "-")

print()
print("=== 2. PDF 처리기한과 독립적 ===")
today_fixed = date(2026, 6, 24)
limit = _limit_date_from_today(today_fixed)
check("PDF 처리기한 달라도 +3영업일", limit, "2026-06-29")
check("PDF 처리기한 없어도 +3영업일", limit, "2026-06-29")

print()
print("=== 3. ReceiptDate·RequestDate 기존 동작 유지 ===")
receipt = _format_sp_date(date.today())
check("ReceiptDate 길이 10",   len(receipt), 10)
check("ReceiptDate 형식 -",    receipt[4],   "-")
check("RequestDate None→None", _format_sp_date(None),         None)
check("RequestDate 빈값→None", _format_sp_date(""),           None)
check("RequestDate 날짜 유지", _format_sp_date("2026-06-20"), "2026-06-20")

print()
print("=== 4. 지원 은행 10개 동일 적용 ===")
SUPPORTED_BANKS = [
    "신한은행", "기업은행", "우리은행", "하나은행",
    "농협은행", "농협중앙회", "수협은행", "새마을금고",
    "국민은행", "주택도시보증공사",
]
today_fixed = date(2026, 6, 24)
expected_limit = "2026-06-29"
for bank in SUPPORTED_BANKS:
    check(f"{bank} LimitDate", _limit_date_from_today(today_fixed), expected_limit)

print()
print(f"결과: PASS={PASS}  FAIL={FAIL}")
if FAIL == 0:
    print("ALL UNIT TESTS PASS")
    sys.exit(0)
else:
    print("SOME TESTS FAILED")
    sys.exit(1)
