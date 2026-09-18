# -*- coding: utf-8 -*-
"""BankOnline API 처리 로그/보안 단위 테스트.

실제 API·DB·Bank24·DNS·인터넷 연결을 금지한다. mock caller와 합성 데이터만 사용.
- 테스트 시작 전에 socket/urllib 실제 연결을 전면 차단하고, 실연결 시 즉시 실패한다.
- 운영 settings.ini·실자격증명·실DB를 읽지 않는다.
- 파일명 접두사 `_test_` : PyInstaller 번들에서 제외되는 규칙을 따른다.

실행:  python _test_bankonline_api.py
"""
import socket
import sys
import urllib.error
import urllib.request

# ── 실제 네트워크 전면 차단 (테스트 시작 전) ──────────────────────────────────
_NET = {"hits": 0}


def _block(*_a, **_k):
    _NET["hits"] += 1
    raise AssertionError("REAL_NETWORK_BLOCKED")


socket.socket.connect = lambda self, *a, **k: _block()
socket.socket.connect_ex = lambda self, *a, **k: _block()
socket.create_connection = _block
socket.getaddrinfo = _block
urllib.request.urlopen = _block

import extract_shinhan as es  # noqa: E402

# ── 합성 시크릿 / PII / 원문 식별자 (로그에 절대 나타나면 안 됨) ────────────────
SECRET_BANK_PW = 'REDACTED_CONFIGURE_LOCALLY'
SECRET_DB_PW   = 'REDACTED_CONFIGURE_LOCALLY'
SECRET_KAPA_PW = 'REDACTED_CONFIGURE_LOCALLY'
SECRET_TOKEN   = 'REDACTED_CONFIGURE_LOCALLY'
STATIC_APPKEY  = 'REDACTED_CONFIGURE_LOCALLY'   # 토큰 endpoint 정적 앱키 (기존 자산)
PII_NAME       = "홍길동데비"
PII_ADDR       = "서울시비밀구합성로77"
ORIG_DOCID     = "9911223344"
ORIG_DOCID2    = "8811224455"
ORIG_ESTNO     = "EST-77777"
ORIG_NEWDOC    = "NDOC-55555"

_LEAK_STRINGS = [
    SECRET_BANK_PW, SECRET_DB_PW, SECRET_KAPA_PW, SECRET_TOKEN, STATIC_APPKEY,
    PII_NAME, PII_ADDR, ORIG_DOCID, ORIG_DOCID2, ORIG_ESTNO, ORIG_NEWDOC,
    "Authorization",
]

# ── 로그 캡처 ────────────────────────────────────────────────────────────────
LOGS = []
es._log_callback = lambda m: LOGS.append(str(m))

_ALLOWED_CODE_TOKENS = set(es._API_SAFE_CODES) | {"none"}


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────
def base_config(bankonline_over=None, **over):
    bo = {
        "enabled": True,
        "endpoint": "https://webrest.kapanet.or.kr/WEB_RESTAPI",
        "token_endpoint": "https://authtoken.kapanet.or.kr/AuthServer",
        "request_format": "form",
        "success_field": "success",
        "success_value": "true",
    }
    if bankonline_over:
        bo.update(bankonline_over)
    cfg = {
        "bank24_id": "bank24user",
        'REDACTED_CONFIGURE_LOCALLY': SECRET_BANK_PW,
        "database": {"username": "dbu", "password": SECRET_DB_PW},
        "bankonline": bo,
    }
    cfg.update(over)
    return cfg


def make_item(docid=ORIG_DOCID, bank="국민은행"):
    return {"은행": bank, "상세창 의뢰번호": docid, "의뢰번호": docid,
            "감정서번호": ORIG_ESTNO, "채무자": PII_NAME, "소재지": PII_ADDR}


def make_output(docid=ORIG_DOCID, newdoc=ORIG_NEWDOC):
    return {"의뢰번호": docid, "NewDocID": newdoc, "채무자": PII_NAME, "소재지": PII_ADDR}


