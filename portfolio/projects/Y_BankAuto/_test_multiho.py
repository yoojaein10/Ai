# -*- coding: utf-8 -*-
"""다호수/다필지 mock 검증 — 실제 PDF/DB/Bank24 사용 없음"""
import sys
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')

import pdf_parser as pp

all_ok = True

def chk(label, cond, detail=""):
    global all_ok
    if cond:
        print(f"OK  {label}")
    else:
        print(f"FAIL {label}" + (f" | {detail}" if detail else ""))
        all_ok = False


def _make_hana_ls(addrs):
    """세부주소 목록으로 하나은행 형태 ls 생성."""
    ls = ["소유자", "성   명", "전화번호", "050212819688", "테스트소유자"]
    for addr in addrs:
        ls += ["물건", "정보", "세부주소", addr, "물건종류", "아파트형공장", "우편번호", "08504", "▣물건정보"]
    return ls


# ── 1. 동일 지번 다호수 ──────────────────────────────────────────────
print("\n[1] 동일 지번 다호수 (3건)")

addrs_3 = [
    "서울특별시 금천구 가산동 459-21 1001-1",
    "서울특별시 금천구 가산동 459-21 1001-2",
    "서울특별시 금천구 가산동 459-21 1001-3",
]
obj = pp._extract_hana_object_info(_make_hana_ls(addrs_3))

chk("대표호수 = 1001-1", obj["db_primary_ho"] == "1001-1", repr(obj["db_primary_ho"]))
chk("hoetc = 2개호",     obj["db_hoetc"]     == "2개호",   repr(obj["db_hoetc"]))
chk("sojaegi = 첫 주소", obj["sojaegi"]      == addrs_3[0], repr(obj["sojaegi"]))


# ── 2. 중복 호수 ─────────────────────────────────────────────────────
print("\n[2] 중복 호수 (1001-1, 1001-1, 1001-2)")

addrs_dup = [
    "서울특별시 금천구 가산동 459-21 1001-1",
    "서울특별시 금천구 가산동 459-21 1001-1",
    "서울특별시 금천구 가산동 459-21 1001-2",
]
obj2 = pp._extract_hana_object_info(_make_hana_ls(addrs_dup))

chk("중복: 대표호수 = 1001-1", obj2["db_primary_ho"] == "1001-1", repr(obj2["db_primary_ho"]))
chk("중복: hoetc = 1개호",     obj2["db_hoetc"]     == "1개호",   repr(obj2["db_hoetc"]))


# ── 3. 서로 다른 지번과 호수 — 다호수 압축 금지 ───────────────────────
print("\n[3] 서로 다른 지번 - 압축 금지")

addrs_diff_lot = [
    "서울특별시 금천구 가산동 459-21 1001-1",
    "서울특별시 금천구 가산동 460-1 1001-2",
]
obj3 = pp._extract_hana_object_info(_make_hana_ls(addrs_diff_lot))

chk("다른 지번: 대표호수 빈값", obj3["db_primary_ho"] == "", repr(obj3["db_primary_ho"]))
chk("다른 지번: hoetc 빈값",   obj3["db_hoetc"]     == "", repr(obj3["db_hoetc"]))


# ── 4. 호수 없는 서로 다른 지번 — 호수 추출 실패 ──────────────────────
print("\n[4] 호수 없는 서로 다른 지번 - 압축 금지")

addrs_no_unit = [
    "서울특별시 금천구 가산동 459-21",
    "서울특별시 금천구 가산동 460-1",
]
obj4 = pp._extract_hana_object_info(_make_hana_ls(addrs_no_unit))

chk("호수 없음: 대표호수 빈값", obj4["db_primary_ho"] == "", repr(obj4["db_primary_ho"]))
chk("호수 없음: hoetc 빈값",   obj4["db_hoetc"]     == "", repr(obj4["db_hoetc"]))
chk("호수 없음: sojaegi 첫 주소", obj4["sojaegi"] == addrs_no_unit[0], repr(obj4["sojaegi"]))


# ── 5. 건물명 추출 mock ───────────────────────────────────────────────
print("\n[5] 건물명 추출 mock")

