# -*- coding: utf-8 -*-
"""지원 은행 canonical helper + filter_shinhan_dambo 단위 검증"""
import sys
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')

import extract_shinhan as es

all_ok = True
_logs = []

def chk(label, cond, detail=""):
    global all_ok
    if cond:
        print(f"OK  {label}")
    else:
        print(f"FAIL {label}" + (f" | {detail}" if detail else ""))
        all_ok = False

def _mock_log(msg):
    _logs.append(str(msg))

es._log_callback = _mock_log

# ── 11. helper 단위 검증 ──────────────────────────────────────────
print("\n[11] canonical helper 단위 검증")

chk("_SUPPORTED_BANKS 10개", len(es._SUPPORTED_BANKS) == 10, str(es._SUPPORTED_BANKS))

supported_cases = [
    ("신한은행",              "신한은행"),
    ("기업은행",              "기업은행"),
    ("IBK기업은행",           "기업은행"),
    ("우리은행",              "우리은행"),
    ("주택도시보증공사",       "주택도시보증공사"),
    ("HUG",                   "주택도시보증공사"),
    ("국민은행",              "국민은행"),
    ("KB국민은행",            "국민은행"),
    ("새마을금고",            "새마을금고"),
    ("사당새마을금고",        "새마을금고"),
    ("하나은행",              "하나은행"),
    ("KEB하나은행",           "하나은행"),
    ("농협은행",              "농협은행"),
    ("NH농협은행",            "농협은행"),
    ("농협중앙회",            "농협중앙회"),
    ("군자농협",              "농협중앙회"),
    ("군자농업협동조합",      "농협중앙회"),
    ("수협은행",              "수협은행"),
    ("Sh수협은행",            "수협은행"),
    ("SH수협은행",            "수협은행"),
    ("수협중앙회",            "수협은행"),
    ("영광군수협",            "수협은행"),
    ("영광군수산업협동조합",  "수협은행"),
]

for bank, expected in supported_cases:
    canon = es._canonical_supported_bank(bank)
    chk(
        f"canonical({bank!r}) == {expected!r}",
        canon == expected,
        f"got={canon!r}",
    )
    chk(
        f"is_supported({bank!r})",
        es._is_supported_bank(bank),
    )
    chk(
        f"canonical in _SUPPORTED_BANKS ({bank!r})",
        canon in es._SUPPORTED_BANKS,
        f"canon={canon!r}",
    )

unsupported_cases = [
    "카카오뱅크",
    "토스뱅크",
    "SC제일은행",
    "한국씨티은행",
    "저축은행",
    "",
]
for bank in unsupported_cases:
    canon = es._canonical_supported_bank(bank)
    chk(
        f"canonical({bank!r}) == ''",
        canon == "",
        f"got={canon!r}",
    )
    chk(
        f"not is_supported({bank!r})",
        not es._is_supported_bank(bank),
    )

# None 처리
canon_none = es._canonical_supported_bank(None)
chk("canonical(None) == ''", canon_none == "", f"got={canon_none!r}")
chk("not is_supported(None)", not es._is_supported_bank(None))

# 모든 canonical 결과가 _SUPPORTED_BANKS 안의 값 또는 ""
all_test_banks = [b for b, _ in supported_cases] + unsupported_cases + [None]
for b in all_test_banks:
    c = es._canonical_supported_bank(b)
    chk(
        f"canonical({b!r}) in _SUPPORTED_BANKS or ''",
        c == "" or c in es._SUPPORTED_BANKS,
        f"got={c!r}",
    )

# ── 12. 필터 mock ─────────────────────────────────────────────────
print("\n[12] filter_shinhan_dambo mock")

mock_rows = [
    {"은행": "신한은행",              "업무구분": "담보"},
    {"은행": "KEB하나은행",           "업무구분": "담보"},
    {"은행": "군자농협",              "업무구분": "담보"},
    {"은행": "영광군수산업협동조합",  "업무구분": "담보"},
    {"은행": "카카오뱅크",           "업무구분": "담보"},
    {"은행": "토스뱅크",             "업무구분": "담보"},
    {"은행": "신한은행",              "업무구분": "신용"},
]

