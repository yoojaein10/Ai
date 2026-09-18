import sys, os
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from pdf_parser import parse_bank24_pdf
from db_writer import _parse_address, _format_bun, parse_building_detail

hana_dir = r'D:\AI\Claude\Y_BankAuto\하나은행'

expected = {
    '1.pdf': {
        '은행': 'KEB하나은행', '의뢰번호': '202606001314', '감정서번호': '01-2606-3-1930',
        '채무자': '주식회사산천대축육곳간', '소유자': '주식회사산천대축육곳간',
        '영업점': '방화동', '담당자': '임율희',
        '담당자 연락처': '', '소유자 연락처': '050215243914',
        '의뢰일자': '2026-06-15 오후 2:27:56',
        '비고': '노승환평가사 사전협의가격 23억원 / 매매가 23억원',
        '물건종류': '일반상가',
        'pdf_소재지': '경기도 가평군 상면 연하리 217-4,6,7',
        'BUN1': '0217', 'BUN2': '0004',
    },
    '2.pdf': {
        '은행': 'KEB하나은행', '의뢰번호': '202604002668', '감정서번호': '01-2604-3-1385',
        '채무자': '정예무역(주)', '소유자': '정예무역(주)',
        '영업점': '대림역', '담당자': '황준형',
        '담당자 연락처': '', '소유자 연락처': '050246487272',
        '의뢰일자': '2026-04-27 오후 12:36:00',
        '비고': '이명헌 평가사 앞 감정 요청 / 684-3 1,2,3동 평가 요청',
        '물건종류': '',
        'pdf_소재지': '경기도 평택시 포승읍 도곡리 만호리 684-3  1',
        'BUN1': '0684', 'BUN2': '0003',
    },
    '3.pdf': {
        '은행': 'KEB하나은행', '의뢰번호': '202604000146', '감정서번호': '01-2604-3-1098',
        '채무자': '제이에이치미디어 주식회사', '소유자': '제이에이치미디어 주식회사',
        '영업점': '가산디지털금융센터', '담당자': '김동혁',
        '담당자 연락처': '010-0000-0000', '소유자 연락처': '050245341456',
        '의뢰일자': '2026-04-03 오후 1:45:06',
        '비고': '정우종 평가사 진행 / 보증금 및 임대료 추정내용 작성 요청',
        '물건종류': '상업용오피스텔',
        'pdf_소재지': '서울특별시 강남구 역삼동  832-2  1 1302',
        'BUN1': '0832', 'BUN2': '0002', 'Dong': '1', 'Ho': '1302',
    },
    '4.pdf': {
        '은행': 'KEB하나은행', '의뢰번호': '202603002131', '감정서번호': '01-2603-3-0966',
        '채무자': '김효원', '소유자': '김효원',
        '영업점': '가산디지털금융센터', '담당자': '정윤지',
        '담당자 연락처': '', '소유자 연락처': '',
        '의뢰일자': '2026-03-23 오후 12:43:43',
        '비고': '',
        '물건종류': '상업용오피스텔',
        'pdf_소재지': '서울특별시 강남구 역삼동  832   510',
        'BUN1': '0832', 'BUN2': '0000', 'Ho': '510',
    },
}

all_ok = True
for fname, exp in sorted(expected.items()):
    path = os.path.join(hana_dir, fname)
    item = parse_bank24_pdf(path)

    rep_addr = item.get('pdf_소재지', '') or ''
    parsed = _parse_address(rep_addr) if rep_addr else {}
    bld = parse_building_detail(rep_addr) if rep_addr else {}
    bun1 = _format_bun(parsed.get('Bun1', ''))
    bun2 = _format_bun(parsed.get('Bun2', ''))

    status = item.get('처리상태', '')
    print(f'=== {fname} (status={status}) ===')
    row_ok = True

    checks = ['은행', '의뢰번호', '감정서번호', '채무자', '소유자', '영업점', '담당자',
              '담당자 연락처', '소유자 연락처', '의뢰일자', '비고', '물건종류', 'pdf_소재지']
    for k in checks:
        if k in exp:
            got = item.get(k, '')
            ok = (got == exp[k])
            if not ok:
                row_ok = False
                all_ok = False
            mark = 'OK' if ok else 'FAIL'
            print(f'  {mark}  {k}: got={got!r}')
            if not ok:
                print(f'       exp={exp[k]!r}')

    for bk, bv in [('BUN1', bun1), ('BUN2', bun2)]:
        if bk in exp:
            ok = (bv == exp[bk])
            if not ok:
                row_ok = False
                all_ok = False
            mark = 'OK' if ok else 'FAIL'
            print(f'  {mark}  {bk}: got={bv!r}  exp={exp[bk]!r}')

    for dk in ['Dong', 'Ho']:
        if dk in exp:
            got_v = bld.get(dk.lower(), '')
            ok = (got_v == exp[dk])
            if not ok:
                row_ok = False
                all_ok = False
            mark = 'OK' if ok else 'FAIL'
            print(f'  {mark}  {dk}: got={got_v!r}  exp={exp[dk]!r}')

    print()

print('ALL PASS' if all_ok else 'SOME FAIL')
