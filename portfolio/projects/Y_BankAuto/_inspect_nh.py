import sys, os, re
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from pdf_parser import parse_bank24_pdf
from db_writer import _parse_address, _format_bun, parse_building_detail

nh_dir = r'D:\AI\Claude\Y_BankAuto\농협은행'

fields = ['은행', '의뢰번호', '감정서번호', '채무자', '소유자',
          '영업점', '담당자', '담당자 연락처', '소유자 연락처',
          '의뢰일자', '처리기한', '비고', '물건종류', 'pdf_소재지']

for fname in sorted(os.listdir(nh_dir)):
    if not fname.endswith('.pdf'):
        continue
    path = os.path.join(nh_dir, fname)
    item = parse_bank24_pdf(path)

    rep = item.get('pdf_소재지', '') or ''
    parsed = _parse_address(rep) if rep else {}
    bld = parse_building_detail(rep) if rep else {}
    bun1 = _format_bun(parsed.get('Bun1', ''))
    bun2 = _format_bun(parsed.get('Bun2', ''))

    print(f'=== {fname} ===')
    for k in fields:
        v = item.get(k, '')
        print(f'  {k}: {v!r}')
    print(f'  BUN1={bun1!r}  BUN2={bun2!r}')
    print(f'  Building={bld.get("building","")!r}  Dong={bld.get("dong","")!r}  Ho={bld.get("ho","")!r}')
    print()