# banks=["전체"]: 지원 4건, 미지원 2건, 신용 1건 제외
_logs.clear()
result_all = es.filter_shinhan_dambo(mock_rows, ["전체"])
chk("전체 필터: 반환 4건",      len(result_all) == 4,  f"got={len(result_all)}")
chk("전체 필터: 담보만",        all(r.get("업무구분") == "담보" for r in result_all))
chk("전체 필터: 원본 은행명 유지",
    result_all[0].get("은행") == "신한은행",
    f"got={result_all[0].get('은행')!r}")

skip_logs = [l for l in _logs if "미지원은행" in l]
chk("전체 필터: 미지원 SKIP 로그 2건", len(skip_logs) == 2, str(skip_logs))
for sl in skip_logs:
    chk("미지원 로그에 의뢰번호 없음", "의뢰번호" not in sl, sl)
    chk("미지원 로그에 채무자 없음",   "채무자"   not in sl, sl)
    chk("미지원 로그에 주소 없음",     "주소"     not in sl, sl)

# banks=["신한은행"]: 반환 1건
_logs.clear()
result_sh = es.filter_shinhan_dambo(mock_rows, ["신한은행"])
chk("신한 필터: 반환 1건",    len(result_sh) == 1, f"got={len(result_sh)}")
chk("신한 필터: 은행=신한은행", result_sh[0].get("은행") == "신한은행")

# unsupported_count는 _is_supported_bank 기반 (담보 6건 중 미지원 2건)
dambo_rows = [r for r in mock_rows if es._norm_col(r.get("업무구분", "")) == "담보"]
unsupported_count = sum(
    1 for r in dambo_rows if not es._is_supported_bank(r.get("은행", ""))
)
chk("unsupported_count=2 (_is_supported_bank 기반)", unsupported_count == 2,
    f"got={unsupported_count}")

# 신한만 선택 시: KEB하나/군자농협/영광군수협은 미지원 아님
chk("KEB하나은행은 지원 은행",           es._is_supported_bank("KEB하나은행"))
chk("군자농협은 지원 은행",              es._is_supported_bank("군자농협"))
chk("영광군수산업협동조합은 지원 은행", es._is_supported_bank("영광군수산업협동조합"))

# ── 13. helper 보안 mock ─────────────────────────────────────────
print("\n[13] helper 보안 mock")

# 검증 A: C0 제어문자 + UID/PWD 마스킹
raw_a = "테스트은행\r\n\t\x00UID=mock-user;PWD=mock-password"
safe_a = es._safe_bank_log_name(raw_a)
chk("A: CR 없음",            "\r"         not in safe_a, repr(safe_a))
chk("A: LF 없음",            "\n"         not in safe_a, repr(safe_a))
chk("A: TAB 없음",           "\t"         not in safe_a, repr(safe_a))
chk("A: NULL 없음",          "\x00"       not in safe_a, repr(safe_a))
chk("A: mock-user 없음",     "mock-user"     not in safe_a, repr(safe_a))
chk("A: mock-password 없음", "mock-password" not in safe_a, repr(safe_a))
chk("A: 길이 80자 이하",     len(safe_a) <= 80, f"len={len(safe_a)}")

# 검증 B: DRIVER+SERVER 조합 → 전체 차단
raw_b = (
    "UID=mock-db-user;"
    'PWD=REDACTED_CONFIGURE_LOCALLY;'
    "DRIVER = X;"
    "SERVER = host;"
    "DATABASE=db"
)
safe_b = es._safe_bank_log_name(raw_b)
chk("B: (보안 차단된 은행명)",   safe_b == "(보안 차단된 은행명)",  repr(safe_b))
chk("B: mock-db-user 없음",      "mock-db-user"     not in safe_b, repr(safe_b))
chk("B: mock-db-password 없음",  "mock-db-password" not in safe_b, repr(safe_b))
chk("B: DRIVER 없음",            "DRIVER"           not in safe_b, repr(safe_b))
chk("B: SERVER 없음",            "SERVER"           not in safe_b, repr(safe_b))

# 검증 C: 빈값/None
chk("C: '' → (알수없음)",   es._safe_bank_log_name("") == "(알수없음)")
chk("C: None → (알수없음)", es._safe_bank_log_name(None) == "(알수없음)")
chk("C: 100자 → 80자 이하", len(es._safe_bank_log_name("A" * 100)) <= 80)

# ── 14. filter 로그 보안 mock ────────────────────────────────────
print("\n[14] filter 로그 보안 mock")

