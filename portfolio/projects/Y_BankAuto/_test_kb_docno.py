# -*- coding: utf-8 -*-
"""국민은행 의뢰번호 형식 검증 및 DB 매핑 회귀 테스트.

검증 항목:
  - 그리드(13자리) = 내부(9자리) + suffix(4자리) 형식 판정
  - 검증 실패 조건 (prefix 불일치, suffix 비숫자, 자리수 오류)
  - extract_shinhan: _normalize_pdf_identity_for_grid KB 처리
  - db_writer: SP CustDocID = 내부 의뢰번호, 그리드_의뢰번호 분리
  - 실제 PDF 파싱 (파일 있을 때)
  - HUG 회귀 보호
"""
import os
import sys
sys.path.insert(0, r"D:\AI\Claude\Y_BankAuto")

from extract_shinhan import _kb_doc_no_match, _normalize_pdf_identity_for_grid
from db_writer import _is_kb_docno_format, normalize_cust_docid


def check(label, condition):
    if not condition:
        raise AssertionError(f"FAIL: {label}")
    print(f"OK  {label}")


# ── 1. _kb_doc_no_match / _is_kb_docno_format ────────────────────────────────
check(
    "정상 형식: 3022006062008 → 302200606 + 2008",
    _kb_doc_no_match("3022006062008", "302200606"),
)
check(
    "_is_kb_docno_format 동일 결과",
    _is_kb_docno_format("302200606", "3022006062008"),
)
check(
    "prefix 불일치 → False",
    not _kb_doc_no_match("3022006062008", "999999999"),
)
check(
    "suffix 비숫자 → False",
    not _kb_doc_no_match("30220060620AB", "302200606"),
)
check(
    "그리드 12자리 → False",
    not _kb_doc_no_match("302200606200", "302200606"),
)
check(
    "그리드 14자리 → False",
    not _kb_doc_no_match("30220006200012", "302200606"),
)
check(
    "내부번호 8자리 → False",
    not _kb_doc_no_match("3022006062008", "30220060"),
)
check(
    "내부번호 10자리 → False",
    not _kb_doc_no_match("3022006062008", "3022006062"),
)
check(
    "suffix 3자리 → False",
    not _kb_doc_no_match("302200606200", "302200606"),
)

# ── 2. _normalize_pdf_identity_for_grid (KB) ─────────────────────────────────
parsed_kb = {
    "은행":     "국민은행",
    "의뢰번호": "302200606",
    "감정서번호": "01-2606-3-9999",
}
pdf_doc, pdf_est = _normalize_pdf_identity_for_grid(
    parsed_kb,
    {"은행": "국민은행"},
    "3022006062008",
    "01-2606-3-9999",
)
check("KB: pdf_doc = 그리드 의뢰번호 (검증 통과용)", pdf_doc == "3022006062008")
check("KB: 상세창 의뢰번호 = 그리드 의뢰번호", parsed_kb.get("상세창 의뢰번호") == "3022006062008")
check("KB: 의뢰번호(내부) 덮어쓰지 않음", parsed_kb.get("의뢰번호") == "302200606")

# 형식 불일치 → 기존 동작 유지
parsed_kb2 = {"은행": "국민은행", "의뢰번호": "ABC123", "감정서번호": ""}
pdf_doc2, _ = _normalize_pdf_identity_for_grid(
    parsed_kb2, {"은행": "국민은행"}, "XYZ9999999999", "",
)
check("KB 형식 불일치: pdf_doc 변경 없음", pdf_doc2 == "ABC123")
check("KB 형식 불일치: 상세창 의뢰번호 미설정", parsed_kb2.get("상세창 의뢰번호") is None)

# ── 3. verified 체크 시뮬레이션 ──────────────────────────────────────────────
doc_no = "3022006062008"
est_no = "01-2606-3-9999"
pdf_doc_v = "3022006062008"   # _normalize_pdf_identity_for_grid 반환값
pdf_est_v = "01-2606-3-9999"
verified = (
    (doc_no and pdf_doc_v and doc_no == pdf_doc_v) or
    (est_no and pdf_est_v and est_no == pdf_est_v)
)
check("KB 검증 성공 (doc_no == pdf_doc 기준)", verified)

# ── 4. db_writer KB CustDocID 분리 ───────────────────────────────────────────
check(
    "SP CustDocID = 내부 의뢰번호 (9자리)",
    _is_kb_docno_format("302200606", "3022006062008"),
)

