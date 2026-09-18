# -*- coding: utf-8 -*-
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from pdf_parser import parse_bank24_pdf
from db_writer import _parse_address, _format_bun, parse_building_detail, resolve_category_code

nhc_dir = r'D:\AI\Claude\Y_BankAuto\농협중앙회'

expected = {
    '1.pdf': {
        '은행': '농협중앙회', '의뢰번호': '3006121194', '감정서번호': '01-2606-3-1912',
        '영업점': '서울축산농협 화곡역지점', '담당자': '김종희',
        '담당자 연락처': '0221815154', '소유자 연락처': '',
        '의뢰일자': '2026-06-11 오후 3:55:00', '처리기한': '2026-06-12',
        '채무자': '서울교회', '소유자': '서울교회',
        '비고': '박중현평가사님', '물건종류': '교회',
        'pdf_소재지': '서울 동대문구 답십리동  231-11',
        'BUN1': '0231', 'BUN2': '0011', 'Category': '03',
    },
    '2.pdf': {
        '은행': '농협중앙회', '의뢰번호': '3006120784', '감정서번호': '01-2606-3-1905',
        '영업점': '북서울농협', '담당자': '윤성필',
        '담당자 연락처': '0222895731', '소유자 연락처': '',
        '의뢰일자': '2026-06-11 오후 12:35:00', '처리기한': '2026-06-12',
        '채무자': '윤순호', '소유자': '윤순호',
        '비고': '노승환평가사님', '물건종류': '상가',
        'pdf_소재지': '서울 도봉구 쌍문동  138-22',
        'BUN1': '0138', 'BUN2': '0022', 'Category': '30',
    },
}

all_ok = True
for fname, exp in sorted(expected.items()):
    path = os.path.join(nhc_dir, fname)
    item = parse_bank24_pdf(path)
    rep = item.get('pdf_소재지', '') or ''
    parsed = _parse_address(rep) if rep else {}
    bun1 = _format_bun(parsed.get('Bun1', ''))
    bun2 = _format_bun(parsed.get('Bun2', ''))
    cat_code = resolve_category_code(item, rep)

    print(f'=== {fname} (status={item.get("처리상태","")}) ===')
    row_ok = True

    checks = ['은행', '의뢰번호', '감정서번호', '채무자', '소유자', '영업점', '담당자',
              '담당자 연락처', '소유자 연락처', '의뢰일자', '처리기한', '비고', '물건종류', 'pdf_소재지']
    for k in checks:
        if k in exp:
            got = item.get(k, '')
            ok = (got == exp[k])
            if not ok:
                row_ok = False; all_ok = False
            mark = 'OK' if ok else 'FAIL'
            print(f'  {mark}  {k}: got={got!r}')
            if not ok:
                print(f'       exp={exp[k]!r}')

    for bk, bv in [('BUN1', bun1), ('BUN2', bun2)]:
        if bk in exp:
            ok = (bv == exp[bk])
            if not ok:
                row_ok = False; all_ok = False
            mark = 'OK' if ok else 'FAIL'
            print(f'  {mark}  {bk}: got={bv!r}  exp={exp[bk]!r}')

    if 'Category' in exp:
        ok = (cat_code == exp['Category'])
        if not ok:
            row_ok = False; all_ok = False
        mark = 'OK' if ok else 'FAIL'
        print(f'  {mark}  Category: got={cat_code!r}  exp={exp["Category"]!r}')

    print()

print('ALL PASS' if all_ok else 'SOME FAIL')
