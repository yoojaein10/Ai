# -*- coding: utf-8 -*-
import sys, io, fitz
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

paths = [
    r'D:\AI\Claude\Y_BankAuto\다필지\01-2606-3-1855_기업(구분건물).pdf',
    r'D:\AI\Claude\Y_BankAuto\다필지\01-2606-3-1952_의뢰.pdf',
]

for path in paths:
    print('='*60)
    print(path)
    print('='*60)
    doc = fitz.open(path)
    text = '\n'.join(page.get_text() for page in doc)
    doc.close()
    ls = [l.strip() for l in text.split('\n')]
    for i, line in enumerate(ls):
        if line:
            print('%4d | %s' % (i, line))
    print()
