#!/usr/bin/env python3
"""
Bank24 신한은행 담보 데이터 추출 — 2단계
Output: D:\\AI\\Claude\\Y_BankAuto\\output\\bank24_shinhan_dambo_YYYYMMDD_HHMMSS.txt
보안: ID/PW 로그/파일 미포함, 절대 좌표 미사용
자동화 우선순위: 컨트롤 식별자 → 키보드 → 창 기준 상대좌표
"""
import sys, time, subprocess, getpass, ctypes, os, re
from datetime import datetime, timedelta
from pathlib import Path

if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass

MISSING = []
try:
    from pywinauto import Application, Desktop
    from pywinauto.keyboard import send_keys
except ImportError:
    MISSING.append("pywinauto")
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.15
except ImportError:
    MISSING.append("pyautogui")
try:
    import pyperclip
except ImportError:
    MISSING.append("pyperclip")

if MISSING:
    print(f"[ERROR] 미설치: {', '.join(MISSING)}")
    raise RuntimeError(f"필수 모듈 로드 실패: {', '.join(MISSING)}")

# ── 상수 ──────────────────────────────────────────────────────────────────────
APP_PATH   = r"C:\KADC\X11\Bank24.exe"
EXE_NAME   = "bank24.exe"
MAIN_CLS   = "TfrmMain"
DETAIL_CLS = "TBnkTop24Rcp"
OUTPUT_DIR = Path(r"C:\Bank24Extractor\output")

DETAIL_FIELDS = [
    "감정서번호", "의뢰번호", "영업점", "담당자",
    "담당자 연락처", "채무자", "소유자", "안심번호", "비고",
]
MAIN_GRID_FIELDS = ["접수일자", "의뢰일자", "처리기한", "은행"]

LABEL_CLS = (
    "TcxLabel", "TcxDBLabel",
    "TLabel", "Static", "TStaticText", "Label",
)
EDIT_CLS = (
    "TcxTextEdit", "TcxDBTextEdit", "TcxCustomInnerTextEdit",
    "TcxDBMemo", "TcxMemo",
    "Edit", "TEdit", "TMemo", "RichEdit", "TMaskEdit", "TDBEdit", "TDBMemo",
)
GRID_CLS = ("TcxGrid", "TDBGrid", "TStringGrid", "TcxGridSite")
_HEADER_MARKER_COLS = {"의뢰영업점", "의뢰번호", "업무구분", "감정서번호"}

KNOWN_LOGIN_CLS = {"TDXLoginDialog", "TfrmLogin", "TfrmLoginDlg", "TLoginForm"}
SKIP_CLS = {
    "Chrome_WidgetWin_1", "Chrome_WidgetWin_0",
    "MozillaWindowClass", "IEFrame", "CabinetWClass",
    "Shell_TrayWnd", "Progman", "WorkerW",
}
_LOGIN_EDIT_CLS = (
    "Edit",
    "TEdit",
    "TMaskEdit",
    "TcxTextEdit",
    "TcxCustomInnerTextEdit",
    "TcxCustomDropDownInnerEdit",
    "TcxCustomMaskEdit",
    "TcxCustomEdit",
)

# ── PDF 관련 상수 ─────────────────────────────────────────────────────────────
_PREVIEW_CLS   = "TfrxPreviewForm"
_PRINT_DLG_CLS = "TfrxPrintDialog"
_PDF_PRINTER   = "Microsoft Print to PDF"
PDF_DIR        = Path(r"\\data\DATA\6.업무2팀\온라인접수")

TODAY     = datetime.today()
DATE_TO   = os.environ.get("BANK24_DATE_TO",   TODAY.strftime("%Y-%m-%d"))
DATE_FROM = os.environ.get("BANK24_DATE_FROM", (TODAY - timedelta(days=3)).strftime("%Y-%m-%d"))
TS            = TODAY.strftime("%Y%m%d_%H%M%S")
SEP           = "─" * 64
DEBUG_SAVE_RAW  = False   # True: raw_scan·main_grid 파일 저장
DEBUG_MAIN_WAIT = True    # True: wait_main 진단 로그 출력
KEEP_PDF_HISTORY = True   # True: DB 성공 후에도 PDF 삭제하지 않고 보존

TAB_RELATIVE_COORDS = {
    "미접수": (147, 29),
    "작성":   (205, 29),
}


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────
def hdr(t):  print(f"\n{SEP}\n  {t}\n{SEP}")

_log_callback = None   # run_extraction() 진입 시 설정, 종료 시 None으로 초기화

def log(msg):
    if _log_callback is not None:
        try:
            _log_callback(str(msg))
        except Exception:
            pass
    else:
        print(f"  {msg}")

def safe_stdout_write(text):
    try:
        if sys.stdout:
            sys.stdout.write(text)
            sys.stdout.flush()
    except Exception:
        pass

def safe_cls(c):
    try:    return c.class_name()
    except: return "?"

def safe_txt(c):
    try:    return c.window_text()
    except: return ""

def safe_rect(c):
    try:
        r = c.rectangle()
        return r.left, r.top, r.right, r.bottom
    except:
        return 0, 0, 0, 0

def safe_val(c):
    """UIA ValuePattern으로 값 읽기"""
    try:    return str(c.get_value()).strip()
    except: return ""

def tasklist_has(exe):
    r = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {exe}"],
        capture_output=True, text=True, encoding="cp949", errors="replace",
    )
    return exe.lower() in r.stdout.lower()

def _timed_descendants(win, cls_filter, timeout=8.0):
    import threading
    result = []
    if isinstance(cls_filter, str):
        cls_filter = (cls_filter,)
    def _do():
        try:
            result.extend(c for c in win.descendants()
                          if safe_cls(c) in cls_filter)
        except Exception as e:
            log(f"[descendants 오류] {e}")
    t = threading.Thread(target=_do, daemon=True)
    t.start(); t.join(timeout=timeout)
    if t.is_alive():
        log(f"[WARN] descendants 타임아웃({timeout}s)")
    return result

def _all_descendants(win, timeout=10.0):
    import threading
    result = []
    def _do():
        try:
            result.extend(win.descendants())
        except Exception as e:
            log(f"[descendants 오류] {e}")
    t = threading.Thread(target=_do, daemon=True)
    t.start(); t.join(timeout=timeout)
    if t.is_alive():
        log(f"[WARN] all_descendants 타임아웃({timeout}s)")
    return result

def clip_read(fallback=""):
    """클립보드 읽기 (오류 시 fallback 반환)"""
    try:    return pyperclip.paste() or fallback
    except: return fallback

def ctrl_c_copy(ctrl, wait=0.5):
    """컨트롤 클릭 후 Ctrl+A→Ctrl+C로 값 읽기"""
    try:
        pyperclip.copy("")
        ctrl.click_input(); time.sleep(0.2)
        ctrl.type_keys("^a", with_spaces=True); time.sleep(0.1)
        ctrl.type_keys("^c", with_spaces=True); time.sleep(wait)
        return clip_read()
    except:
        return ""

def _norm_col(s): return "".join(s.split())


_SUPPORTED_BANKS = frozenset({
    "신한은행",
    "기업은행",
    "우리은행",
    "주택도시보증공사",
    "국민은행",
    "새마을금고",
    "하나은행",
    "농협은행",
    "농협중앙회",
    "수협은행",
})

_BANKONLINE_CUSTKEY = {
    "국민은행":         "KBB",
    "신한은행":         "SHG",
    "기업은행":         "KIB",
    "하나은행":         "HNB",
    "농협은행":         "NHB",
    "농협중앙회":       "NHJ",
    "우리은행":         "WRB",
    "수협은행":         "SSB",
    "새마을금고":       "MGB",
    "주택도시보증공사": "HUG",
}


def _safe_bank_log_name(value) -> str:
    text = str(value or "(알수없음)")
    # CR/LF, TAB, NULL, ANSI 제어문자 등 C0 제어문자 제거
    text = re.sub(
        r"[\x00-\x1f\x7f]+",
        " ",
        text,
    ).strip()
    if not text:
        return "(알수없음)"
    # 일반적인 연결 문자열 인증정보 값 마스킹
    text = re.sub(
        r"(?i)\b(PWD|PASSWORD|UID|USER ID)\s*=\s*[^;\s]*",
        r"\1=***",
        text,
    )
    # DRIVER/SERVER 조합은 연결 문자열로 보고 전체 차단
    has_driver = re.search(
        r"(?i)\bDRIVER\s*=",
        text,
    )
    has_server = re.search(
        r"(?i)\bSERVER\s*=",
        text,
    )
    if has_driver and has_server:
        return "(보안 차단된 은행명)"
    return text[:80] or "(알수없음)"


def _canonical_supported_bank(bank_name: str) -> str:
    if not bank_name:
        return ""

    bank = _norm_col(str(bank_name))

    exact_aliases = {
        _norm_col("신한은행"):         "신한은행",

        _norm_col("기업은행"):         "기업은행",
        _norm_col("IBK기업은행"):      "기업은행",

        _norm_col("우리은행"):         "우리은행",

        _norm_col("주택도시보증공사"):  "주택도시보증공사",
        _norm_col("HUG"):              "주택도시보증공사",

        _norm_col("국민은행"):         "국민은행",
        _norm_col("KB국민은행"):       "국민은행",

        _norm_col("새마을금고"):       "새마을금고",

        _norm_col("하나은행"):         "하나은행",
        _norm_col("KEB하나은행"):      "하나은행",

        _norm_col("농협은행"):         "농협은행",
        _norm_col("NH농협은행"):       "농협은행",
        _norm_col("농협중앙회"):       "농협중앙회",

        _norm_col("수협은행"):         "수협은행",
        _norm_col("Sh수협은행"):       "수협은행",
        _norm_col("SH수협은행"):       "수협은행",
        _norm_col("수협중앙회"):       "수협은행",
    }

    if bank in exact_aliases:
        return exact_aliases[bank]

    if bank.endswith(_norm_col("새마을금고")):
        return "새마을금고"

    if (
        bank.endswith(_norm_col("농협"))
        or bank.endswith(_norm_col("농업협동조합"))
    ):
        return "농협중앙회"

    if (
        bank.endswith(_norm_col("수협"))
        or bank.endswith(_norm_col("수산업협동조합"))
    ):
        return "수협은행"

    return ""


def _is_supported_bank(bank_name: str) -> bool:
    canonical = _canonical_supported_bank(bank_name)
    return bool(
        canonical
        and canonical in _SUPPORTED_BANKS
    )


def _kb_doc_no_match(grid_no: str, pdf_no: str) -> bool:
    """국민은행 의뢰번호 형식 검증.
    그리드(13자리 숫자) = 내부 PDF 의뢰번호(9자리 숫자) + suffix(숫자 4자리)"""
    g = (grid_no or "").strip()
    p = (pdf_no  or "").strip()
    return (
        g.isdigit() and len(g) == 13
        and p.isdigit() and len(p) == 9
        and g.startswith(p)
        and len(g[9:]) == 4
    )


def _normalize_pdf_identity_for_grid(parsed: dict, target_row: dict, doc_no: str, est_no: str) -> tuple:
    """PDF 번호를 그리드 기준으로 보정하고 검증에 사용할 (pdf_doc, pdf_est)를 반환한다."""
    pdf_doc = str(parsed.get("의뢰번호", "") or "").strip()
    pdf_est = str(parsed.get("감정서번호", "") or "").strip()
    bank = target_row.get("은행") or parsed.get("은행", "")
    canon = _canonical_supported_bank(bank)

    if canon == "주택도시보증공사":
        if not doc_no:
            return pdf_doc, pdf_est
        # HUG의 업무상 의뢰번호는 Bank24 그리드 값을 기준으로 한다.
        parsed["의뢰번호"] = doc_no
        parsed["상세창 의뢰번호"] = doc_no

        if est_no:
            corrected_est = est_no
        elif pdf_est == doc_no:
            # 미접수 HUG PDF에서 의뢰번호가 감정서번호로 잘못 인식된 경우.
            corrected_est = ""
        else:
            corrected_est = pdf_est
        parsed["감정서번호"] = corrected_est
        parsed["상세창 감정서번호"] = corrected_est
        return doc_no, corrected_est

    elif canon == "국민은행" and doc_no and _kb_doc_no_match(doc_no, pdf_doc):
        # 국민은행: 그리드(13자리) = 내부 의뢰번호(9자리) + suffix(4자리)
        # 상세창 의뢰번호 = 그리드 번호 (GUI 행 매칭·API 용도)
        # 의뢰번호(내부 9자리)는 그대로 유지 — DB CustDocID 용도
        parsed["상세창 의뢰번호"] = doc_no
        # 기존 verified 체크(doc_no == pdf_doc)를 통과시키기 위해 doc_no 반환
        return doc_no, pdf_est

    elif canon in {"농협은행", "농협중앙회"} and est_no and pdf_doc and pdf_est == pdf_doc:
        # NH PDF에는 감정서번호 칸이 비어 있어 의뢰번호가 감정서번호 fallback으로 들어간다.
        # 그리드의 실제 감정서번호로 교정한다.
        parsed["감정서번호"] = est_no
        parsed["상세창 감정서번호"] = est_no
        return pdf_doc, est_no

    return pdf_doc, pdf_est


def _build_bankonline_payload(item: dict, new_doc_id: str, config: dict) -> dict:
    from db_writer import normalize_cust_docid
    raw_req_id = item.get("상세창 의뢰번호") or item.get("의뢰번호", "")
    dambo_no   = normalize_cust_docid(raw_req_id)
    gam_no     = str(new_doc_id or "").strip()
    bank_name  = item.get("은행", "")
    canonical  = _canonical_supported_bank(bank_name)
    custkey    = _BANKONLINE_CUSTKEY.get(canonical, "")
    # REST_BANK_JUBSU_UPD 인증값은 GUI에서 입력한 Bank24 계정을 그대로 사용한다.
    uid        = str(config.get("bank24_id", "") or "").strip()
    pwd        = str(config.get('REDACTED_CONFIGURE_LOCALLY', "") or "")
    if not (
        len(custkey) == 3
        and dambo_no and len(dambo_no) <= 20
        and gam_no   and len(gam_no)   <= 20
        and uid      and len(uid)       <= 24
        and pwd      and len(pwd)       <= 24
    ):
        return {}
    return {
        "Procedure":   "REST_BANK_JUBSU_UPD",
        "CUSTKEY":     custkey,
        "UPMU_GUBUN": "1",
        "DAMBO_NO":    dambo_no,
        "GAM_NO":      gam_no,
        "APPCODE":     "300611",
        "UID":         uid,
        "PWD":         pwd,
    }


def _bankonline_rest_config(config: dict) -> dict:
    value = config.get("bankonline", {})
    return value if isinstance(value, dict) else {}


def _bankonline_rest_enabled(config: dict) -> bool:
    rest = _bankonline_rest_config(config)
    enabled = str(rest.get("enabled", "false") or "false").strip().lower()
    return enabled in ("1", "true", "yes", "on") and bool(str(rest.get("endpoint", "") or "").strip())


def _has_bankonline_caller(config: dict) -> bool:
    return callable(config.get("_bankonline_api_caller")) or _bankonline_rest_enabled(config)


def _bankonline_auto_send_enabled(config: dict) -> bool:
    """DB 저장 직후 자동 전송 여부. 기본 false — 수기('API 전송' 버튼) 전송이 기본."""
    rest = _bankonline_rest_config(config)
    value = str(rest.get("auto_send", "false") or "false").strip().lower()
    return value in ("1", "true", "yes", "on")


