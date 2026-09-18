# -*- coding: utf-8 -*-
'HUG 202606100000260 실 PDF 기반 회귀 테스트.\n\n검증 항목:\n  - 신청번호 == 2026005615\n  - 채무자 연락처 == 010-0000-0000\n  - 소유자 연락처 == 050253110210\n  - 담당자 == 남건우\n  - SP CustDocID == 2026005615  (db_writer 로직 기준)\n  - SP CustCharge == 남건우(HUG)\n  - SP DebtrPhone == 010-0000-0000\n  - API DAMBO_NO == 202606100000260  (_build_bankonline_payload 기준)\n'
import os
import sys

PDF_PATH = 'C:\\Users\\PUBLIC_USER\\Desktop\\202606100000260_20260624_112808.pdf'
GRID_DOC_NO = "202606100000260"


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"OK  {label}")


if not os.path.exists(PDF_PATH):
    print(f"SKIP  PDF 파일 없음: {PDF_PATH}")
    sys.exit(0)

from pdf_parser import parse_bank24_pdf
from db_writer import normalize_cust_docid, resolve_debtr_phone, resolve_cust_charge
import extract_shinhan as es

parsed = parse_bank24_pdf(PDF_PATH)

check("파싱 성공", parsed.get("처리상태") != "실패")
check("은행 = 주택도시보증공사", parsed.get("은행") == "주택도시보증공사")
check("신청번호 == 2026005615", parsed.get("신청번호") == "2026005615")
check('채무자 연락처 == 010-0000-0000', parsed.get("채무자 연락처") == '010-0000-0000')
check("소유자 연락처 == 050253110210", parsed.get("소유자 연락처") == "050253110210")
check("담당자 == 남건우", parsed.get("담당자") == "남건우")

# _normalize_pdf_identity_for_grid 적용
target_row = {"은행": "주택도시보증공사"}
pdf_doc, pdf_est = es._normalize_pdf_identity_for_grid(
    parsed, target_row, GRID_DOC_NO, "",
)
check("PDF 검증: 상세창 의뢰번호 = 그리드 의뢰번호", parsed.get("상세창 의뢰번호") == GRID_DOC_NO)
check("API DAMBO_NO = 그리드 의뢰번호", pdf_doc == GRID_DOC_NO)

# SP CustDocID: db_writer 로직과 동일 조건 재현
_app_no = normalize_cust_docid(parsed.get("신청번호", ""))
sp_cust_doc = _app_no if _app_no else normalize_cust_docid(
    parsed.get("상세창 의뢰번호") or parsed.get("의뢰번호", "")
)
check("SP CustDocID == 2026005615", sp_cust_doc == "2026005615")

# SP CustCharge
sp_cust_charge = resolve_cust_charge(parsed, "주택도시보증공사")
check("SP CustCharge == 남건우(HUG)", sp_cust_charge == "남건우(HUG)")
check("(HUG) 중복 suffix 없음", sp_cust_charge.count("(HUG)") == 1)

# SP DebtrPhone
sp_debtr_phone = resolve_debtr_phone(parsed, "주택도시보증공사")
check('SP DebtrPhone == 010-0000-0000', sp_debtr_phone == '010-0000-0000')

# 소유자 연락처와 DebtrPhone 뒤바뀜 없음
check("소유자 연락처 != DebtrPhone", sp_debtr_phone != parsed.get("소유자 연락처"))

# BankOnline DAMBO_NO
fake_config = {"bank24_id": "testid", 'REDACTED_CONFIGURE_LOCALLY': "testpw"}
payload = es._build_bankonline_payload(parsed, "01-2626-3-9999", fake_config)
check("DAMBO_NO == 202606100000260", payload.get("DAMBO_NO") == GRID_DOC_NO)

print("ALL PASS")
