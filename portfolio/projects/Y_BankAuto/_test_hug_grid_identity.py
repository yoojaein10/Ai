# -*- coding: utf-8 -*-
import extract_shinhan as es
from db_writer import resolve_debtr_phone, resolve_cust_charge


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"OK  {label}")


# 미접수 HUG: 의뢰번호가 감정서번호 칸으로 들어온 사례
parsed = {
    "은행": "주택도시보증공사",
    "의뢰번호": "2026005615",
    "감정서번호": "202606100000260",
}
pdf_doc, pdf_est = es._normalize_pdf_identity_for_grid(
    parsed,
    {"은행": "주택도시보증공사"},
    "202606100000260",
    "",
)
check("HUG 의뢰번호를 그리드 값으로 교정", pdf_doc == "202606100000260")
check("HUG 상세창 의뢰번호도 교정", parsed["상세창 의뢰번호"] == "202606100000260")
check("의뢰번호로 오인된 감정서번호 제거", pdf_est == "" and parsed["상세창 감정서번호"] == "")
# HUG DebtrPhone: 채무자 연락처(신청인 전화번호) 사용, 소유자 연락처 fallback 없음
parsed["채무자 연락처"] = '010-0000-0000'
parsed["소유자 연락처"] = "050253110210"
check(
    "HUG DebtrPhone은 채무자 연락처(신청인 전화번호) 사용",
    resolve_debtr_phone(parsed, "주택도시보증공사") == '010-0000-0000',
)
check(
    "HUG 채무자 연락처 없으면 DebtrPhone 빈값 (소유자 fallback 없음)",
    resolve_debtr_phone({"소유자 연락처": "050253110210"}, "주택도시보증공사") == "",
)


# 이미 정상 감정서번호가 있는 HUG는 보존
parsed2 = {
    "은행": "주택도시보증공사",
    "의뢰번호": "2026005007",
    "감정서번호": "01-2606-3-1869",
}
pdf_doc2, pdf_est2 = es._normalize_pdf_identity_for_grid(
    parsed2,
    {"은행": "주택도시보증공사"},
    "202606100000095",
    "",
)
check("정상 HUG 감정서번호 보존", pdf_est2 == "01-2606-3-1869")
check("정상 HUG도 그리드 의뢰번호 사용", pdf_doc2 == "202606100000095")


# 타 은행은 기존 비교값 유지
parsed3 = {"은행": "신한은행", "의뢰번호": "A", "감정서번호": "B"}
pdf_doc3, pdf_est3 = es._normalize_pdf_identity_for_grid(
    parsed3, {"은행": "신한은행"}, "C", "D",
)
check("타 은행 번호 변경 없음", (pdf_doc3, pdf_est3) == ("A", "B"))


# ── CustCharge (HUG suffix) 단위 테스트 ──────────────────────────────────────
check(
    "HUG CustCharge: 담당자명 + (HUG)",
    resolve_cust_charge({"담당자": "남건우"}, "주택도시보증공사") == "남건우(HUG)",
)
check(
    "HUG CustCharge: 이미 (HUG) 끝나면 중복 없음",
    resolve_cust_charge({"담당자": "남건우(HUG)"}, "주택도시보증공사") == "남건우(HUG)",
)
check(
    "HUG CustCharge: 담당자 비어있으면 빈값 (suffix 단독 저장 안 함)",
    resolve_cust_charge({"담당자": ""}, "주택도시보증공사") == "",
)
check(
    "타 은행 CustCharge: (HUG) suffix 없음",
    resolve_cust_charge({"담당자": "홍길동"}, "신한은행") == "홍길동",
)

print("ALL PASS")
