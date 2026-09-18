# -*- coding: utf-8 -*-
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')

from pdf_parser import _extract_ibk_address_extra, _extract_nh_additional_lots
from db_writer import extract_additional_lot_hoetc, _resolve_customer_lookup_bank_name

all_ok = True

# ── 기업은행 새주소 상세 다호수 ──────────────────────────────────────────────
cases_ibk = [
    (['새주소 상세', '522호,523호,524'],   '522', '523,524호'),
    (['새주소 상세', '522호, 523호, 524호'], '522', '523,524호'),
    (['새주소 상세', '522,523,524호'],    '522', '523,524호'),
    (['새주소 상세', '일반 문자열'],       '',    ''),
    (['다른라벨',   '522호,523호'],       '',    ''),
]
for ls, exp_ho, exp_etc in cases_ibk:
    r = _extract_ibk_address_extra(ls)
    got_ho = r['primary_ho']
    got_etc = r['hoetc']
    ok = (got_ho == exp_ho and got_etc == exp_etc)
    mark = 'OK' if ok else 'FAIL'
    print('%s IBK [%s] -> ho=%r hoetc=%r  (exp=%r,%r)' % (mark, ls[-1], got_ho, got_etc, exp_ho, exp_etc))
    if not ok:
        all_ok = False

# ── 추가 필지 hoetc ───────────────────────────────────────────────────────────
cases_lot = [
    ('경기도 포천시 설운동 466-4, 467-1,466-2', '',    '467-1, 466-2'),
    ('444-12 외 4필지',                          '',    ''),
    ('293-17외 1필지',                           '',    ''),
    ('217-4,6,7',                               '',    ''),
    ('712,713,714,715',                         '',    ''),
    ('1호동 307호',                              '',    ''),
    ('경기도 포천시 설운동 466-4, 467-1,466-2', '466', ''),  # primary_ho 있으면 빈값
]
for addr, pho, exp in cases_lot:
    r = extract_additional_lot_hoetc(addr, pho)
    ok = (r == exp)
    mark = 'OK' if ok else 'FAIL'
    print('%s LOT %r pho=%r -> %r  (exp=%r)' % (mark, addr[:50], pho, r, exp))
    if not ok:
        all_ok = False

# ── 농협 추가 필지 (ls 시뮬레이션) ──────────────────────────────────────────
ls_nh = [
    '▣물건내역',
    '일련번호',
    '우편번호',
    '경기 화성시 서신면 전곡리 193-19',
    '소재지',
    '▣물건내역',
    '일련번호',
    '우편번호',
    '경기 화성시 서신면 전곡리 193-17',
    '소재지',
    '▣물건내역',
    '일련번호',
    '우편번호',
    '경기 화성시 서신면 전곡리 산169-6',
    '소재지',
]
r_nh = _extract_nh_additional_lots(ls_nh)
exp_nh = '-17, 산169-6'
ok_nh = (r_nh == exp_nh)
print('%s NH additional lots -> %r  (exp=%r)' % ('OK' if ok_nh else 'FAIL', r_nh, exp_nh))
if not ok_nh:
    all_ok = False

# ── 농협 전화번호 시뮬레이션은 _extract_nh_request_info로 (실제 PDF로 검증) ──

# ── 군자농협 lookup 이름 확장 ─────────────────────────────────────────────────
cases_nh_lookup = [
    ({'은행': '농협중앙회', '영업점': '군자농협'},          '군자농업협동조합'),
    ({'은행': '농협중앙회', '영업점': '북서울농협'},        '북서울농업협동조합'),
    ({'은행': '농협중앙회', '영업점': '서울축산농협 화곡역지점'}, '농협중앙회'),
    ({'은행': '농협중앙회', '영업점': '의정부역금융센터'},  '농협중앙회'),
    ({'은행': '농협은행',   '영업점': '군자농협'},          '농협은행'),
    ({'은행': '수협은행',   '영업점': '군자농협', '지역수협명': ''}, '수협은행'),
]
for item, exp in cases_nh_lookup:
    r = _resolve_customer_lookup_bank_name(item)
    ok = (r == exp)
    mark = 'OK' if ok else 'FAIL'
    print('%s lookup %s+%s -> %r  (exp=%r)' % (mark, item.get('은행',''), item.get('영업점',''), r, exp))
    if not ok:
        all_ok = False

print()
print('ALL PASS' if all_ok else 'SOME FAIL')
