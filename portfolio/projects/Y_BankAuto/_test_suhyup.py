# -*- coding: utf-8 -*-
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from pdf_parser import parse_bank24_pdf
from db_writer import _parse_address, _format_bun, parse_building_detail, resolve_category_code

sh_dir = r'D:\AI\Claude\Y_BankAuto\수협은행'

expected = {
    '1.pdf': {
        '은행': '수협은행', '의뢰번호': '20260616100038000001',
        '감정서번호': '012604-3-1310-1',
        '영업점': '여의도종합금융본부', '담당자': '정유진',
        '담당자 연락처': '0262788773', '소유자 연락처': '',
        '의뢰일자': '2026-06-16 오후 3:42:01', '처리기한': '2026-06-17',
        '채무자': '티제이아이여주(주)', '소유자': '티제이아이여주(주)',
        '비고': '', '물건종류': '토지',
        'pdf_소재지': '경기 여주시 오금동 일반 444 - 12 외 4필지',
        'BUN1': '0444', 'BUN2': '0012', 'Category': '03',
    },
    '2.pdf': {
        '영업점': '수협은행 봉천동지점', '담당자': '김성용',
        '담당자 연락처': '028881333',
        '의뢰일자': '2026-06-04 오후 5:08:16', '처리기한': '2026-06-02',
        '채무자': '김영숙', '소유자': '김영숙',
        '비고': '최병산 평가사님 사전협의건입니다.', '물건종류': '토지',
        'BUN1': '0730', 'BUN2': '0090',
    },
    '3.pdf': {
        '영업점': '가락동금융센터', '담당자': '이재욱',
        '담당자 연락처': '010-0000-0000',
        '의뢰일자': '2026-05-21 오전 10:25:08', '처리기한': '2026-05-22',
        '채무자': '홍진우', '소유자': '홍진우',
        '비고': '유승민평가사지정요청', '물건종류': '토지',
        'BUN1': '0035', 'BUN2': '0016',
    },
    '4.pdf': {
        '영업점': '수협은행 DMC금융센터', '담당자': '김이슬',
        '담당자 연락처': '023752301',
        '의뢰일자': '2026-05-14 오후 3:12:19', '처리기한': '2026-05-14',
        '채무자': '주식회사동은종합건설', '소유자': '주식회사동은종합건설',
        '비고': '박중호 평가사님 전달 부탁드립니다', '물건종류': '토지',
        'BUN1': '0075', 'BUN2': '0012',
    },
    '5.pdf': {
        '영업점': '수협은행 봉천동지점', '담당자': '곽종훈',
        '담당자 연락처': '028881333',
        '의뢰일자': '2026-04-09 오전 11:07:26', '처리기한': '2026-04-09',
        '채무자': '주식회사연홍개발', '소유자': '주식회사연홍개발',
        '비고': '최병산 평가사님 사전 협의건.', '물건종류': '집합물건(건물)',
        'BUN1': '0847', 'BUN2': '0001', 'Ho': '101호', 'Category': '30',
    },
    '6.pdf': {
        '영업점': '강남역삼지점', '담당자': '황제현',
        '담당자 연락처': '0220845906',
        '의뢰일자': '2026-04-08 오전 9:09:43', '처리기한': '2026-04-08',
        '채무자': '이은정', '소유자': '이은정',
        '비고': '정우종 대표이사님 감정 부탁드리겠습니다.', '물건종류': '토지',
        'BUN1': '0183', 'BUN2': '0472',
    },
    '7.pdf': {
        '영업점': '을지로금융센터', '담당자': '강태양',
        '담당자 연락처': '0222798561',
        '의뢰일자': '2026-04-02 오전 8:40:43', '처리기한': '2026-04-02',
        '채무자': '(주)메디엘', '소유자': '(주)메디엘',
        '비고': '정우종이사님', '물건종류': '토지',
        'BUN1': '1980', 'BUN2': '0000',
    },
    '8.pdf': {
        '영업점': '서여의도종합금융본부', '담당자': '',
        '담당자 연락처': '027866211',
        '의뢰일자': '2026-03-25 오전 10:13:46', '처리기한': '2026-03-25',
        '채무자': '장민호', '소유자': '',
        '비고': '오병오 평가사 탁감건', '물건종류': '집합물건(건물)',
        'BUN1': '0065', 'BUN2': '0000', 'Dong': '상가동', 'Ho': '104호', 'Category': '30',
    },
}

all_ok = True
for fname, exp in sorted(expected.items()):
    path = os.path.join(sh_dir, fname)
    item = parse_bank24_pdf(path)
    rep = item.get('pdf_소재지', '') or ''
    parsed = _parse_address(rep) if rep else {}
    bld = parse_building_detail(rep) if rep else {}
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

    for dk in ['Building', 'Dong', 'Ho']:
        if dk in exp:
            got_v = bld.get(dk.lower(), '')
            ok = (got_v == exp[dk])
            if not ok:
                row_ok = False; all_ok = False
            mark = 'OK' if ok else 'FAIL'
            print(f'  {mark}  {dk}: got={got_v!r}  exp={exp[dk]!r}')

    if 'Category' in exp:
        ok = (cat_code == exp['Category'])
        if not ok:
            row_ok = False; all_ok = False
        mark = 'OK' if ok else 'FAIL'
        print(f'  {mark}  Category: got={cat_code!r}  exp={exp["Category"]!r}')

    print()

print('ALL PASS' if all_ok else 'SOME FAIL')
