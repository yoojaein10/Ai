import sys
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from pdf_parser import parse_bank24_pdf
from db_writer import _parse_address, _format_bun, parse_building_detail, resolve_category_code
import os

# HUG 9건 파서 검증
print("=== HUG PDF 파서 검증 ===")
hug_dir = r'D:\AI\Claude\Y_BankAuto\주택도시보증공사'
for fn in sorted(os.listdir(hug_dir)):
    if not fn.endswith('.pdf'):
        continue
    path = os.path.join(hug_dir, fn)
    r = parse_bank24_pdf(path)
    sojaegi = r.get('pdf_소재지', '')
    postal  = r.get('pdf_우편번호주소', '')
    status  = r.get('처리상태', '')
    bank    = r.get('은행', '')
    branch  = r.get('영업점', '')
    cat_nm  = r.get('물건종류', '')
    parsed = _parse_address(sojaegi) if sojaegi else {}
    bld = parse_building_detail(sojaegi) if sojaegi else {}
    cat = resolve_category_code(r, sojaegi)
    bun1 = _format_bun(parsed.get('Bun1', ''))
    bun2 = _format_bun(parsed.get('Bun2', ''))
    print(fn)
    print("  status=%s bank=%s branch=%s cat_nm=%s" % (status, bank, branch, cat_nm))
    print("  sojaegi=%s" % sojaegi)
    print("  postal=%s" % postal)
    print("  Bun1=%s Bun2=%s Dong=%s Ho=%s Category=%s" % (
        bun1, bun2, bld.get('dong',''), bld.get('ho',''), cat))
    print()

# 주소 단위 테스트
print("=== db_writer 주소 단위 테스트 ===")
tests = [
    ('서울특별시 강서구  화공동  938-11   805',
     {'Bun1':'0938','Bun2':'0011','ho':'805'}),
    ('서울특별시 은평구  역초동  20-28   203',
     {'Bun1':'0020','Bun2':'0028','ho':'203'}),
    ('서울특별시 관악구  봉천동  649-36',
     {'Bun1':'0649','Bun2':'0036','ho':''}),
    ('서울특별시 강남구  논현동  40-0  103 101',
     {'Bun1':'0040','Bun2':'0000','dong':'103','ho':'101'}),
    ('서울특별시 동작구  노량진동  39-20 한강더퍼스트타워  1610',
     {'Bun1':'0039','Bun2':'0020','ho':'1610'}),
    ('서울특별시 송파구  오금동  73-9 더 하임 오금  601호',
     {'Bun1':'0073','Bun2':'0009','ho':'601'}),
    ('서울특별시 용산구  청파동3가  134-68',
     {'Bun1':'0134','Bun2':'0068','ho':''}),
    ('서울특별시 용산구 청파동3가 134-68 E동 501호',
     {'Bun1':'0134','Bun2':'0068','dong':'E동','ho':'501'}),
]

all_pass = True
for addr, expected in tests:
    p = _parse_address(addr)
    b = parse_building_detail(addr)
    bun1 = _format_bun(p.get('Bun1',''))
    bun2 = _format_bun(p.get('Bun2',''))
    ho_got = b.get('ho','').replace('호','')
    ho_exp = str(expected.get('ho','')).replace('호','')
    ok_bun1 = bun1 == expected.get('Bun1','')
    ok_bun2 = bun2 == expected.get('Bun2','')
    ok_ho   = 'ho'   not in expected or ho_got == ho_exp
    ok_dong = 'dong' not in expected or b.get('dong','') == expected.get('dong','')
    status = 'PASS' if (ok_bun1 and ok_bun2 and ok_ho and ok_dong) else 'FAIL'
    if status == 'FAIL':
        all_pass = False
    print("%s: %s" % (status, addr[:45]))
    if status == 'FAIL':
        print("  expected: Bun1=%s Bun2=%s ho=%s dong=%s" % (
            expected.get('Bun1',''), expected.get('Bun2',''),
            expected.get('ho',''), expected.get('dong','')))
        print("  got:      Bun1=%s Bun2=%s ho=%s dong=%s" % (
            bun1, bun2, b.get('ho',''), b.get('dong','')))

print()
print("ALL PASS" if all_pass else "SOME FAILED")