mock_row_sec = {
    "은행": (
        "테스트은행\r\n\x1b[31m"
        "UID=mock-user;"
        'PWD=REDACTED_CONFIGURE_LOCALLY;'
        "DRIVER = X;"
        "SERVER = host"
    ),
    "업무구분": "담보",
    "의뢰번호": "SECRET-DOCID",
    "채무자":   "SECRET-DEBTOR",
    "주소":     "SECRET-ADDRESS",
}

_logs.clear()
result_sec = es.filter_shinhan_dambo([mock_row_sec], ["전체"])
chk("filter 결과 빈 list", result_sec == [], f"got={result_sec}")

skip_sec = [l for l in _logs if "미지원은행" in l]
chk("미지원 SKIP 1건", len(skip_sec) == 1, str(skip_sec))

for sl in skip_sec:
    chk("제어문자 없음",           not any(c < " " for c in sl),     repr(sl[:100]))
    chk("ANSI escape 없음",        "\x1b"            not in sl,       repr(sl[:100]))
    chk("mock-user 없음",          "mock-user"        not in sl,       repr(sl[:100]))
    chk("mock-password 없음",      "mock-password"    not in sl,       repr(sl[:100]))
    chk("DRIVER 없음",             "DRIVER"           not in sl,       repr(sl[:100]))
    chk("SERVER 없음",             "SERVER"           not in sl,       repr(sl[:100]))
    chk("SECRET-DOCID 없음",       "SECRET-DOCID"     not in sl,       repr(sl[:100]))
    chk("SECRET-DEBTOR 없음",      "SECRET-DEBTOR"    not in sl,       repr(sl[:100]))
    chk("SECRET-ADDRESS 없음",     "SECRET-ADDRESS"   not in sl,       repr(sl[:100]))
    chk("행 dict 없음",            "업무구분"         not in sl,       repr(sl[:100]))
    chk("(보안 차단된 은행명) 존재", "(보안 차단된 은행명)" in sl,    repr(sl[:100]))

# ── 15. 콘솔 경로 보안 mock ──────────────────────────────────────
print("\n[15] 콘솔 경로 보안 mock")

import contextlib
import io

saved_callback = es._log_callback
captured = io.StringIO()

try:
    es._log_callback = None
    with contextlib.redirect_stdout(captured):
        es.filter_shinhan_dambo([mock_row_sec], ["전체"])
finally:
    es._log_callback = saved_callback

console_text = captured.getvalue()

chk("callback 복원됨",             es._log_callback is saved_callback)
chk("콘솔 mock-user 없음",         "mock-user"           not in console_text, console_text[:200])
chk("콘솔 mock-password 없음",     "mock-password"       not in console_text, console_text[:200])
chk("콘솔 DRIVER 없음",            "DRIVER"              not in console_text, console_text[:200])
chk("콘솔 SERVER 없음",            "SERVER"              not in console_text, console_text[:200])
chk("콘솔 SECRET-DOCID 없음",      "SECRET-DOCID"        not in console_text, console_text[:200])
chk("콘솔 SECRET-DEBTOR 없음",     "SECRET-DEBTOR"       not in console_text, console_text[:200])
chk("콘솔 SECRET-ADDRESS 없음",    "SECRET-ADDRESS"      not in console_text, console_text[:200])
chk("콘솔 (보안 차단된 은행명) 존재", "(보안 차단된 은행명)" in console_text, console_text[:200])

# ── 16. 처리 순서 정적 검증 ──────────────────────────────────────
print("\n[16] 처리 순서 정적 검증")

import inspect

src = inspect.getsource(es.run_extraction)

positions = {
    "filter":    src.find("filter_shinhan_dambo("),
    "duplicate": src.find("find_existing_cust_docids("),
    "pdf":       src.find("_save_pdf_with_retry("),
    "insert":    src.find("insert_apw_master_expand("),
}

chk(
    "처리 단계 문자열 모두 존재",
    all(pos >= 0 for pos in positions.values()),
    str({k: v for k, v in positions.items() if v < 0}),
)

order_ok = (
    all(pos >= 0 for pos in positions.values())
    and positions["filter"] < positions["duplicate"]
    and positions["filter"] < positions["pdf"]
    and positions["filter"] < positions["insert"]
)

chk(
    "지원 은행 필터가 중복/PDF/DB보다 앞",
    order_ok,
    str(positions),
)

# 복원
es._log_callback = None

print()
print("ALL PASS" if all_ok else "SOME FAIL")