def _call_bankonline_rest(payload: dict, config: dict):
    """REST_BANK_JUBSU_UPD 호출. payload/응답 원문은 반환하거나 기록하지 않는다."""
    import json
    import urllib.parse
    import urllib.request

    rest = _bankonline_rest_config(config)
    endpoint = str(rest.get("endpoint", "") or "").strip()
    authorization = str(config.get("_bankonline_authorization", "") or "").strip()
    if not authorization:
        raise ValueError("BANKONLINE_AUTHORIZATION_MISSING")
    parsed = urllib.parse.urlsplit(endpoint)
    allow_http = str(rest.get("allow_http", "false") or "false").strip().lower() in ("1", "true", "yes", "on")
    if parsed.scheme not in (("http", "https") if allow_http else ("https",)) or not parsed.netloc:
        raise ValueError("BANKONLINE_ENDPOINT_NOT_ALLOWED")

    method = str(rest.get("method", "POST") or "POST").strip().upper()
    if method not in ("POST", "PUT", "PATCH"):
        raise ValueError("BANKONLINE_METHOD_NOT_ALLOWED")

    request_format = str(rest.get("request_format", "json") or "json").strip().lower()
    if request_format == "json":
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        content_type = "application/json; charset=utf-8"
    elif request_format == "form":
        body = urllib.parse.urlencode(payload).encode("utf-8")
        content_type = "application/x-www-form-urlencoded; charset=utf-8"
    else:
        raise ValueError("BANKONLINE_REQUEST_FORMAT_NOT_ALLOWED")

    try:
        timeout = float(rest.get("timeout_seconds", 10) or 10)
    except (TypeError, ValueError):
        timeout = 10.0
    timeout = min(max(timeout, 1.0), 60.0)

    request = urllib.request.Request(
        endpoint,
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": content_type,
            "Authorization": authorization,
            "User-Agent": "Bank24Extractor/0.4",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("BANKONLINE_RESPONSE_TOO_LARGE")
        status = int(getattr(response, "status", 0) or response.getcode() or 0)
    if not 200 <= status < 300:
        return False

    try:
        decoded = json.loads(raw.decode("utf-8-sig")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(decoded, dict):
        return False

    success_field = str(rest.get("success_field", "success") or "success").strip()
    value = decoded
    for part in success_field.split("."):
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
    expected = str(rest.get("success_value", "true") or "true").strip().lower()
    if isinstance(value, bool):
        return value is (expected in ("1", "true", "yes", "y"))
    return str(value).strip().lower() == expected


def _fetch_bankonline_token(kapa_id: str, kapa_pw: str, config: dict) -> str:
    """KAPA 토큰을 1회 발급한다. 응답 원문과 계정값은 기록하지 않는다."""
    import urllib.parse
    import urllib.request

    rest = _bankonline_rest_config(config)
    endpoint = str(
        rest.get("token_endpoint", "https://authtoken.kapanet.or.kr/AuthServer")
        or "https://authtoken.kapanet.or.kr/AuthServer"
    ).strip()
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("TOKEN_ENDPOINT_NOT_ALLOWED")
    body = urllib.parse.urlencode({
        "userid": kapa_id,
        "userpass": kapa_pw,
        "appcode": "300611",
    }).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json, text/plain; q=0.9",
            "Accept-Charset": "UTF-8, *;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": 'REDACTED_CONFIGURE_LOCALLY',
            "User-Agent": "Embarcadero RESTClient/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(4097)
        if len(raw) > 4096:
            raise ValueError("TOKEN_RESPONSE_TOO_LARGE")
    token = raw.decode("utf-8-sig").strip()
    if not token or len(token) > 512 or any(ch.isspace() for ch in token):
        raise ValueError("TOKEN_REJECTED")
    if token.lower().startswith(("no auth", "error", "fail")):
        raise ValueError("TOKEN_REJECTED")
    return token


def _call_bankonline_api(payload: dict, config: dict) -> tuple:
    """반환: ("Y" 또는 "N", 안전한 오류 유형)"""
    if not payload:
        return ("N", "INVALID_PAYLOAD")
    caller = config.get("_bankonline_api_caller")
    if not callable(caller) and _bankonline_rest_enabled(config):
        caller = lambda p: _call_bankonline_rest(p, config)
    if not callable(caller):
        return ("N", "CALLER_NOT_CONFIGURED")
    try:
        response = caller(payload)
        if response is True:
            return ("Y", "")
        if isinstance(response, dict) and response.get("success") is True:
            return ("Y", "")
        return ("N", "API_REJECTED")
    except Exception as e:
        return ("N", type(e).__name__)


def _apply_bankonline_updates(db_result: dict, items: list, config: dict) -> dict:
    from db_writer import normalize_cust_docid
    result = {"enabled": True, "tried": 0, "success": 0, "fail": 0, "blocked": 0, "errors": []}
    outputs = db_result.get("outputs") or []
    if not outputs:
        return result

    api_config = config
    setup_error = ""
    if _bankonline_rest_enabled(config) and not callable(config.get("_bankonline_api_caller")):
        rest = _bankonline_rest_config(config)
        try:
            from db_writer import fetch_kapa_credentials
            kapa_id, kapa_pw = fetch_kapa_credentials(
                config.get("database", {}) or {},
                str(rest.get("kapa_user_name", "이일우") or "이일우").strip(),
            )
            token = _fetch_bankonline_token(kapa_id, kapa_pw, config)
            api_config = dict(config)
            api_config["_kapa_userid"] = kapa_id
            api_config["_kapa_userpass"] = kapa_pw
            api_config["_bankonline_authorization"] = token
        except Exception as exc:
            safe_code = str(exc)
            setup_error = safe_code if re.fullmatch(r"[A-Z0-9_]+", safe_code) else type(exc).__name__

    item_map = {}
    for it in items:
        raw = it.get("상세창 의뢰번호") or it.get("의뢰번호", "")
        key = normalize_cust_docid(raw)
        if key:
            item_map[key] = it

    rollback = db_result.get("rollback_test", False)

    for output in outputs:
        output["BankOnline_In"]        = "N"
        output["BankOnline_ErrorType"] = ""
        norm_out  = normalize_cust_docid(output.get("의뢰번호", ""))
        # HUG: 의뢰번호=신청번호, item_map 키=그리드 의뢰번호 → 그리드_의뢰번호로 매칭
        norm_grid = normalize_cust_docid(
            output.get("그리드_의뢰번호") or output.get("의뢰번호", "")
        )
        new_doc_id = str(output.get("NewDocID", "") or "").strip()

        if rollback:
            output["BankOnline_ErrorType"] = "ROLLBACK_TEST"
            result["blocked"] += 1
            _log_callback and _log_callback(f"[BankOnline] 호출 보류: 의뢰번호={norm_out}, 오류유형=ROLLBACK_TEST")
            continue

        if not new_doc_id:
            output["BankOnline_ErrorType"] = "NO_NEWDOCID"
            result["blocked"] += 1
            _log_callback and _log_callback(f"[BankOnline] 호출 보류: 의뢰번호={norm_out}, 오류유형=NO_NEWDOCID")
            continue

        item = item_map.get(norm_grid)
        if item is None:
            output["BankOnline_ErrorType"] = "ITEM_MATCH_FAIL"
            result["blocked"] += 1
            _log_callback and _log_callback(f"[BankOnline] 호출 보류: 의뢰번호={norm_out}, 오류유형=ITEM_MATCH_FAIL")
            result["errors"].append({"의뢰번호": norm_out, "error": "ITEM_MATCH_FAIL"})
            continue

        if setup_error:
            output["BankOnline_ErrorType"] = setup_error
            result["blocked"] += 1
            _log_callback and _log_callback(f"[BankOnline] 호출 보류: 의뢰번호={norm_out}, 오류유형={setup_error}")
            continue

        payload = _build_bankonline_payload(item, new_doc_id, api_config)
        if not payload:
            if not _has_bankonline_caller(api_config):
                err_type = "CALLER_NOT_CONFIGURED"
            else:
                err_type = "INVALID_PAYLOAD"
            output["BankOnline_ErrorType"] = err_type
            result["blocked"] += 1
            _log_callback and _log_callback(f"[BankOnline] 호출 보류: 의뢰번호={norm_out}, 오류유형={err_type}")
            continue

        if not _has_bankonline_caller(api_config):
            output["BankOnline_ErrorType"] = "CALLER_NOT_CONFIGURED"
            result["blocked"] += 1
            _log_callback and _log_callback(f"[BankOnline] 호출 보류: 의뢰번호={norm_out}, 오류유형=CALLER_NOT_CONFIGURED")
            continue

        status, err_type = _call_bankonline_api(payload, api_config)
        result["tried"] += 1
        output["BankOnline_In"]        = status
        output["BankOnline_ErrorType"] = err_type
        if status == "Y":
            result["success"] += 1
            _log_callback and _log_callback(f"[BankOnline] 성공: 의뢰번호={norm_out}")
        else:
            result["fail"] += 1
            _log_callback and _log_callback(f"[BankOnline] 실패: 의뢰번호={norm_out}, 오류유형={err_type}")
            result["errors"].append({"의뢰번호": norm_out, "error": err_type})

    return result


def manual_bankonline_send(entries: list, config: dict, log=None) -> dict:
    """GUI 'API 전송' 버튼용 수기 BankOnline 전송.

    entries: [{"의뢰번호": DB CustDocID, "그리드_의뢰번호": DAMBO_NO용 원본,
               "은행": 은행명, "_row": GUI 행번호(선택)}]
    전송 시점에 APW_Master에서 최신 감정서번호(DocID)를 재조회해 GAM_NO로 쓴다
    (저장 이후 감정서번호가 바뀐 경우 대응). 재조회 실패 시 전송하지 않는다(fail-closed).

    반환: {"outputs": [...], "result": {...}} — outputs는 entries와 같은 순서이며
    각 항목에 BankOnline_In/BankOnline_ErrorType/NewDocID(재조회값)/_row가 담긴다.
    """
    global _log_callback
    from db_writer import fetch_current_docids, normalize_cust_docid

    prev_log = _log_callback
    if log is not None:
        _log_callback = log
    try:
        lookup = fetch_current_docids(
            config.get("database", {}) or {},
            [e.get("의뢰번호", "") for e in entries],
        )

        outputs, items = [], []
        for e in entries:
            cust = normalize_cust_docid(e.get("의뢰번호", ""))
            grid = str(e.get("그리드_의뢰번호") or e.get("의뢰번호") or "").strip()
            bank = str(e.get("은행", "") or "").strip()
            outputs.append({
                "의뢰번호":        cust,
                "그리드_의뢰번호": grid,
                "NewDocID":        str(lookup["docids"].get(cust, "") or "").strip()
                                   if lookup.get("ok") else "",
                "_row":            e.get("_row"),
            })
            items.append({"의뢰번호": grid, "은행": bank})

        if not lookup.get("ok"):
            err = str(lookup.get("error", "") or "DOCID_LOOKUP_FAILED")
            for output in outputs:
                output["BankOnline_In"] = "N"
                output["BankOnline_ErrorType"] = "DOCID_LOOKUP_FAILED"
            _log_callback and _log_callback(
                f"[BankOnline] 감정서번호 재조회 실패({err}) — 전송 보류 {len(outputs)}건"
            )
            return {
                "outputs": outputs,
                "result": {"enabled": True, "tried": 0, "success": 0, "fail": 0,
                           "blocked": len(outputs),
                           "errors": [{"error": "DOCID_LOOKUP_FAILED"}]},
            }

        db_result = {"outputs": outputs, "rollback_test": False}
        result = _apply_bankonline_updates(db_result, items, config)
        return {"outputs": outputs, "result": result}
    finally:
        _log_callback = prev_log


def _is_header_line(cols):
    if not cols: return False
    if _norm_col(cols[0]) == "은행": return True
    return bool({_norm_col(c) for c in cols} & _HEADER_MARKER_COLS)


# ══════════════════════════════════════════════════════════════════════════════
# 창 전면화
# ══════════════════════════════════════════════════════════════════════════════
def force_foreground(hwnd, label):
    """창을 강제로 전면에 가져온다. 성공 여부와 foreground hwnd를 로그로 남긴다."""
    user32  = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    SW_RESTORE = 9

    # 1) ShowWindow(SW_RESTORE) + SetForegroundWindow
    user32.ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.15)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        log(f"[전면화 OK] {label}  hwnd={hwnd:#010x}  foreground 확인")
        return True

    log(f"[전면화 WARN] {label}  SetForegroundWindow 실패 — AttachThreadInput 시도")

    # 2) AttachThreadInput fallback
    try:
        cur_tid = kernel32.GetCurrentThreadId()
        fg_tid  = user32.GetWindowThreadProcessId(fg,   None)
        tgt_tid = user32.GetWindowThreadProcessId(hwnd, None)
        user32.AttachThreadInput(cur_tid, fg_tid,  True)
        user32.AttachThreadInput(cur_tid, tgt_tid, True)
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
        fg2 = user32.GetForegroundWindow()
        user32.AttachThreadInput(cur_tid, fg_tid,  False)
        user32.AttachThreadInput(cur_tid, tgt_tid, False)
        if fg2 == hwnd:
            log(f"[전면화 OK] {label}  AttachThreadInput 성공  hwnd={hwnd:#010x}")
            return True
        log(f"[전면화 FAIL] {label}  foreground={fg2:#010x}  target={hwnd:#010x}")
    except Exception as e:
        log(f"[전면화 FAIL] {label}  예외: {e}")
    return False


def _ensure_foreground_window(win, label="", log=None, retries=3, wait=0.25):
    """force_foreground()를 최대 retries회 재시도. 성공 True, 실패 False."""
    _log = log or (lambda m: None)
    if win is None:
        _log(f"[FOCUS][WARN] {label} foreground 대상 확인 실패: win is None")
        return False
    try:
        hwnd = win.handle
    except Exception as e:
        _log(f"[FOCUS][WARN] {label} foreground 대상 확인 실패: {type(e).__name__}: {e}")
        return False
    if not hwnd:
        _log(f"[FOCUS][WARN] {label} foreground 대상 확인 실패: handle=0")
        return False
    user32 = ctypes.windll.user32
    for _ in range(retries):
        try:
            if force_foreground(hwnd, label):
                return True
        except Exception as e:
            _log(f"[FOCUS][WARN] {label} foreground 대상 확인 실패: {type(e).__name__}: {e}")
            return False
        actual = user32.GetForegroundWindow()
        _log(f"[FOCUS][WARN] {label} foreground 복구 실패: "
             f"expected={hwnd:#010x}, actual={actual:#010x}")
        time.sleep(wait)
    return False


def _safe_send_keys(win, keys, label="", log=None, retries=2, pause=0.15):
    """포커스 확인 후 send_keys 전송. keys 원문은 로그에 남기지 않는다."""
    _log = log or (lambda m: None)
    if win is None:
        _log(f"[FOCUS][WARN] {label} send_keys 대상 없음: win is None")
        return False
    try:
        hwnd = win.handle
    except Exception as e:
        _log(f"[FOCUS][WARN] {label} send_keys 대상 확인 실패: {type(e).__name__}: {e}")
        return False
    if not hwnd:
        _log(f"[FOCUS][WARN] {label} send_keys 대상 확인 실패: handle=0")
        return False
    user32 = ctypes.windll.user32
    for attempt in range(retries):
        if user32.GetForegroundWindow() != hwnd:
            if not _ensure_foreground_window(win, label=label, log=_log):
                _log(f"[FOCUS][WARN] {label} 전면화 실패, send_keys 건너뜀 (attempt {attempt + 1})")
                time.sleep(pause)
                continue
        try:
            send_keys(keys)
            return True
        except Exception as e:
            _log(f"[FOCUS][WARN] {label} send_keys 실패 (attempt {attempt + 1}): {e}")
            time.sleep(pause)
    _log(f"[FOCUS][WARN] {label} send_keys {retries}회 모두 실패")
    return False


# ══════════════════════════════════════════════════════════════════════════════
# 그리드 안정화 대기
# ══════════════════════════════════════════════════════════════════════════════
def _poll_grid_stable(main_win, before_down1_snap, timeout=30):
    """조회 완료 대기. Ctrl+Home → Down1 위치 복사값이 2회 연속 동일하면 안정화 판단."""
    deadline = time.time() + timeout
    prev = None
    stable_count = 0
    time.sleep(2)
    while time.time() < deadline:
        try:
            grid = _get_main_grid(main_win)
            if grid:
                grid.click_input(); time.sleep(0.2)
                send_keys("^{HOME}"); time.sleep(0.15)
                send_keys("{DOWN}");  time.sleep(0.15)
                pyperclip.copy("")
                send_keys("^c"); time.sleep(0.4)
                cur = clip_read()
                if cur:
                    if cur == prev:
                        stable_count += 1
                        if stable_count >= 2:
                            changed  = (cur != before_down1_snap)
                            elapsed  = timeout - (deadline - time.time())
                            log(f"조회 완료 ({'변경됨' if changed else '변경없음'}, 안정화, {elapsed:.1f}초 경과)")
                            return cur
                    else:
                        stable_count = 1
                    prev = cur
                else:
                    stable_count = 0
        except Exception as e:
            log(f"[polling 오류] {e}")
        safe_stdout_write(".")
        time.sleep(1)
    if sys.stdout: print()
    log("[WARN] 조회 완료 대기 타임아웃")
    return clip_read()


# ══════════════════════════════════════════════════════════════════════════════
# 자격증명 입력
# ══════════════════════════════════════════════════════════════════════════════
def prompt_credentials():
    hdr("Step 0. 자격증명 입력")
    import os
    uid = os.environ.get("BANK24_ID", "").strip()
    pwd = os.environ.get("BANK24_PW", "").strip()
    if not uid:
        uid = input("Bank24 ID: ").strip()
    if not uid:
        log("[ERROR] ID가 비어 있음"); sys.exit(1)
    if not pwd:
        pwd = getpass.getpass("Bank24 PW: ")
    if not pwd:
        log("[ERROR] PW가 비어 있음"); sys.exit(1)
    log(f"ID hint: {uid[:2]}*** (런타임 입력, 저장 안 함)")
    log(f"날짜 범위: {DATE_FROM} ~ {DATE_TO}")
    return uid, pwd


# ══════════════════════════════════════════════════════════════════════════════
# Bank24 종료
# ══════════════════════════════════════════════════════════════════════════════
def kill_existing():
    hdr("Step 1. Bank24 기존 프로세스 정리")
    if not tasklist_has(EXE_NAME):
        log("실행 중 아님"); return
    log("실행 감지 — 정상 종료 시도")
    try:
        app = Application(backend="win32").connect(class_name=MAIN_CLS, timeout=4)
        app.top_window().close()
        time.sleep(3)
        if not tasklist_has(EXE_NAME):
            log("정상 종료"); return
    except Exception as e:
        log(f"정상 종료 실패: {e}")
    subprocess.run(["taskkill", "/F", "/IM", EXE_NAME], capture_output=True)
    time.sleep(2)
    log("강제 종료 완료")


# ══════════════════════════════════════════════════════════════════════════════
# 실행 + 로그인
# ══════════════════════════════════════════════════════════════════════════════
def _snapshot_hwnd_set():
    s = set()
    try:
        for w in Desktop(backend="win32").windows():
            try: s.add(w.handle)
            except: pass
    except: pass
    return s

def _find_login_win(before):
    try:
        all_wins = Desktop(backend="win32").windows()
    except:
        return None, "Desktop 오류"

    candidates = []
    for w in all_wins:
        try:
            if w.handle in before: continue
            cls = safe_cls(w)
            if cls in SKIP_CLS: continue
            ttl = safe_txt(w)
            if cls in KNOWN_LOGIN_CLS:
                return w, f"클래스 직접 매칭: {cls!r}"
            if any(k in cls for k in ("TBnk", "TDX", "TForm", "TfrLogin")):
                candidates.append((w, cls, ttl))
            elif any(k in ttl for k in ("BANK", "Bank", "bank", "로그인", "Login")):
                candidates.append((w, cls, ttl))
        except:
            pass

    for w, cls, ttl in candidates:
        try:
            eds = [c for c in w.descendants()
                   if safe_cls(c) in ("Edit", "TEdit", "TMaskEdit",
                                      "TcxCustomDropDownInnerEdit")]
            if len(eds) >= 2:
                return w, f"Edit 2개 이상: class={cls!r} title={ttl!r}"
        except:
            pass

    if candidates:
        w, cls, ttl = candidates[0]
        return w, f"후보: class={cls!r} title={ttl!r}"
    return None, "신규 창 없음"

def _count_login_edit_candidates(win) -> int:
    """로그인창 후보 판정용 visible+enabled Edit 후보 수 반환."""
    try:
        descs = _timed_descendants(win, _LOGIN_EDIT_CLS, timeout=3.0)
        count = 0
        for c in descs:
            try:
                if c.is_visible() and c.is_enabled():
                    count += 1
            except Exception:
                pass
        return count
    except Exception:
        return 0


def _select_login_fallback_window(new_wins):
    """새로운 창 목록에서 로그인 창으로 가장 적합한 창 선택.
    반환: (창, 선택 이유 문자열)
    """
    if not new_wins:
        return None, "후보 없음"

    _EXCLUDE_CLS = ("TApplication", "TProgressDlg")

    # 1순위: TDXLoginDialog
    for w in new_wins:
        try:
            if safe_cls(w) == "TDXLoginDialog":
                return w, "1순위: TDXLoginDialog"
        except:
            pass

    # 2순위: visible+enabled Edit 2개 이상 (TApplication/TProgressDlg 제외), Edit 수 최다
    best_win, best_count = None, 0
    for w in new_wins:
        try:
            if safe_cls(w) in _EXCLUDE_CLS:
                continue
            n = _count_login_edit_candidates(w)
            if n >= 2 and n > best_count:
                best_win, best_count = w, n
        except:
            pass
    if best_win:
        return best_win, f"2순위: Edit {best_count}개"

    # 3순위: title 매칭 (TApplication/TProgressDlg 제외)
    for w in new_wins:
        try:
            cls = safe_cls(w)
            if cls in _EXCLUDE_CLS:
                continue
            ttl = safe_txt(w)
            if "BANK ONLINE" in ttl or "금융기관온라인" in ttl or "X11" in ttl:
                return w, f"3순위: title 매칭({ttl!r})"
        except:
            pass

    # 4순위: 최소 면적 (TApplication/TProgressDlg 제외)
    candidates = [w for w in new_wins if safe_cls(w) not in _EXCLUDE_CLS]
    if not candidates:
        return None, "후보 없음"
    w = min(candidates,
            key=lambda ww: (safe_rect(ww)[2] - safe_rect(ww)[0])
                           * (safe_rect(ww)[3] - safe_rect(ww)[1]))
    log("[로그인][WARN] 최소 면적 창 fallback 사용")
    return w, "4순위: 최소면적"


def _set_edit_text_direct(ctrl, value: str, label: str, secret: bool = False) -> bool:
    """Edit/TEdit/TMaskEdit에 키보드 포커스 없이 값을 직접 설정한다."""
    WM_SETTEXT    = 0x000C
    EM_SETSEL     = 0x00B1
    EM_REPLACESEL = 0x00C2
    SendMessageW  = ctypes.windll.user32.SendMessageW
    try:
        try:
            if not ctrl.is_visible() or not ctrl.is_enabled():
                log(f"[로그인][WARN] {label} 직접 입력 실패: 비활성/비표시 컨트롤")
                return False
        except Exception:
            pass
        hwnd = ctrl.handle
        # 1순위: set_edit_text
        try:
            ctrl.set_edit_text(value)
            log(f"[로그인] {label} 직접 입력 성공: set_edit_text")
            return True
        except Exception as e:
            log(f"[로그인][WARN] {label} set_edit_text 실패: {type(e).__name__}: {e}")
        # 2순위: WM_SETTEXT
        try:
            SendMessageW(hwnd, WM_SETTEXT, 0, ctypes.c_wchar_p(value))
            log(f"[로그인] {label} 직접 입력 성공: WM_SETTEXT")
            return True
        except Exception as e:
            log(f"[로그인][WARN] {label} WM_SETTEXT 실패: {type(e).__name__}: {e}")
        # 3순위: EM_SETSEL + EM_REPLACESEL
        try:
            SendMessageW(hwnd, EM_SETSEL, 0, -1)
            SendMessageW(hwnd, EM_REPLACESEL, True, ctypes.c_wchar_p(value))
            log(f"[로그인] {label} 직접 입력 성공: EM_REPLACESEL")
            return True
        except Exception as e:
            log(f"[로그인][WARN] {label} 직접 입력 실패: EM_REPLACESEL 실패: {type(e).__name__}: {e}")
        return False
    except Exception as e:
        log(f"[로그인][WARN] {label} 직접 입력 예외: {type(e).__name__}: {e}")
        return False


def _read_edit_text_safe(ctrl, secret: bool = False) -> str:
    """입력 검증용 컨트롤 값 읽기. secret=True이면 반환값을 로그에 출력 금지."""
    try:
        return ctrl.window_text()
    except Exception:
        pass
    try:
        txts = ctrl.texts()
        return txts[0] if txts else ""
    except Exception:
        pass
    return ""


def _click_login_ok_button(login_win) -> bool:
    """로그인창의 확인 버튼을 BM_CLICK으로 직접 누른다."""
    BM_CLICK     = 0x00F5
    SendMessageW = ctypes.windll.user32.SendMessageW
    btn = None
    try:
        for c in login_win.descendants():
            try:
                if safe_cls(c) in ("TButton", "Button") and safe_txt(c).strip() == "확인":
                    btn = c
                    break
            except Exception:
                pass
    except Exception:
        pass
    if btn is None:
        log("[로그인][WARN] 확인 버튼을 찾지 못함")
        return False
    # 1순위: BM_CLICK
    try:
        SendMessageW(btn.handle, BM_CLICK, 0, 0)
        log("[로그인] 확인 버튼 클릭: BM_CLICK")
        return True
    except Exception as e:
        log(f"[로그인][WARN] BM_CLICK 실패: {type(e).__name__}: {e}")
    # 2순위: button.click
    try:
        btn.click()
        log("[로그인] 확인 버튼 클릭: button.click")
        return True
    except Exception as e:
        log(f"[로그인][WARN] 확인 버튼 클릭 실패: {type(e).__name__}: {e}")
        return False


def launch_and_login(uid, pwd):
    hdr("Step 2. Bank24 실행 및 로그인")
    before = _snapshot_hwnd_set()
    log(f"실행 전 창 수: {len(before)}")

    # 수정 1: Bank24 실행 try/except
    try:
        subprocess.Popen(APP_PATH)
    except Exception as e:
        log(f"[로그인][ERROR] Bank24 실행 실패: {type(e).__name__}: {e}")
        raise RuntimeError("Bank24 실행 실패")

    # 수정 2: 6초 고정 대기 → 최대 30초 polling
    log("[로그인] 로그인창 대기 시작: 최대 30초")
    login_win = None
    new_wins = []
    seen_new_handles = set()
    t_start = time.time()

    while time.time() - t_start < 30:
        try:
            for w in Desktop(backend="win32").windows():
                try:
                    hwnd = w.handle
                    cls  = safe_cls(w)
                    ttl  = safe_txt(w)

                    # TDXLoginDialog는 before 여부와 무관하게 최우선 인정
                    if cls == "TDXLoginDialog":
                        try:
                            if w.is_visible() and w.is_enabled():
                                elapsed = time.time() - t_start
                                if hwnd in before:
                                    log(f"[로그인] 기존 TDXLoginDialog 재사용: hwnd={hwnd:#010x}, title={ttl!r}, elapsed={elapsed:.1f}s")
                                else:
                                    log(f"[로그인] 로그인창 발견: class={cls!r}, title={ttl!r}, elapsed={elapsed:.1f}s")
                                login_win = w
                                break
                        except Exception:
                            pass

                    if hwnd in before:
                        continue
                    if cls in SKIP_CLS:
                        continue
                    if hwnd not in seen_new_handles:
                        seen_new_handles.add(hwnd)
                        new_wins.append(w)

                    # title 매칭 — TApplication/TProgressDlg 제외, Edit 2개 이상 조건
                    if cls not in ("TApplication", "TProgressDlg"):
                        if "BANK ONLINE" in ttl or "금융기관온라인" in ttl or "X11" in ttl:
                            n = _count_login_edit_candidates(w)
                            if n >= 2:
                                elapsed = time.time() - t_start
                                log(f"[로그인] 로그인창 발견 (title+Edit): class={cls!r}, title={ttl!r}, edit_count={n}, elapsed={elapsed:.1f}s")
                                login_win = w
                                break
                except Exception:
                    pass
        except Exception:
            pass

        if login_win:
            break
        time.sleep(0.5)

    if not login_win:
        log("[로그인][WARN] 로그인창 30초 내 미발견")
        # 수정 3: 신규 창 목록 진단 로그
        for w in new_wins:
            try:
                cls  = safe_cls(w)
                ttl  = safe_txt(w)
                rect = safe_rect(w)
                log(f"[로그인][DEBUG] 신규창: hwnd={w.handle:#010x}, class={cls!r}, title={ttl!r}, rect={rect}")
                if cls == "TDXLoginDialog":
                    log(f"[로그인][DEBUG] 후보: reason=TDXLoginDialog, hwnd={w.handle:#010x}, class={cls!r}, title={ttl!r}")
                elif cls != "TProgressDlg" and (
                    "BANK ONLINE" in ttl or "금융기관온라인" in ttl or "X11" in ttl
                ):
                    log(f"[로그인][DEBUG] 후보: reason=title매칭, hwnd={w.handle:#010x}, class={cls!r}, title={ttl!r}")
            except Exception:
                pass
        # 3순위: _find_login_win fallback
        login_win, reason = _find_login_win(before)
        if login_win:
            log(f"[로그인] fallback _find_login_win: {reason}")

    # 실패 추적 변수
    failure_reason = ""
    edit_candidates_count = 0
    fallback_used = False
    login_ok = False
    login_win_found = (login_win is not None)

    # 시도 1: pywinauto win32
    if login_win:
        fg_ok = force_foreground(login_win.handle, "로그인창")
        log(f"로그인창 전면화: {'성공' if fg_ok else '실패'}")
        try:
            edits = []
            for c in login_win.descendants():
                if safe_cls(c) in _LOGIN_EDIT_CLS:
                    try:
                        if c.is_visible() and c.is_enabled():
                            edits.append(c)
                    except Exception:
                        pass
            edits.sort(key=lambda c: (safe_rect(c)[1], safe_rect(c)[0]))
            edit_candidates_count = len(edits)
            log(f"[로그인][DEBUG] Edit 후보 수: {edit_candidates_count}")
            for c in edits:
                try:
                    r = c.rectangle()
                    log(f"[로그인][DEBUG] Edit 후보: class={safe_cls(c)!r}, rect=({r.left},{r.top},{r.right},{r.bottom}), visible={c.is_visible()}, enabled={c.is_enabled()}")
                except Exception:
                    pass
            if len(edits) >= 2:
                id_ctrl, pw_ctrl = edits[0], edits[1]
                id_ok = _set_edit_text_direct(id_ctrl, uid, "ID", secret=False)
                pw_ok = _set_edit_text_direct(pw_ctrl, pwd, "PW", secret=True)
                if not id_ok or not pw_ok:
                    failure_reason = "직접 입력 실패"
                    log("[로그인][WARN] 직접 입력 실패 — fallback 진행")
                else:
                    id_val     = _read_edit_text_safe(id_ctrl, secret=False)
                    pw_val     = _read_edit_text_safe(pw_ctrl, secret=True)
                    id_match   = (id_val == uid)
                    id_not_pwd = (id_val != pwd)
                    if pw_val:
                        pw_status = "OK" if len(pw_val) == len(pwd) else "FAIL"
                    else:
                        pw_status = "UNKNOWN"
                    log(f"[로그인] ID 입력 검증: {'OK' if id_match else 'FAIL'}")
                    log(f"[로그인] PW 입력 검증: {pw_status}")
                    log(f"[로그인] ID/PW 뒤섞임 검증: {'OK' if id_not_pwd else 'FAIL'}")
                    if not id_match or not id_not_pwd:
                        failure_reason = "ID/PW 입력 검증 실패"
                        log("[로그인][WARN] 직접 입력 검증 실패 — fallback 진행")
                    else:
                        if _click_login_ok_button(login_win):
                            login_ok = True
                            log("pywinauto 로그인 전송 완료(ID/PW 직접 값 설정)")
                        else:
                            failure_reason = "확인 버튼 클릭 실패"
                            log("[로그인][WARN] 확인 버튼 클릭 실패 — fallback 진행")
            else:
                failure_reason = f"Edit 후보 {edit_candidates_count}개 미만"
        except Exception as e:
            failure_reason = f"시도1 예외: {e}"
            log(f"로그인 실패: {type(e).__name__}: {e}")

    # fallback 전: 기존 TDXLoginDialog를 new_wins 앞에 보강
    if not login_ok:
        try:
            existing_handles = {w.handle for w in new_wins}
            prepend = []
            for w in Desktop(backend="win32").windows():
                try:
                    if safe_cls(w) == "TDXLoginDialog" and w.is_visible() and w.is_enabled():
                        if w.handle not in existing_handles:
                            prepend.append(w)
                            log(f"[로그인] fallback 후보에 기존 TDXLoginDialog 추가: hwnd={w.handle:#010x}")
                except Exception:
                    pass
            if prepend:
                new_wins = prepend + new_wins
        except Exception:
            pass

    # 시도 2: fallback 창 선택 + 2-A Edit 탐색 우선, 2-B 좌표 fallback
    if not login_ok and new_wins:
        fallback_used = True
        log("Fallback: 신규 창 상대좌표 방식")

        dlg, fb_reason = _select_login_fallback_window(new_wins)
        if dlg:
            log(f"[로그인] fallback 대상 선택: {fb_reason}, class={safe_cls(dlg)!r}, title={safe_txt(dlg)!r}")
        else:
            failure_reason = "fallback 창 선택 실패"

        if dlg:
            l, t, r, b = safe_rect(dlg)
            w_w, w_h = r - l, b - t

            # 2-A: Edit 컨트롤 탐색
            try:
                dlg.set_focus(); time.sleep(0.3)
                login_edits = []
                for c in dlg.descendants():
                    if safe_cls(c) in _LOGIN_EDIT_CLS:
                        try:
                            if c.is_visible() and c.is_enabled():
                                _r = c.rectangle()
                                login_edits.append((_r.top, _r.left, c))
                        except Exception:
                            pass
                login_edits.sort(key=lambda x: (x[0], x[1]))
                edit_candidates_count = len(login_edits)
                log(f"[로그인][DEBUG] Edit 후보 수: {edit_candidates_count}")
                for top_, left_, c in login_edits:
                    try:
                        log(f"[로그인][DEBUG] Edit 후보: class={safe_cls(c)!r}, rect=({left_},{top_},...), visible=True, enabled=True")
                    except Exception:
                        pass
                if len(login_edits) >= 2:
                    id_ctrl = login_edits[0][2]
                    pw_ctrl = login_edits[1][2]
                    id_ok = _set_edit_text_direct(id_ctrl, uid, "ID", secret=False)
                    pw_ok = _set_edit_text_direct(pw_ctrl, pwd, "PW", secret=True)
                    if not id_ok or not pw_ok:
                        failure_reason = "2-A 직접 입력 실패"
                        log("[로그인][WARN] 2-A 직접 입력 실패 — fallback 진행")
                    else:
                        id_val     = _read_edit_text_safe(id_ctrl, secret=False)
                        pw_val     = _read_edit_text_safe(pw_ctrl, secret=True)
                        id_match   = (id_val == uid)
                        id_not_pwd = (id_val != pwd)
                        if pw_val:
                            pw_status = "OK" if len(pw_val) == len(pwd) else "FAIL"
                        else:
                            pw_status = "UNKNOWN"
                        log(f"[로그인] ID 입력 검증: {'OK' if id_match else 'FAIL'}")
                        log(f"[로그인] PW 입력 검증: {pw_status}")
                        log(f"[로그인] ID/PW 뒤섞임 검증: {'OK' if id_not_pwd else 'FAIL'}")
                        if not id_match or not id_not_pwd:
                            failure_reason = "2-A ID/PW 입력 검증 실패"
                            log("[로그인][WARN] 2-A 직접 입력 검증 실패 — fallback 진행")
                        else:
                            if _click_login_ok_button(dlg):
                                login_ok = True
                                log("[로그인] fallback Edit 탐색으로 ID/PW 입력 성공")
                            else:
                                failure_reason = "2-A 확인 버튼 클릭 실패"
                                log("[로그인][WARN] 2-A 확인 버튼 클릭 실패 — fallback 진행")
                else:
                    failure_reason = f"Edit 후보 {edit_candidates_count}개 미만"
            except Exception as e:
                failure_reason = f"fallback 입력 예외: {e}"
                log(f"2-A Edit 탐색 실패: {e}")

            # 2-B: 좌표 fallback (최후 수단)
            if not login_ok:
                edit_count_2b = _count_login_edit_candidates(dlg)
                if edit_count_2b == 0:
                    failure_reason = "Edit 후보 없음 — 좌표 fallback 불가"
                    log("[로그인][WARN] Edit 후보 없음 — 좌표 fallback 불가")
                else:
                    try:
                        log("[WARN] 로그인 좌표 fallback: id_y+25")
                        dlg.set_focus(); time.sleep(0.3)
                        id_x, id_y = l + w_w // 2, t + w_h // 3
                        pw_x, pw_y = id_x, id_y + 25
                        pyautogui.click(id_x, id_y); time.sleep(0.3)
                        pyautogui.hotkey("ctrl", "a")
                        pyautogui.typewrite(uid, interval=0.07)
                        pyperclip.copy(pwd)
                        pyautogui.click(pw_x, pw_y); time.sleep(0.3)
                        pyautogui.hotkey("ctrl", "a")
                        pyautogui.hotkey("ctrl", "v")
                        time.sleep(0.3)
                        pyautogui.press("enter")
                        login_ok = True
                        log("상대좌표 로그인 전송 완료")
                    except Exception as e:
                        failure_reason = f"좌표 fallback 예외: {e}"
                        log(f"fallback 실패: {e}")
                    finally:
                        pyperclip.copy("")

    del pwd, uid
    if not login_ok:
        log("[로그인][FAIL] 로그인 전송 실패")
        log(f"[로그인][FAIL] login_win_found={login_win_found}")
        log(f"[로그인][FAIL] new_wins_count={len(new_wins)}")
        log(f"[로그인][FAIL] fallback_used={fallback_used}")
        log(f"[로그인][FAIL] edit_candidates={edit_candidates_count}")
        log(f"[로그인][FAIL] reason={failure_reason or '로그인창 미발견'}")
        log("[ERROR] 로그인 전송 실패")
        raise RuntimeError("로그인 전송 실패")


# ══════════════════════════════════════════════════════════════════════════════
# 메인 창 대기
# ══════════════════════════════════════════════════════════════════════════════
_BANK24_TITLE_HINTS = (
    "BANK24",
    "KADC_LOADER",
    "금융기관",
    "BANK ONLINE",
    "X11",
)

def _is_bank24_title(title):
    t = title.upper()
    return any(h in t for h in _BANK24_TITLE_HINTS)

def _dump_bank24_windows(context: str):
    """진단용: top-level 창 중 Bank24/로그인/팝업 후보를 로그로 남긴다."""
    _DUMP_CLASSES = {"TfrmMain", "TDXLoginDialog", "TProgressDlg", "#32770", "TApplication"}
    _DUMP_TITLE_KEYWORDS = (
        "BANK24", "Bank24", "금융기관", "BANK ONLINE", "X11",
        "오류", "확인", "알림", "인증", "비밀번호", "로그인", "서버", "Progress",
    )
    try:
        for w in Desktop(backend="win32").windows():
            try:
                cls   = safe_cls(w)
                title = safe_txt(w).strip()
                if cls not in _DUMP_CLASSES and not any(k in title for k in _DUMP_TITLE_KEYWORDS):
                    continue
                try:    rect    = safe_rect(w)
                except: rect    = None
                try:    visible = w.is_visible()
                except: visible = None
                try:    enabled = w.is_enabled()
                except: enabled = None
                log(f"[MAIN][DEBUG] {context}: hwnd={w.handle:#010x}, class={cls!r}, title={title!r}, rect={rect}, visible={visible}, enabled={enabled}")
            except Exception:
                pass
    except Exception:
        pass

def wait_main():
    hdr("Step 3. 메인 창 대기 (최대 90초)")
    LOADING_TITLES = {"ProgressDlg", ""}
    POPUP_TITLE_KEYWORDS = ("오류", "확인", "알림", "인증", "비밀번호", "로그인", "서버")
    deadline = time.time() + 90
    candidate = None
    seen_ignored_main_handles = set()
    seen_popup_handles = set()
    last_login_warn_time = 0.0
    _dump_bank24_windows("wait_main 시작")
    while time.time() < deadline:
        for w in Desktop(backend="win32").windows():
            cls   = safe_cls(w)
            title = safe_txt(w).strip()

            # [수정 4] TDXLoginDialog 잔존 감지 (10초 간격)
            if cls == "TDXLoginDialog":
                now = time.time()
                if now - last_login_warn_time >= 10.0:
                    last_login_warn_time = now
                    log(f"[MAIN][WARN] 로그인창이 아직 열려 있음: title={title!r}")

            # [수정 5] 팝업 후보 감지 (hwnd 중복 방지)
            if cls == "#32770" or any(k in title for k in POPUP_TITLE_KEYWORDS):
                hwnd = w.handle
                if hwnd not in seen_popup_handles:
                    seen_popup_handles.add(hwnd)
                    log(f"[MAIN][WARN] 팝업 후보 감지: class={cls!r}, title={title!r}, hwnd={hwnd:#010x}")

            if cls != MAIN_CLS:
                continue

            if not _is_bank24_title(title) and title not in LOADING_TITLES:
                # [수정 3] TfrmMain 무시 DEBUG 로그 (hwnd 중복 방지)
                if DEBUG_MAIN_WAIT and w.handle not in seen_ignored_main_handles:
                    seen_ignored_main_handles.add(w.handle)
                    log(f"[MAIN][DEBUG] TfrmMain 무시: title={title!r}, hwnd={w.handle:#010x}")
                continue
            if title in LOADING_TITLES:
                candidate = w
                safe_stdout_write(f"[로딩중:{title}]")
                continue
            log(f"메인 창 준비 완료: {title!r}")
            fg_ok = force_foreground(w.handle, "메인창")
            log(f"메인창 전면화: {'성공' if fg_ok else '실패'}")
            return w
        safe_stdout_write(".")
        time.sleep(1)
    if sys.stdout: print()
    _dump_bank24_windows("wait_main 타임아웃")
    if candidate:
        log(f"[WARN] 로딩 타임아웃 — 마지막 창으로 진행: {safe_txt(candidate)!r}")
        fg_ok = force_foreground(candidate.handle, "메인창(타임아웃)")
        log(f"메인창 전면화: {'성공' if fg_ok else '실패'}")
        return candidate
    log("[ERROR] 메인 창 대기 초과"); return None


# ══════════════════════════════════════════════════════════════════════════════
# 신한은행 버튼 클릭
# ══════════════════════════════════════════════════════════════════════════════
def click_shinhan_button(main_win):
    hdr("Step 4. 신한은행 은행 버튼 선택")
    if not main_win:
        log("skip (메인 창 없음)"); return False

    EXACT = "신한은행"  # 정확 일치만 — 신협중앙회 등 오탐 방지

    # 전략 1: 모든 descendants 중 텍스트 정확 일치
    try:
        descs = _all_descendants(main_win)
        # 버튼 계열 우선
        for c in descs:
            if safe_txt(c).strip() == EXACT:
                cls = safe_cls(c)
                if any(k in cls for k in ("Button", "TcxButton", "TdxBar",
                                          "TSpeedButton", "TBitBtn")):
                    c.click_input(); time.sleep(1.0)
                    log(f"신한은행 버튼 클릭 완료: class={cls!r}")
                    return True
        # 버튼이 없으면 정확 일치 첫 번째 컨트롤
        for c in descs:
            if safe_txt(c).strip() == EXACT:
                cls = safe_cls(c)
                c.click_input(); time.sleep(1.0)
                log(f"신한은행 버튼 클릭 완료(비버튼): class={cls!r}")
                return True
    except Exception as e:
        log(f"버튼 탐색 실패: {e}")

    # 전략 2: TdxBarControl 하위에서 정확 일치
    try:
        bars = _timed_descendants(main_win, "TdxBarControl")
        log(f"TdxBarControl: {len(bars)}개")
        for bar in bars:
            try:
                for c in bar.descendants():
                    if safe_txt(c).strip() == EXACT:
                        c.click_input(); time.sleep(1.0)
                        log(f"신한은행 버튼 클릭 완료(toolbar): class={safe_cls(c)!r}")
                        return True
            except:
                pass
    except Exception as e:
        log(f"TdxBarControl 탐색 실패: {e}")

    log("신한은행 버튼을 찾지 못함 — BANK_FILTER_NOT_CONFIRMED")
    return False


# ══════════════════════════════════════════════════════════════════════════════
# 담보 필터 + 날짜 + 조회
# ══════════════════════════════════════════════════════════════════════════════
def select_bank24_source_tab(main_win, source_tab: str) -> bool:
    """Bank24 상단 toolbar에서 대상 탭(작성/미접수)을 클릭한다."""
    # source_tab 정규화
    tab = source_tab.strip().replace(" ", "")
    if tab in ("작성", "작성(테스트)"):
        tab = "작성"
    elif tab in ("미접수", "미접수(운영)"):
        tab = "미접수"
    else:
        log(f"[탭][WARN] 지원하지 않는 대상 탭: {source_tab!r}")
        return False

    coords = TAB_RELATIVE_COORDS[tab]

    # toolbar 탐색
    toolbar = None
    try:
        bars = [c for c in main_win.descendants() if safe_cls(c) == "TdxBarControl"]
        for b in bars:
            if safe_txt(b).strip() == "toolbar":
                toolbar = b
                log("[탭] toolbar 탐색: window_text 매칭")
                break
        if toolbar is None and bars:
            bars_sorted = sorted(bars, key=lambda b: (safe_rect(b)[1], safe_rect(b)[0]))
            toolbar = bars_sorted[0]
            log(f"[탭] toolbar 탐색: y좌표 fallback (window_text={safe_txt(toolbar)!r})")
    except Exception as e:
        log(f"[탭][WARN] toolbar 탐색 중 오류: {type(e).__name__}: {e}")

    if toolbar is None:
        log("[탭][WARN] toolbar를 찾지 못함")
        return False

    # 탭 클릭
    try:
        log(f"[탭] 대상 탭 선택: {tab}")
        log(f"[탭] toolbar 기준 상대 클릭: tab={tab}, coords={coords}")
        toolbar.click_input(coords=coords)
        time.sleep(1.0)
    except Exception as e:
        log(f"[탭][WARN] 대상 탭 선택 실패: {type(e).__name__}: {e}")
        return False

    # 약식 검증
    try:
        verified = False
        if tab in safe_txt(main_win):
            verified = True
        else:
            for c in main_win.descendants():
                try:
                    if tab in safe_txt(c):
                        verified = True
                        break
                except Exception:
                    pass
        if verified:
            log(f"[탭] 대상 탭 선택 검증됨: {tab}")
        else:
            log(f"[탭][WARN] 대상 탭 선택 검증 불가: {tab}")
    except Exception:
        log(f"[탭][WARN] 대상 탭 선택 검증 불가: {tab}")

    return True


def apply_filter(main_win):
    hdr("Step 5. 담보 필터 + 날짜 + 조회")
    if not main_win:
        log("skip"); return

    log(f"조회기간: {DATE_FROM} ~ {DATE_TO}")

    # ── 업무구분: 담보 ────────────────────────────────────────────────────────
    def _norm(t): return "".join(t.split())  # 공백 모두 제거

    dambo_selected = False
    try:
        radios = _timed_descendants(main_win, "TcxCustomRadioGroupButton")
        log(f"업무구분 라디오: {len(radios)}개")
        for r in radios:
            log(f"  라디오 텍스트: {safe_txt(r)!r}")
        for r in radios:
            if _norm(safe_txt(r)) == "담보":
                r.click_input(); time.sleep(0.4)
                log("업무구분 담보 선택 완료 (텍스트 매칭)")
                dambo_selected = True; break
        if not dambo_selected and len(radios) > 3:
            radios[3].click_input(); time.sleep(0.4)
            log("업무구분 담보 선택 완료 (index=3 fallback)")
            dambo_selected = True
    except Exception as e:
        log(f"업무구분 라디오 실패: {e}")

    # 담보 선택 재확인
    if dambo_selected:
        try:
            radios2 = _timed_descendants(main_win, "TcxCustomRadioGroupButton")
            confirmed = False
            for r in radios2:
                if _norm(safe_txt(r)) == "담보":
                    # pywinauto는 라디오 checked 상태를 get_check_state()로 확인
                    try:
                        state = r.get_check_state()
                        if state == 1:
                            log("담보 선택 재확인 OK (get_check_state=1)")
                            confirmed = True
                    except:
                        pass
                    break
            if not confirmed:
                log("[WARN] 담보 선택 재확인 불가 — 선택 동작은 수행했음")
        except Exception as e:
            log(f"담보 재확인 실패: {e}")
    else:
        log("[WARN] 담보 라디오를 선택하지 못함 — '전체' 상태로 조회될 수 있음")

    # ── 기간검색: 직접입력 ─────────────────────────────────────────────────────
    try:
        descs_all = _all_descendants(main_win)
        found_di = False
        for c in descs_all:
            if safe_txt(c).strip() == "직접입력":
                cls = safe_cls(c)
                log(f"기간검색 직접입력 선택: class={cls!r}")
                c.click_input(); time.sleep(0.3)
                found_di = True; break
        if not found_di:
            for c in descs_all:
                if safe_cls(c) in ("TcxComboBox", "TComboBox", "ComboBox"):
                    try:
                        if hasattr(c, "item_texts"):
                            its = c.item_texts()
                            if "직접입력" in its:
                                c.select(its.index("직접입력"))
                                log("기간검색 직접입력 선택 (콤보박스)")
                                time.sleep(0.3)
                                found_di = True; break
                    except:
                        pass
        if not found_di:
            log("[WARN] 기간검색 직접입력 미발견 — 계속 진행")
    except Exception as e:
        log(f"기간검색 직접입력 설정 실패: {e}")

    # ── 날짜 입력 ──────────────────────────────────────────────────────────────
    try:
        inner = _timed_descendants(main_win, "TcxCustomDropDownInnerEdit")
        log(f"날짜 편집 컨트롤: {len(inner)}개")
        if len(inner) >= 2:
            for ctrl, val, label in [
                (inner[1], DATE_FROM, "시작일"),
                (inner[0], DATE_TO,   "종료일"),
            ]:
                ctrl.click_input(); time.sleep(0.2)
                ctrl.type_keys("^a",  with_spaces=True)
                ctrl.type_keys(val,   with_spaces=True)
                ctrl.type_keys("{TAB}", with_spaces=True)
                log(f"{label}: {val}")
                time.sleep(0.2)
        log(f"조회기간 설정: {DATE_FROM} ~ {DATE_TO}")
    except Exception as e:
        log(f"날짜 설정 실패: {e}")

    # ── 조회 전 그리드 스냅샷 (Ctrl+Home 위치 / Down1 위치) ─────────────────
    before_ctrl_home_copy = ""
    before_down1_copy     = ""

    def _snap_analyze(val, label):
        has_tab  = "\t" in val
        no_sp    = val.replace("\t", "").replace(" ", "")
        look_hdr = has_tab and not any(c.isdigit() for c in no_sp[:30])
        look_dat = has_tab and any(c.isdigit() for c in val)
        log(f"{label}: {val[:100]!r}")
        log(f"  탭 포함: {has_tab}  헤더 추정: {look_hdr}  데이터 추정: {look_dat}")

    before_ctrl_home_copy = ""
    before_down1_copy     = ""
    try:
        grid = _get_main_grid(main_win)
        if grid:
            grid.click_input(); time.sleep(0.3)
            if not _ensure_foreground_window(main_win, "apply_filter 스냅샷", log):
                log("[FOCUS][WARN] apply_filter 스냅샷 foreground 실패 — 스냅샷 스킵")
            else:
                if not _safe_send_keys(main_win, "^{HOME}", "apply_filter snapshot HOME", log):
                    log("[FOCUS][WARN] apply_filter snapshot HOME 실패")
                    before_ctrl_home_copy = ""
                else:
                    time.sleep(0.2)
                    pyperclip.copy("")
                    if not _safe_send_keys(main_win, "^c", "apply_filter snapshot copy home", log):
                        log("[FOCUS][WARN] apply_filter snapshot copy home 실패")
                        before_ctrl_home_copy = ""
                    else:
                        time.sleep(0.4)
                        before_ctrl_home_copy = clip_read()
                        _snap_analyze(before_ctrl_home_copy, "before_ctrl_home_copy")

                if not _safe_send_keys(main_win, "{DOWN}", "apply_filter snapshot DOWN", log):
                    log("[FOCUS][WARN] apply_filter snapshot DOWN 실패")
                    before_down1_copy = ""
                else:
                    time.sleep(0.2)
                    pyperclip.copy("")
                    if not _safe_send_keys(main_win, "^c", "apply_filter snapshot copy down", log):
                        log("[FOCUS][WARN] apply_filter snapshot copy down 실패")
                        before_down1_copy = ""
                    else:
                        time.sleep(0.4)
                        before_down1_copy = clip_read()
                        _snap_analyze(before_down1_copy, "before_down1_copy")
        else:
            log("[WARN] 조회 전 그리드 없음")
    except Exception as e:
        log(f"before 스냅샷 오류: {e}")

    before_snap_for_poll = before_down1_copy or before_ctrl_home_copy

    # ── 조회 버튼 클릭 ────────────────────────────────────────────────────────
    clicked = False
    try:
        btns = _timed_descendants(main_win, "TcxButton")
        log(f"TcxButton: {len(btns)}개")
        for b in btns:
            if safe_txt(b).strip() in ("조회", "검색", "Search"):
                b.click_input()
                log(f"조회 버튼 클릭 (텍스트={safe_txt(b)!r})")
                clicked = True; break
        if not clicked and len(btns) >= 4:
            btns[3].click_input()
            log("조회 버튼 클릭 (index=3 fallback)")
            clicked = True
    except Exception as e:
        log(f"조회 버튼 클릭 실패: {e}")

    # ── 조회 완료 대기 (polling) ──────────────────────────────────────────────
    if clicked:
        _poll_grid_stable(main_win, before_snap_for_poll, timeout=30)
    else:
        log("[WARN] 조회 버튼 클릭 미수행 — 2초 대기 후 진행")
        time.sleep(2)


# ══════════════════════════════════════════════════════════════════════════════
# 메인 그리드 행 목록 읽기
# ══════════════════════════════════════════════════════════════════════════════
def _parse_tsv(text):
    """탭 구분 텍스트를 헤더+행 리스트로 파싱"""
    if not text:
        return [], []
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return [], []
    headers = [h.strip() for h in lines[0].split("\t")]
    rows = []
    for line in lines[1:]:
        cols = [c.strip() for c in line.split("\t")]
        while len(cols) < len(headers):
            cols.append("")
        rows.append(dict(zip(headers, cols)))
    return headers, rows

def _get_main_grid(main_win):
    """TfrmMain의 메인 그리드(가장 큰 TcxGrid) 반환"""
    grids = _timed_descendants(main_win, GRID_CLS)
    if not grids:
        return None
    return max(grids, key=lambda g: g.rectangle().width() * g.rectangle().height())

def read_main_grid_rows(main_win):
    """
    메인 그리드에서 모든 행 읽기.
    반환: (headers, rows_list)
           rows_list = [{"은행": ..., "접수일자": ..., ...}, ...]
    """
    hdr("Step 6. 메인 그리드 행 읽기")
    grid = _get_main_grid(main_win)
    if not grid:
        log("[WARN] 그리드 없음"); return [], []

    r = grid.rectangle()
    log(f"그리드: {safe_cls(grid)!r}  {r.width()}×{r.height()}")

    # 전략 1: 그리드 포커스 후 Ctrl+A→Ctrl+C (전체 선택 복사)
    try:
        grid.click_input(); time.sleep(0.3)
        send_keys("^{HOME}"); time.sleep(0.2)
        pyperclip.copy("")
        send_keys("^a"); time.sleep(0.3)
        send_keys("^c"); time.sleep(0.8)
        text = clip_read()
        if text and "\t" in text and "\n" in text:
            headers, rows = _parse_tsv(text)
            log(f"클립보드 파싱: 헤더={headers}")
            log(f"행 수: {len(rows)}")
            return headers, rows
        elif text:
            log(f"클립보드 단일값: {text[:80]!r}")
    except Exception as e:
        log(f"Ctrl+A 복사 실패: {e}")

    # 전략 2: 행 단위 Down 키 + 클립보드 (행 수 카운트)
    log("전략 2: 행 단위 키보드 네비게이션")
    rows_data = []
    try:
        grid.click_input(); time.sleep(0.3)
        send_keys("^{HOME}"); time.sleep(0.2)
        prev_val = None
        for i in range(300):  # 최대 300행
            pyperclip.copy("")
            send_keys("^c"); time.sleep(0.3)
            val = clip_read()
            if val == prev_val and i > 0:
                log(f"행 반복 감지 → {i}행에서 종료")
                break
            if val:
                rows_data.append({"_raw": val, "_row_idx": i})
            prev_val = val
            send_keys("{DOWN}"); time.sleep(0.1)
        log(f"행 단위 읽기: {len(rows_data)}행")
    except Exception as e:
        log(f"행 단위 실패: {e}")

    return [], rows_data

def count_grid_rows(main_win):
    """메인 그리드 행 수를 Down 키로 카운트"""
    grid = _get_main_grid(main_win)
    if not grid:
        return 0
    try:
        grid.click_input(); time.sleep(0.3)
        send_keys("^{HOME}"); time.sleep(0.2)
        pyperclip.copy("")
        send_keys("^c"); time.sleep(0.3)
        first_val = clip_read()
        if not first_val:
            return 0

        count = 1
        for _ in range(500):
            send_keys("{DOWN}"); time.sleep(0.08)
            pyperclip.copy("")
            send_keys("^c"); time.sleep(0.25)
            val = clip_read()
            if val == first_val and count > 1:
                break
            if not val:
                break
            count += 1
        return count
    except Exception as e:
        log(f"행 수 카운트 실패: {e}")
        return 0


# ══════════════════════════════════════════════════════════════════════════════
# 메인 그리드 특정 행으로 이동
# ══════════════════════════════════════════════════════════════════════════════
def navigate_to_row(main_win, row_idx):
    """Ctrl+Home → row_idx회 Down 키로 특정 행 이동"""
    grid = _get_main_grid(main_win)
    if not grid:
        return False
    try:
        grid.click_input(); time.sleep(0.3)
        send_keys("^{HOME}"); time.sleep(0.2)
        for _ in range(row_idx):
            send_keys("{DOWN}"); time.sleep(0.05)
        time.sleep(0.2)
        return True
    except Exception as e:
        log(f"행 이동 실패: {e}")
        return False

def _verify_at_position(target_doc, target_est):
    """현재 그리드 포커스 행 Ctrl+C로 의뢰번호/감정서번호 포함 여부 확인"""
    try:
        pyperclip.copy(""); send_keys("^c"); time.sleep(0.4)
        raw = clip_read()
        if target_doc and target_doc in raw: return True
        if target_est and target_est in raw: return True
    except:
        pass
    return False


# ══════════════════════════════════════════════════════════════════════════════
# 종합접수(TBnkTop24Rcp) 열기
# ══════════════════════════════════════════════════════════════════════════════
def _find_detail():
    for w in Desktop(backend="win32").windows():
        if safe_cls(w) == DETAIL_CLS:
            return w
    return None


def snapshot_detail_handles():
    """현재 열려 있는 모든 TBnkTop24Rcp 창 handle 스냅샷 반환 (dict: handle → info)"""
    snap = {}
    try:
        for w in Desktop(backend="win32").windows():
            if safe_cls(w) == DETAIL_CLS:
                h = w.handle
                snap[h] = {"handle": h, "title": safe_txt(w)}
    except Exception as e:
        log(f"[WARN] 스냅샷 오류: {e}")
    log(f"종합접수 스냅샷: {len(snap)}개")
    return snap


def open_detail(main_win, row_idx):
    """현재 포커스 행에 컨텍스트 메뉴({APPS}) → '0' 으로 종합접수 열기"""
    existing = _find_detail()
    if existing:
        existing.close(); time.sleep(0.8)

    if not navigate_to_row(main_win, row_idx):
        return None

    # 전략 1: {APPS} 키 (컨텍스트 메뉴 키)
    apps_ok = False
    try:
        grid = _get_main_grid(main_win)
        if grid:
            grid.click_input(); time.sleep(0.2)
            # 다시 해당 행으로 이동
            send_keys("^{HOME}"); time.sleep(0.15)
            for _ in range(row_idx):
                send_keys("{DOWN}"); time.sleep(0.05)
            time.sleep(0.2)
            if not _safe_send_keys(main_win, "{APPS}", "open_detail APPS", log):
                log("[FOCUS][WARN] open_detail APPS 전송 실패 — fallback으로 이동")
            else:
                time.sleep(1.2)
                if not _safe_send_keys(main_win, "0", "open_detail menu select", log):
                    log("[FOCUS][WARN] open_detail menu select 실패 — fallback으로 이동")
                else:
                    apps_ok = True
                    time.sleep(3.0)
    except Exception as e:
        log(f"APPS 키 실패: {e}")

    if not apps_ok:
        # Fallback: 그리드 중앙 우클릭 (창 기준 상대좌표)
        try:
            grid = _get_main_grid(main_win)
            if grid:
                r = grid.rectangle()
                # 첫 데이터 행 y = 헤더(약 25px) + row_idx*행높이(약 20px) + 10
                rel_y = 25 + row_idx * 20 + 10
                cx = r.left + r.width() // 2
                cy = r.top + min(rel_y, r.height() - 10)
                if not _ensure_foreground_window(main_win, "open_detail rightClick", log):
                    log("[FOCUS][WARN] open_detail rightClick foreground 실패")
                else:
                    pyautogui.rightClick(cx, cy); time.sleep(1.2)
                    if not _ensure_foreground_window(main_win, "open_detail menu select fallback", log):
                        log("[FOCUS][WARN] open_detail menu select fallback foreground 실패")
                    else:
                        pyautogui.press("0"); time.sleep(3.0)
        except Exception as e2:
            log(f"우클릭 fallback 실패: {e2}")

    # 폴링
    log("TBnkTop24Rcp 폴링…")
    deadline = time.time() + 15
    while time.time() < deadline:
        w = _find_detail()
        if w:
            log(f"종합접수 발견: {safe_txt(w)!r}")
            return w
        safe_stdout_write(".")
        time.sleep(0.5)
    if sys.stdout: print()
    log("[WARN] 종합접수 창 미발견")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# TBnkTop24Rcp 필드 읽기
# ══════════════════════════════════════════════════════════════════════════════
def _read_field_by_label(descs_w32, field_name):
    """라벨 근접 편집 컨트롤에서 값 읽기"""
    labels = [(c, safe_txt(c).strip(), safe_rect(c))
              for c in descs_w32
              if safe_cls(c) in LABEL_CLS and safe_txt(c).strip()]
    edits  = [(c, safe_cls(c), safe_rect(c))
              for c in descs_w32
              if safe_cls(c) in EDIT_CLS]

    for ctrl, ltxt, (lL, lT, lR, lB) in labels:
        if field_name not in ltxt and ltxt not in field_name:
            continue
        # 같은 y±15, 오른쪽에서 가장 가까운 편집 컨트롤
        best, best_d = None, 9999
        for ec, ec_cls, (eL, eT, eR, eB) in edits:
            if abs(eT - lT) <= 15 and eL >= lL:
                d = eL - lR
                if 0 <= d < best_d:
                    best_d, best = d, ec
        if best:
            return safe_txt(best).strip()
    return None

def _read_field_uia(uia_win, field_name):
    """UIA ValuePattern으로 필드 값 읽기"""
    try:
        for c in uia_win.descendants():
            try:
                name = safe_txt(c).strip()
                if field_name in name or name in field_name:
                    v = safe_val(c)
                    if v:
                        return v
            except:
                pass
    except:
        pass
    return None

def _read_field_clipboard(descs_w32, field_name):
    """편집 컨트롤 클릭+클립보드로 읽기 (fallback)"""
    # 해당 라벨 근처 컨트롤 찾기
    labels = [(c, safe_txt(c).strip(), safe_rect(c))
              for c in descs_w32
              if safe_cls(c) in LABEL_CLS and safe_txt(c).strip()]
    edits  = [(c, safe_cls(c), safe_rect(c))
              for c in descs_w32
              if safe_cls(c) in EDIT_CLS]

    for ctrl, ltxt, (lL, lT, lR, lB) in labels:
        if field_name not in ltxt and ltxt not in field_name:
            continue
        best, best_d = None, 9999
        for ec, ec_cls, (eL, eT, eR, eB) in edits:
            if abs(eT - lT) <= 15 and eL >= lL:
                d = eL - lR
                if 0 <= d < best_d:
                    best_d, best = d, ec
        if best:
            val = ctrl_c_copy(best, wait=0.4)
            if val:
                return val
    return None

def read_detail_fields(detail_win):
    """TBnkTop24Rcp에서 DETAIL_FIELDS 모두 읽기"""
    result = {}

    # win32 descendants
    try:
        app32  = Application(backend="win32").connect(handle=detail_win.handle)
        win32  = app32.top_window()
        descs32 = win32.descendants()
    except Exception as e:
        log(f"[ERROR] win32 연결 실패: {e}")
        return result

    # UIA window (ValuePattern fallback용)
    uia_win = None
    try:
        app_uia = Application(backend="uia").connect(handle=detail_win.handle)
        uia_win = app_uia.top_window()
    except:
        pass

    for field in DETAIL_FIELDS:
        val = None

        # 1차: 라벨 근접 편집 컨트롤 window_text
        val = _read_field_by_label(descs32, field)
        if val:
            result[field] = val
            continue

        # 2차: UIA ValuePattern
        if uia_win:
            val = _read_field_uia(uia_win, field)
            if val:
                result[field] = val
                continue

        # 3차: 클립보드 복사
        val = _read_field_clipboard(descs32, field)
        if val:
            result[field] = val
            continue

        result[field] = ""

    # 읽기 결과 출력 (값이 있는 것만)
    for f in DETAIL_FIELDS:
        v = result.get(f, "")
        status = "OK" if v else "--"
        log(f"  [{status}] {f:<18} = {v!r}")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# 주소 그리드 전체 행 읽기
# ══════════════════════════════════════════════════════════════════════════════
_ADDR_HDR_WORDS = {"순서", "주소", "번호", "no", "순번", "주소목록"}

def _is_addr_header(val):
    """그리드 헤더 행 판별 — True이면 주소 목록에서 제외"""
    if not val: return True
    s = val.strip()
    if s.isdigit(): return True
    # 탭 구분인 경우 각 파트 검사
    parts = [p.strip() for p in s.split("\t")]
    # 첫 파트가 숫자라면 순번+주소 형식 → 헤더 아님
    if parts[0].isdigit(): return False
    # 공백·탭 제거 후 헤더 키워드
    no_ws = s.replace(" ", "").replace("\t", "").lower()
    if no_ws in _ADDR_HDR_WORDS: return True
    # 첫 파트만 검사
    no_ws_first = parts[0].replace(" ", "").lower()
    if no_ws_first in _ADDR_HDR_WORDS: return True
    if len(s) < 4: return True
    return False

def _extract_addr(val):
    """순번\t주소 형식에서 주소만 추출, 그 외는 val 그대로"""
    if "\t" not in val: return val.strip()
    parts = [p.strip() for p in val.split("\t")]
    if parts[0].isdigit():
        return "\t".join(parts[1:]).strip()
    return val.strip()

# PDF 기반 추출 전환 후 미사용 — 함수 정의는 참고용으로 보존
def read_address_grid(detail_win):
    """TBnkTop24Rcp 주소 그리드의 모든 행을 Down 키 + Ctrl+C로 읽기"""
    try:
        app32  = Application(backend="win32").connect(handle=detail_win.handle)
        win32  = app32.top_window()
        descs32 = win32.descendants()
    except Exception as e:
        log(f"[ERROR] 주소 그리드 연결 실패: {e}")
        return []

    grids = [(c, safe_cls(c), safe_rect(c))
             for c in descs32 if safe_cls(c) in GRID_CLS]

    if not grids:
        log("주소 그리드 없음"); return []

    # 가장 큰 그리드 (주소 목록)
    largest = max(grids, key=lambda x: (x[2][2]-x[2][0])*(x[2][3]-x[2][1]))
    g_ctrl, g_cls, (l, t, r, b) = largest
    log(f"주소 그리드: {g_cls!r}  {r-l}×{b-t}")

    def _add_addr_lines(val):
        """val을 줄 단위로 분해 후 헤더 제거, 순번 제거해 addresses에 추가"""
        for line in val.splitlines():
            line = line.strip()
            if not line or _is_addr_header(line): continue
            clean = _extract_addr(line)
            if clean and clean not in addresses:
                addresses.append(clean)

    addresses = []
    try:
        g_ctrl.click_input(); time.sleep(0.3)
        send_keys("^{HOME}"); time.sleep(0.2)

        prev_val = None
        consecutive_same = 0
        for i in range(200):
            pyperclip.copy("")
            send_keys("^c"); time.sleep(0.4)
            val = clip_read()

            if not val:
                if i == 0:
                    cx = l + (r-l)//2
                    cy = t + 35
                    pyautogui.click(cx, cy); time.sleep(0.3)
                    send_keys("^c"); time.sleep(0.4)
                    val = clip_read()
                if not val:
                    break

            if val == prev_val:
                consecutive_same += 1
                if consecutive_same >= 2:
                    log(f"주소 반복 감지 → {i}행에서 종료")
                    break
            else:
                consecutive_same = 0
                _add_addr_lines(val)

            prev_val = val
            send_keys("{DOWN}"); time.sleep(0.1)

    except Exception as e:
        log(f"주소 그리드 읽기 실패: {e}")

    log(f"주소 {len(addresses)}건 추출")
    return addresses


# ══════════════════════════════════════════════════════════════════════════════
# 종합접수 창 닫기
# ══════════════════════════════════════════════════════════════════════════════
# PDF 기반 추출 전환 후 미사용 — 함수 정의는 참고용으로 보존
def close_detail(detail_win):
    if not detail_win:
        return
    try:
        detail_win.set_focus(); time.sleep(0.2)
        send_keys("%{F4}"); time.sleep(0.8)
        log("종합접수 닫기 완료")
    except Exception as e:
        log(f"닫기 실패: {e}")
        try:
            detail_win.close()
        except:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# 메인 그리드에서 현재 행의 은행/날짜 정보 읽기
# ══════════════════════════════════════════════════════════════════════════════
def read_main_row_data(main_win, headers, rows, row_idx):
    """
    클립보드로 파싱한 rows에서 row_idx행 데이터 반환.
    rows가 없으면 키보드 네비게이션으로 읽기 시도.
    """
    if rows and row_idx < len(rows):
        return rows[row_idx]

    # fallback: 해당 행으로 이동 후 Tab으로 컬럼별 읽기
    data = {}
    try:
        grid = _get_main_grid(main_win)
        if not grid:
            return data
        grid.click_input(); time.sleep(0.3)
        send_keys("^{HOME}"); time.sleep(0.15)
        for _ in range(row_idx):
            send_keys("{DOWN}"); time.sleep(0.05)
        time.sleep(0.2)

        # 이 행에서 Tab 이동하며 각 열 값 읽기 (최대 10열)
        vals = []
        for _ in range(10):
            pyperclip.copy("")
            send_keys("^c"); time.sleep(0.3)
            v = clip_read()
            vals.append(v)
            send_keys("{TAB}"); time.sleep(0.1)

        # 날짜 패턴으로 접수일자/의뢰일자/처리기한 추정
        import re
        date_pat = re.compile(r"\d{4}[-/]\d{2}[-/]\d{2}|\d{8}")
        date_vals = [v for v in vals if date_pat.match(v or "")]
        field_names = ["접수일자", "의뢰일자", "처리기한"]
        for i, fn in enumerate(field_names):
            if i < len(date_vals):
                data[fn] = date_vals[i]

        # 은행명 추정 (날짜가 아닌 한글 포함 값)
        for v in vals:
            if v and not date_pat.match(v) and any("가" <= ch <= "힣" for ch in v):
                data["은행"] = v
                break

    except Exception as e:
        log(f"행 데이터 읽기 실패: {e}")

    return data


# ══════════════════════════════════════════════════════════════════════════════
# 메인 그리드 raw 덤프 — Ctrl+A 방식 (진단용)
# ══════════════════════════════════════════════════════════════════════════════
def dump_ctrl_a(main_win):
    hdr("Step 7a. Ctrl+A 방식 raw 덤프")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fname = OUTPUT_DIR / f"raw_main_grid_ctrl_a_{TS}.txt"

    grid = _get_main_grid(main_win)
    if not grid:
        log("[WARN] 그리드 없음"); return None, None

    raw_text = ""

    # 시도 1: grid click + Ctrl+A → Ctrl+C
    try:
        grid.click_input(); time.sleep(0.3)
        send_keys("^{HOME}"); time.sleep(0.2)
        pyperclip.copy("")
        send_keys("^a"); time.sleep(0.4)
        send_keys("^c"); time.sleep(1.0)
        raw_text = clip_read()
        if raw_text and "\t" in raw_text and "\n" in raw_text:
            log(f"Ctrl+A→Ctrl+C 성공: {len(raw_text)}자")
        else:
            log(f"Ctrl+A→Ctrl+C 결과(탭/줄바꿈 없음): {raw_text[:80]!r}")
            raw_text = ""
    except Exception as e:
        log(f"Ctrl+A→Ctrl+C 실패: {e}")

    # 시도 2: 그리드 상단 클릭(창 기준 상대좌표) 후 재시도
    if not raw_text:
        log("fallback: 그리드 상단 클릭 후 Ctrl+A→Ctrl+C 재시도")
        try:
            r = grid.rectangle()
            pyautogui.click(r.left + r.width() // 2, r.top + 10)
            time.sleep(0.3)
            pyperclip.copy("")
            send_keys("^a"); time.sleep(0.4)
            send_keys("^c"); time.sleep(1.0)
            raw_text = clip_read()
            if raw_text and "\t" in raw_text and "\n" in raw_text:
                log(f"fallback 성공: {len(raw_text)}자")
            else:
                raw_text = ""
        except Exception as e:
            log(f"fallback 실패: {e}")

    if not raw_text:
        log("[WARN] Ctrl+A 덤프 실패"); return None, None

    lines     = [l for l in raw_text.splitlines() if l.strip()]
    data_rows = lines[1:] if lines else []
    has_tab   = "\t" in raw_text
    has_bank  = any("은행" in l for l in lines[:3])
    has_shin  = any("신한은행" in l for l in lines)
    has_dambo = any("담보" in l for l in lines)

    log(f"문자 수: {len(raw_text)}")
    log(f"줄 수: {len(lines)}")
    log(f"탭 포함: {has_tab}")
    log(f"'은행' 컬럼 존재: {has_bank}")
    log(f"데이터 행 추정: {len(data_rows)}건")
    log(f"'신한은행' 포함: {has_shin}")
    log(f"'담보' 포함: {has_dambo}")
    if len(lines) <= 2:
        log("[WARN] Ctrl+A가 전체 행을 복사하지 못했을 가능성 있음")

    with open(fname, "w", encoding="utf-8") as f:
        f.write(raw_text)
    log(f"저장: {fname}  ({fname.stat().st_size:,} bytes)")

    return fname, {
        "lines": len(lines), "data_rows": len(data_rows),
        "has_tab": has_tab, "has_bank": has_bank,
        "has_shinhan": has_shin, "has_dambo": has_dambo,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 메인 그리드 raw 덤프 — Row-by-row scan 방식 (진단용)
# ══════════════════════════════════════════════════════════════════════════════
def dump_row_scan(main_win):
    hdr("Step 7b. Row-by-row scan 덤프")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fname = OUTPUT_DIR / f"raw_main_grid_row_scan_{TS}.txt"

    grid = _get_main_grid(main_win)
    if not grid:
        log("[WARN] 그리드 없음"); return None, None

    items = []  # 원본 순서, 중복 제거 없음
    try:
        grid.click_input(); time.sleep(0.3)
        send_keys("^{HOME}"); time.sleep(0.2)

        consecutive_same  = 0
        consecutive_empty = 0
        prev_val = None

        for i in range(500):
            pyperclip.copy("")
            send_keys("^c"); time.sleep(0.35)
            val = clip_read()

            if not val:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    log(f"빈 값 3회 연속 → {i}회에서 종료")
                    break
                send_keys("{DOWN}"); time.sleep(0.1)
                continue
            consecutive_empty = 0

            if val == prev_val:
                consecutive_same += 1
                if consecutive_same >= 3:
                    log(f"동일 값 3회 연속 → {i}회에서 종료")
                    break
            else:
                consecutive_same = 0

            items.append(val)
            prev_val = val
            send_keys("{DOWN}"); time.sleep(0.1)

    except Exception as e:
        log(f"row scan 실패: {e}")

    if not items:
        log("[WARN] row scan 실패 — 수집 없음"); return None, None

    unique_items = list(dict.fromkeys(items))
    tab_count    = sum(1 for x in items if "\t" in x)
    tab_ratio    = tab_count / len(items)
    has_bank     = any("은행" in x for x in items)
    has_shin     = any("신한은행" in x for x in items)
    has_dambo    = any("담보" in x for x in items)
    is_cell_unit = tab_ratio < 0.3

    log(f"수집 개수: {len(items)}")
    log(f"고유 값 개수: {len(unique_items)}")
    log(f"문자 수: {sum(len(x) for x in items)}")
    log(f"탭 포함 비율: {tab_ratio:.1%}")
    log(f"'은행' 포함: {has_bank}")
    log(f"'신한은행' 포함: {has_shin}")
    log(f"'담보' 포함: {has_dambo}")

    if is_cell_unit:
        log("row scan은 현재 셀 단위 복사로 보임")
        log("신한은행 값 존재 여부 확인에는 참고 가능")
        log("전체 행 필드 추출 방식으로는 불충분")
    else:
        log("row scan은 행 단위 복사로 보임")

    raw_text = "\n".join(items)
    with open(fname, "w", encoding="utf-8") as f:
        f.write(raw_text)
    log(f"저장: {fname}  ({fname.stat().st_size:,} bytes)")

    return fname, {
        "items": len(items), "unique": len(unique_items),
        "tab_ratio": tab_ratio, "is_cell_unit": is_cell_unit,
        "has_bank": has_bank, "has_shinhan": has_shin, "has_dambo": has_dambo,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 두 방식 비교 (진단용)
# ══════════════════════════════════════════════════════════════════════════════
def compare_dumps(ctrl_a_info, rs_info):
    hdr("Step 8. 두 방식 결과 비교")

    ca_rows  = ctrl_a_info.get("data_rows", 0)   if ctrl_a_info else 0
    ca_tab   = ctrl_a_info.get("has_tab",  False) if ctrl_a_info else False
    rs_items = rs_info.get("items",        0)     if rs_info     else 0
    rs_cell  = rs_info.get("is_cell_unit", True)  if rs_info     else True

    log(f"Ctrl+A  — 데이터 행 추정: {ca_rows}건  탭 포함: {ca_tab}")
    log(f"row scan — 수집: {rs_items}건  셀 단위: {rs_cell}")

    if ctrl_a_info is None and rs_info is None:
        verdict = "4) 둘 다 불충분 — 그리드 접근 방식 재검토 필요"
    elif ca_tab and ca_rows > 1:
        verdict = "1) Ctrl+A 방식 사용 가능 후보"
    elif ca_rows <= 1 and rs_items > 1 and not rs_cell:
        verdict = "2) Ctrl+A 폐기 후보, row scan 행 단위 방식 우선"
    elif ca_rows <= 1 and rs_items > 1 and rs_cell:
        verdict = "3) row scan은 셀 단위라 참고만 가능 — 전체 행 추출 방식 추가 검토 필요"
    elif ca_rows <= 1 and rs_items <= 1:
        verdict = "4) 둘 다 1건 이하 — 조회조건/그리드 포커스 문제 가능성"
    else:
        verdict = "추가 검토 필요"

    log(f"최종 판단: {verdict}")

    shin_ca = ctrl_a_info.get("has_shinhan", False) if ctrl_a_info else False
    shin_rs = rs_info.get("has_shinhan",    False)  if rs_info     else False
    dmb_ca  = ctrl_a_info.get("has_dambo",  False)  if ctrl_a_info else False
    dmb_rs  = rs_info.get("has_dambo",      False)  if rs_info     else False
    log(f"'신한은행' — Ctrl+A: {shin_ca}  row scan: {shin_rs}")
    log(f"'담보'    — Ctrl+A: {dmb_ca}  row scan: {dmb_rs}")


# ══════════════════════════════════════════════════════════════════════════════
# 메인 그리드 row scan (프로덕션)
# ══════════════════════════════════════════════════════════════════════════════
def scan_main_grid(main_win):
    """Row-by-row scan: 각 행 Ctrl+C 복사, (scan_index, tsv_text) 목록 반환"""
    hdr("Step 7. 메인 그리드 row scan")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fname = OUTPUT_DIR / f"raw_scan_{TS}.txt"

    grid = _get_main_grid(main_win)
    if not grid:
        log("[WARN] 그리드 없음"); return []

    items = []
    try:
        grid.click_input(); time.sleep(0.3)
        send_keys("^{HOME}"); time.sleep(0.2)

        consecutive_same  = 0
        consecutive_empty = 0
        prev_val = None

        for i in range(500):
            pyperclip.copy("")
            send_keys("^c"); time.sleep(0.35)
            val = clip_read()

            if not val:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    log(f"빈 값 3회 연속 → {i}회에서 종료")
                    break
                send_keys("{DOWN}"); time.sleep(0.1)
                continue
            consecutive_empty = 0

            if val == prev_val:
                consecutive_same += 1
                if consecutive_same >= 3:
                    log(f"동일 값 3회 연속 → {i}회에서 종료")
                    break
            else:
                consecutive_same = 0

            items.append((i, val))
            prev_val = val
            send_keys("{DOWN}"); time.sleep(0.1)

    except Exception as e:
        log(f"row scan 실패: {e}")

    log(f"수집: {len(items)}건")
    if DEBUG_SAVE_RAW:
        raw_text = "\n".join(v for _, v in items)
        with open(fname, "w", encoding="utf-8") as f:
            f.write(raw_text)
        log(f"저장: {fname}  ({fname.stat().st_size:,} bytes)")
    return items


def parse_scan_results(scan_items):
    """scan_items[(scan_idx, tsv)] → 헤더 스킵, 컬럼 매핑 후 row dict 목록

    Bank24 TcxGrid는 Ctrl+C 시 '헤더행\n데이터행' 형태로 클립보드에 복사하는 경우가 있으므로
    각 scan item을 splitlines() 후 줄 단위로 처리한다.
    """
    if not scan_items: return []
    headers = []
    rows = []
    seen_rows = set()  # 중복 데이터 행 제거용 (의뢰번호 기준)
    for scan_idx, val in scan_items:
        if "\t" not in val: continue
        lines = [l for l in val.splitlines() if "\t" in l and l.strip()]
        for line in lines:
            cols = [c.strip() for c in line.split("\t")]
            if _is_header_line(cols):
                headers = [_norm_col(c) for c in cols]
                continue
            if not headers: continue
            padded = cols + [""] * max(0, len(headers) - len(cols))
            row = dict(zip(headers, padded))
            # 중복 행 제거: 의뢰번호 기준
            key = row.get("의뢰번호", "").strip()
            if key and key in seen_rows: continue
            if key: seen_rows.add(key)
            row["_scan_index"] = scan_idx
            rows.append(row)
    log(f"파싱: {len(rows)}행  헤더: {headers[:10]}...")
    return rows


def filter_shinhan_dambo(parsed_rows, selected_banks=None):
    """지원 은행 AND 업무구분==담보 필터링."""
    selected_banks = selected_banks or ["신한은행"]
    all_banks = "전체" in selected_banks

    selected_canonical = {
        _canonical_supported_bank(bank)
        for bank in selected_banks
        if bank and bank != "전체"
    }
    selected_canonical.discard("")

    result = []
    unsupported_rows = []

    for row in parsed_rows:
        if (
            _norm_col(row.get("업무구분", ""))
            != _norm_col("담보")
        ):
            continue

        original_bank = row.get("은행", "")
        canonical = _canonical_supported_bank(original_bank)

        if not canonical:
            unsupported_rows.append(row)
            continue

        if all_banks or canonical in selected_canonical:
            result.append(row)

    dambo_count = sum(
        1
        for row in parsed_rows
        if (
            _norm_col(row.get("업무구분", ""))
            == _norm_col("담보")
        )
    )

    unsupported_by_bank = {}
    for row in unsupported_rows:
        safe_name = _safe_bank_log_name(
            row.get("은행", "")
        )
        unsupported_by_bank[safe_name] = (
            unsupported_by_bank.get(safe_name, 0) + 1
        )

    label = (
        "지원 은행 전체"
        if all_banks
        else ", ".join(
            _safe_bank_log_name(bank)
            for bank in selected_banks
        )
    )

    log(
        f"지원 은행 담보 필터({label}): "
        f"담보 {dambo_count}건 -> "
        f"처리 대상 {len(result)}건 / "
        f"미지원 SKIP {len(unsupported_rows)}건"
    )

    for bank_name, count in unsupported_by_bank.items():
        log(
            f"[SKIP][미지원은행] "
            f"{bank_name}: {count}건"
        )

    return result


_GRID_OUTPUT_FIELDS = [
    "scan_index", "은행", "의뢰영업점", "의뢰번호", "업무구분",
    "감정서번호", "의뢰일자", "접수일자", "상태",
]

def save_shinhan_grid(rows, counts):
    """신한은행 담보 그리드 행 목록을 TXT로 저장 (건수 집계 포함)"""
    if not DEBUG_SAVE_RAW:
        return None
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fname = OUTPUT_DIR / f"main_grid_shinhan_dambo_{TS}.txt"
    lines = [
        "Bank24 신한은행 담보 그리드 추출",
        f"추출일시: {TODAY.strftime('%Y-%m-%d %H:%M:%S')}",
        f"조회기간: {DATE_FROM} ~ {DATE_TO}",
        f"전체 데이터행 수: {counts['total']}",
        f"전체 담보 행 수: {counts['total_dambo']}",
        f"신한은행 전체 행 수: {counts['shinhan_all']}",
        f"신한은행 담보 행 수: {counts['shinhan_dambo']}",
        "=" * 64, "",
    ]
    for i, row in enumerate(rows, 1):
        lines.append(f"===== ROW {i} =====")
        for fld in _GRID_OUTPUT_FIELDS:
            if fld == "scan_index":
                lines.append(f"scan_index: {row.get('_scan_index', '')}")
            else:
                lines.append(f"{fld}: {row.get(fld, '')}")
        lines.append("")
    with open(fname, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log(f"저장: {fname}  ({fname.stat().st_size:,} bytes)")
    return fname


def navigate_and_verify(main_win, target_row):
    """scan_index로 이동 후 의뢰번호/감정서번호로 위치 검증, -5~+8 순차 탐색"""
    scan_idx   = target_row.get("_scan_index", 0)
    target_doc = (target_row.get("의뢰번호")   or "").strip()
    target_est = (target_row.get("감정서번호") or "").strip()

    grid = _get_main_grid(main_win)
    if not grid: return False

    try:
        grid.click_input(); time.sleep(0.3)
        if not _ensure_foreground_window(main_win, "navigate 진입", log):
            log("[FOCUS][WARN] navigate 진입 foreground 실패")
            return False
        if not _safe_send_keys(main_win, "^{HOME}", "navigate ^HOME", log):
            log("[FOCUS][WARN] navigate ^HOME 실패")
            return False
        time.sleep(0.2)
        if scan_idx > 0:
            if not _ensure_foreground_window(main_win, "navigate scan 루프 진입", log):
                log("[FOCUS][WARN] navigate scan 루프 진입 foreground 실패")
                return False
            for i in range(scan_idx):
                send_keys("{DOWN}"); time.sleep(0.05)
                if (i + 1) % 25 == 0:
                    if not _ensure_foreground_window(main_win, f"navigate scan 중간 {i+1}", log):
                        log(f"[FOCUS][WARN] navigate scan 중간 {i+1} foreground 실패")
                        return False
            if not _ensure_foreground_window(main_win, "navigate scan 루프 완료", log):
                log("[FOCUS][WARN] navigate scan 루프 완료 foreground 실패")
                return False
        time.sleep(0.2)
    except Exception as e:
        log(f"navigate 이동 실패: {e}"); return False

    if _verify_at_position(target_doc, target_est):
        log(f"위치 검증 OK: scan_index={scan_idx}"); return True

    # 1차 검증 실패 — -5~+8 순차 탐색
    if not target_doc and not target_est:
        log("[WARN] 위치 검증 최종 실패: 의뢰번호/감정서번호 둘 다 없음")
        return False

    log(f"[ROW][RECOVER] 주변 탐색 시작: 의뢰번호={target_doc}, 감정서번호={target_est}")

    # Up 5번으로 시작점(offset=-5)으로 이동
    for _ in range(5):
        try:
            if not _safe_send_keys(main_win, "{UP}", "navigate recovery UP", log):
                if DEBUG_SAVE_RAW:
                    log("[FOCUS][WARN] navigate recovery UP step 실패 - skip")
        except Exception:
            pass

    # offset -5 ~ +8 순서로 14개 위치 순차 검사
    for offset in range(-5, 9):
        try:
            if _verify_at_position(target_doc, target_est):
                log(f"[ROW][RECOVER] 주변 탐색 성공: offset={offset}, "
                    f"의뢰번호={target_doc}, 감정서번호={target_est}")
                return True
        except Exception as e:
            if DEBUG_SAVE_RAW:
                log(f"[ROW][RECOVER] offset={offset} 검증 오류: {e}")
        # 마지막 offset이 아니면 Down 1번으로 다음 위치 이동
        if offset < 8:
            try:
                if not _safe_send_keys(main_win, "{DOWN}", "navigate recovery DOWN", log):
                    if DEBUG_SAVE_RAW:
                        log("[FOCUS][WARN] navigate recovery DOWN step 실패 - skip")
            except Exception:
                pass

    log(f"[ROW][RECOVER] 주변 탐색 실패: 의뢰번호={target_doc}, 감정서번호={target_est}")
    return False


# PDF 기반 추출 전환 후 미사용 — 함수 정의는 참고용으로 보존
def open_detail_at_current(main_win, before_handles):
    """종합접수 열기: 1차 APPS→0 (5초 폴링) → 2차 우클릭→0 (10초 폴링).
    before_handles: snapshot_detail_handles() 결과 — 이 handle에 없는 신규 창만 반환.
    """

    def _poll_new(timeout, label):
        deadline = time.time() + timeout
        while time.time() < deadline:
            new_wins = [w for w in Desktop(backend="win32").windows()
                        if safe_cls(w) == DETAIL_CLS and w.handle not in before_handles]
            if new_wins:
                if len(new_wins) > 1:
                    log(f"[WARN] 신규 종합접수 {len(new_wins)}개 — 첫 번째 사용")
                w = new_wins[0]
                elapsed = timeout - (deadline - time.time())
                log(f"[{label}] 신규 창 발견 ({elapsed:.1f}초 후): handle={w.handle:#010x}  title={safe_txt(w)!r}")
                return w
            safe_stdout_write(".")
            time.sleep(0.5)
        if sys.stdout: print()
        return None

    # 1차: pyautogui apps → 0 (navigate_and_verify가 포커스 행을 이미 설정한 상태)
    # grid.click_input() 금지 — 마우스 클릭이 선택 행을 변경함
    apps_ok = False
    try:
        grid = _get_main_grid(main_win)
        if grid:
            if not _ensure_foreground_window(main_win, "메인창-종합접수전", log):
                log("[FOCUS][WARN] 메인창-종합접수전 foreground 실패 — 1차 apps 건너뜀")
            else:
                time.sleep(0.2)
                pyautogui.press("apps"); time.sleep(1.0)
                if not _ensure_foreground_window(main_win, "메인창-메뉴선택전", log):
                    log("[FOCUS][WARN] 메인창-메뉴선택전 foreground 실패")
                else:
                    pyautogui.press("0");    time.sleep(3.0)
                    apps_ok = True
                    log("1차 pyautogui apps→0 전송")
        else:
            log("[WARN] 그리드 없음 — 1차 apps 건너뜀")
    except Exception as e:
        log(f"1차 pyautogui apps→0 실패: {e}")

    log("1차 폴링 (5초)…")
    result = _poll_new(5, "1차")
    if result:
        log("1차 신규 handle 발견")
        return result
    log("1차 신규 handle 미발견")

    # 2차 fallback: 그리드 기준 상대 좌표 우클릭 → 0
    log("2차 fallback: 우클릭→0  [WARN] fallback 우클릭 사용 — 선택 행 불일치 가능성 있음")
    try:
        grid = _get_main_grid(main_win)
        if grid:
            r = grid.rectangle()
            cx = r.left + r.width() // 2
            cy = r.top + 35
            grid.click_input(); time.sleep(0.2)
            if not _ensure_foreground_window(main_win, "2차 우클릭 전", log):
                log("[FOCUS][WARN] 2차 우클릭 전 foreground 실패")
            else:
                pyautogui.rightClick(cx, cy); time.sleep(1.2)
                if not _ensure_foreground_window(main_win, "2차 메뉴선택", log):
                    log("[FOCUS][WARN] 2차 메뉴선택 foreground 실패")
                else:
                    pyautogui.press("0"); time.sleep(3.0)
                    log("2차: 우클릭→0 전송")
    except Exception as e:
        log(f"2차 우클릭→0 실패: {e}")

    log("2차 폴링 (10초)…")
    result = _poll_new(10, "2차")
    if result:
        return result

    log(f"[WARN] 종합접수 신규 창 미발견  1차APPS={apps_ok}")
    return None


CONSERVATIVE_FIELDS = ["감정서번호", "의뢰번호", "은행", "비고"]
_BIGO_CLS = "TcxCustomInnerMemo"


# PDF 기반 추출 전환 후 미사용 — 함수 정의는 참고용으로 보존
def read_bigo_from_inner_memo(detail_win):
    """TBnkTop24Rcp에서 TcxCustomInnerMemo를 직접 찾아 비고 값 읽기.

    반환: (bigo_val, method, ctrl_found)
      method: "1차UIA" | "2차win32" | "3차clipboard" | "빈값" | "미발견"
      ctrl_found: True = 컨트롤 발견, False = 컨트롤 없음
    """
    bigo_val  = ""
    method    = "미발견"
    uia_found = 0
    w32_found = 0
    uia_ctrls = []
    w32_ctrls = []

    # 1차: UIA backend
    try:
        app_uia = Application(backend="uia").connect(handle=detail_win.handle)
        uia_win = app_uia.top_window()
        for c in uia_win.descendants():
            try:
                cls  = safe_cls(c)
                fcls = ""
                try: fcls = c.friendly_class_name()
                except: pass
                if _BIGO_CLS in (cls, fcls):
                    uia_ctrls.append(c)
            except:
                pass
        uia_found = len(uia_ctrls)
        if uia_ctrls and len(uia_ctrls) > 1:
            for c in uia_ctrls:
                r = safe_rect(c)
                nm = ""
                try: nm = c.window_text()[:30]
                except: pass
                vl = safe_val(c)[:30] if safe_val(c) else ""
                log(f"  [UIA] {safe_cls(c)}  rect={r}  name={nm!r}  val={vl!r}")
        for c in uia_ctrls:
            v = safe_val(c).strip()
            if not v:
                try: v = c.window_text().strip()
                except: pass
            if v:
                bigo_val = v
                method = "1차UIA"
                break
    except Exception as e:
        log(f"  UIA 탐색 오류: {e}")

    # 2차: win32 backend
    if not bigo_val:
        try:
            app32 = Application(backend="win32").connect(handle=detail_win.handle)
            win32 = app32.top_window()
            for c in win32.descendants():
                if safe_cls(c) == _BIGO_CLS:
                    w32_ctrls.append(c)
            w32_found = len(w32_ctrls)
            if w32_ctrls and len(w32_ctrls) > 1:
                for c in w32_ctrls:
                    r = safe_rect(c)
                    log(f"  [w32] {safe_cls(c)}  rect={r}  text={safe_txt(c)[:30]!r}")
            for c in w32_ctrls:
                v = safe_txt(c).strip()
                if v:
                    bigo_val = v
                    method = "2차win32"
                    break
        except Exception as e:
            log(f"  win32 탐색 오류: {e}")

    # 3차: clipboard fallback (control 기준 click_input만 사용)
    if not bigo_val:
        ctrl_for_clip = uia_ctrls[0] if uia_ctrls else (w32_ctrls[0] if w32_ctrls else None)
        if ctrl_for_clip is not None:
            try:
                pyperclip.copy("")
                ctrl_for_clip.click_input(); time.sleep(0.2)
                ctrl_for_clip.type_keys("^a", with_spaces=True); time.sleep(0.1)
                ctrl_for_clip.type_keys("^c", with_spaces=True); time.sleep(0.4)
                v = clip_read().strip()
                pyperclip.copy("")
                if v:
                    bigo_val = v
                    method = "3차clipboard"
            except Exception as e:
                log(f"  clipboard fallback 오류: {e}")
                pyperclip.copy("")

    # 방식 최종 결정
    ctrl_found = (uia_found > 0 or w32_found > 0)
    if ctrl_found and not bigo_val and method == "미발견":
        method = "빈값"

    # 로그
    log(f"  UIA {_BIGO_CLS}: {uia_found}개  win32: {w32_found}개")
    log(f"  비고 읽기 방식: {method}")
    if bigo_val:
        log(f"  비고 값(앞50자): {bigo_val[:50]!r}")
    elif ctrl_found:
        log(f"  컨트롤 발견 후 빈값 (실제 내용 없음)")
    else:
        log(f"  비고 컨트롤 미발견")

    return bigo_val, method, ctrl_found


def read_detail_fields_conservative(detail_win):
    """TBnkTop24Rcp에서 보수적 4개 필드만 읽기, 중복값 감지"""
    result = {}
    try:
        app32   = Application(backend="win32").connect(handle=detail_win.handle)
        win32   = app32.top_window()
        descs32 = win32.descendants()
    except Exception as e:
        log(f"[ERROR] win32 연결 실패: {e}"); return result

    uia_win = None
    try:
        app_uia = Application(backend="uia").connect(handle=detail_win.handle)
        uia_win = app_uia.top_window()
    except:
        pass

    vals_seen    = {}
    missing_fields = []

    # 비고 외 필드: 기존 label-proximity 방식
    for field in ("감정서번호", "의뢰번호", "은행"):
        val = _read_field_by_label(descs32, field)
        if not val and uia_win:
            val = _read_field_uia(uia_win, field)
        if not val:
            val = _read_field_clipboard(descs32, field)
        val = (val or "").strip()

        if val and val in vals_seen:
            log(f"  [DUP] {field} = {val!r} (중복: {vals_seen[val]!r}에서도 읽힘)")
            val = ""
        elif val:
            vals_seen[val] = field

        if not val:
            missing_fields.append(field)
            log(f"  [--] {field:<12} = ''")
        else:
            log(f"  [OK] {field:<12} = {val!r}")
        result[field] = val

    # 비고: TcxCustomInnerMemo 전용 읽기
    log(f"  --- 비고 읽기 (TcxCustomInnerMemo)")
    bigo_val, bigo_method, bigo_ctrl_found = read_bigo_from_inner_memo(detail_win)
    result["비고"] = bigo_val

    if bigo_val:
        log(f"  [OK] 비고           = {bigo_val[:50]!r}  (방식: {bigo_method})")
    elif bigo_ctrl_found:
        missing_fields.append("비고 빈값(내용 없음)")
        log(f"  [--] 비고  컨트롤 발견, 내용 빈값  (방식: {bigo_method})")
    else:
        missing_fields.append("비고 컨트롤 미발견")
        log(f"  [--] 비고  컨트롤 미발견")

    log(f"  missing_fields에서 '비고' 제거됨: {bigo_val != ''}")

    result["_missing"] = missing_fields
    return result


_DETAIL_OUTPUT_ORDER = [
    "접수일자", "의뢰일자", "처리기한", "은행",
    "감정서번호", "의뢰번호", "영업점", "담당자",
    "담당자 연락처", "채무자", "소유자", "안심번호", "비고",
]

# ══════════════════════════════════════════════════════════════════════════════
# 상단 그리드 읽기 + 내부 검증
# ══════════════════════════════════════════════════════════════════════════════
_TOP_GRID_REQUIRED_COLS = {"의뢰번호", "감정서번호"}
_TOP_GRID_FIELD_MAP = {
    "채무자": "채무자",
    "소유자": "소유자",
    "영업점": "영업점",
    "담당자": "담당자",
}


def _map_top_grid_col(ncol, all_norm_headers):
    """상단 그리드 norm_col → 출력 필드명. None이면 skip."""
    if ncol in _TOP_GRID_FIELD_MAP:
        return _TOP_GRID_FIELD_MAP[ncol]
    if "Memo" in ncol or "memo" in ncol:
        return None
    if "안심번호" in ncol:
        return "소유자 연락처"
    if "연락처" in ncol:
        tel_cols = [h for h in all_norm_headers
                    if "연락처" in h and "Memo" not in h
                    and "memo" not in h and "안심번호" not in h]
        if tel_cols and ncol == tel_cols[-1]:
            return "담당자 연락처"
    return None


def read_top_grid_from_detail(detail_win):
    """TBnkTop24Rcp 내 상단 그리드(의뢰정보 그리드) 한 행 읽기.
    반환: ({norm_col: value, ...}, raw_str_500). 미발견 시 ({}, "").
    """
    try:
        app32 = Application(backend="win32").connect(handle=detail_win.handle)
        win32 = app32.top_window()
        descs = win32.descendants()
    except Exception as e:
        log(f"  [ERROR] 상단 그리드 연결 실패: {e}")
        return {}, ""

    grids = [c for c in descs if safe_cls(c) in GRID_CLS]
    log(f"  상단 그리드 탐색: {len(grids)}개 그리드")

    for g in grids:
        g_cls  = safe_cls(g)
        g_rect = safe_rect(g)
        log(f"  [시도] class={g_cls!r}  rect={g_rect}")
        try:
            g.click_input(); time.sleep(0.3)
            send_keys("^{HOME}"); time.sleep(0.15)
            pyperclip.copy("")
            send_keys("^c"); time.sleep(0.45)
            raw = clip_read()
            if not raw or "\t" not in raw:
                log(f"    → Ctrl+C 결과 없음 또는 탭 없음: {raw[:80]!r}")
                continue
            log(f"    → raw[:300]: {raw[:300]!r}")
            raw_lines = [l for l in raw.splitlines() if "\t" in l and l.strip()]
            log(f"    → splitlines(탭 포함): {len(raw_lines)}")

            headers  = None
            data_row = None

            for line in raw_lines:
                cols = [c.strip() for c in line.split("\t")]
                ncols_set = {_norm_col(c) for c in cols}
                if ncols_set & _TOP_GRID_REQUIRED_COLS:
                    headers = [_norm_col(c) for c in cols]
                elif headers is not None:
                    data_row = cols
                    break

            log(f"    → 헤더 발견: {headers is not None}  데이터행 발견: {data_row is not None}")

            if headers is None:
                continue

            if data_row is None:
                send_keys("{DOWN}"); time.sleep(0.2)
                pyperclip.copy("")
                send_keys("^c"); time.sleep(0.45)
                raw2 = clip_read()
                if raw2 and "\t" in raw2:
                    for l2 in [l2 for l2 in raw2.splitlines() if "\t" in l2 and l2.strip()]:
                        cols2 = [c.strip() for c in l2.split("\t")]
                        if not ({_norm_col(c) for c in cols2} & _TOP_GRID_REQUIRED_COLS):
                            data_row = cols2
                            break

            if data_row is None:
                log(f"  헤더만 발견 (데이터 없음): {headers}")
                continue

            padded = data_row + [""] * max(0, len(headers) - len(data_row))
            result = dict(zip(headers, padded))
            log(f"  상단 그리드 OK: {list(result.items())[:4]}...")
            return result, raw[:500]

        except Exception as e:
            log(f"  그리드 시도 오류: {e}")

    log("  상단 그리드 미발견 (의뢰번호/감정서번호 컬럼 없음)")
    return {}, ""


# PDF 기반 추출 전환 후 미사용 — 함수 정의는 참고용으로 보존
def verify_detail_and_extract(detail_win, target_row):
    """상단 그리드 의뢰번호/감정서번호 검증 + 채무자/소유자/영업점/담당자/담당자 연락처 추출.
    반환: (verified: bool, fields: dict)
    """
    target_doc = target_row.get("의뢰번호",   "").strip()
    target_est = target_row.get("감정서번호", "").strip()

    top_raw, top_raw_text = read_top_grid_from_detail(detail_win)
    if not top_raw:
        return False, {}

    got_doc = top_raw.get("의뢰번호", "").strip()
    got_est = top_raw.get("감정서번호", "").strip()
    log(f"  [검증] 대상 doc={target_doc!r}  est={target_est!r}")
    log(f"  [검증] 창   doc={got_doc!r}  est={got_est!r}")

    verified = False
    if target_doc and got_doc and target_doc == got_doc:
        verified = True
        log("  [OK] 의뢰번호 일치")
    elif target_est and got_est and target_est == got_est:
        verified = True
        log("  [OK] 감정서번호 일치")
    else:
        log("  [FAIL] 의뢰번호/감정서번호 불일치")

    all_norm_headers = list(top_raw.keys())
    fields = {
        "상세창 의뢰번호":  got_doc,
        "상세창 감정서번호": got_est,
    }
    for ncol, val in top_raw.items():
        mapped = _map_top_grid_col(ncol, all_norm_headers)
        if mapped:
            fields[mapped] = val.strip()

    return verified, fields


_RESULT_OUTPUT_ORDER = [
    "처리상태", "실패사유",
    "접수일자", "의뢰일자", "처리기한", "은행",
    "감정서번호", "의뢰번호",
    "영업점", "담당자", "담당자 연락처",
    "채무자", "소유자", "소유자 연락처", "비고",
    "물건종류", "pdf_우편번호주소", "pdf_소재지", "pdf_path",
]
_SKIP_IF_EMPTY = {"실패사유"}


def save_result(items, counts):
    """신한은행 담보 추출 결과 저장 (검증 상태 포함)"""
    success_n = sum(1 for it in items if it.get("처리상태") == "성공")
    fail_n    = len(items) - success_n

    if success_n == 0 and fail_n == 0:
        log("처리 결과 없음 - 결과 파일 저장 생략")
        return None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fname = OUTPUT_DIR / f"bank24_dambo_{TS}.txt"

    lines = [
        "Bank24 신한은행 담보 종합접수 추출",
        f"추출일시: {TODAY.strftime('%Y-%m-%d %H:%M:%S')}",
        f"조회기간: {DATE_FROM} ~ {DATE_TO}",
        f"전체 데이터행 수: {counts['total']}",
        f"전체 담보 행 수: {counts['total_dambo']}",
        f"신한은행 전체 행 수: {counts['shinhan_all']}",
        f"신한은행 담보 행 수: {counts['shinhan_dambo']}",
        f"PDF 시도 수: {counts.get('pdf_tried', 0)}",
        f"PDF 저장 성공 수: {counts.get('pdf_success', 0)}",
        f"PDF 검증 성공 수: {counts.get('pdf_parse_success', 0)}",
        f"PDF 검증 실패 수: {counts.get('pdf_parse_fail', 0)}",
        f"성공: {success_n}건  실패: {fail_n}건",
        "=" * 64, "",
    ]

    for i, item in enumerate(items, 1):
        lines.append(f"===== ITEM {i} =====")
        for f in _RESULT_OUTPUT_ORDER:
            val = item.get(f, "")
            if f in _SKIP_IF_EMPTY and not val:
                continue
            lines.append(f"{f}: {val}")
        addrs = item.get("addresses", [])
        lines.append("주소목록:")
        for j, addr in enumerate(addrs, 1):
            lines.append(f"  {j}. {addr}")
        missing = item.get("_missing", [])
        if missing:
            lines.append(f"미읽힘 필드: {', '.join(missing)}")
        lines.append("")

    with open(fname, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log(f"저장: {fname}")
    log(f"크기: {fname.stat().st_size:,} bytes")
    return fname


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def _log_counts(counts):
    log(f"전체 데이터행 수:      {counts['total']}")
    log(f"전체 담보 행 수:       {counts['total_dambo']}")
    log(f"선택 은행 전체 행 수:  {counts.get('selected_bank_all', counts['shinhan_all'])}")
    log(f"선택 은행 담보 행 수:  {counts.get('selected_bank_dambo', counts['shinhan_dambo'])}")


def main():
    print("=" * 64)
    print("  Bank24 신한은행 담보 데이터 추출 — 운영")
    print(f"  조회기간: {DATE_FROM} ~ {DATE_TO}  (최근 3일)")
    print("  보안: ID/PW 출력 없음 / 절대 좌표 없음")
    print("=" * 64)

    uid, pwd = prompt_credentials()
    kill_existing()
    launch_and_login(uid, pwd)

    main_win = wait_main()
    if main_win is None:
        log("[ABORT] 메인 창 없음"); sys.exit(1)
    time.sleep(2)

    log("row scan 방식 사용 — 은행전체 조회 후 그리드 은행 컬럼으로 필터링")

    apply_filter(main_win)

    scan_items  = scan_main_grid(main_win)
    parsed_rows = parse_scan_results(scan_items)

    # ── 건수 집계 ──────────────────────────────────────────────────────────────
    total_dambo   = sum(1 for r in parsed_rows
                        if _norm_col(r.get("업무구분", "")) == "담보")
    shinhan_all   = sum(1 for r in parsed_rows
                        if _norm_col(r.get("은행", "")) == "신한은행")
    shinhan_rows  = filter_shinhan_dambo(parsed_rows)
    counts = {
        "total":         len(parsed_rows),
        "total_dambo":   total_dambo,
        "shinhan_all":   shinhan_all,
        "shinhan_dambo": len(shinhan_rows),
    }

    hdr("건수 집계")
    _log_counts(counts)

    if not shinhan_rows:
        log(f"최근 3일 조회 결과 신한은행 담보 건 없음")
        save_result([], counts)
        print(f"\n{'='*64}\n  추출 완료\n{'='*64}")
        return

    save_shinhan_grid(shinhan_rows, counts)

    MAX_DETAIL_OPEN = len(shinhan_rows)
    items  = []
    opened = 0
    counts.update({
        "detail_open_tried":   0,
        "detail_open_success": 0,
        "detail_verify_success": 0,
        "detail_verify_fail":  0,
    })

    for target_row in shinhan_rows:
        if opened >= MAX_DETAIL_OPEN:
            break

        doc_no = target_row.get("의뢰번호", "")
        est_no = target_row.get("감정서번호", "")
        log(f"\n--- 종합접수 열기: 의뢰번호={doc_no}  감정서번호={est_no}")

        nav_ok = navigate_and_verify(main_win, target_row)
        if not nav_ok:
            log("[SKIP] 위치 검증 실패 — 종합접수 미오픈")
            continue

        # 기존 상세창 닫기 → 스냅샷 → 신규 열기
        existing = _find_detail()
        if existing:
            existing.close(); time.sleep(0.8)
        before_handles = snapshot_detail_handles()
        counts["detail_open_tried"] += 1
        detail_win = open_detail_at_current(main_win, before_handles)
        if not detail_win:
            log("[SKIP] 종합접수 창 미발견 — 건너뜀")
            continue

        opened += 1
        counts["detail_open_success"] += 1
        hdr(f"Step 8-{opened}. 종합접수 검증 + 필드 읽기")

        verified, top_fields = verify_detail_and_extract(detail_win, target_row)

        if not verified:
            counts["detail_verify_fail"] += 1
            log("[FAIL] 상세창 내부 검증 실패 — 데이터 불일치")
            item = {
                "처리상태": "실패",
                "실패사유": "상세창 내부 검증 실패 (의뢰번호/감정서번호 불일치)",
                **top_fields,
                "비고": "",
                "addresses": [],
                "_missing": ["검증 실패"],
            }
        else:
            counts["detail_verify_success"] += 1
            log("[OK] 상세창 내부 검증 성공")
            bigo_val, bigo_method, bigo_ctrl_found = read_bigo_from_inner_memo(detail_win)
            missing = []
            if not bigo_val:
                missing.append("비고 빈값(내용 없음)" if bigo_ctrl_found else "비고 컨트롤 미발견")
            addrs = read_address_grid(detail_win)
            item = {
                "처리상태": "성공",
                **top_fields,
                "비고": bigo_val,
                "addresses": addrs,
                "_missing": missing,
            }

        # target_row 값으로 그리드 필드 보강 (성공/실패 공통)
        for fld in ("접수일자", "의뢰일자", "처리기한", "은행",
                    "의뢰번호", "감정서번호"):
            grid_val = target_row.get(fld, "").strip()
            if grid_val:
                item[fld] = grid_val

        items.append(item)
        close_detail(detail_win)
        time.sleep(0.5)

    save_result(items, counts)
    print(f"\n{'='*64}\n  추출 완료\n{'='*64}")


# ══════════════════════════════════════════════════════════════════════════════
# PDF 저장 자동화 (TfrxPreviewForm → Microsoft Print to PDF)
# ══════════════════════════════════════════════════════════════════════════════

def _pdf_snapshot_preview_handles():
    snap = set()
    try:
        for w in Desktop(backend="win32").windows():
            if safe_cls(w) == _PREVIEW_CLS:
                snap.add(w.handle)
    except Exception:
        pass
    return snap


def _snapshot_dialog_handles():
    """현재 Desktop의 #32770 클래스 창 hwnd set 반환. 오클릭 방지 스냅샷용."""
    snap = set()
    try:
        for w in Desktop(backend="win32").windows():
            if safe_cls(w) == "#32770":
                snap.add(w.handle)
    except Exception:
        pass
    return snap


def _pdf_find_new_preview(before_handles, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for w in Desktop(backend="win32").windows():
                if safe_cls(w) == _PREVIEW_CLS and w.handle not in before_handles:
                    elapsed = timeout - (deadline - time.time())
                    log(f"[PDF] 미리보기 창 발견 ({elapsed:.1f}초 후): {safe_txt(w)!r}")
                    return w
        except Exception:
            pass
        time.sleep(0.5)
    return None


def _pdf_find_save_dialog(timeout=8.0, before_handles=None):
    """OK 클릭 이후 새로 나타난 저장 다이얼로그만 반환.

    before_handles: OK 클릭 직전 #32770 hwnd 스냅샷. 기존 창은 제외.
    후보가 before_handles에 있으면 다른 프로그램의 창으로 간주하고 무시.
    """
    _before = before_handles if before_handles is not None else set()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for w in Desktop(backend="win32").windows():
                if safe_cls(w) != "#32770":
                    continue
                if w.handle in _before:
                    continue
                r = w.rectangle()
                if r.width() < 400 or r.height() < 200:
                    continue
                for ctrl in w.children():
                    if safe_cls(ctrl) == "Button" and "저장" in safe_txt(ctrl):
                        return w
        except Exception:
            pass
        time.sleep(0.3)
    return None


def _pdf_find_filename_edit(save_dlg):
    edits = []
    try:
        for ctrl in save_dlg.descendants():
            if safe_cls(ctrl) == "Edit":
                r = ctrl.rectangle()
                if r.width() > 100 and r.height() < 50:
                    edits.append((r.width(), ctrl))
    except Exception:
        pass
    if not edits:
        return None
    edits.sort(key=lambda x: x[0], reverse=True)
    return edits[0][1]


def _pdf_close_preview(preview_win=None, log=None):
    _log = log or (lambda m: None)
    if preview_win is None:
        try:
            wins = [w for w in Desktop(backend="win32").windows()
                    if safe_cls(w) == _PREVIEW_CLS]
            preview_win = wins[0] if wins else None
        except Exception:
            pass
    if not preview_win:
        return
    try:
        for ctrl in preview_win.descendants():
            t = safe_txt(ctrl).strip()
            if t in ("닫기", "&Close", "Close"):
                ctrl.click()
                time.sleep(0.5)
                return
    except Exception:
        pass
    try:
        if _ensure_foreground_window(preview_win, "미리보기 닫기", _log):
            pyautogui.hotkey("alt", "f4")
            time.sleep(0.5)
        else:
            _log("[FOCUS][WARN] 미리보기 닫기 foreground 실패")
    except Exception:
        pass


def _pdf_safe_filename(s):
    return re.sub(r'[\\/:*?"<>|]', '_', str(s or ""))


def _safe_pdf_name_part(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    value = re.sub(r"\s+", "_", value)
    return value.strip("._ ")


def save_pdf_for_row(main_win, target_row, pdf_path):
    """메인 그리드 포커스 행에서 APPS→C → Microsoft Print to PDF → 파일 저장.

    navigate_and_verify() 이후 grid.click_input() 재호출 없이 바로 사용.
    Returns True if PDF created successfully, False otherwise.
    """
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc_no = target_row.get("의뢰번호", "")
    est_no = target_row.get("감정서번호", "")
    log(f"[PDF] 의뢰서 PDF 생성 시작: {doc_no} / {est_no}")

    before_handles = _pdf_snapshot_preview_handles()

    # 메인창 전면화 후 APPS → C (그리드 포커스 유지 필수, 재클릭 금지)
    if not _ensure_foreground_window(main_win, "메인창-PDF APPS", log):
        log("[FOCUS][WARN] 메인창-PDF APPS foreground 실패")
        return False
    pyautogui.press("apps")
    time.sleep(1.2)
    if not _ensure_foreground_window(main_win, "메인창-PDF C", log):
        log("[FOCUS][WARN] 메인창-PDF C foreground 실패")
        return False
    pyautogui.press("c")
    time.sleep(3.0)

    preview_win = _pdf_find_new_preview(before_handles, timeout=15)
    if not preview_win:
        log("[PDF] TfrxPreviewForm 신규 창 미발견 — 실패")
        return False

    # Ctrl+P → TfrxPrintDialog
    try:
        preview_win.set_focus()
        time.sleep(0.3)
    except Exception:
        pass
    if not _ensure_foreground_window(preview_win, "미리보기-CtrlP", log):
        log("[FOCUS][WARN] 미리보기-CtrlP foreground 실패")
        _pdf_close_preview(preview_win, log)
        return False
    pyautogui.hotkey("ctrl", "p")

    print_dlg = None
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            wins = [w for w in Desktop(backend="win32").windows()
                    if safe_cls(w) == _PRINT_DLG_CLS]
            if wins:
                print_dlg = wins[0]
                break
        except Exception:
            pass
        time.sleep(0.3)
    if not print_dlg:
        log("[PDF] TfrxPrintDialog 미발견 — 실패")
        _pdf_close_preview(preview_win, log)
        return False

    # Microsoft Print to PDF 선택
    time.sleep(0.5)
    printer_ok = False
    try:
        for ctrl in print_dlg.descendants():
            cls = safe_cls(ctrl)
            if cls in ("TcxComboBox", "TComboBox", "ComboBox"):
                items = ctrl.item_texts() if hasattr(ctrl, "item_texts") else []
                idx = next((i for i, t in enumerate(items) if t.strip() == _PDF_PRINTER), None)
                if idx is None:
                    idx = next((i for i, t in enumerate(items)
                                if "MICROSOFT" in t.upper() and "PDF" in t.upper()), None)
                if idx is not None:
                    ctrl.select(idx)
                    log(f"[PDF] 프린터 선택: {items[idx]}")
                    printer_ok = True
                    time.sleep(0.3)
                    break
    except Exception as e:
        log(f"[PDF] 프린터 콤보 오류: {e}")

    if not printer_ok:
        log("[PDF] Microsoft Print to PDF 선택 실패 — 실패")
        try:
            for ctrl in print_dlg.descendants():
                if safe_cls(ctrl) == "TButton" and "취소" in safe_txt(ctrl):
                    ctrl.click_input(); break
        except Exception:
            pass
        _pdf_close_preview(preview_win, log)
        return False

    # OK 클릭
    ok_clicked = False
    before_32770 = _snapshot_dialog_handles()   # 저장창 식별용 스냅샷
    if not _ensure_foreground_window(print_dlg, "인쇄다이얼로그-OK", log):
        log("[FOCUS][WARN] 인쇄다이얼로그-OK foreground 실패")
        _pdf_close_preview(preview_win, log)
        return False
    try:
        for ctrl in print_dlg.descendants():
            if safe_cls(ctrl) == "TButton" and "OK" in safe_txt(ctrl):
                ctrl.click_input()
                ok_clicked = True
                log("[PDF] 인쇄 OK 클릭")
                break
    except Exception as e:
        log(f"[PDF] OK 버튼 오류: {e}")
    if not ok_clicked:
        log("[PDF] OK 버튼 미발견 — 실패")
        _pdf_close_preview(preview_win, log)
        return False

    # 저장 다이얼로그
    time.sleep(1.5)
    save_dlg = _pdf_find_save_dialog(timeout=8, before_handles=before_32770)
    if not save_dlg:
        log("[PDF] 저장 다이얼로그 미발견 — 실패")
        _pdf_close_preview(preview_win, log)
        return False

    # 파일명 입력 (3단계 fallback)
    output_path = str(pdf_path)
    save_dlg.set_focus()
    time.sleep(0.3)
    if not _ensure_foreground_window(save_dlg, "저장다이얼로그", log):
        log("[FOCUS][WARN] 저장다이얼로그 foreground 실패")
        return False
    edit_ctrl = _pdf_find_filename_edit(save_dlg)
    try:
        if edit_ctrl:
            # 1단계: _pdf_find_filename_edit 성공
            edit_ctrl.click_input()
            time.sleep(0.2)
            edit_ctrl.type_keys("^a", with_spaces=True)
            time.sleep(0.1)
            pyperclip.copy(output_path)
            if not _ensure_foreground_window(save_dlg, "저장-CtrlV 1단계", log):
                log("[FOCUS][WARN] 저장-CtrlV 1단계 foreground 실패")
                return False
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.4)
            try: pyperclip.copy("")
            except Exception: pass
        else:
            # 2단계: descendants()에서 Edit 탐색
            fb_edit = None
            try:
                candidates = []
                for c in save_dlg.descendants():
                    if safe_cls(c) == "Edit":
                        try:
                            if c.is_visible() and c.is_enabled():
                                _r = c.rectangle()
                                candidates.append((_r.top, _r.left, c))
                        except Exception:
                            pass
                if candidates:
                    candidates.sort(key=lambda x: (x[0], x[1]))
                    fb_edit = candidates[-1][2]
            except Exception:
                pass

            if fb_edit is not None:
                log("[PDF] 파일명 입력창 fallback(Edit 탐색) 사용")
                fb_edit.click_input()
                time.sleep(0.2)
                fb_edit.type_keys("^a", with_spaces=True)
                time.sleep(0.1)
                pyperclip.copy(output_path)
                if not _ensure_foreground_window(save_dlg, "저장-CtrlV 2단계", log):
                    log("[FOCUS][WARN] 저장-CtrlV 2단계 foreground 실패")
                    return False
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.4)
                try: pyperclip.copy("")
                except Exception: pass
            else:
                log("[PDF][WARN] 파일명 Edit 미발견 — 저장 실패 처리")
                return False
    except Exception as e:
        log(f"[PDF] 파일명 입력 오류: {e}")
    finally:
        try: pyperclip.copy("")
        except Exception: pass

    before_32770_enter = _snapshot_dialog_handles()   # 덮어쓰기 확인창 식별용 스냅샷
    if not _ensure_foreground_window(save_dlg, "저장-Enter", log):
        log("[FOCUS][WARN] 저장-Enter foreground 실패")
        return False
    pyautogui.press("enter")
    time.sleep(1.0)

    # 덮어쓰기 확인창 처리 — Enter 이후 새로 나타난 창만 대상
    # 기존 #32770 창(before_32770_enter)은 제외하고, 컨텍스트 검증 후에만 클릭
    _OW_CTX = frozenset(["이미 있습니다", "덮어쓰시겠습니까", "바꾸기", "Overwrite", "Replace", "파일 바꾸기", "충돌"])
    _OW_YES = frozenset(["예(&Y)", "예(Y)", "예", "Yes", "확인"])
    try:
        deadline_ow = time.time() + 2.0
        while time.time() < deadline_ow:
            found = False
            try:
                for w in Desktop(backend="win32").windows():
                    if safe_cls(w) != "#32770":
                        continue
                    if w.handle in before_32770_enter:
                        continue
                    r = w.rectangle()
                    if r.width() >= 500 or r.height() >= 200:
                        continue
                    ctx = safe_txt(w) + " " + " ".join(safe_txt(c) for c in w.children())
                    if not any(kw in ctx for kw in _OW_CTX):
                        log(f"[PDF] 확인창 컨텍스트 불일치 — 클릭 안 함: hwnd={w.handle:#010x}")
                        continue
                    for ctrl in w.children():
                        t = safe_txt(ctrl)
                        if any(k in t for k in _OW_YES):
                            ctrl.click_input()
                            log(f"[PDF] 덮어쓰기 확인 클릭: {t!r}")
                            time.sleep(0.3)
                            found = True
                            break
                    if found:
                        break
            except Exception:
                pass
            if found:
                break
            time.sleep(0.3)
    except Exception:
        pass

    # PDF 생성 polling (최대 20초)
    deadline = time.time() + 20
    while time.time() < deadline:
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            log(f"[PDF] 저장 완료: {output_path} ({os.path.getsize(output_path):,} bytes)")
            _pdf_close_preview(preview_win, log)
            return True
        time.sleep(0.5)

    log(f"[PDF] 생성 대기 시간 초과: {output_path}")
    _pdf_close_preview(preview_win, log)
    return False


def _save_pdf_with_retry(main_win, target_row, pdf_path,
                          log, max_attempts=2, wait_sec=2.0):
    """save_pdf_for_row()를 최대 max_attempts회 재시도."""
    _CLEANUP_CLS = {"TfrxPreviewForm", "TfrxPrintDialog", "#32770"}
    for attempt in range(1, max_attempts + 1):
        ok = save_pdf_for_row(main_win, target_row, pdf_path)
        if ok:
            return True
        if attempt < max_attempts:
            log(f"[PDF][RETRY] 시도 {attempt}/{max_attempts} 실패 — {wait_sec}초 후 재시도")
            # 열려 있는 관련 창 닫기
            try:
                for w in Desktop(backend="win32").windows():
                    cls = safe_cls(w)
                    if cls in _CLEANUP_CLS:
                        try:
                            try:
                                w.close()
                            except Exception:
                                if not _safe_send_keys(w, "%{F4}", "PDF창닫기", log):
                                    log(f"[FOCUS][WARN] PDF창닫기 Alt+F4 실패: {cls}")
                            time.sleep(0.5)
                        except Exception as _e:
                            log(f"[PDF][RETRY] 창 닫기 실패: {cls} / {type(_e).__name__}")
            except Exception as _e:
                log(f"[PDF][RETRY] 창 닫기 실패: Desktop / {type(_e).__name__}")
            # 기존 PDF 파일 삭제
            try:
                if os.path.exists(str(pdf_path)):
                    os.remove(str(pdf_path))
            except Exception as _e:
                log(f"[PDF][RETRY] 기존 PDF 삭제 실패: {pdf_path} / {type(_e).__name__}")
            time.sleep(wait_sec)
    log(f"[PDF][RETRY] {max_attempts}회 모두 실패")
    return False


def delete_inserted_pdfs(items: list, log) -> dict:
    """DB insert commit 성공 후 처리상태==성공 item의 PDF 파일 삭제.

    반환: {"tried": int, "deleted": int, "fail": int, "errors": list}
    """
    result = {"tried": 0, "deleted": 0, "fail": 0, "errors": []}
    for item in items:
        if item.get("처리상태") != "성공":
            continue
        pdf_path = item.get("pdf_path", "")
        if not pdf_path:
            continue
        result["tried"] += 1
        try:
            p = Path(pdf_path)
            if not p.exists():
                log(f"[PDF] 삭제 스킵(파일 없음): {pdf_path}")
                continue
            p.unlink()
            log(f"[PDF] DB insert 완료 → PDF 삭제: {pdf_path}")
            result["deleted"] += 1
        except Exception as e:
            log(f"[PDF] 삭제 실패: {pdf_path} / {type(e).__name__}")
            result["fail"] += 1
            result["errors"].append({"pdf_path": pdf_path, "error": str(e)})
    return result


def _has_db_address(item: dict) -> bool:
    if (item.get("pdf_소재지") or "").strip():
        return True
    if (item.get("소재지") or "").strip():
        return True
    if (item.get("pdf_우편번호주소") or "").strip():
        return True
    if item.get("addresses"):
        return True
    return False


def _is_db_insertable_item(item: dict) -> bool:
    if item.get("처리상태") != "성공":
        return False
    if (item.get("실패사유") or "").strip():
        return False
    if not _has_db_address(item):
        return False
    return True


def run_extraction(config: dict, callbacks: dict = None):
    'GUI 호출용 추출 진입점. 콘솔 main() 과 공존하며 input()/getpass() 호출 없음.\n\n    config keys:\n        bank24_id, REDACTED_CONFIGURE_LOCALLY, date_from, date_to, banks,\n        output_dir, save_txt, db_insert, restart\n    callbacks keys:\n        on_log(str), on_step(name, state), on_summary(dict),\n        on_item(dict), should_stop() -> bool\n    '
    global DATE_FROM, DATE_TO, OUTPUT_DIR, TS, _log_callback

    if callbacks is None:
        callbacks = {}

    _log_callback  = callbacks.get("on_log")
    on_step        = callbacks.get("on_step",    lambda n, s: None)
    on_summary     = callbacks.get("on_summary", lambda d: None)
    on_item        = callbacks.get("on_item",    lambda it: None)
    should_stop    = callbacks.get("should_stop", lambda: False)

    # 날짜 결정 — date_mode에 따라 당일 자동 또는 직접 지정
    _DATE_RE  = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    date_mode = config.get("date_mode", "today")
    if date_mode == "manual":
        _df = config.get("date_from", "")
        _dt = config.get("date_to",   "")
        if _df and _dt and _DATE_RE.match(_df) and _DATE_RE.match(_dt):
            if _df > _dt:
                log(f"[WARN] 조회 시작일이 종료일보다 늦어 날짜를 교환했습니다.")
                _df, _dt = _dt, _df
            DATE_FROM = _df
            DATE_TO   = _dt
        else:
            _today = datetime.now().strftime("%Y-%m-%d")
            DATE_FROM = _today
            DATE_TO   = _today
            if _df or _dt:
                log(f"[WARN] 날짜 형식 오류 (date_from={_df!r}, date_to={_dt!r}) — 오늘 날짜로 대체: {_today}")
    else:
        _today = datetime.now().strftime("%Y-%m-%d")
        DATE_FROM = _today
        DATE_TO   = _today

    OUTPUT_DIR = Path(config.get("output_dir", str(OUTPUT_DIR)))
    TS         = datetime.now().strftime("%Y%m%d_%H%M%S")

    uid = config["bank24_id"]
    pwd = config['REDACTED_CONFIGURE_LOCALLY']
    selected_banks = config.get("banks") or [config.get("bank", "신한은행")]
    if isinstance(selected_banks, str):
        selected_banks = [b.strip() for b in selected_banks.split(",") if b.strip()]
    if not selected_banks:
        selected_banks = ["신한은행"]

    current_step = None

    def set_step(name: str, state: str):
        nonlocal current_step
        current_step = name
        on_step(name, state)

    try:
        # ── 로그인 ──────────────────────────────────────────────────
        set_step("로그인", "running")
        log("Bank24 인증정보: 입력 확인")
        if date_mode == "manual":
            log(f"날짜 범위: {DATE_FROM} ~ {DATE_TO} (직접 지정)")
        else:
            log(f"날짜 범위: {DATE_FROM} ~ {DATE_TO} (당일 자동)")
        log(f"선택 은행: {', '.join(selected_banks)}")

        if config.get("restart", True):
            kill_existing()
            launch_and_login(uid, pwd)
        else:
            _existing_main = None
            try:
                for _w in Desktop(backend="win32").windows():
                    if safe_cls(_w) == MAIN_CLS and any(
                            h in safe_txt(_w) for h in _BANK24_TITLE_HINTS):
                        _existing_main = _w
                        break
            except Exception:
                pass
            if _existing_main is None:
                log("실행 중인 Bank24 미발견 — 새로 실행")
                launch_and_login(uid, pwd)
            else:
                log("기존 Bank24 메인 창 재사용")
                force_foreground(_existing_main.handle, "기존 메인창")
                time.sleep(1)

        if should_stop():
            set_step("로그인", "stopped"); return

        main_win = wait_main()
        if main_win is None:
            set_step("로그인", "error")
            raise RuntimeError("메인 창을 찾을 수 없습니다.")
        time.sleep(2)
        set_step("로그인", "done")

        # ── 대상 탭 선택 ─────────────────────────────────────────────
        source_tab = config.get("source_tab", "작성")
        if not select_bank24_source_tab(main_win, source_tab):
            log(f"[탭][WARN] 대상 탭 선택 실패 — 현재 탭 상태로 계속 진행: {source_tab!r}")

        # ── 조회 ────────────────────────────────────────────────────
        set_step("조회", "running")
        if should_stop(): set_step("조회", "stopped"); return
        apply_filter(main_win)
        set_step("조회", "done")

        # ── 그리드 추출 ─────────────────────────────────────────────
        set_step("그리드 추출", "running")
        if should_stop(): set_step("그리드 추출", "stopped"); return

        scan_items  = scan_main_grid(main_win)
        parsed_rows = parse_scan_results(scan_items)

        total_dambo  = sum(1 for r in parsed_rows
                          if _norm_col(r.get("업무구분", "")) == "담보")
        all_banks = "전체" in selected_banks
        bank_set = {_norm_col(b) for b in selected_banks if b and b != "전체"}
        selected_all = (
            len(parsed_rows) if all_banks else
            sum(1 for r in parsed_rows if _norm_col(r.get("은행", "")) in bank_set)
        )

        dambo_rows = [
            row for row in parsed_rows
            if _norm_col(row.get("업무구분", "")) == _norm_col("담보")
        ]
        unsupported_count = sum(
            1 for row in dambo_rows
            if not _is_supported_bank(row.get("은행", ""))
        )

        shinhan_rows = filter_shinhan_dambo(parsed_rows, selected_banks)
        counts = {
            "total":                    len(parsed_rows),
            "total_dambo":              total_dambo,
            "shinhan_all":              selected_all,
            "shinhan_dambo":            len(shinhan_rows),
            "selected_bank_all":        selected_all,
            "selected_bank_dambo":      len(shinhan_rows),
            "unsupported_bank_skipped": unsupported_count,
        }
        _log_counts(counts)
        set_step("그리드 추출", "done")

        if not shinhan_rows:
            log("[지원은행] 처리 대상 0건 - PDF/파싱/DB 저장 생략")
            set_step("저장", "running")
            fname = save_result([], counts)
            on_summary({"counts": counts, "file": str(fname) if fname else "", "items": [],
                        "db": {"enabled": False}})
            set_step("저장", "done")
            return

        save_shinhan_grid(shinhan_rows, counts)

        prefilter_duplicate_count = 0
        prefilter_duplicate_docids = []

        if (
            config.get("db_insert", False)
            and source_tab.strip().replace(" ", "") == "미접수"
        ):
            from db_writer import (
                normalize_cust_docid,
                find_existing_cust_docids,
            )
            db_config = config.get("database", {})
            docids = [
                normalize_cust_docid(row.get("의뢰번호", ""))
                for row in shinhan_rows
            ]
            dup_result = find_existing_cust_docids(
                db_config,
                docids,
                log=log,
            )
            if dup_result["ok"]:
                filtered_rows = []
                for row in shinhan_rows:
                    docid = normalize_cust_docid(row.get("의뢰번호", ""))
                    if docid and docid in dup_result["existing"]:
                        prefilter_duplicate_count += 1
                        prefilter_duplicate_docids.append(docid)
                        log(
                            f"[DB][DUP-SKIP] 의뢰번호={docid} "
                            "이미 저장됨 — PDF 추출 생략"
                        )
                        continue
                    filtered_rows.append(row)
                shinhan_rows = filtered_rows
            else:
                log(
                    "[DB][DUP-CHECK][WARN] 사전 중복 확인 실패 "
                    "— 최종 INSERT 직전 재확인"
                )
            counts["db_duplicate_skipped"] = prefilter_duplicate_count
            counts["db_new_targets"] = len(shinhan_rows)
            log(
                f"[DB][DUP-CHECK] 기존 저장={prefilter_duplicate_count}건 "
                f"/ 신규 대상={len(shinhan_rows)}건"
            )

        if not shinhan_rows:
            log("[DB][DUP-CHECK] 신규 대상 0건 — 상세 추출 및 DB INSERT 생략")
            set_step("저장", "running")
            fname = save_result([], counts)
            db_result = {
                "enabled": True,
                "tried": 0,
                "success": 0,
                "fail": 0,
                "duplicate_skipped": prefilter_duplicate_count,
                "errors": [],
            }
            on_summary({"counts": counts, "file": str(fname) if fname else "", "items": [], "db": db_result})
            set_step("저장", "done")
            return

        # ── 상세 추출 (PDF 기반) ────────────────────────────────────────────────────
        set_step("상세 추출", "running")
        MAX_DETAIL_OPEN = len(shinhan_rows)
        items  = []
        opened = 0
        counts.update({
            "pdf_tried": 0, "pdf_success": 0,
            "pdf_parse_success": 0, "pdf_parse_fail": 0,
            "detail_open_tried": 0, "detail_open_success": 0,
            "detail_verify_success": 0, "detail_verify_fail": 0,
        })
        pdf_dir = Path(config.get("pdf_dir", str(PDF_DIR)))
        pdf_dir.mkdir(parents=True, exist_ok=True)

        # ── 자동 인쇄 매니저 (불변 스냅샷 기반, 완전 격리) ──────────────────
        # 인쇄는 비필수 후처리다. 초기화/조회/인쇄 실패는 저장·파싱·검증·DB 및 다음
        # 문서 처리에 영향을 주지 않는다. 허용 디렉터리는 이번 실행의 pdf_dir로 고정.
        _pm = None
        _print_mgr = None
        _print_snap = config.get("auto_print") or {}
        if _print_snap.get("enabled"):
            try:
                import print_manager as _pm
                _print_mgr = _pm.PrintManager(
                    enabled=True,
                    printer_name=_print_snap.get("printer", ""),
                    allowed_dir=str(pdf_dir),
                    max_jobs_per_run=_print_snap.get(
                        "max_jobs_per_run", _pm.DEFAULT_MAX_JOBS_PER_RUN),
                )
                log("[인쇄] 자동 인쇄 활성 — 저장·검증 성공 건당 1부")
            except Exception:
                _print_mgr = None  # 초기화 실패도 전체 작업 실패로 처리하지 않음

        for target_row in shinhan_rows:
            if opened >= MAX_DETAIL_OPEN:
                break
            if should_stop():
                set_step("상세 추출", "stopped"); return

            doc_no = target_row.get("의뢰번호", "")
            est_no = target_row.get("감정서번호", "")
            log(f"\n--- PDF 추출: 의뢰번호={doc_no}  감정서번호={est_no}")

            nav_ok = navigate_and_verify(main_win, target_row)
            if not nav_ok:
                log("[SKIP] 위치 검증 실패 — 건너뜀"); continue

            opened += 1
            counts["pdf_tried"] += 1

            # PDF 파일 경로
            req_no = (
                (doc_no or "").strip()
                or (target_row.get("의뢰번호") or "").strip()
                or (target_row.get("상세창 의뢰번호") or "").strip()
            )
            safe_req = _safe_pdf_name_part(req_no)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if safe_req:
                pdf_name = f"{safe_req}_{timestamp}.pdf"
            else:
                pdf_name = f"NOREQ_{timestamp}.pdf"
            pdf_path = pdf_dir / pdf_name
            log(f"[PDF] 저장 파일명: {pdf_name}")

            # PDF 저장
            pdf_ok = _save_pdf_with_retry(main_win, target_row, pdf_path, log)
            if not pdf_ok:
                log(f"[PDF] 저장 실패: {doc_no}/{est_no}")
                item = {
                    "처리상태": "실패", "실패사유": "PDF 저장 실패",
                    "의뢰번호": doc_no, "감정서번호": est_no,
                    "상세창 의뢰번호": doc_no, "상세창 감정서번호": est_no,
                    "addresses": [], "pdf_path": "",
                }
                for fld in ("접수일자", "의뢰일자", "처리기한", "은행"):
                    gv = (target_row.get(fld) or "").strip()
                    if gv: item[fld] = gv
                items.append(item); on_item(item); continue

            counts["pdf_success"] += 1

            # PDF 파싱
            try:
                from pdf_parser import parse_bank24_pdf
                parsed = parse_bank24_pdf(str(pdf_path))
                if not isinstance(parsed, dict):
                    raise RuntimeError(f"PDF parser returned non-dict: {type(parsed).__name__}")
                parsed["pdf_path"] = str(pdf_path)
            except Exception as _pdf_exc:
                import traceback as _tb2
                log(f"[PDF] 파싱 오류: {type(_pdf_exc).__name__}: {_pdf_exc}")
                log(_tb2.format_exc())
                item = {
                    "처리상태": "실패",
                    "실패사유": f"PDF 파싱 오류: {type(_pdf_exc).__name__}",
                    "의뢰번호": doc_no, "감정서번호": est_no,
                    "상세창 의뢰번호": doc_no, "상세창 감정서번호": est_no,
                    "addresses": [], "pdf_path": str(pdf_path),
                }
                for fld in ("접수일자", "의뢰일자", "처리기한", "은행"):
                    gv = (target_row.get(fld) or "").strip()
                    if gv: item[fld] = gv
                items.append(item); on_item(item); continue

            log(f"[PDF] 파싱 완료: 우편번호주소={parsed.get('pdf_우편번호주소','')} / 소재지={parsed.get('pdf_소재지','')}")

            # 검증
            pdf_doc, pdf_est = _normalize_pdf_identity_for_grid(
                parsed, target_row, doc_no, est_no,
            )
            verified = (
                (doc_no and pdf_doc and doc_no == pdf_doc) or
                (est_no and pdf_est and est_no == pdf_est)
            )

            parser_status = (parsed.get("처리상태") or "").strip()
            parser_reason = (parsed.get("실패사유") or "").strip()
            parser_failed = (parser_status == "실패") or bool(parser_reason)

            if parser_failed:
                counts["pdf_parse_fail"] += 1
                parsed["처리상태"] = "실패"
                if not parser_reason:
                    parsed["실패사유"] = "PDF 파서 실패"
                    parser_reason = parsed["실패사유"]
                log(f"[PDF] 파서 실패: {parser_reason}")

            elif verified:
                counts["pdf_parse_success"] += 1
                log("[PDF] 검증 성공")
                parsed["처리상태"] = "성공"
                parsed["실패사유"] = ""

            else:
                counts["pdf_parse_fail"] += 1
                log(f"[PDF] 검증 실패: grid={doc_no}/{est_no}  pdf={pdf_doc}/{pdf_est}")
                parsed["처리상태"] = "실패"
                parsed["실패사유"] = f"PDF 검증 실패 (grid={doc_no}, pdf={pdf_doc})"

            # 그리드 값으로 보강 (날짜, 은행 등 PDF에 없을 수 있음)
            for fld in ("접수일자", "의뢰일자", "처리기한", "은행", "의뢰번호", "감정서번호"):
                gv = (target_row.get(fld) or "").strip()
                if gv and not parsed.get(fld):
                    parsed[fld] = gv
            # 영업점 fallback: PDF에서 못 찾으면 그리드 의뢰영업점 사용
            if not parsed.get("영업점"):
                gv = (target_row.get("의뢰영업점") or "").strip()
                if gv:
                    parsed["영업점"] = gv

            # ── 자동 인쇄 (저장·파싱·검증 성공 건만, 완전 격리) ──────────────
            # PDF 저장 재시도와 무관하게 문서당 최대 1회만 인쇄 요청한다(매니저가 경로
            # 기준 중복을 차단). 인쇄 상태는 PDF/파싱/DB 상태와 분리해 기록한다.
            if _print_mgr is not None and parsed.get("처리상태") == "성공":
                try:
                    _pr = _print_mgr.print_document(str(pdf_path))
                    parsed["인쇄상태"] = _pr.status
                    parsed["인쇄코드"] = _pr.code  # 비식별 코드
                    log(f"[인쇄] 결과={_pr.status} 코드={_pr.code}")
                except Exception:
                    # print_document는 예외를 전파하지 않지만 이중 안전장치로 격리.
                    parsed["인쇄상태"] = "인쇄 실패"
                    parsed["인쇄코드"] = "INTERNAL_ERROR"

            items.append(parsed)
            on_item(parsed)
            time.sleep(0.5)

        set_step("상세 추출", "done")

        # ── 저장 ────────────────────────────────────────────────────
        if should_stop(): set_step("저장", "stopped"); return
        set_step("저장", "running")

        fname = save_result(items, counts)

        db_result = {"enabled": False, "tried": 0, "success": 0, "fail": 0,
                     "duplicate_skipped": 0, "errors": [], "rollback_test": False}
        if config.get("db_insert", False):
            db_cfg = config.get("database", {})
            try:
                from db_writer import insert_apw_master_expand

                # DB insert 대상 필터링
                db_items   = []
                skip_items = []
                for _it in items:
                    if _is_db_insertable_item(_it):
                        db_items.append(_it)
                    else:
                        _reason = (_it.get("실패사유") or "").strip()
                        if not _reason and not _has_db_address(_it):
                            _reason = "소재지 없음"
                        if not _reason:
                            _reason = "DB 저장 제외 대상"
                        skip_items.append(_it)
                        log(f"[DB][SKIP] 의뢰번호={_it.get('의뢰번호','')} 사유={_reason}")

                log(f"[DB] insert 대상={len(db_items)}, skip={len(skip_items)}")

                if not db_items:
                    log("[DB] insert 대상 0건 — DB insert 생략")
                    db_result = {"enabled": True, "tried": 0, "success": 0, "fail": 0,
                                 "duplicate_skipped": prefilter_duplicate_count,
                                 "errors": [], "rollback_test": False}
                else:
                    rollback_flag = db_cfg.get("rollback_test", False)
                    db_result = insert_apw_master_expand(
                        db_items,
                        db_cfg,
                        log=log,
                        rollback_test=rollback_flag,
                    )
                    db_result["duplicate_skipped"] = (
                        db_result.get("duplicate_skipped", 0)
                        + prefilter_duplicate_count
                    )
                log(f"SP insert: 시도={db_result['tried']} 성공={db_result['success']} 실패={db_result['fail']} 중복SKIP={db_result.get('duplicate_skipped', 0)}")
                for err in db_result.get("errors", []):
                    if err.get("의뢰번호"):
                        log(f"  SP 실패: {err['의뢰번호']} → {err.get('error','')}")
            except Exception as _db_exc:
                import traceback as _tb
                log(f"SP insert 오류: {type(_db_exc).__name__}: {_db_exc}")
                log(_tb.format_exc())
                db_result = {"enabled": True, "tried": 0, "success": 0, "fail": 0,
                             "duplicate_skipped": prefilter_duplicate_count,
                             "errors": [{"error": f"{type(_db_exc).__name__}"}],
                             "rollback_test": False}

        if _has_bankonline_caller(config):
            if _bankonline_auto_send_enabled(config):
                bankonline_result = _apply_bankonline_updates(db_result, items, config)
                db_result["bankonline"] = bankonline_result
            else:
                # auto_send=false: DB 저장까지만. 전송은 GUI 'API 전송' 버튼에서
                # 감정서번호를 재조회해 수행한다(감정서번호 사후 변경 대응).
                deferred_outputs = db_result.get("outputs") or []
                for output in deferred_outputs:
                    output["BankOnline_In"] = "대기"
                    output["BankOnline_ErrorType"] = "AUTO_SEND_OFF"
                if deferred_outputs:
                    log(f"[BankOnline] 자동 전송 꺼짐 — 'API 전송' 버튼으로 수기 전송 ({len(deferred_outputs)}건 대기)")
                db_result["bankonline"] = {"enabled": False, "deferred": len(deferred_outputs)}

        if KEEP_PDF_HISTORY:
            log("[PDF] 이력 보존 설정: PDF 삭제 단계 건너뜀")
        elif (
            db_result.get("enabled")
            and db_result.get("tried", 0) > 0
            and db_result.get("success") == db_result.get("tried")
            and db_result.get("fail") == 0
            and not db_result.get("rollback_test", False)
        ):
            pdf_del = delete_inserted_pdfs(items, log)
            log(f"PDF 삭제: 시도={pdf_del['tried']} 완료={pdf_del['deleted']} 실패={pdf_del['fail']}")

        # 인쇄 요약 (성공·건너뜀·실패·확인필요 건수만; DB 실패 집계와 무관)
        print_summary = {"enabled": _print_mgr is not None}
        if _print_mgr is not None:
            print_summary.update(_print_mgr.counts)

        on_summary({"counts": counts, "file": str(fname) if fname else "", "items": items,
                    "db": db_result, "print": print_summary})
        set_step("저장", "done")

    except Exception as exc:
        import traceback as _tb
        log(f"[ERROR] {exc}")
        log(_tb.format_exc())
        if current_step:
            on_step(current_step, "error")
        raise
    finally:
        _log_callback = None


if __name__ == "__main__":
    main()
