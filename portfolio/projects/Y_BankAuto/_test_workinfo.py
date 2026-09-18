# -*- coding: utf-8 -*-
"""WorkInfo(업무정보) 코드 결정 회귀 검증.

규칙: 기본 '30'. 단 주택도시보증공사(HUG) + 감정평가담보구분='일반거래용' → '80'.
"""
import sys
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from db_writer import resolve_workinfo_code

CASES = [
    # (item, 기대값, 설명)
    ({"은행": "주택도시보증공사", "감정평가담보구분": "일반거래용"}, "80", "HUG 일반거래용 → 80"),
    ({"은행": "주택도시보증공사", "감정평가담보구분": "담보제공용"}, "30", "HUG 담보제공용 → 30"),
    ({"은행": "주택도시보증공사", "감정평가담보구분": ""},          "30", "HUG 구분없음 → 30"),
    ({"은행": "국민은행",         "감정평가담보구분": "일반거래용"}, "30", "비HUG는 일반거래용이어도 30"),
    ({"은행": "신한은행",         "감정평가담보구분": ""},          "30", "일반 은행 → 30"),
    ({},                                                          "30", "빈 item → 30"),
]

all_pass = True
for item, expected, desc in CASES:
    got = resolve_workinfo_code(item)
    ok = got == expected
    all_pass = all_pass and ok
    print("%s: %s (got=%s, exp=%s)" % ("PASS" if ok else "FAIL", desc, got, expected))

print()
print("ALL PASS" if all_pass else "SOME FAILED")
sys.exit(0 if all_pass else 1)
