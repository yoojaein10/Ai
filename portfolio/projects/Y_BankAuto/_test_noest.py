# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')

from pdf_parser import parse_bank24_pdf

PDF = r'C:\Bank24Extractor\pdf\NOEST_2026171570.pdf'
if not os.path.exists(PDF):
    print('PDF 파일 없음:', PDF)
    sys.exit(1)

r = parse_bank24_pdf(PDF)
branch  = r.get('영업점', '')
manager = r.get('담당자', '')
addr    = r.get('pdf_주소', '')

print(f'영업점 : {branch!r}')
print(f'담당자 : {manager!r}')
print(f'주소   : {addr!r}')

ok_branch  = branch  == '자양동'
ok_manager = manager == '장준민'
print()
print(f'[{"OK" if ok_branch  else "FAIL"}] 영업점 = {branch!r}  (기대: "자양동")')
print(f'[{"OK" if ok_manager else "FAIL"}] 담당자 = {manager!r}  (기대: "장준민")')

# 회귀 테스트
print()
print('=== 회귀 검증 ===')

REG = [
    (r'C:\Bank24Extractor\pdf\01-2606-3-1853_2026171622.pdf', '광교영업부', '장원혁'),
    (r'C:\Bank24Extractor\pdf\01-2605-3-1631._0311260760.pdf', '가양동', '이은정'),
    (r'D:\AI\Claude\Y_BankAuto\기업은행.pdf', '인천원당', '배동관'),
]
for pdf, exp_br, exp_mg in REG:
    if not os.path.exists(pdf):
        print(f'  [SKIP] {os.path.basename(pdf)} (파일 없음)')
        continue
    rv = parse_bank24_pdf(pdf)
    br = rv.get('영업점', '')
    mg = rv.get('담당자', '')
    ok = br == exp_br and mg == exp_mg
    print(f'  [{"OK" if ok else "FAIL"}] {os.path.basename(pdf)} → 영업점={br!r}({exp_br}), 담당자={mg!r}({exp_mg})')