def db_ok(outputs, rollback=False):
    return {"enabled": True, "tried": len(outputs), "success": len(outputs),
            "fail": 0, "errors": [], "rollback_test": rollback, "outputs": outputs}


def run_stage(db_result, items, config):
    start = len(LOGS)
    res = es._apply_bankonline_updates(db_result, items, config)
    return res, LOGS[start:]


def parse_summary(lines):
    s = [l for l in lines if "[API][SUMMARY]" in l]
    assert len(s) == 1, f"SUMMARY는 정확히 1회여야 함, got {len(s)}: {s}"
    import re
    m = dict(re.findall(r"(target|attempted|success|failed|skipped)=(\d+)", s[0]))
    d = {k: int(v) for k, v in m.items()}
    assert d["attempted"] == d["success"] + d["failed"], f"attempted 불변식 위반: {d}"
    assert d["target"] == d["attempted"] + d["skipped"], f"target 불변식 위반: {d}"
    return d


def last_skip_reason(lines):
    r = [l for l in lines if "[API][SKIP]" in l]
    assert r, f"SKIP 로그 없음: {lines}"
    import re
    return re.search(r"reason=(\w+)", r[-1]).group(1)


def assert_codes_allowlisted(lines):
    import re
    for l in lines:
        for tok in re.findall(r"(?:error_code|reason)=([^\s]+)", l):
            assert tok in _ALLOWED_CODE_TOKENS, f"비-allowlist 코드: {tok} in {l}"


# ── FakeOpener (urllib 대체, 실연결 없음) ─────────────────────────────────────
class FakeResp:
    def __init__(self, body=b"", status=200):
        self._b = body
        self.status = status

    def read(self, n=-1):
        return self._b[:n] if (n is not None and n >= 0) else self._b

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, body=b"", status=200, raise_exc=None):
        self.captured = []
        self._body, self._status, self._raise = body, status, raise_exc

    def open(self, request, timeout=None):
        self.captured.append(request)
        if self._raise:
            raise self._raise
        return FakeResp(self._body, self._status)


# ══════════════════════════════════════════════════════════════════════════════
# 테스트
# ══════════════════════════════════════════════════════════════════════════════
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def t_disabled():
    cfg = base_config(bankonline_over={"enabled": False})
    res, lines = run_stage(db_ok([make_output()]), [make_item()], cfg)
    assert last_skip_reason(lines) == "DISABLED"
    d = parse_summary(lines)
    assert d == {"target": 0, "attempted": 0, "success": 0, "failed": 0, "skipped": 0}


@test
def t_endpoint_missing():
    cfg = base_config(bankonline_over={"endpoint": ""})
    _, lines = run_stage(db_ok([make_output()]), [make_item()], cfg)
    assert last_skip_reason(lines) == "ENDPOINT_MISSING"
    parse_summary(lines)


@test
def t_endpoint_not_https():
    cfg = base_config(bankonline_over={"endpoint": "http://webrest.kapanet.or.kr/x"})
    _, lines = run_stage(db_ok([make_output()]), [make_item()], cfg)
    assert last_skip_reason(lines) == "ENDPOINT_INVALID"


@test
def t_endpoint_userinfo():
    cfg = base_config(bankonline_over={"endpoint": 'https://contact@example.com/x'})
    _, lines = run_stage(db_ok([make_output()]), [make_item()], cfg)
    assert last_skip_reason(lines) == "ENDPOINT_INVALID"


@test
def t_endpoint_not_allowed():
    cfg = base_config(bankonline_over={"endpoint": "https://evil.example.com/WEB_RESTAPI"})
    _, lines = run_stage(db_ok([make_output()]), [make_item()], cfg)
    assert last_skip_reason(lines) == "ENDPOINT_NOT_ALLOWED"


@test
def t_token_endpoint_not_allowed():
    cfg = base_config(bankonline_over={"token_endpoint": "https://evil.example.com/AuthServer"})
    _, lines = run_stage(db_ok([make_output()]), [make_item()], cfg)
    assert last_skip_reason(lines) == "ENDPOINT_NOT_ALLOWED"


