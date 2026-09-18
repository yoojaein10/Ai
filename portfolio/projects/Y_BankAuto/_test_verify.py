import sys, re
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from pdf_parser import (
    _is_person_name, _is_employee_name_candidate,
    _is_valid_branch, _is_business_label,
    _BAD_BRANCH_ENDINGS, _is_stop, _is_date, _is_phone, _is_label,
)
from db_writer  import has_unit_no, parse_building_detail

# _good_branch는 parse_bank24_pdf() 안의 로컬 함수이므로 여기서 동일하게 재현
def _bad(v):
    if not v: return True
    if _is_stop(v) or _is_date(v) or _is_phone(v) or _is_label(v): return True
    if '@' in v or 'E-Mail' in v: return True
    if any(v.endswith(e) for e in _BAD_BRANCH_ENDINGS): return True
    return len(v) < 2

def _good_branch(v):
    return bool(v and not _bad(v) and not _is_business_label(v) and _is_valid_branch(v))

print('=== helper 검증 ===')
cases = [
    ('_is_person_name',            _is_person_name,            '장준민', True),
    ('_is_person_name',            _is_person_name,            '자양동', False),
    ('_is_employee_name_candidate',_is_employee_name_candidate,'자양동', True),
    ('_good_branch',               _good_branch,               '자양동', True),
]
for fn, f, v, exp in cases:
    got  = f(v)
    mark = 'OK' if got == exp else 'FAIL'
    print(f'  [{mark}] {fn}({v!r}) = {got}  (기대: {exp})')

print()
print('=== has_unit_no() 단위 테스트 ===')
hcases = [
    ('경기 하남시 신장동 427-93번지 베라시떼 1-2001', True),
    ('서울 송파구 문정동 651번지 A 115호',            True),
    ('서울 강서구 마곡동 774-2번지 리더스애비뉴 2층 제1202호', True),
    ('경기 하남시 신장동 427-93번지',   False),
    ('경기 가평군 상면 163번지',        False),
    ('서울 중구 광희동2가 359번지',     False),
]
for addr, exp in hcases:
    got  = has_unit_no(addr)
    mark = 'OK' if got == exp else 'FAIL'
    print(f'  [{mark}] has_unit_no({addr!r}) = {got}  (기대: {exp})')

print()
print('=== parse_building_detail() 단위 테스트 ===')
# NOEST 케이스
addr1 = '경기 하남시 신장동 427-93번지 베라시떼 1-2001'
r1 = parse_building_detail(addr1)
exp1 = {'building': '베라시떼', 'dong': '', 'floor': '', 'ho': '1-2001'}
mark1 = 'OK' if r1 == exp1 else 'FAIL'
print(f'  [{mark1}] NOEST 케이스: {addr1!r}')
print(f'         결과: {r1}')
print(f'         기대: {exp1}')

# SP mock params
sp_ho1    = r1['ho']  # no "호" suffix
sp_floor1 = r1['floor']
print(f'         SP Building={r1["building"]!r}  Ho={sp_ho1!r}  Floor={sp_floor1!r}')

print()
# 회귀 케이스
addr2 = '서울 강서구 마곡동 774-2번지 리더스애비뉴 2층 제1202호'
r2 = parse_building_detail(addr2)
exp2 = {'building': '리더스애비뉴', 'dong': '', 'floor': '2층', 'ho': '제1202호'}
mark2 = 'OK' if r2 == exp2 else 'FAIL'
print(f'  [{mark2}] 회귀 케이스: {addr2!r}')
print(f'         결과: {r2}')
print(f'         기대: {exp2}')

sp_floor2 = r2['floor'][:-1] if r2['floor'].endswith('층') else r2['floor']
sp_ho2    = re.sub(r'\s+', '', r2['ho'][:-1].strip()) if r2['ho'].endswith('호') else r2['ho']
print(f'         SP Floor={sp_floor2!r} (기대:2)  Ho={sp_ho2!r} (기대:제1202)')
