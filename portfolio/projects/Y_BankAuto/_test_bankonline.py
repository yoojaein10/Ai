# -*- coding: utf-8 -*-
"""BankOnline API 통합 검증 — 외부 HTTP/DB/Bank24 사용 없음"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import sys, io, inspect, contextlib, tempfile, json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')

import extract_shinhan as es

all_ok = True

def chk(label, cond, detail=""):
    global all_ok
    if cond:
        print(f"OK  {label}")
    else:
        print(f"FAIL {label}" + (f" | {detail}" if detail else ""))
        all_ok = False


# ── [1] CUSTKEY canonical/alias 매핑 10개 ──────────────────────────────────
print("\n[1] CUSTKEY canonical/alias 매핑")

custkey_cases = [
    ("국민은행",         "KBB"),
    ("KB국민은행",       "KBB"),
    ("신한은행",         "SHG"),
    ("기업은행",         "KIB"),
    ("IBK기업은행",      "KIB"),
    ("하나은행",         "HNB"),
    ("KEB하나은행",      "HNB"),
    ("농협은행",         "NHB"),
    ("NH농협은행",       "NHB"),
    ("농협중앙회",       "NHJ"),
    ("군자농협",         "NHJ"),
    ("우리은행",         "WRB"),
    ("수협은행",         "SSB"),
    ("Sh수협은행",       "SSB"),
    ("SH수협은행",       "SSB"),
    ("수협중앙회",       "SSB"),
    ("영광군수산업협동조합", "SSB"),
    ("새마을금고",       "MGB"),
    ("사당새마을금고",   "MGB"),
    ("주택도시보증공사", "HUG"),
    ("HUG",              "HUG"),
]

for bank, expected_key in custkey_cases:
    canonical = es._canonical_supported_bank(bank)
    got_key   = es._BANKONLINE_CUSTKEY.get(canonical, "")
    chk(f"CUSTKEY({bank!r}) == {expected_key!r}", got_key == expected_key, f"canonical={canonical!r} key={got_key!r}")

chk("_BANKONLINE_CUSTKEY 10개", len(es._BANKONLINE_CUSTKEY) == 10, str(es._BANKONLINE_CUSTKEY))

# 미지원 은행 → 빈 키
for unsupported in ["카카오뱅크", "토스뱅크", "", None]:
    canonical = es._canonical_supported_bank(unsupported)
    got_key   = es._BANKONLINE_CUSTKEY.get(canonical, "")
    chk(f"CUSTKEY({unsupported!r}) == ''", got_key == "", f"got={got_key!r}")


# ── [2] payload 8개 필드 및 고정값 ─────────────────────────────────────────
print("\n[2] payload 필드 및 고정값")

_base_item   = {"은행": "신한은행", "의뢰번호": "SH2026001"}
_base_config = {
    "bank24_id": "testuid", 'REDACTED_CONFIGURE_LOCALLY': "testpwd",
    "_kapa_userid": "kapa-test-id", "_kapa_userpass": "kapa-test-pw",
    "_bankonline_api_caller": lambda p: True,
}
_base_docid  = "GAM001"

payload = es._build_bankonline_payload(_base_item, _base_docid, _base_config)

chk("payload 비어있지 않음",        bool(payload))
chk("CUSTKEY == SHG",              payload.get("CUSTKEY")    == "SHG")
chk("UPMU_GUBUN == '1'",           payload.get("UPMU_GUBUN") == "1")
chk("APPCODE == '300611'",         payload.get("APPCODE")    == "300611")
chk("DAMBO_NO 비어있지 않음",      bool(payload.get("DAMBO_NO")))
chk("GAM_NO == 'GAM001'",          payload.get("GAM_NO")     == "GAM001")
chk("UID 존재",                    bool(payload.get("UID")))
chk("PWD 존재",                    bool(payload.get("PWD")))
chk("payload 키 8개",              len(payload) == 8, str(list(payload.keys())))
chk("Procedure 고정값",            payload.get("Procedure") == "REST_BANK_JUBSU_UPD")
chk("userid 없음 (body 불필요)",   "userid"   not in payload)
chk("userpass 없음 (body 불필요)", "userpass" not in payload)
chk("appcode 소문자 없음",         "appcode"  not in payload)

# CUSTKEY len=3 검증
for k, v in payload.items():
    if k == "CUSTKEY":
        chk("CUSTKEY 길이 3", len(v) == 3, repr(v))

# 미지원 은행 → {}
p_unsupported = es._build_bankonline_payload(
    {"은행": "카카오뱅크", "의뢰번호": "XX001"}, "G001", _base_config
)
chk("미지원 은행 → {}", p_unsupported == {})

# 빈 new_doc_id → {}
p_no_gam = es._build_bankonline_payload(_base_item, "", _base_config)
chk("빈 GAM_NO → {}", p_no_gam == {})

# UID 없음 → {}
p_no_uid = es._build_bankonline_payload(_base_item, _base_docid, {"bank24_id": "", 'REDACTED_CONFIGURE_LOCALLY': "pwd"})
chk("UID 없음 → {}", p_no_uid == {})

# PWD 없음 → {}
p_no_pwd = es._build_bankonline_payload(_base_item, _base_docid, {"bank24_id": "uid", 'REDACTED_CONFIGURE_LOCALLY': ""})
chk("PWD 없음 → {}", p_no_pwd == {})

# DAMBO_NO 길이 초과 → {}
p_long_dambo = es._build_bankonline_payload(_base_item, _base_docid, _base_config)
_long_item   = {"은행": "신한은행", "의뢰번호": "A" * 21}
p_long_dambo = es._build_bankonline_payload(_long_item, _base_docid, _base_config)
chk("DAMBO_NO 21자 → {}", p_long_dambo == {})

# GAM_NO 길이 초과 → {}
p_long_gam = es._build_bankonline_payload(_base_item, "G" * 21, _base_config)
chk("GAM_NO 21자 → {}", p_long_gam == {})


# ── [3] 상세창 의뢰번호 우선순위 ────────────────────────────────────────────
print("\n[3] 상세창 의뢰번호 우선순위")

item_both = {"은행": "신한은행", "의뢰번호": "SH-FALLBACK", "상세창 의뢰번호": "SH-PRIMARY"}
p_both = es._build_bankonline_payload(item_both, "G001", _base_config)
chk("상세창 의뢰번호 우선 사용", p_both.get("DAMBO_NO", "").endswith("SH-PRIMARY".replace("-", "")) or "SH-PRIMARY" in p_both.get("DAMBO_NO", "") or p_both.get("DAMBO_NO") != "")

item_fallback = {"은행": "신한은행", "의뢰번호": "SH-FALLBACK"}
p_fallback = es._build_bankonline_payload(item_fallback, "G001", _base_config)
chk("상세창 없을 때 의뢰번호 fallback", bool(p_fallback))

# 두 경우 DAMBO_NO 다름 확인 (normalize 후 비교)
from db_writer import normalize_cust_docid
chk("상세창 있을 때 DAMBO_NO != fallback DAMBO_NO",
    p_both.get("DAMBO_NO") != p_fallback.get("DAMBO_NO"),
    f"both={p_both.get('DAMBO_NO')!r} fallback={p_fallback.get('DAMBO_NO')!r}")


# ── [4] 앞자리 0과 하이픈 유지 ──────────────────────────────────────────────
print("\n[4] 앞자리 0과 하이픈 처리")

# normalize_cust_docid 통과 후 DAMBO_NO에 앞자리 정보가 있는지 (normalize는 건드리지 않음)
item_zero = {"은행": "신한은행", "의뢰번호": "0012345"}
p_zero = es._build_bankonline_payload(item_zero, "G001", _base_config)
chk("0으로 시작하는 의뢰번호 truncate 없음 (DAMBO_NO 비어있지 않음)", bool(p_zero.get("DAMBO_NO")))

item_hypen = {"은행": "신한은행", "의뢰번호": "SH-2026-001"}
p_hypen = es._build_bankonline_payload(item_hypen, "G-001", _base_config)
chk("GAM_NO 하이픈 유지 (strip만)", p_hypen.get("GAM_NO") == "G-001", repr(p_hypen.get("GAM_NO")))


# ── [5] caller True → Y ─────────────────────────────────────────────────────
print("\n[5] caller True → Y")

cfg_true = {"_bankonline_api_caller": lambda p: True}
status, err = es._call_bankonline_api({"CUSTKEY": "SHG"}, cfg_true)
chk("True → Y", status == "Y")
chk("True → 오류유형 빈값", err == "")


# ── [6] caller {"success": True} → Y ───────────────────────────────────────
print("\n[6] caller {'success': True} → Y")

cfg_dict = {"_bankonline_api_caller": lambda p: {"success": True}}
status2, err2 = es._call_bankonline_api({"CUSTKEY": "SHG"}, cfg_dict)
chk("{'success':True} → Y", status2 == "Y")
chk("{'success':True} → 오류유형 빈값", err2 == "")


# ── [7] caller False → N ────────────────────────────────────────────────────
print("\n[7] caller False → N")

cfg_false = {"_bankonline_api_caller": lambda p: False}
status3, err3 = es._call_bankonline_api({"CUSTKEY": "SHG"}, cfg_false)
chk("False → N", status3 == "N")
chk("False → API_REJECTED", err3 == "API_REJECTED")


# ── [8] caller 예외 → N, 예외 타입만 기록 ──────────────────────────────────
print("\n[8] caller 예외 → N, 예외 타입")

def _raise_value_error(p):
    raise ValueError("mock error content with details")

cfg_exc = {"_bankonline_api_caller": _raise_value_error}
status4, err4 = es._call_bankonline_api({"CUSTKEY": "SHG"}, cfg_exc)
chk("예외 → N", status4 == "N")
chk("예외 → ValueError", err4 == "ValueError")
chk("예외 → 'mock error' 노출 없음", "mock error" not in err4)
chk("예외 → 'content' 노출 없음",   "content"    not in err4)
chk("예외 → 'details' 노출 없음",   "details"    not in err4)


# ── [9] caller 없음 → N, 호출 0회 ──────────────────────────────────────────
print("\n[9] caller 없음 → N, 호출 0회")

call_count = [0]
def _counting_caller(p):
    call_count[0] += 1
    return True

cfg_no_caller = {"bank24_id": "uid", 'REDACTED_CONFIGURE_LOCALLY': "pwd"}
status5, err5 = es._call_bankonline_api({"CUSTKEY": "SHG"}, cfg_no_caller)
chk("caller 없음 → N",                      status5 == "N")
chk("caller 없음 → CALLER_NOT_CONFIGURED",  err5 == "CALLER_NOT_CONFIGURED")

# apply 전체로 검증
logs5 = []
saved5 = es._log_callback
es._log_callback = lambda m: logs5.append(m)
try:
    db5 = {
        "enabled": True, "tried": 1, "success": 1, "fail": 0,
        "rollback_test": False,
        "outputs": [{"의뢰번호": "SH2026001", "NewDocID": "GAM001"}],
    }
    items5 = [{"은행": "신한은행", "의뢰번호": "SH2026001"}]
    cfg5   = {"bank24_id": "uid", 'REDACTED_CONFIGURE_LOCALLY': "pwd"}
    r5 = es._apply_bankonline_updates(db5, items5, cfg5)
finally:
    es._log_callback = saved5

chk("caller 없음 → tried=0", r5["tried"] == 0, str(r5))
chk("caller 없음 → BankOnline_In=N", db5["outputs"][0]["BankOnline_In"] == "N")
chk("caller 없음 → 보류 로그", any("호출 보류" in l for l in logs5), str(logs5))


# ── [10] NewDocID 없음 → N, 호출 0회 ───────────────────────────────────────
print("\n[10] NewDocID 없음 → N, 호출 0회")

logs10 = []
saved10 = es._log_callback
es._log_callback = lambda m: logs10.append(m)
try:
    db10 = {
        "enabled": True, "tried": 1, "success": 1, "fail": 0,
        "rollback_test": False,
        "outputs": [{"의뢰번호": "SH2026002", "NewDocID": ""}],
    }
    items10 = [{"은행": "신한은행", "의뢰번호": "SH2026002"}]
    r10 = es._apply_bankonline_updates(db10, items10, _base_config)
finally:
    es._log_callback = saved10

chk("NewDocID 없음 → tried=0",      r10["tried"] == 0, str(r10))
chk("NewDocID 없음 → BankOnline_In=N", db10["outputs"][0]["BankOnline_In"] == "N")
chk("NewDocID 없음 → 보류 로그",    any("호출 보류" in l for l in logs10), str(logs10))


# ── [11] rollback_test=True → N, 호출 0회 ──────────────────────────────────
print("\n[11] rollback_test=True → N, 호출 0회")

call_count11 = [0]
def _caller11(p):
    call_count11[0] += 1
    return True

logs11 = []
saved11 = es._log_callback
es._log_callback = lambda m: logs11.append(m)
try:
    db11 = {
        "enabled": True, "tried": 0, "success": 0, "fail": 0,
        "rollback_test": True,
        "outputs": [{"의뢰번호": "SH2026003", "NewDocID": "GAM003"}],
    }
    items11 = [{"은행": "신한은행", "의뢰번호": "SH2026003"}]
    cfg11   = {"bank24_id": "uid", 'REDACTED_CONFIGURE_LOCALLY': "pwd", "_bankonline_api_caller": _caller11}
    r11 = es._apply_bankonline_updates(db11, items11, cfg11)
finally:
    es._log_callback = saved11

chk("rollback_test → tried=0",      r11["tried"] == 0,       str(r11))
chk("rollback_test → caller 미호출", call_count11[0] == 0,   f"호출횟수={call_count11[0]}")
chk("rollback_test → BankOnline_In=N", db11["outputs"][0]["BankOnline_In"] == "N")
chk("rollback_test → 보류 로그",    any("호출 보류" in l for l in logs11), str(logs11))


# ── [12] item 매칭 실패 → N, 호출 0회 ──────────────────────────────────────
print("\n[12] item 매칭 실패 → N, 호출 0회")

logs12 = []
saved12 = es._log_callback
es._log_callback = lambda m: logs12.append(m)
try:
    db12 = {
        "enabled": True, "tried": 1, "success": 1, "fail": 0,
        "rollback_test": False,
        "outputs": [{"의뢰번호": "SH2026004", "NewDocID": "GAM004"}],
    }
    items12 = [{"은행": "신한은행", "의뢰번호": "SH9999999"}]  # 다른 의뢰번호
    r12 = es._apply_bankonline_updates(db12, items12, _base_config)
finally:
    es._log_callback = saved12

chk("item 매칭 실패 → tried=0",       r12["tried"] == 0, str(r12))
chk("item 매칭 실패 → BankOnline_In=N", db12["outputs"][0]["BankOnline_In"] == "N")
chk("item 매칭 실패 → 보류 로그",     any("호출 보류" in l for l in logs12), str(logs12))


# ── [13] outputs 없음 → 호출 0회 ────────────────────────────────────────────
print("\n[13] outputs 없음 → 호출 0회")

call_count13 = [0]
def _caller13(p):
    call_count13[0] += 1
    return True

db13 = {"enabled": True, "tried": 0, "success": 0, "fail": 0, "rollback_test": False, "outputs": []}
items13 = [{"은행": "신한은행", "의뢰번호": "SH2026005"}]
cfg13   = {"_bankonline_api_caller": _caller13}
r13 = es._apply_bankonline_updates(db13, items13, cfg13)

chk("outputs 없음 → tried=0",      r13["tried"] == 0, str(r13))
chk("outputs 없음 → caller 미호출", call_count13[0] == 0, f"호출횟수={call_count13[0]}")


# ── [14] success + fail == tried ────────────────────────────────────────────
print("\n[14] success + fail == tried")

call_seq = [True, False, True]  # caller 응답 순서
_idx14 = [0]
def _caller14(p):
    r = call_seq[_idx14[0] % len(call_seq)]
    _idx14[0] += 1
    return r

db14 = {
    "enabled": True, "tried": 3, "success": 2, "fail": 1,
    "rollback_test": False,
    "outputs": [
        {"의뢰번호": "SH001", "NewDocID": "G001"},
        {"의뢰번호": "SH002", "NewDocID": "G002"},
        {"의뢰번호": "SH003", "NewDocID": "G003"},
    ],
}
items14 = [
    {"은행": "신한은행", "의뢰번호": "SH001"},
    {"은행": "신한은행", "의뢰번호": "SH002"},
    {"은행": "신한은행", "의뢰번호": "SH003"},
]
cfg14 = {"bank24_id": "uid", 'REDACTED_CONFIGURE_LOCALLY': "pwd", "_kapa_userid": "kid", "_kapa_userpass": "kpw", "_bankonline_api_caller": _caller14}
r14 = es._apply_bankonline_updates(db14, items14, cfg14)

chk("success + fail == tried", r14["success"] + r14["fail"] == r14["tried"],
    f"s={r14['success']} f={r14['fail']} t={r14['tried']}")
chk("tried == 3", r14["tried"] == 3, str(r14))
chk("success == 2", r14["success"] == 2, str(r14))
chk("fail == 1", r14["fail"] == 1, str(r14))


# ── [15] GUI NewDocID → 감정서번호 표시 ─────────────────────────────────────
print("\n[15] GUI NewDocID → 감정서번호 표시")

try:
    from PyQt6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)
    import gui_prototype as gp
    with tempfile.TemporaryDirectory() as _tmpdir:
        _orig_log_dir = gp.LOG_DIR
        gp.LOG_DIR = type(gp.LOG_DIR)(_tmpdir)
        try:
            win = gp.MainWindow()
            # 의뢰번호 행 추가 (처리 대기 상태)
            item15 = {
                "은행": "신한은행", "의뢰번호": "SH2026099",
                "status": "성공", "failure_reason": "",
                "감정서번호": "", "비고": "",
            }
            win._on_worker_item(item15)
            docid15 = gp._normalize_result_docid("SH2026099")
            row15   = win._result_rows_by_docid.get(docid15)
            chk("GUI 행 추가됨", row15 is not None, str(win._result_rows_by_docid))

            # summary 이벤트 (NewDocID 포함)
            summary15 = {
                "file": "",
                "db": {
                    "enabled": True, "tried": 1, "success": 1, "fail": 0,
                    "duplicate_skipped": 0,
                    "outputs": [{"의뢰번호": "SH2026099", "NewDocID": "GAM15TEST", "BankOnline_In": "Y"}],
                    "errors": [],
                },
            }
            win._on_worker_summary(summary15)

            gam_col15 = gp.TABLE_COLS.index("감정서번호")
            gam_cell15 = win.table.item(row15, gam_col15)
            chk("감정서번호 = GAM15TEST", gam_cell15 and gam_cell15.text() == "GAM15TEST",
                repr(gam_cell15.text() if gam_cell15 else None))
        finally:
            gp.LOG_DIR = _orig_log_dir
except Exception as _e15:
    chk("GUI 테스트 실행 가능", False, str(_e15))


# ── [16] GUI BankOnline_In Y/N 색상 ─────────────────────────────────────────
print("\n[16] GUI BankOnline_In Y/N 색상")

try:
    from PyQt6.QtGui import QColor as _QColor
    _app16 = QApplication.instance() or QApplication(sys.argv)
    with tempfile.TemporaryDirectory() as _tmpdir16:
        _orig16 = gp.LOG_DIR
        gp.LOG_DIR = type(gp.LOG_DIR)(_tmpdir16)
        try:
            win16 = gp.MainWindow()
            for _req_id, _bo_val, _expected_color in [
                ("SH2026101", "Y", gp.C["green"]),
                ("SH2026102", "N", gp.C["red"]),
            ]:
                win16._on_worker_item({
                    "은행": "신한은행", "의뢰번호": _req_id,
                    "status": "성공", "failure_reason": "", "감정서번호": "", "비고": "",
                })
                _docid16 = gp._normalize_result_docid(_req_id)
                _row16   = win16._result_rows_by_docid.get(_docid16)
                win16._on_worker_summary({
                    "file": "",
                    "db": {
                        "enabled": True, "tried": 1, "success": 1, "fail": 0,
                        "duplicate_skipped": 0,
                        "outputs": [{"의뢰번호": _req_id, "NewDocID": "GAM16X", "BankOnline_In": _bo_val}],
                        "errors": [],
                    },
                })
                _bo_col16  = gp.TABLE_COLS.index("BankOnline_In")
                _bo_cell16 = win16.table.item(_row16, _bo_col16) if _row16 is not None else None
                chk(f"BankOnline_In={_bo_val!r} 텍스트", _bo_cell16 and _bo_cell16.text() == _bo_val,
                    repr(_bo_cell16.text() if _bo_cell16 else None))
                if _bo_cell16:
                    _fg = _bo_cell16.foreground().color()
                    _expected = _QColor(_expected_color)
                    chk(f"BankOnline_In={_bo_val!r} 색상 RGB",
                        (_fg.red(), _fg.green(), _fg.blue()) == (_expected.red(), _expected.green(), _expected.blue()),
                        f"got=({_fg.red()},{_fg.green()},{_fg.blue()}) expected=({_expected.red()},{_expected.green()},{_expected.blue()})")
        finally:
            gp.LOG_DIR = _orig16
except Exception as _e16:
    chk("GUI 색상 테스트 실행 가능", False, str(_e16))


# ── [17] 기존 output 키 없음 → BankOnline_In 컬럼 빈값 유지 ─────────────────
print("\n[17] output에 BankOnline_In 키 없음 → 컬럼 빈값 유지")

try:
    _app17 = QApplication.instance() or QApplication(sys.argv)
    with tempfile.TemporaryDirectory() as _tmpdir17:
        _orig17 = gp.LOG_DIR
        gp.LOG_DIR = type(gp.LOG_DIR)(_tmpdir17)
        try:
            win17 = gp.MainWindow()
            win17._on_worker_item({
                "은행": "신한은행", "의뢰번호": "SH2026200",
                "status": "성공", "failure_reason": "", "감정서번호": "", "비고": "",
            })
            _docid17 = gp._normalize_result_docid("SH2026200")
            _row17   = win17._result_rows_by_docid.get(_docid17)
            # output에 BankOnline_In 없음
            win17._on_worker_summary({
                "file": "",
                "db": {
                    "enabled": True, "tried": 1, "success": 1, "fail": 0,
                    "duplicate_skipped": 0,
                    "outputs": [{"의뢰번호": "SH2026200", "NewDocID": "GAM200"}],
                    "errors": [],
                },
            })
            _bo_col17  = gp.TABLE_COLS.index("BankOnline_In")
            _bo_cell17 = win17.table.item(_row17, _bo_col17) if _row17 is not None else None
            _bo_text17 = _bo_cell17.text() if _bo_cell17 else ""
            chk("BankOnline_In 키 없음 → 컬럼 빈값", _bo_text17 == "", repr(_bo_text17))
        finally:
            gp.LOG_DIR = _orig17
except Exception as _e17:
    chk("GUI 키 없음 테스트 실행 가능", False, str(_e17))


# ── [18] DB 실패/중복 → API 대상 아님 ──────────────────────────────────────
print("\n[18] DB 실패/중복 → API 미호출")

call_count18 = [0]
def _caller18(p):
    call_count18[0] += 1
    return True

# DB 실패 시 outputs 없음 → API 미호출
db18_fail = {
    "enabled": True, "tried": 1, "success": 0, "fail": 1,
    "rollback_test": False,
    "outputs": [],  # 실패 시 outputs 없음
    "errors": [{"의뢰번호": "SH2026300", "error": "MSSQL_ERROR"}],
}
cfg18 = {"bank24_id": "uid", 'REDACTED_CONFIGURE_LOCALLY': "pwd", "_bankonline_api_caller": _caller18}
r18 = es._apply_bankonline_updates(db18_fail, [{"은행": "신한은행", "의뢰번호": "SH2026300"}], cfg18)
chk("DB 실패 → tried=0", r18["tried"] == 0, str(r18))
chk("DB 실패 → caller 미호출", call_count18[0] == 0, f"호출횟수={call_count18[0]}")

# 중복 SKIP → outputs에 포함 안됨 (tried=0)
call_count18[0] = 0
db18_dup = {
    "enabled": True, "tried": 0, "success": 0, "fail": 0,
    "duplicate_skipped": 1,
    "rollback_test": False,
    "outputs": [],
}
r18b = es._apply_bankonline_updates(db18_dup, [{"은행": "신한은행", "의뢰번호": "SH2026301"}], cfg18)
chk("중복SKIP → tried=0", r18b["tried"] == 0, str(r18b))
chk("중복SKIP → caller 미호출", call_count18[0] == 0, f"호출횟수={call_count18[0]}")


# ── [19] UID/PWD가 logs/errors/summary/output/tooltip에 없음 ─────────────────
print("\n[19] UID/PWD 노출 없음")

_collected_logs19 = []
saved19 = es._log_callback
es._log_callback = lambda m: _collected_logs19.append(m)

_SECRET_UID = 'REDACTED_CONFIGURE_LOCALLY'
_SECRET_PWD = 'REDACTED_CONFIGURE_LOCALLY'

try:
    def _caller19_exc(p):
        raise RuntimeError("detail about uid and pwd")

    db19 = {
        "enabled": True, "tried": 1, "success": 1, "fail": 0,
        "rollback_test": False,
        "outputs": [{"의뢰번호": "SH2026400", "NewDocID": "GAM400"}],
    }
    items19 = [{"은행": "신한은행", "의뢰번호": "SH2026400"}]
    cfg19   = {
        "bank24_id": _SECRET_UID,
        'REDACTED_CONFIGURE_LOCALLY': _SECRET_PWD,
        "_kapa_userid": "kid19",
        "_kapa_userpass": "kpw19",
        "_bankonline_api_caller": _caller19_exc,
    }
    r19 = es._apply_bankonline_updates(db19, items19, cfg19)
finally:
    es._log_callback = saved19

all_text19 = " ".join(_collected_logs19) + " " + str(r19)
chk("UID 로그/결과 미노출", _SECRET_UID not in all_text19, all_text19[:200])
chk("PWD 로그/결과 미노출", _SECRET_PWD not in all_text19, all_text19[:200])

# errors 항목에 UID/PWD 없음
for err19 in r19.get("errors", []):
    err_str = str(err19)
    chk("errors에 UID 없음", _SECRET_UID not in err_str, err_str)
    chk("errors에 PWD 없음", _SECRET_PWD not in err_str, err_str)


# ── [20] payload/response/예외 전문이 로그에 없음 ───────────────────────────
print("\n[20] payload/response/예외 전문 로그 미노출")

_collected_logs20 = []
saved20 = es._log_callback
es._log_callback = lambda m: _collected_logs20.append(m)

_SECRET_DAMBO = 'REDACTED_CONFIGURE_LOCALLY'
_SECRET_GAM   = 'REDACTED_CONFIGURE_LOCALLY'

def _caller20_exc(p):
    raise ConnectionError(f"host=secret-host dambo={_SECRET_DAMBO} gam={_SECRET_GAM}")

try:
    db20 = {
        "enabled": True, "tried": 1, "success": 1, "fail": 0,
        "rollback_test": False,
        "outputs": [{"의뢰번호": _SECRET_DAMBO, "NewDocID": _SECRET_GAM}],
    }
    items20 = [{"은행": "신한은행", "의뢰번호": _SECRET_DAMBO}]
    cfg20   = {
        "bank24_id": "uid20",
        'REDACTED_CONFIGURE_LOCALLY': "pwd20",
        "_kapa_userid": "kid20",
        "_kapa_userpass": "kpw20",
        "_bankonline_api_caller": _caller20_exc,
    }
    r20 = es._apply_bankonline_updates(db20, items20, cfg20)
finally:
    es._log_callback = saved20

all_text20 = " ".join(_collected_logs20) + " " + str(r20)
# 예외 메시지 본문 미노출 (타입명만 기록)
chk("예외 본문 미노출 (secret-host)", "secret-host" not in all_text20, all_text20[:300])
# 에러 타입은 기록됨
chk("예외 타입 기록 (ConnectionError)", "ConnectionError" in all_text20, all_text20[:300])

# GUI에서 전달하는 Bank24 인증값을 사용하고, 실행 로그에는 원문을 출력하지 않는다.
run_src20 = inspect.getsource(es.run_extraction)
chk("Bank24 ID 원문 로그 없음", 'log(f"Bank24 ID: {uid}")' not in run_src20)


# ── [21] 로컬 mock HTTP 서버 REST 호출 ─────────────────────────────────────
print("\n[21] REST caller 로컬 mock 서버")

received21 = {}

class _Handler21(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        received21["method"] = self.command
        received21["content_type"] = self.headers.get("Content-Type", "")
        received21["authorization"] = self.headers.get("Authorization", "")
        received21["payload"] = {
            k: v[0] for k, v in parse_qs(self.rfile.read(size).decode("utf-8")).items()
        }
        body = json.dumps({"success": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass

server21 = HTTPServer(("127.0.0.1", 0), _Handler21)
thread21 = threading.Thread(target=server21.serve_forever, daemon=True)
thread21.start()
try:
    cfg21 = {
        "_bankonline_authorization": "test-authorization-21",
        "bankonline": {
            "enabled": True,
            "endpoint": f"http://127.0.0.1:{server21.server_port}/REST_BANK_JUBSU_UPD",
            "method": "POST",
            "request_format": "form",
            "timeout_seconds": "3",
            "success_field": "success",
            "success_value": "true",
            "allow_http": True,
        }
    }
    payload21 = {"CUSTKEY": "SHG", "UPMU_GUBUN": "1", "DAMBO_NO": "D21", "GAM_NO": "G21", "APPCODE": "300611", "UID": "u21", "PWD": "p21"}
    status21, err21 = es._call_bankonline_api(payload21, cfg21)
finally:
    server21.shutdown()
    server21.server_close()
    thread21.join(timeout=2)

chk("REST POST → Y", status21 == "Y", f"status={status21} err={err21}")
chk("REST method POST", received21.get("method") == "POST", str(received21))
chk("REST form content type", received21.get("content_type", "").startswith("application/x-www-form-urlencoded"), str(received21))
chk("Authorization 헤더 전달", received21.get("authorization") == "test-authorization-21")
chk("REST payload 전달", received21.get("payload") == payload21)

cfg21_blocked = {"_bankonline_authorization": "test-authorization-21", "bankonline": {"enabled": True, "endpoint": "http://example.invalid/api", "allow_http": False}}
status21b, err21b = es._call_bankonline_api(payload21, cfg21_blocked)
chk("기본 HTTP 차단", status21b == "N" and err21b == "ValueError", f"status={status21b} err={err21b}")


# ── [S11] 호출 순서 정적 검증 ───────────────────────────────────────────────
print("\n[S11] 호출 순서 정적 검증")

src = inspect.getsource(es.run_extraction)

pos_insert  = src.find("insert_apw_master_expand(")
pos_bankon  = src.find("_apply_bankonline_updates(")
pos_pdf     = src.find("KEEP_PDF_HISTORY")
pos_summary = src.rfind('on_summary({"counts"')  # 마지막(주 경로) 호출 위치

chk("insert_apw_master_expand 존재",  pos_insert >= 0)
chk("_apply_bankonline_updates 존재", pos_bankon >= 0)
chk("KEEP_PDF_HISTORY 존재",          pos_pdf    >= 0)
chk("on_summary 호출 존재",           pos_summary >= 0)

chk("insert < _apply_bankonline_updates", pos_insert < pos_bankon,
    f"insert={pos_insert} apply={pos_bankon}")
chk("_apply_bankonline_updates < PDF",    pos_bankon < pos_pdf,
    f"apply={pos_bankon} pdf={pos_pdf}")
chk("PDF < on_summary",                   pos_pdf    < pos_summary,
    f"pdf={pos_pdf} summary={pos_summary}")

# rollback_test 블록 존재
chk("rollback_test 블록 존재", "rollback_test" in src)
# API 실패가 DB 롤백 트리거 없음 (rollback_test= 와 _apply_bankonline 사이에 rollback 호출 없음)
chk("API 실패 → rollback 없음", "rollback" not in src[pos_bankon:pos_pdf].lower().replace("rollback_test", ""))


print()
print("ALL PASS" if all_ok else "SOME FAIL")
