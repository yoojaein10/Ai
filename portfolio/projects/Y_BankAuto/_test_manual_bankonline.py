# -*- coding: utf-8 -*-
"""수기 BankOnline 전송(manual_bankonline_send) + auto_send 게이트 검증.

실 DB/네트워크/Bank24 미사용 — fetch_current_docids와 API caller를 주입해 검증한다.
실행: python _test_manual_bankonline.py
"""
import sys

import db_writer
import extract_shinhan as es

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} {detail}")


# ── 1) auto_send 플래그 파싱 (기본 false) ─────────────────────────
check("auto_send 기본값 false", not es._bankonline_auto_send_enabled({"bankonline": {}}))
check("auto_send 미설정+빈 config false", not es._bankonline_auto_send_enabled({}))
for v in ("true", "1", "yes", "on", True):
    check(f"auto_send={v!r} → true",
          es._bankonline_auto_send_enabled({"bankonline": {"auto_send": v}}))
for v in ("false", "0", "no", "", None, False):
    check(f"auto_send={v!r} → false",
          not es._bankonline_auto_send_enabled({"bankonline": {"auto_send": v}}))

# ── 공통 준비 ─────────────────────────────────────────────────────
_orig_fetch = db_writer.fetch_current_docids

def make_config(caller):
    return {
        "bank24_id": "tester",
        'REDACTED_CONFIGURE_LOCALLY': "pw",
        "database": {"server": "x", "database": "y", "username": "u", "password": "p"},
        "_bankonline_api_caller": caller,
    }

ENTRIES = [
    {"의뢰번호": "CD-001", "그리드_의뢰번호": "GRID-001", "은행": "국민은행", "_row": 0},
    {"의뢰번호": "CD-002", "그리드_의뢰번호": "GRID-002", "은행": "신한은행", "_row": 3},
]

# ── 2) 정상 경로: 바뀐 감정서번호를 재조회해 GAM_NO로 전송 ────────
db_writer.fetch_current_docids = lambda cfg, ids, office="10": {
    "ok": True, "docids": {"CD-001": "NEWGAM-111", "CD-002": "NEWGAM-222"}, "error": "",
}
sent_payloads = []

def ok_caller(payload):
    sent_payloads.append(dict(payload))
    return {"success": True}

res = es.manual_bankonline_send(ENTRIES, make_config(ok_caller), log=lambda m: None)
outs = res["outputs"]
check("정상: 2건 모두 Y", [o["BankOnline_In"] for o in outs] == ["Y", "Y"],
      str([o.get("BankOnline_In") for o in outs]))
check("정상: GAM_NO=재조회값(바뀐 감정서번호)",
      [p["GAM_NO"] for p in sent_payloads] == ["NEWGAM-111", "NEWGAM-222"],
      str([p.get("GAM_NO") for p in sent_payloads]))
check("정상: DAMBO_NO=그리드 의뢰번호",
      [p["DAMBO_NO"] for p in sent_payloads] == ["GRID-001", "GRID-002"],
      str([p.get("DAMBO_NO") for p in sent_payloads]))
check("정상: CUSTKEY 은행별",
      [p["CUSTKEY"] for p in sent_payloads] == ["KBB", "SHG"],
      str([p.get("CUSTKEY") for p in sent_payloads]))
check("정상: _row 보존", [o.get("_row") for o in outs] == [0, 3])
check("정상: NewDocID=재조회값", [o["NewDocID"] for o in outs] == ["NEWGAM-111", "NEWGAM-222"])
check("정상: result 집계", res["result"]["success"] == 2 and res["result"]["fail"] == 0)

# ── 3) 재조회 실패 → 전송 0건(fail-closed) ───────────────────────
db_writer.fetch_current_docids = lambda cfg, ids, office="10": {
    "ok": False, "docids": {}, "error": "OperationalError",
}
called = []
res = es.manual_bankonline_send(ENTRIES, make_config(lambda p: called.append(p)),
                                log=lambda m: None)
check("재조회실패: API 호출 0건", not called, str(len(called)))
check("재조회실패: 전부 N + DOCID_LOOKUP_FAILED",
      all(o["BankOnline_In"] == "N" and o["BankOnline_ErrorType"] == "DOCID_LOOKUP_FAILED"
          for o in res["outputs"]))
check("재조회실패: blocked 집계", res["result"]["blocked"] == 2)

# ── 4) 일부 의뢰번호 미존재 → 그 건만 NO_NEWDOCID 보류 ───────────
db_writer.fetch_current_docids = lambda cfg, ids, office="10": {
    "ok": True, "docids": {"CD-001": "NEWGAM-111"}, "error": "",
}
sent_payloads = []
res = es.manual_bankonline_send(ENTRIES, make_config(ok_caller), log=lambda m: None)
outs = res["outputs"]
check("일부미존재: 1건만 전송", [p["GAM_NO"] for p in sent_payloads] == ["NEWGAM-111"])
check("일부미존재: 미존재건 NO_NEWDOCID",
      outs[1]["BankOnline_In"] == "N" and outs[1]["BankOnline_ErrorType"] == "NO_NEWDOCID",
      f"{outs[1].get('BankOnline_In')}/{outs[1].get('BankOnline_ErrorType')}")
check("일부미존재: 존재건 Y", outs[0]["BankOnline_In"] == "Y")

# ── 5) caller 미구성(REST off) → 전부 보류 ───────────────────────
db_writer.fetch_current_docids = lambda cfg, ids, office="10": {
    "ok": True, "docids": {"CD-001": "NEWGAM-111", "CD-002": "NEWGAM-222"}, "error": "",
}
cfg_nocaller = {
    "bank24_id": "tester", 'REDACTED_CONFIGURE_LOCALLY': "pw",
    "database": {}, "bankonline": {"enabled": "false"},
}
res = es.manual_bankonline_send(ENTRIES, cfg_nocaller, log=lambda m: None)
check("caller미구성: 전부 CALLER_NOT_CONFIGURED",
      all(o["BankOnline_ErrorType"] == "CALLER_NOT_CONFIGURED" for o in res["outputs"]))

# ── 6) 빈 entries → 빈 결과, DB 미접근 ───────────────────────────
def _boom(*a, **k):
    raise AssertionError("fetch_current_docids must not be called")
db_writer.fetch_current_docids = lambda cfg, ids, office="10": (
    {"ok": True, "docids": {}, "error": ""}
)
res = es.manual_bankonline_send([], make_config(ok_caller), log=lambda m: None)
check("빈 entries: outputs 비고 tried=0",
      res["outputs"] == [] and res["result"].get("tried", 0) == 0)

db_writer.fetch_current_docids = _orig_fetch
print(f"\n결과: {PASS} PASS / {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
