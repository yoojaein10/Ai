# -*- coding: utf-8 -*-
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import fitz

sh_dir = r'D:\AI\Claude\Y_BankAuto\수협은행'
for fname in sorted(os.listdir(sh_dir)):
    if not fname.endswith('.pdf'):
        continue
    doc = fitz.open(os.path.join(sh_dir, fname))
    page = doc[0]
    ls = [line.strip() for block in page.get_text("blocks")
          for line in block[4].split('\n')]
    print(f'=== {fname} ===')
    for i, v in enumerate(ls[:80]):
        print(f'  [{i:03d}] {v!r}')
    print()
    doc.close()
