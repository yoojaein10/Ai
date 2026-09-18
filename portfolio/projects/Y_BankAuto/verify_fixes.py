import sys, glob, os, re
sys.path.insert(0, 'D:/AI/Claude/Y_BankAuto')
from pdf_parser import parse_bank24_pdf
from db_writer import (_parse_address, parse_building_detail,
                       _supplement_building_detail, resolve_category_code,
                       _format_sp_date, _format_bun)

all_ok = True

def check(label, got, exp):
    global all_ok
    ok = (got == exp)
    status = "OK" if ok else "FAIL"
    if not ok:
        all_ok = False
    print(f"  {status}: {label} = {got!r}  (expected {exp!r})")
    return ok


# ── FIX-1 단위 테스트 ────────────────────────────────────────────
print("=== FIX-1: _format_sp_date ===")
check("오후", _format_sp_date("2026-06-11 오후 5:47:00"), "2026-06-11")
check("오전", _format_sp_date("2026-06-11 오전 9:34:00"), "2026-06-11")
check("8자리", _format_sp_date("20260611"), "2026-06-11")
check("의뢰번호 차단", _format_sp_date("202606100000136"), None)
check("빈값", _format_sp_date(""), None)
check("None", _format_sp_date(None), None)


# ── FIX-2: 202606100000136 ───────────────────────────────────────
print("\n=== FIX-2: 202606100000136 채무자 ===")
p = parse_bank24_pdf(r"C:\Bank24Extractor\pdf\202606100000136_20260612_093543.pdf")
check("채무자", p.get("채무자", ""), "정유리")
check("소유자", p.get("소유자", ""), "김은서")
check("물건종류", p.get("물건종류", ""), "다세대주택")


# ── FIX-3: 202606100000106 ───────────────────────────────────────
print("\n=== FIX-3: 202606100000106 Building ===")
p2 = parse_bank24_pdf(r"C:\Bank24Extractor\pdf\202606100000106_20260612_093721.pdf")
check("채무자", p2.get("채무자", ""), "황수웅")
sojaej = p2.get("pdf_소재지", "")
rep_addr = sojaej
cat = resolve_category_code(p2, rep_addr)
check("Category", cat, "03")
pa = _parse_address(sojaej)
check("BUN1", _format_bun(pa["Bun1"]), "0649")
check("BUN2", _format_bun(pa["Bun2"]), "0036")
bld = _supplement_building_detail(parse_building_detail(sojaej), p2)
check("Building", bld["building"], "")
print(f"  INFO: pdf_소재지={sojaej!r}")
print(f"  INFO: pdf_우편번호주소={p2.get('pdf_우편번호주소','')!r}")


# ── TXT 파싱 helper ───────────────────────────────────────────────
def parse_txt_items(txt_path):
    """TXT 파일에서 ITEM별 dict 파싱."""
    with open(txt_path, encoding="utf-8") as f:
        content = f.read()
    items = {}
    for block in re.split(r'=====\s*ITEM\s*\d+\s*=====', content):
        d = {}
        for line in block.splitlines():
            if ': ' in line:
                k, _, v = line.partition(': ')
                d[k.strip()] = v.strip()
        docid = d.get("의뢰번호", "")
        if docid:
            items[docid] = d
    return items


# ── 7건 전체 mock (TXT에서 의뢰일자 읽어 FIX-1 검증) ────────────
print("\n=== 오늘 7건 전체 mock ===")
txt_items = parse_txt_items(r"C:\Bank24Extractor\pdf\bank24_dambo_20260612_093437.txt")
pdfs = sorted(glob.glob(r"C:\Bank24Extractor\pdf\202606100000*_20260612_093*.pdf"))
print(f"  대상: {len(pdfs)}건")
DEBTOR_EXPECT = {
    "202606100000139": "이지흔",
    "202606100000136": "정유리",
    "202606100000119": "황옥남",
    "202606100000116": "장효주",
    "202606100000112": "이은정",
    "202606100000109": "(주)신영",
    "202606100000106": "황수웅",
}
BUILD_BLANK = {"202606100000106"}

for pdf_path in pdfs:
    docid = os.path.basename(pdf_path).split("_")[0]
    r = parse_bank24_pdf(pdf_path)
    debtor = r.get("채무자", "")

    # 의뢰일자: 그리드 스캔 값 (TXT에서 읽음)
    req_raw = txt_items.get(docid, {}).get("의뢰일자", "")
    req_fmt = _format_sp_date(req_raw)

    # Building
    sojaej2 = r.get("pdf_소재지", "")
    bld2 = _supplement_building_detail(parse_building_detail(sojaej2), r)
    building = bld2["building"]

    exp_debtor = DEBTOR_EXPECT.get(docid, "?")
    d_ok = (debtor == exp_debtor)
    r_ok = (req_fmt is not None)
    b_ok = (building == "") if docid in BUILD_BLANK else True

    if not d_ok: all_ok = False
    if not r_ok: all_ok = False
    if not b_ok: all_ok = False

    d_s = "OK" if d_ok else "FAIL"
    r_s = "OK" if r_ok else "FAIL"
    b_s = "OK" if b_ok else f"FAIL(building={building!r})"
    print(f"  {docid}  채무자[{d_s}]={debtor!r}  의뢰일자[{r_s}]={req_fmt!r}  building[{b_s}]")


# ── 회귀: 은행별 샘플 ─────────────────────────────────────────────
print("\n=== 회귀 검증 (은행별) ===")
bank_dirs = {
    "신한": r"D:\AI\Claude\Y_BankAuto\신한은행",
    "기업": r"D:\AI\Claude\Y_BankAuto\기업은행",
    "우리": r"D:\AI\Claude\Y_BankAuto\우리은행",
    "HUG":  r"D:\AI\Claude\Y_BankAuto\주택도시보증공사",
}
HUG_INVALID = {"상품명", "의뢰", "기관", "기 타", "정 보", "비 고"}
for bank_label, folder in bank_dirs.items():
    pdfs_r = sorted(glob.glob(os.path.join(folder, "*.pdf")))
    fail_list = []
    for pf in pdfs_r:
        r = parse_bank24_pdf(pf)
        debtor = r.get("채무자", "")
        owner  = r.get("소유자", "")
        fname  = os.path.basename(pf)
        status = r.get("처리상태", "")
        if status != "성공":
            fail_list.append(f"처리상태={status!r} ({fname})")
        if bank_label == "HUG":
            if debtor in HUG_INVALID:
                fail_list.append(f"채무자오염={debtor!r} ({fname})")
            if owner in HUG_INVALID:
                fail_list.append(f"소유자오염={owner!r} ({fname})")
    count = len(pdfs_r)
    if fail_list:
        all_ok = False
        for f in fail_list:
            print(f"  FAIL [{bank_label}] {f}")
    else:
        print(f"  OK   [{bank_label}] {count}건 — 회귀 없음")


print("\n" + "=" * 50)
print("최종:", "ALL PASS" if all_ok else "SOME FAIL")
sys.exit(0 if all_ok else 1)
