# -*- coding: utf-8 -*-
"""다필지 대상 PDF 파서 + SP mock 검증"""
import sys, os, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')

from pdf_parser import parse_bank24_pdf
from db_writer import (
    _parse_address, _format_bun, parse_building_detail,
    resolve_category_code, extract_hoetc_from_addr,
    extract_additional_lot_hoetc, build_representative_address,
    _supplement_building_detail,
)

base = r'D:\AI\Claude\Y_BankAuto\다필지'

def sp_mock(item):
    """insert_apw_master_expand 핵심 경로만 시뮬레이션 (DB 접속 없음)."""
    rep_addr, _, _ = build_representative_address(item)
    parsed = _parse_address(rep_addr) if rep_addr else {"San":1,"Bun1":"","Bun2":""}
    bld = _supplement_building_detail(parse_building_detail(rep_addr), item)

    sp_ho = (item.get("DB 대표호수") or "").strip() or bld["ho"]
    if sp_ho.endswith("호"):
        sp_ho = re.sub(r'\s+', ' ', sp_ho[:-1].strip())

    if (item.get("DB hoetc") or "").strip():
        hoetc = (item.get("DB hoetc") or "").strip()[:50]
    else:
        hoetc = extract_hoetc_from_addr(rep_addr, sp_ho)
        if not hoetc:
            hoetc = extract_additional_lot_hoetc(rep_addr, sp_ho)

    category = resolve_category_code(item, rep_addr, building_name=bld.get("building", ""))
    bun1 = _format_bun(parsed["Bun1"])
    bun2 = _format_bun(parsed["Bun2"])

    return {
        "BUN1": bun1, "BUN2": bun2,
        "Ho": sp_ho, "hoetc": hoetc,
        "Category": category,
    }

all_ok = True

# ──────────────────────────────────────────────────────────────────────────────
# 0356260411: 기업은행 새주소 상세 다호수
# ──────────────────────────────────────────────────────────────────────────────
pdf_ibk = os.path.join(base, '01-2606-3-1936_기업(구분건물).pdf')
if os.path.exists(pdf_ibk):
    item = parse_bank24_pdf(pdf_ibk)
    print('=== 0356260411 (기업은행 구분건물) ===')
    print('  status:', item.get('처리상태'))
    print('  DB 대표호수:', repr(item.get('DB 대표호수')))
    print('  DB hoetc:',    repr(item.get('DB hoetc')))
    print('  pdf_소재지:',  repr(item.get('pdf_소재지')))

    exp_ho = '522'
    exp_etc = '523,524호'
    ok1 = item.get('DB 대표호수') == exp_ho
    ok2 = item.get('DB hoetc') == exp_etc
    print('  PARSER DB 대표호수:', 'OK' if ok1 else 'FAIL(%r)' % item.get('DB 대표호수'))
    print('  PARSER DB hoetc:',   'OK' if ok2 else 'FAIL(%r)' % item.get('DB hoetc'))
    if not (ok1 and ok2): all_ok = False

    sp = sp_mock(item)
    print('  SP BUN1:', sp['BUN1'], '  BUN2:', sp['BUN2'])
    print('  SP Ho:',   repr(sp['Ho']), '  hoetc:', repr(sp['hoetc']))
    print('  SP Category:', sp['Category'])
    ok_bun  = (sp['BUN1'] == '1098' and sp['BUN2'] == '0002')
    ok_ho   = (sp['Ho'] == '522')
    ok_etc  = (sp['hoetc'] == '523,524호')
    ok_cat  = (sp['Category'] == '30')
    print('  SP BUN:', 'OK' if ok_bun else 'FAIL(%s/%s)' % (sp['BUN1'], sp['BUN2']))
    print('  SP Ho:', 'OK' if ok_ho else 'FAIL')
    print('  SP hoetc:', 'OK' if ok_etc else 'FAIL')
    print('  SP Category:', 'OK' if ok_cat else 'FAIL')
    if not (ok_bun and ok_ho and ok_etc and ok_cat): all_ok = False
    print()
else:
    print('SKIP 0356260411: 파일 없음', pdf_ibk)

# ──────────────────────────────────────────────────────────────────────────────
# 0640260794: 명시된 추가 필지 hoetc (다른 기업은행 파일)
# 파일명 추측: 01-2606-3-1952_의뢰.pdf 또는 비슷한 파일
# ──────────────────────────────────────────────────────────────────────────────
# 두 의뢰.pdf 파일 중 포천시 466-4가 있는 파일 탐색
for fname in ['01-2606-3-1952_의뢰.pdf', '01-2606-3-1959_의뢰.pdf']:
    pdf_lot = os.path.join(base, fname)
    if not os.path.exists(pdf_lot):
        continue
    item = parse_bank24_pdf(pdf_lot)
    rep, _, _ = build_representative_address(item)
    if '466' not in rep:
        continue
    print('=== 0640260794 (%s) ===' % fname)
    print('  status:', item.get('처리상태'))
    print('  pdf_소재지:', repr(item.get('pdf_소재지')))
    print('  DB hoetc:',  repr(item.get('DB hoetc')))
    sp = sp_mock(item)
    print('  SP BUN1:', sp['BUN1'], '  BUN2:', sp['BUN2'])
    print('  SP Ho:',  repr(sp['Ho']),   '  hoetc:', repr(sp['hoetc']))
    print('  SP Category:', sp['Category'])
    ok_bun = (sp['BUN1'] == '0466' and sp['BUN2'] == '0004')
    ok_ho  = (sp['Ho'] == '')
    ok_etc = (sp['hoetc'] == '467-1, 466-2')
    ok_cat = (sp['Category'] == '03')  # 근린생활시설+건물명없음+호수없음 → 03
    print('  SP BUN:', 'OK' if ok_bun else 'FAIL(%s/%s)' % (sp['BUN1'], sp['BUN2']))
    print('  SP Ho:', 'OK' if ok_ho else 'FAIL(%r)' % sp['Ho'])
    print('  SP hoetc:', 'OK' if ok_etc else 'FAIL(%r)' % sp['hoetc'])
    print('  SP Category:', 'OK' if ok_cat else 'FAIL')
    if not (ok_bun and ok_ho and ok_etc and ok_cat): all_ok = False
    print()
    break

