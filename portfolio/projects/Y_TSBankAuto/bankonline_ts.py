# -*- coding: utf-8 -*-
"""Y_TSBankAuto BankOnline update call.

DB 저장 성공 후 받은 NewMasterID를 REST_BANK_JUBSU_UPD.GAM_NO로 전달한다.
Secrets/PII are never logged by this module.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request


def _log(logger, message: str) -> None:
    if callable(logger):
        logger(f"BankOnline 진단: {message}")


def _norm(value) -> str:
    return "".join(str(value or "").split())


def normalize_docid(value) -> str:
    return str(value or "").strip()


def _mask_docid(value: str) -> str:
    v = str(value or "")
    if len(v) <= 4:
        return "*" * len(v)
    return "*" * (len(v) - 4) + v[-4:]


def _endpoint_summary(endpoint: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(str(endpoint or ""))
    except Exception:
        return "invalid"
    host = parsed.netloc or ""
    path = parsed.path or ""
    return f"{parsed.scheme}://{host}{path}" if parsed.scheme or host or path else "empty"


def _response_preview(raw: bytes, limit: int = 120) -> str:
    text = (raw or b"").decode("utf-8-sig", "replace")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\d{5,}", lambda m: "*" * (len(m.group(0)) - 4) + m.group(0)[-4:], text)
    if len(text) > limit:
        text = text[:limit] + "..."
    return text or "<empty>"


def canonical_bank(bank_name: str) -> str:
    bank = _norm(bank_name)
    if not bank:
        return ""
    if "국민" in bank or bank.startswith("KB"):
        return "국민은행"
    if "신한" in bank:
        return "신한은행"
    if "기업" in bank or bank.startswith("IBK"):
        return "기업은행"
    if "우리" in bank:
        return "우리은행"
    if "하나" in bank:
        return "하나은행"
    if "아이엠" in bank or "IM뱅크" in bank.upper() or "IM은행" in bank.upper() or "DGB" in bank.upper():
        return "아이엠뱅크"
    if "농협중앙" in bank:
        return "농협중앙회"
    if "농협" in bank or bank.startswith("NH"):
        return "농협은행"
    if "수협" in bank:
        return "수협은행"
    if "새마을금고" in bank:
        return "새마을금고"
    if bank == "HUG" or "주택도시보증공사" == bank:
        return "주택도시보증공사"
    return ""


CUSTKEY = {
    "국민은행": "KBB",
    "신한은행": "SHG",
    "기업은행": "KIB",
    "하나은행": "HNB",
    "아이엠뱅크": "DGB",
    "농협은행": "NHB",
    "농협중앙회": "NHB",
    "우리은행": "WRB",
    "수협은행": "SSB",
    "새마을금고": "MGB",
    "주택도시보증공사": "HUG",
}


def payload_block_reasons(output: dict, app) -> list[str]:
    bo = getattr(app, "bankonline", None)
    login = getattr(app, "login", None)
    dambo_no = normalize_docid(
        output.get("RequestNo") or output.get("DAMBO_NO") or output.get("request_no")
    )
    gam_no = str(output.get("NewMasterID") or "").strip()
    bank = canonical_bank(output.get("Bank") or output.get("CustName") or "")
    custkey = CUSTKEY.get(bank, "")
    uid = str(getattr(login, "bank24_id", "") or "").strip()
    pwd = str(getattr(login, 'REDACTED_CONFIGURE_LOCALLY', "") or "")
    appcode = str(getattr(app, "app_code", "300611") or "300611").strip()
    reasons = []
    if not bo:
        reasons.append("CONFIG_MISSING")
    if len(custkey) != 3:
        reasons.append("CUSTKEY_UNRESOLVED")
    if not dambo_no:
        reasons.append("DAMBO_NO_MISSING")
    elif len(dambo_no) > 20:
        reasons.append("DAMBO_NO_TOO_LONG")
    if not gam_no:
        reasons.append("GAM_NO_MISSING")
    elif len(gam_no) > 20:
        reasons.append("GAM_NO_TOO_LONG")
    if not appcode:
        reasons.append("APPCODE_MISSING")
    if not uid:
        reasons.append("UID_MISSING")
    elif len(uid) > 24:
        reasons.append("UID_TOO_LONG")
    if not pwd:
        reasons.append("PWD_MISSING")
    elif len(pwd) > 24:
        reasons.append("PWD_TOO_LONG")
    return reasons


def enabled(app) -> bool:
    bo = getattr(app, "bankonline", None)
    return bool(
        bo
        and getattr(bo, "enabled", False)
        and str(getattr(bo, "endpoint", "") or "").strip()
    )


def build_payload(output: dict, app) -> dict:
    """Build TS BankOnline payload. Returns {} when required data is missing."""
    bo = getattr(app, "bankonline", None)
    login = getattr(app, "login", None)
    dambo_no = normalize_docid(
        output.get("RequestNo") or output.get("DAMBO_NO") or output.get("request_no")
    )
    gam_no = str(output.get("NewMasterID") or "").strip()
    bank = canonical_bank(output.get("Bank") or output.get("CustName") or "")
    custkey = CUSTKEY.get(bank, "")
    uid = str(getattr(login, "bank24_id", "") or "").strip()
    pwd = str(getattr(login, 'REDACTED_CONFIGURE_LOCALLY', "") or "")
    appcode = str(getattr(app, "app_code", "300611") or "300611").strip()
    if payload_block_reasons(output, app):
        return {}
    return {
        "Procedure": "REST_BANK_JUBSU_UPD",
        "CUSTKEY": custkey,
        "UPMU_GUBUN": "2",
        "DAMBO_NO": dambo_no,
        "GAM_NO": gam_no,
        "APPCODE": appcode,
        "UID": uid,
        "PWD": pwd,
    }


def call_rest(payload: dict, app, logger=None) -> bool:
    bo = getattr(app, "bankonline", None)
    endpoint = str(getattr(bo, "endpoint", "") or "").strip()
    _log(logger, f"HTTP 준비 endpoint={_endpoint_summary(endpoint)} method={getattr(bo, 'method', '')}")
    auth = resolve_authorization(app)
    _log(logger, f"Authorization 준비 완료 len={len(auth)}")
    parsed = urllib.parse.urlsplit(endpoint)
    schemes = ("http", "https") if getattr(bo, "allow_http", False) else ("https",)
    if parsed.scheme not in schemes or not parsed.netloc:
        raise ValueError("BANKONLINE_ENDPOINT_NOT_ALLOWED")
    method = str(getattr(bo, "method", "POST") or "POST").strip().upper()
    if method not in ("POST", "PUT", "PATCH"):
        raise ValueError("BANKONLINE_METHOD_NOT_ALLOWED")
    request_format = str(getattr(bo, "request_format", "json") or "json").strip().lower()
    if request_format == "json":
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        content_type = "application/json; charset=utf-8"
    elif request_format == "form":
        body = urllib.parse.urlencode(payload).encode("utf-8")
        content_type = "application/x-www-form-urlencoded; charset=utf-8"
    else:
        raise ValueError("BANKONLINE_REQUEST_FORMAT_NOT_ALLOWED")
    timeout = min(max(float(getattr(bo, "timeout_seconds", 10.0) or 10.0), 1.0), 60.0)
    _log(logger, f"HTTP 전송 format={request_format} bytes={len(body)} timeout={timeout:g}s")
    req = urllib.request.Request(
        endpoint,
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": content_type,
            "Authorization": auth,
            "User-Agent": "Y_TSBankAuto/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("BANKONLINE_RESPONSE_TOO_LARGE")
        status = int(getattr(resp, "status", 0) or resp.getcode() or 0)
    _log(logger, f"HTTP 응답 status={status} bytes={len(raw)}")
    if not 200 <= status < 300:
        return False
    text = (raw or b"").decode("utf-8-sig", "replace").strip()
    if text.lower() == "procedure success":
        _log(logger, "응답 텍스트 성공 Procedure Success")
        return True
    try:
        decoded = json.loads(raw.decode("utf-8-sig")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _log(logger, f"응답 JSON 파싱 실패 code={type(exc).__name__} preview={_response_preview(raw)}")
        return False
    if not isinstance(decoded, dict):
        _log(logger, f"응답 JSON 타입 불일치 type={type(decoded).__name__} preview={_response_preview(raw)}")
        return False
    value = decoded
    field = str(getattr(bo, "success_field", "success") or "success").strip()
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            _log(logger, f"응답 success_field 없음 field={field}")
            return False
        value = value[part]
    expected = str(getattr(bo, "success_value", "true") or "true").strip().lower()
    if isinstance(value, bool):
        ok = value is (expected in ("1", "true", "yes", "y"))
    else:
        ok = str(value).strip().lower() == expected
    _log(logger, f"응답 판정 field={field} expected={expected} result={'Y' if ok else 'N'}")
    return ok


def fetch_kapa_credentials(app) -> tuple[str, str]:
    """실서버 KAPA 계정을 조회한다. 조회값은 로그/예외 메시지에 포함하지 않는다."""
    db = getattr(app, "db", None)
    bo = getattr(app, "bankonline", None)
    user_name = str(getattr(bo, "kapa_user_name", "\uc774\uc77c\uc6b0") or "\uc774\uc77c\uc6b0").strip()
    if not db:
        raise RuntimeError("KAPA_DB_CONFIG_MISSING")
    conn = None
    try:
        import pyodbc
        import ts_db_writer
        conn = pyodbc.connect(
            ts_db_writer.build_connection_string(db, db.username, db.password),
            timeout=10,
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT Kapa_Id, Kapa_Pw "
            "FROM apworksdw.dbo.Apw_YJI_KapaID_List "
            "WHERE User_Name = ?",
            (user_name,),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError("KAPA_CREDENTIALS_NOT_FOUND")
        kapa_id = str(row[0] or "").strip()
        kapa_pw = str(row[1] or "")
        if not kapa_id or not kapa_pw:
            raise LookupError("KAPA_CREDENTIALS_EMPTY")
        return kapa_id, kapa_pw
    except LookupError:
        raise
    except Exception as exc:
        raise RuntimeError("KAPA_CREDENTIALS_LOOKUP_FAILED") from exc
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def fetch_token(kapa_id: str, kapa_pw: str, app) -> str:
    """KAPA AuthServer 토큰을 발급한다. 응답 원문/계정값은 기록하지 않는다."""
    bo = getattr(app, "bankonline", None)
    endpoint = str(
        getattr(bo, "token_endpoint", "https://authtoken.kapanet.or.kr/AuthServer")
        or "https://authtoken.kapanet.or.kr/AuthServer"
    ).strip()
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("TOKEN_ENDPOINT_NOT_ALLOWED")
    body = urllib.parse.urlencode({
        "userid": kapa_id,
        "userpass": kapa_pw,
        "appcode": str(getattr(app, "app_code", "300611") or "300611"),
    }).encode("utf-8")
    req = urllib.request.Request(
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
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read(4097)
        if len(raw) > 4096:
            raise ValueError("TOKEN_RESPONSE_TOO_LARGE")
    token = raw.decode("utf-8-sig").strip()
    if not token or len(token) > 512 or any(ch.isspace() for ch in token):
        raise ValueError("TOKEN_REJECTED")
    if token.lower().startswith(("no auth", "error", "fail")):
        raise ValueError("TOKEN_REJECTED")
    return token


def resolve_authorization(app) -> str:
    bo = getattr(app, "bankonline", None)
    configured = str(getattr(bo, "authorization", "") or "").strip()
    if configured:
        return configured
    kapa_id, kapa_pw = fetch_kapa_credentials(app)
    return fetch_token(kapa_id, kapa_pw, app)


def call(output: dict, app, caller=None, logger=None) -> tuple[str, str]:
    """Return (BankOnline_In, safe_error_code)."""
    _log(logger, "호출 시작")
    if not enabled(app):
        bo = getattr(app, "bankonline", None)
        _log(logger, f"건너뜀 enabled={bool(getattr(bo, 'enabled', False))} endpoint={_endpoint_summary(getattr(bo, 'endpoint', ''))}")
        return ("", "DISABLED")
    reasons = payload_block_reasons(output, app)
    dambo_no = normalize_docid(
        output.get("RequestNo") or output.get("DAMBO_NO") or output.get("request_no")
    )
    gam_no = str(output.get("NewMasterID") or "").strip()
    bank = canonical_bank(output.get("Bank") or output.get("CustName") or "")
    _log(
        logger,
        "payload 점검 "
        f"CUSTKEY={CUSTKEY.get(bank, '') or '-'} "
        f"DAMBO_NO={_mask_docid(dambo_no)} GAM_NO={gam_no or '-'} "
        f"reasons={','.join(reasons) if reasons else '-'}",
    )
    if reasons:
        return ("N", "INVALID_PAYLOAD")
    payload = build_payload(output, app)
    if not payload:
        return ("N", "INVALID_PAYLOAD")
    try:
        response = caller(payload) if callable(caller) else call_rest(payload, app, logger=logger)
        if response is True or (isinstance(response, dict) and response.get("success") is True):
            _log(logger, "호출 성공")
            return ("Y", "")
        _log(logger, "호출 실패 API_REJECTED")
        return ("N", "API_REJECTED")
    except Exception as exc:
        _log(logger, f"예외 발생 code={type(exc).__name__}")
        return ("N", type(exc).__name__)
