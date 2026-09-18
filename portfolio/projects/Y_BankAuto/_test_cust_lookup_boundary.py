# -*- coding: utf-8 -*-
"""lookup_cust_code 회귀 테스트 (DB 불필요, FakeConn 사용)

검증 대상:
1. 영업점 어절 경계 매칭 — '계동'이 '상계동지점'에 오탐되지 않아야 함
2. 하나은행 표기 변형 — 'KEB하나은행' PDF가 '하나은행 xx지점' 등록건을 찾아야 함
3. PDF 은행명(primary) 우선 — 동일 지점이 양쪽 표기로 있으면 PDF 표기 우선
4. 기존 동작 회귀 없음 — 정확매칭/타행/빈값
"""
import re
import sys

sys.path.insert(0, r"D:\AI\Claude\Y_BankAuto")
from db_writer import lookup_cust_code


def _like_to_re(pattern: str):
    return re.compile("^" + ".*".join(re.escape(p) for p in pattern.split("%")) + "$")


class FakeCursor:
    """lookup_cust_code가 생성하는 SQL만 해석하는 최소 구현."""

    def __init__(self, table):
        self._table = table  # [(CustID, CustName, Active), ...] 전부 Office='10' 가정
        self._rows = []

    def execute(self, sql, params=()):
        where = sql.split(" WHERE ", 1)[1]
        conds = where.split(" AND ")
        params = list(params)
        checks = []  # CustName에 대한 판정 함수 목록
        for cond in conds:
            cond = cond.strip()
            if cond == "Office='10'":
                continue
            if cond == "Active='Y'":
                checks.append(("active", None))
            elif cond == "CustName=?":
                checks.append(("eq", params.pop(0)))
            elif cond == "CustName LIKE ?":
                checks.append(("like", _like_to_re(params.pop(0))))
            elif cond.startswith("(") and cond.endswith(")"):
                pats = []
                for part in cond[1:-1].split(" OR "):
                    assert part.strip() == "CustName LIKE ?", f"미지원 조건: {part}"
                    pats.append(_like_to_re(params.pop(0)))
                checks.append(("like_or", pats))
            else:
                raise AssertionError(f"미지원 조건: {cond}")
        assert not params, "파라미터 수 불일치"

        def ok(row):
            cid, cname, active = row
            for kind, arg in checks:
                if kind == "active" and active != "Y":
                    return False
                if kind == "eq" and cname != arg:
                    return False
                if kind == "like" and not arg.match(cname):
                    return False
                if kind == "like_or" and not any(p.match(cname) for p in arg):
                    return False
            return True

        self._rows = [r for r in self._table if ok(r)]

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, table):
        self._table = table

    def cursor(self):
        return FakeCursor(self._table)


TABLE = [
    ("001982", "하나은행 상계동지점",     "Y"),
    ("002524", "하나은행 하계동지점",     "Y"),
    ("005031", "하나은행 중계동지점장",   "Y"),
    ("012137", "KEB하나은행 상계동지점",  "Y"),
    ("014227", "KEB하나은행 중계동지점",  "Y"),
    ("014447", "하나은행 계동지점",       "Y"),
    ("017079", "하나은행 호계동지점",     "Y"),
    ("020001", "신한은행 신길동지점",     "Y"),
    ("020002", "신한은행 길동지점",       "Y"),
    ("030001", "국민은행 종로지점",       "Y"),
    ("040001", "KEB하나은행 서소문지점",  "Y"),
    ("040002", "하나은행 서소문지점",     "N"),
]

CASES = [
    # (설명, bank_name, branch_name, 기대 CustID)
    ("계동 → 상계동 오탐 방지 + 하나은행 표기 변형", "KEB하나은행", "계동",   "014447"),
    ("하나은행 표기로도 동일 결과",                  "하나은행",    "계동",   "014447"),
    ("상계동은 PDF 표기(KEB) 우선",                  "KEB하나은행", "상계동", "012137"),
    ("하나은행 표기 PDF의 상계동은 하나은행 우선",   "하나은행",    "상계동", "001982"),
    ("타행 어절 경계: 길동이 신길동에 오탐 금지",    "신한은행",    "길동",   "020002"),
    ("타행 부분 문자열 매칭 유지: 신길동",           "신한은행",    "신길동", "020001"),
    ("타행 기존 동작: 단일후보 부분매칭",            "국민은행",    "종로",   "030001"),
    ("Active 우선(동일 지점 양표기, 하나는 N)",      "하나은행",    "서소문", "040001"),
]


def main():
    conn = FakeConn(TABLE)
    fails = 0
    for desc, bank, branch, expect in CASES:
        r = lookup_cust_code(conn, bank, branch)
        got = r["CustCode"]
        status = "PASS" if got == expect else "FAIL"
        if status == "FAIL":
            fails += 1
        print(f"[{status}] {desc}: ({bank}, {branch}) → {got} ({r['CustName']}, method={r['method']})"
              + ("" if status == "PASS" else f"  기대={expect}"))

    # 빈값 가드
    r = lookup_cust_code(conn, "", "")
    status = "PASS" if not r["matched"] else "FAIL"
    if status == "FAIL":
        fails += 1
    print(f"[{status}] 빈값 → 미매칭")

    print(f"\n{'ALL PASS' if fails == 0 else f'{fails} FAILED'}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
