# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import fitz, os
from db_writer import resolve_category_code
from pdf_parser import parse_bank24_pdf

sh_dir = r'D:\AI\Claude\Y_BankAuto\수협은행'
for fname in ['5.pdf', '8.pdf']:
    doc = fitz.open(os.path.join(sh_dir, fname))
    page = doc[0]
    ls = [line.strip() for block in page.get_text('blocks') for line in block[4].split('\n')]
    for i, v in enumerate(ls):
        if v == '구 분':
            nxt = [ls[j] for j in range(i+1, min(i+5, len(ls)))]
            print(f'{fname} [{i}]=구 분 => next5: {nxt!r}')
    item = parse_bank24_pdf(os.path.join(sh_dir, fname))
    rep = item.get('pdf_소재지', '') or ''
    cat_raw = item.get('물건종류', '')
    cat_code = resolve_category_code(item, rep)
    print(f'  raw_category={cat_raw!r}  code={cat_code!r}')
    doc.close()