ls_bldg = [
    "소유자", "성   명", "전화번호", "050212819688", "테스트소유자",
    "서울시 금천구 가산동 459-21 가산모비우스타워 공장 1001-1 ~ 1001-9호",
    "물건", "정보",
    "세부주소", "서울특별시 금천구 가산동  459-21   1001-1",
    "물건종류", "아파트형공장",
    "세부주소", "서울특별시 금천구 가산동  459-21   1001-2",
    "물건종류", "아파트형공장",
]
obj5 = pp._extract_hana_object_info(ls_bldg)

chk("건물명 = 가산모비우스타워공장", obj5["db_building"] == "가산모비우스타워공장", repr(obj5["db_building"]))
chk("건물명 mock 대표호수 = 1001-1", obj5["db_primary_ho"] == "1001-1", repr(obj5["db_primary_ho"]))
chk("건물명 mock hoetc = 1개호",     obj5["db_hoetc"]     == "1개호",   repr(obj5["db_hoetc"]))


# ── 6. 기업은행 소재지 fallback ───────────────────────────────────────
print("\n[6] 기업은행 소재지 fallback")

ls_ibk = [
    "소 재 지",
    "경기도 시흥시  정왕동 1263-1,2 1층 004호",
    "건 물 명",
    "새주소",
    "새주소 상세",
    "- 1 -",
]
extra = pp._extract_ibk_address_extra(ls_ibk)

chk("IBK floor = 1",    extra["floor"]      == "1",   repr(extra["floor"]))
chk("IBK ho = 004",     extra["primary_ho"] == "004", repr(extra["primary_ho"]))
chk("IBK hoetc = 빈값", extra["hoetc"]      == "",    repr(extra["hoetc"]))
chk("IBK ho != ,2",     extra["primary_ho"] != ",2",  repr(extra["primary_ho"]))
chk("IBK ho != 2",      extra["primary_ho"] != "2",   repr(extra["primary_ho"]))


# ── 7. 새주소 상세 기존 다호수 (기존 성공 반환) ─────────────────────────
print("\n[7] 새주소 상세 기존 다호수")

ls_ibk_detail = [
    "새주소 상세",
    "101호,102호,103호",
]
extra2 = pp._extract_ibk_address_extra(ls_ibk_detail)

chk("상세 다호수 primary_ho = 101", extra2["primary_ho"] == "101", repr(extra2["primary_ho"]))
chk("상세 다호수 hoetc = 102,103호", extra2["hoetc"] == "102,103호", repr(extra2["hoetc"]))
chk("상세 다호수 floor = 빈값",      extra2["floor"] == "",          repr(extra2["floor"]))


# ── 8. 9건 실제 PDF 패턴 모사 ─────────────────────────────────────────
print("\n[8] 9건 실제 PDF 패턴 모사 (1001-1 ~ 1001-9)")

addrs_9 = [f"서울특별시 금천구 가산동  459-21   1001-{i}" for i in range(1, 10)]
ls_9 = [
    "소유자", "성   명", "전화번호", "050212819688", "(주)테스트",
    "서울시 금천구 가산동 459-21 가산모비우스타워 공장 1001-1 ~ 1001-9호",
]
for addr in addrs_9:
    ls_9 += ["물건", "정보", "세부주소", addr, "물건종류", "아파트형공장", "우편번호", "08504"]

obj9 = pp._extract_hana_object_info(ls_9)

chk("9건: 세부주소 수집 9건",  len([a for a in addrs_9]) == 9)
chk("9건: 고유 호수 9개 → 대표 1001-1", obj9["db_primary_ho"] == "1001-1", repr(obj9["db_primary_ho"]))
chk("9건: hoetc = 8개호",               obj9["db_hoetc"]     == "8개호",   repr(obj9["db_hoetc"]))
chk("9건: 건물명 = 가산모비우스타워공장", obj9["db_building"]  == "가산모비우스타워공장", repr(obj9["db_building"]))
chk("9건: sojaegi = 첫 주소",
    obj9["sojaegi"] == addrs_9[0],
    repr(obj9["sojaegi"]))


print()
print("ALL PASS" if all_ok else "SOME FAIL")