@test
def t_db_failed():
    cfg = base_config()
    cfg["_bankonline_api_caller"] = lambda p: True
    db = {"enabled": True, "tried": 1, "success": 0, "fail": 1,
          "errors": [{"error": "X"}], "rollback_test": False, "outputs": []}
    _, lines = run_stage(db, [make_item()], cfg)
    assert last_skip_reason(lines) == "DB_FAILED"
    parse_summary(lines)


@test
def t_no_output():
    cfg = base_config()
    cfg["_bankonline_api_caller"] = lambda p: True
    db = {"enabled": True, "tried": 0, "success": 0, "fail": 0,
          "errors": [], "rollback_test": False, "outputs": []}
    _, lines = run_stage(db, [make_item()], cfg)
    assert last_skip_reason(lines) == "NO_OUTPUT"
    parse_summary(lines)


@test
def t_no_newdocid():
    cfg = base_config()
    cfg["_bankonline_api_caller"] = lambda p: True
    out = make_output(newdoc="")
    _, lines = run_stage(db_ok([out]), [make_item()], cfg)
    assert last_skip_reason(lines) == "NO_NEWDOCID"
    assert out["BankOnline_In"] == "N"
    d = parse_summary(lines)
    assert d["skipped"] == 1 and d["target"] == 1


@test
def t_item_match_failed():
    cfg = base_config()
    cfg["_bankonline_api_caller"] = lambda p: True
    out = make_output(docid=ORIG_DOCID)
    item = make_item(docid=ORIG_DOCID2)  # 다른 docid → 매칭 실패
    _, lines = run_stage(db_ok([out]), [item], cfg)
    assert last_skip_reason(lines) == "ITEM_MATCH_FAILED"
    assert any("[API][ITEM]" in l and "matched=false" in l for l in lines)


@test
def t_rollback():
    cfg = base_config()
    cfg["_bankonline_api_caller"] = lambda p: True
    _, lines = run_stage(db_ok([make_output()], rollback=True), [make_item()], cfg)
    assert last_skip_reason(lines) == "ROLLBACK_TEST"


@test
def t_token_credentials_unavailable(monkey):
    monkey("db_writer", "fetch_kapa_credentials", lambda *a, **k: ("", ""))
    cfg = base_config()
    _, lines = run_stage(db_ok([make_output()]), [make_item()], cfg)
    assert any("[API][TOKEN] result=failure" in l for l in lines)
    assert last_skip_reason(lines) == "TOKEN_CREDENTIALS_UNAVAILABLE"


@test
def t_token_request_failed(monkey):
    monkey("db_writer", "fetch_kapa_credentials", lambda *a, **k: ("kid", SECRET_KAPA_PW))
    monkey("extract_shinhan", "_fetch_bankonline_token",
           lambda *a, **k: (_ for _ in ()).throw(es._ApiError("TOKEN_REQUEST_FAILED")))
    cfg = base_config()
    _, lines = run_stage(db_ok([make_output()]), [make_item()], cfg)
    assert last_skip_reason(lines) == "TOKEN_REQUEST_FAILED"


@test
def t_api_success_mock():
    seen = {}
    cfg = base_config()
    cfg["_bankonline_api_caller"] = lambda p: seen.update(p) or True
    out = make_output()
    _, lines = run_stage(db_ok([out]), [make_item()], cfg)
    assert out["BankOnline_In"] == "Y"
    assert seen.get("APPCODE") == "300617"                    # payload appcode
    assert any("[API][SEND]" in l and "appcode=300617" in l for l in lines)
    assert any("[API][RESULT]" in l and "BankOnline_In=Y" in l for l in lines)
    d = parse_summary(lines)
    assert d == {"target": 1, "attempted": 1, "success": 1, "failed": 0, "skipped": 0}