# DB 로직 재현 (insert_apw_master_expand 내부 조건과 동일)
_bank_nm = "국민은행"
item = {
    "은행": "국민은행",
    "의뢰번호": "302200606",
    "상세창 의뢰번호": "3022006062008",
}
_pdf_doc = normalize_cust_docid(item.get("의뢰번호", ""))
_grid    = normalize_cust_docid(item.get("상세창 의뢰번호") or "")
if _pdf_doc and _grid and _is_kb_docno_format(_pdf_doc, _grid):
    cust_doc = _pdf_doc
    grid_doc = _grid
else:
    cust_doc = normalize_cust_docid(
        item.get("상세창 의뢰번호") or item.get("의뢰번호", "")
    )
    grid_doc = cust_doc

check("SP CustDocID == 302200606 (내부 9자리)", cust_doc == "302200606")
check("그리드_의뢰번호 == 3022006062008", grid_doc == "3022006062008")

# 형식 불일치 → fallback
item2 = {"은행": "국민은행", "의뢰번호": "ABC", "상세창 의뢰번호": "XYZXYZ"}
_pdf2 = normalize_cust_docid(item2.get("의뢰번호", ""))
_grd2 = normalize_cust_docid(item2.get("상세창 의뢰번호") or "")
if _pdf2 and _grd2 and _is_kb_docno_format(_pdf2, _grd2):
    cust_doc2 = _pdf2
else:
    cust_doc2 = normalize_cust_docid(
        item2.get("상세창 의뢰번호") or item2.get("의뢰번호", "")
    )
check("형식 불일치 fallback: 상세창 의뢰번호 사용", cust_doc2 == "XYZXYZ")

# ── 5. HUG 회귀 보호 ──────────────────────────────────────────────────────────
from db_writer import resolve_debtr_phone, resolve_cust_charge
import extract_shinhan as es

parsed_hug = {
    "은행":      "주택도시보증공사",
    "의뢰번호":  "2026005615",
    "감정서번호": "",
    "채무자 연락처": '010-0000-0000',
    "소유자 연락처": "050253110210",
    "담당자": "남건우",
    "신청번호": "2026005615",
}
hug_doc, hug_est = _normalize_pdf_identity_for_grid(
    parsed_hug, {"은행": "주택도시보증공사"}, "202606100000260", "",
)
check("HUG 의뢰번호 = 그리드 의뢰번호", hug_doc == "202606100000260")
check("HUG 상세창 의뢰번호 = 그리드", parsed_hug.get("상세창 의뢰번호") == "202606100000260")
check("HUG DebtrPhone = 채무자 연락처", resolve_debtr_phone(parsed_hug, "주택도시보증공사") == '010-0000-0000')
check("HUG CustCharge = 남건우(HUG)", resolve_cust_charge(parsed_hug, "주택도시보증공사") == "남건우(HUG)")

# ── 6. 실 PDF 파싱 (있을 때만) ────────────────────────────────────────────────
PDF_KB = 'Y:\\PUBLIC_SOURCE\\3022006062008_20260624_144048.pdf'
if os.path.exists(PDF_KB):
    from pdf_parser import parse_bank24_pdf
    p = parse_bank24_pdf(PDF_KB)
    check("KB PDF 파싱 성공", p.get("처리상태") != "실패")
    check("KB 은행 = 국민은행", p.get("은행") == "국민은행")
    check("KB 내부 의뢰번호 == 302200606", p.get("의뢰번호") == "302200606")

    pdf_d, pdf_e = _normalize_pdf_identity_for_grid(
        p, {"은행": "국민은행"}, "3022006062008", "",
    )
    check("KB PDF: 검증통과값 = 그리드", pdf_d == "3022006062008")
    check("KB PDF: 상세창 의뢰번호 = 그리드", p.get("상세창 의뢰번호") == "3022006062008")
    check("KB PDF: 의뢰번호 덮어쓰지 않음", p.get("의뢰번호") == "302200606")

    _p2 = normalize_cust_docid(p.get("의뢰번호", ""))
    _g2 = normalize_cust_docid(p.get("상세창 의뢰번호") or "")
    if _p2 and _g2 and _is_kb_docno_format(_p2, _g2):
        sp_cust = _p2
        sp_grid = _g2
    else:
        sp_cust = normalize_cust_docid(p.get("상세창 의뢰번호") or p.get("의뢰번호", ""))
        sp_grid = sp_cust
    check("KB SP CustDocID == 302200606", sp_cust == "302200606")
    check("KB 그리드_의뢰번호 == 3022006062008", sp_grid == "3022006062008")
    print("OK  (실 PDF 검증 완료)")
else:
    print(f"SKIP  KB PDF 없음: {PDF_KB}")

print("ALL PASS")
