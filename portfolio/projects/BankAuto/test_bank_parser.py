"""test_bank_parser.py — 은행별 파싱 결과 검증"""
import os
from bank_parser import parse_pdf

PDF_DIR = r"D:\AI\Claude\BankAuto\output\bank"

EXPECTED = {
    '광주은행.pdf':          {'Docid': '01-2603-3-0765',  'CustNm': '광주은행',       'CustDocid': '0217202631000008',      'CustNm_Sub': '부평',              'CustEmp': '김혜승', 'CustPhone': '0325034700', 'Debtor': '(주)그리핀베이'},
    '국민은행.pdf':          {'Docid': '01-2604-3-1091',  'CustNm': '국민은행',       'CustDocid': '302175611',             'CustNm_Sub': '용인종합금융센터',   'CustEmp': '진미숙', 'CustPhone': '010-0000-0000', 'Debtor': '노권래'},
    '기업은행.pdf':          {'Docid': '01-2604-3-1113',  'CustNm': '기업은행',       'CustDocid': '0524260352',            'CustNm_Sub': '오포',              'CustEmp': '이은지', 'CustPhone': '0317659504'},
    '농협은행.pdf':          {'Docid': '01-2602-3-0644',  'CustNm': '농협은행',       'CustDocid': '5001863648',            'CustNm_Sub': '송도대기업금융센터','CustEmp': '류지연', 'CustPhone': '0324566362'},
    '새마을금고.pdf':        {'Docid': '01-2604-3-1072',  'CustNm': '새마을금고',     'CustDocid': '10000000000016878290', 'CustNm_Sub': '더좋은 본점',       'CustEmp': '김태형', 'CustPhone': '02-963-3185', 'Debtor': '류필열'},
    '수협은행.pdf':          {'Docid': '01-2604-3-1083',  'CustNm': '수협은행',       'CustDocid': '20260402125507000001', 'CustNm_Sub': '수협은행 신당역지점','CustEmp': '정솔',  'CustPhone': '0222336211'},
    '신한은행.pdf':          {'Docid': '01-2604-3-1116',  'CustNm': '신한은행',       'CustDocid': '2026112643',            'CustNm_Sub': '공덕금융센터',      'CustEmp': '오현석', 'CustPhone': '010-0000-0000', 'Debtor': '임동현'},
    '우리은행.pdf':          {'Docid': '01-2604-3-1082',  'CustNm': '우리은행',       'CustDocid': '2026040070',            'CustNm_Sub': '상암DMC금융센터',   'CustEmp': '이미선', 'CustPhone': '02-3151-2525', 'Debtor': '주식회사 현진컴퍼니'},
    '주택도시보증공사.pdf':  {'Docid': '01-2604-3-1111',  'CustNm': '주택도시보증공사','CustDocid': '202604100000051',       'CustNm_Sub': '본점',              'CustEmp': '남건우', 'CustPhone': '051-998-6708', 'Debtor': '곽한성'},
    '하나은행.pdf':          {'Docid': '01-2604-3-1103',  'CustNm': 'KEB하나은행',    'CustDocid': '202604000307',          'CustNm_Sub': '대림역',            'CustEmp': '황준형', 'CustPhone': '02  863 5140', 'Debtor': '(주)벡트(VECT Co.,Ltd.)'},
}

total_ok = 0
total_fail = 0

for pdf_name in sorted(os.listdir(PDF_DIR)):
    if not pdf_name.endswith('.pdf'):
        continue
    path = os.path.join(PDF_DIR, pdf_name)
    result = parse_pdf(path)
    expected = EXPECTED.get(pdf_name, {})

    print(f"\n{'='*55}")
    print(f"[{pdf_name}]")

    bank_ok = bank_fail = 0
    for key, exp_val in expected.items():
        got = result.get(key)
        ok = (got == exp_val)
        mark = '✓' if ok else '✗'
        if ok:
            bank_ok += 1
            total_ok += 1
            print(f"  {mark} {key}: {got!r}")
        else:
            bank_fail += 1
            total_fail += 1
            print(f"  {mark} {key}: {got!r}  (expected: {exp_val!r})")

    # 기타 파싱된 값 출력
    extra_keys = [k for k in result if k not in expected and result[k]]
    if extra_keys:
        print("  --- 추가 파싱 결과 ---")
        for k in extra_keys:
            print(f"     {k}: {result[k]!r}")

    print(f"  → {bank_ok}/{bank_ok+bank_fail} 정확")

print(f"\n{'='*55}")
print(f"전체: {total_ok} 정확 / {total_fail} 오류")