@test
def t_api_rejected_mock():
    cfg = base_config()
    cfg["_bankonline_api_caller"] = lambda p: False   # 성공 필드 아님 → 거절
    out = make_output()
    _, lines = run_stage(db_ok([out]), [make_item()], cfg)
    assert out["BankOnline_In"] == "N"
    assert out["BankOnline_ErrorType"] == "API_REJECTED"
    d = parse_summary(lines)
    assert d == {"target": 1, "attempted": 1, "success": 0, "failed": 1, "skipped": 0}


@test
def t_api_http_error_mock():
    def _raise(p):
        raise urllib.error.HTTPError("https://x", 500, "err", {}, None)
    cfg = base_config()
    cfg["_bankonline_api_caller"] = _raise
    out = make_output()
    _, lines = run_stage(db_ok([out]), [make_item()], cfg)
    assert out["BankOnline_In"] == "N"
    assert out["BankOnline_ErrorType"] == "HTTP_STATUS_ERROR"
    assert any("http_status=500" in l for l in lines)


@test
def t_duplicate_blocked():
    cfg = base_config()
    cfg["_bankonline_api_caller"] = lambda p: True
    outs = [make_output(docid=ORIG_DOCID), make_output(docid=ORIG_DOCID)]  # 동일 건 2회
    _, lines = run_stage(db_ok(outs), [make_item(docid=ORIG_DOCID)], cfg)
    assert any("reason=DUPLICATE_ATTEMPT_BLOCKED" in l for l in lines)
    d = parse_summary(lines)
    assert d["attempted"] == 1 and d["skipped"] == 1 and d["target"] == 2


@test
def t_summary_on_exception():
    cfg = base_config()
    cfg["_bankonline_api_caller"] = lambda p: True
    # items=None → 내부 반복에서 예외 → UNEXPECTED_ERROR 흡수 + SUMMARY 1회
    res, lines = run_stage(db_ok([make_output()]), None, cfg)
    assert any("reason=UNEXPECTED_ERROR" in l for l in lines)
    assert len([l for l in lines if "[API][SUMMARY]" in l]) == 1


@test
def t_ref_differs_and_irreversible():
    cfg = base_config()
    cfg["_bankonline_api_caller"] = lambda p: True
    import re
    _, l1 = run_stage(db_ok([make_output()]), [make_item()], cfg)
    _, l2 = run_stage(db_ok([make_output()]), [make_item()], cfg)
    r1 = re.search(r"\[API\]\[ITEM\] ref=(\w+)", " ".join(l1)).group(1)
    r2 = re.search(r"\[API\]\[ITEM\] ref=(\w+)", " ".join(l2)).group(1)
    assert r1 != r2, "실행 salt가 다르면 ref도 달라야 함"
    assert len(r1) == 12 and all(c in '0REDACTED_CONFIGURE_LOCALLY789abcdef' for c in r1)
    assert ORIG_DOCID not in r1 and r1 not in ORIG_DOCID  # 원문 복원/포함 불가


@test
def t_scrub_control_chars():
    out = es._api_scrub("a\r\nb\x00c\x1bd\x85e\ttab")
    for bad in ("\r", "\n", "\x00", "\x1b", "\x85", "\t"):
        assert bad not in out, f"제어문자 미제거: {bad!r}"
    assert len(es._api_scrub("x" * 5000)) <= es._API_LOG_MAXLEN


@test
def t_endpoint_check_unit():
    ok = es._api_check_endpoint("https://webrest.kapanet.or.kr/x", es._API_ENDPOINT_HOSTS)
    assert ok == (True, True, True, "")
    assert es._api_check_endpoint("", es._API_ENDPOINT_HOSTS)[3] == "ENDPOINT_MISSING"
    assert es._api_check_endpoint("http://webrest.kapanet.or.kr/x", es._API_ENDPOINT_HOSTS)[3] == "ENDPOINT_INVALID"
    assert es._api_check_endpoint("https://sub.evil.com/x", es._API_ENDPOINT_HOSTS)[3] == "ENDPOINT_NOT_ALLOWED"
    # suffix 혼동 방지: 'webrest.kapanet.or.kr.evil.com'은 허용되면 안 됨
    assert es._api_check_endpoint("https://webrest.kapanet.or.kr.evil.com/x", es._API_ENDPOINT_HOSTS)[3] == "ENDPOINT_NOT_ALLOWED"