# ──────────────────────────────────────────────────────────────────────────────
# 3006124423: 지역농협 + 추가 필지 + 채무자 전화번호
# ──────────────────────────────────────────────────────────────────────────────
for fname in ['01-2606-3-1952_의뢰.pdf', '01-2606-3-1959_의뢰.pdf']:
    pdf_nhc = os.path.join(base, fname)
    if not os.path.exists(pdf_nhc):
        continue
    item = parse_bank24_pdf(pdf_nhc)
    if item.get('은행') not in ('농협중앙회', '농협은행'):
        continue
    if '193' not in (item.get('pdf_소재지') or ''):
        continue
    print('=== 3006124423 (%s) ===' % fname)
    print('  status:', item.get('처리상태'))
    print('  은행:', repr(item.get('은행')))
    print('  영업점:', repr(item.get('영업점')))
    print('  pdf_소재지:', repr(item.get('pdf_소재지')))
    print('  DB hoetc:',  repr(item.get('DB hoetc')))
    print('  채무자 연락처:', repr(item.get('채무자 연락처')))

    ok_sojaegi = ('193-19' in (item.get('pdf_소재지') or ''))
    ok_etc     = (item.get('DB hoetc') == '-17, 산169-6')
    ok_phone   = (item.get('채무자 연락처') == '0322533456')
    print('  PARSER 소재지 193-19:', 'OK' if ok_sojaegi else 'FAIL')
    print('  PARSER DB hoetc:', 'OK' if ok_etc else 'FAIL(%r)' % item.get('DB hoetc'))
    print('  PARSER 채무자 연락처:', 'OK' if ok_phone else 'FAIL(%r)' % item.get('채무자 연락처'))
    if not (ok_sojaegi and ok_etc and ok_phone): all_ok = False

    sp = sp_mock(item)
    print('  SP BUN1:', sp['BUN1'], '  BUN2:', sp['BUN2'])
    print('  SP Ho:',  repr(sp['Ho']),  '  hoetc:', repr(sp['hoetc']))
    ok_bun = (sp['BUN1'] == '0193' and sp['BUN2'] == '0019')
    ok_ho  = (sp['Ho'] == '')
    ok_sp_etc = (sp['hoetc'] == '-17, 산169-6')
    print('  SP BUN:', 'OK' if ok_bun else 'FAIL(%s/%s)' % (sp['BUN1'], sp['BUN2']))
    print('  SP Ho:', 'OK' if ok_ho else 'FAIL(%r)' % sp['Ho'])
    print('  SP hoetc:', 'OK' if ok_sp_etc else 'FAIL(%r)' % sp['hoetc'])
    if not (ok_bun and ok_ho and ok_sp_etc): all_ok = False
    print()
    break

# ──────────────────────────────────────────────────────────────────────────────
# 0002260565 회귀: 기업은행 구분건물 대표 지번/호수 불변
# ──────────────────────────────────────────────────────────────────────────────
pdf_regr = r'D:\AI\Claude\Y_BankAuto\기업은행\0002260565.pdf'
if os.path.exists(pdf_regr):
    item = parse_bank24_pdf(pdf_regr)
    print('=== 0002260565 회귀 (기업은행) ===')
    print('  status:', item.get('처리상태'))
    print('  DB 대표호수:', repr(item.get('DB 대표호수')))
    print('  DB hoetc:',   repr(item.get('DB hoetc')))
    sp = sp_mock(item)
    print('  SP BUN1:', sp['BUN1'], '  BUN2:', sp['BUN2'])
    print('  SP Ho:',  repr(sp['Ho']),  '  hoetc:', repr(sp['hoetc']))
    print('  SP Category:', sp['Category'])
    ok_bun  = (sp['BUN1'] == '0774' and sp['BUN2'] == '0002')
    ok_ho   = (sp['Ho'] in ('제1202', '1202'))
    ok_etc  = (sp['hoetc'] == '')
    ok_cat  = (sp['Category'] == '30')
    print('  BUN: ', 'OK' if ok_bun else 'FAIL(%s/%s)' % (sp['BUN1'], sp['BUN2']))
    print('  Ho:  ', 'OK' if ok_ho else 'FAIL(%r)' % sp['Ho'])
    print('  hoetc:', 'OK' if ok_etc else 'FAIL(%r)' % sp['hoetc'])
    print('  Cat: ', 'OK' if ok_cat else 'FAIL')
    if not (ok_bun and ok_ho and ok_etc and ok_cat): all_ok = False
    print()
else:
    print('SKIP 0002260565: 파일 없음')

print('ALL PASS' if all_ok else 'SOME FAIL')