@test
def t_redirect_handler_unit():
    opener = es._api_build_opener()
    handler = next(h for h in opener.handlers if h.__class__.__name__ == "_NoRedirect")
    try:
        handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example.com/")
        assert False, "리다이렉트가 차단되지 않음"
    except es._ApiError as e:
        assert e.code == "REDIRECT_REJECTED"


@test
def t_rest_response_too_large(monkey):
    big = b"x" * (1024 * 1024 + 5)
    monkey("extract_shinhan", "_api_build_opener", lambda: FakeOpener(body=big, status=200))
    cfg = base_config()
    cfg["_bankonline_authorization"] = SECRET_TOKEN
    try:
        es._call_bankonline_rest({"APPCODE": "300617"}, cfg)
        assert False, "RESPONSE_TOO_LARGE가 발생하지 않음"
    except es._ApiError as e:
        assert e.code == "RESPONSE_TOO_LARGE"


@test
def t_rest_success_and_token_appcode(monkey):
    # 토큰: FakeOpener로 발급 (appcode=300617 검증), REST: FakeOpener 성공 응답
    tok_opener = FakeOpener(body=b"MYTOKEN123", status=200)
    rest_opener = FakeOpener(body=b'{"success":"true"}', status=200)
    openers = iter([tok_opener, rest_opener])
    monkey("extract_shinhan", "_api_build_opener", lambda: next(openers))
    monkey("db_writer", "fetch_kapa_credentials", lambda *a, **k: ("kid", SECRET_KAPA_PW))

    cfg = base_config()
    out = make_output()
    _, lines = run_stage(db_ok([out]), [make_item()], cfg)

    # 토큰 요청 body에 appcode=300617 포함
    tok_req = tok_opener.captured[0]
    assert b"appcode=300617" in tok_req.data
    # REST 요청 body(form)에 APPCODE=300617 포함
    rest_req = rest_opener.captured[0]
    assert b"APPCODE=300617" in rest_req.data
    assert out["BankOnline_In"] == "Y"
    assert any("[API][TOKEN] result=success" in l for l in lines)


# ── monkeypatch 지원 (자동 복원) ──────────────────────────────────────────────
def _run_all():
    import importlib
    passed = failed = 0
    for fn in TESTS:
        patches = []

        def monkey(modname, attr, value):
            mod = importlib.import_module(modname)
            patches.append((mod, attr, getattr(mod, attr)))
            setattr(mod, attr, value)

        try:
            if fn.__code__.co_argcount == 1:
                fn(monkey)
            else:
                fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
        finally:
            for mod, attr, orig in reversed(patches):
                setattr(mod, attr, orig)
    return passed, failed


def main():
    passed, failed = _run_all()

    # ── 전역 안전 스캔 ────────────────────────────────────────────────────────
    joined = "\n".join(LOGS)
    leaks = [s for s in _LEAK_STRINGS if s in joined]
    assert not leaks, f"[LEAK] 로그에 민감/원문 substring 노출: {leaks}"
    for bad in ("\r", "\n\n", "\x00"):
        pass
    for l in LOGS:
        assert "\r" not in l and "\x00" not in l, f"CR/NUL 미제거: {l!r}"
        assert "{" not in l and "}" not in l, f"객체 직렬화 의심 로그: {l!r}"
    assert_codes_allowlisted(LOGS)
    assert _NET["hits"] == 0, f"실제 네트워크 연결 시도 {_NET['hits']}건 (0이어야 함)"

    total = passed + failed
    print(f"\n합성 로그 라인수: {len(LOGS)}  | 민감정보 스캔: 0건  | 실연결 시도: {_NET['hits']}건")
    print(f"결과: {passed}/{total} PASS, {failed} FAIL")
    if failed:
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
