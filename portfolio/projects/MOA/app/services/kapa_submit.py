"""협회(KAPA) 업무실적 REST 전송.

엔드포인트: POST {base}/rest/LAWREP/insXml.php
폼 파라미터: APPCODE, BUNGI, MON, USERID, PASSWD, AK(날짜토큰), TYPE='JSON', DATAS(JSON 배열).
응답: {"RESULT":"0","MSG":"...","DATA":[{"SUCCESS_CNT":N,"ALREADY_CNT":M}]} — RESULT='0' 성공.
응답코드·필드 규격은 협회 명세 페이지 /rest/LAWREP/insXml_t.php 에 있다(RESULT 70=마감).
인증 AK = 년 × 월 × 일 × 상수 (호출일 기준). 상수는 API별로 다르다(실호출로 확정):
조회(rest/LAWREP/)=137, 전송(insXml.php)=261. 섞으면 'AK Validation Error'.

⚠️ 실제 전송은 협회 프로덕션이며 호출이력이 모니터링된다. 기본 dry_run=True로 두고,
호출측이 명시적으로 dry_run=False를 줄 때만 실제 전송한다.
"""

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

import requests

from app.config import get_settings

LAWREP_PATH = "/rest/LAWREP/insXml.php"
LAWREP_QUERY_PATH = "/rest/LAWREP/"
AK_QUERY_CONST = 137   # 조회용
AK_SUBMIT_CONST = 261  # 전송용

# DATAS JSON 필드 순서(협회 규약, upmu 샘플). 성명(GAMMAN)은 제외 — 협회가 자격번호로 채운다.
_DATAS_FIELDS = (
    ["ID_NUM", "QUANO", "GNAME", "REG", "EUB", "SAN", "BUN1", "BUN2", "CUST",
     "CUSTCODE", "PCODE", "YCODE", "INDATE", "OUTDATE", "CONSULTDATE", "FEE", "SUSU", "GAMGA"]
    + [f"CATEGORY{i}" for i in range(1, 11)]
    + [f"PRICE{i}" for i in range(1, 11)]
    + [f"CNT{i}" for i in range(1, 11)]
)
_DATE_FIELDS = {"INDATE", "OUTDATE", "CONSULTDATE"}
# 숫자 필드 — 협회는 정수 문자열로 저장한다(실측 20263/7월 402건: SUSU·GAMGA 전부
# 소수점 없음). 우리 원천은 float 이라 str() 하면 '688000.0'·'0.0' 이 되고, 협회는
# 그 행을 못 넣어 'Unable To Process' 로 통째 거부한다 (2026-09-07 본사 전송 실패).
_NUMERIC_FIELDS = (
    {"CUSTCODE", "FEE", "SUSU", "GAMGA"}
    | {f"CATEGORY{i}" for i in range(1, 11)}
    | {f"PRICE{i}" for i in range(1, 11)}
    | {f"CNT{i}" for i in range(1, 11)}
)
# JSON 키 → 매핑 행 dict 키 (INDATE만 이름이 다르다).
_ROW_KEY = {"INDATE": "IN_DATE"}


class KapaNotConfiguredError(RuntimeError):
    pass


class KapaQueryError(RuntimeError):
    pass


def compute_ak(today: date, constant: int = AK_SUBMIT_CONST) -> str:
    """협회 인증 토큰. 호출일의 년×월×일×상수 (조회 137 / 전송 261)."""
    return str(today.year * today.month * today.day * constant)


def fetch_registered_rows(
    appcode: str, bungi: str, mon: int, *, today: date | None = None, timeout: int = 40
) -> list[dict[str, Any]]:
    """협회 서버에 이미 등록된 업무실적 원본 행(해당 분기·월).

    전송은 행 단위 추가라 이 행들을 다시 보낼 필요가 없다(2026-09-07 실측·명세 확인).
    등록 여부 표시와 '이미 등록된 건 빼고 보내기'에 쓴다.
    """
    settings = get_settings()
    if not settings.is_kapa_configured:
        raise KapaNotConfiguredError("협회 계정(KAPA_LAWREP_USER/PW)이 설정되지 않았습니다.")
    try:
        response = requests.post(
            settings.kapa_lawrep_base_url.rstrip("/") + LAWREP_QUERY_PATH,
            data={
                "APPCODE": appcode, "BUNGI": bungi, "MON": str(mon),
                "USERID": settings.kapa_lawrep_user,
                "PASSWD": settings.kapa_lawrep_pw.get_secret_value(),
                "AK": compute_ak(today or date.today(), AK_QUERY_CONST),
            },
            timeout=timeout,
        )
    except requests.RequestException as error:
        raise KapaQueryError(f"협회 기존 자료 조회에 실패했습니다: {error}") from error
    try:
        body = response.json()
    except ValueError as error:
        raise KapaQueryError(f"협회 응답 파싱 실패 (HTTP {response.status_code})") from error
    if str(body.get("RESULT")) != "0":
        raise KapaQueryError(f"협회 조회 실패: {body.get('MSG') or body.get('RESULT')}")
    rows = body.get("DATA") or []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise KapaQueryError("협회 조회 결과의 DATA 형식이 올바르지 않습니다.")
    return rows


def fetch_registered_doc_ids(
    appcode: str, bungi: str, mon: int, *, today: date | None = None, timeout: int = 40
) -> set[str]:
    """협회 서버에 이미 등록된 감정서번호 집합. 화면의 등록 여부 표시에 쓴다."""
    return {
        str(row.get("ID_NUM")).strip()
        for row in fetch_registered_rows(
            appcode, bungi, mon, today=today, timeout=timeout
        )
        if row.get("ID_NUM")
    }


def _numeric_text(text: str) -> str:
    """'688000.0' → '688000'. 숫자로 못 읽으면 원문 그대로 둔다(빈 값 포함)."""
    try:
        return str(int(Decimal(text).to_integral_value(rounding=ROUND_HALF_UP)))
    except (InvalidOperation, ValueError):
        return text


def _field_value(row: dict[str, Any], field: str) -> str:
    value = row.get(_ROW_KEY.get(field, field))
    if value is None:
        return ""
    text = str(value)
    if field in _DATE_FIELDS:
        return text[:10]  # 'YYYY-MM-DD'
    text = text.strip()
    if field in _NUMERIC_FIELDS and text:
        return _numeric_text(text)
    return text


def build_datas(rows: list[dict[str, Any]]) -> str:
    """전송용 DATAS(JSON 배열 문자열). 모든 값 문자열, 공백/개행 없음."""
    payload = [{field: _field_value(row, field) for field in _DATAS_FIELDS} for row in rows]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def merge_registered_rows(
    registered: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """협회 기존 행을 그대로 두고 미등록 감정서만 뒤에 추가한다.

    기존 행을 ID_NUM dict로 재구성하지 않는 이유는 협회에 중복 행이 있더라도 이번
    전송 때문에 조용히 사라지지 않게 하기 위해서다. 같은 번호의 수정은 이 '추가 전송'
    경로에서 하지 않고 협회 기존 값을 우선한다.
    """
    merged = list(registered)
    known = {
        str(row.get("ID_NUM") or "").strip()
        for row in registered
        if str(row.get("ID_NUM") or "").strip()
    }
    added = 0
    for row in incoming:
        doc_id = str(row.get("ID_NUM") or "").strip()
        if not doc_id:
            raise KapaQueryError("전송 목록에 감정서번호가 없는 행이 있습니다.")
        if doc_id in known:
            continue
        merged.append(row)
        known.add(doc_id)
        added += 1
    return merged, added


# 협회가 채워 넣기를 요구하는 숫자 필드. 실측(20263/7월 402건·8월 121건)에서 협회
# 등록분은 이 두 필드가 한 건도 비어 있지 않다. 거부 사유는 행을 짚어 주지 않으므로
# 우리 쪽에서 짚어 준다. (2026-09-07 8월 거부의 원인은 회차 마감이었고 이 값들은
# 아니었다 — 그래도 협회 자료 품질을 위해 표시는 남긴다.)
_REQUIRED_NUMERIC = ("CUSTCODE", "GAMGA")


def suspect_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """협회가 거부할 만한 행 — 필수 숫자값이 빈 건."""
    suspects = []
    for row in rows:
        missing = [
            field for field in _REQUIRED_NUMERIC
            if not _field_value(row, field).strip()
        ]
        if missing:
            suspects.append({
                "doc_id": _field_value(row, "ID_NUM"),
                "missing": ", ".join(missing),
            })
    return suspects


# 협회 공식 응답코드 (명세 https://m.kapanet.or.kr/rest/LAWREP/insXml_t.php).
# 협회 MSG 는 'Unable To Process' 처럼 원인을 알 수 없는 영문이라 담당자가 손쓸
# 길이 없었다 — 코드로 뜻을 붙여 준다 (2026-09-07 8월분 전송 실패 추적).
RESULT_MESSAGES = {
    "10": "https 통신이 아닙니다.",
    "20": "필수 파라미터가 빠졌습니다.",
    "30": "파라미터 값이 규격에 맞지 않습니다.",
    "40": "협회 인증(AK) 오류입니다.",
    "50": "협회 계정 인증에 실패했습니다.",
    "60": "이 계정에 협회 API 권한이 없습니다.",
    "70": "협회에서 마감된 회차라 전송할 수 없습니다. 협회에 마감 해제를 요청하세요.",
    "80": "협회 실적 보고기간이 아닙니다.",
    "90": "협회가 JSON 을 읽지 못했습니다.",
    "100": "협회가 XML 을 읽지 못했습니다.",
}


def _parse_response(text: str) -> dict[str, Any]:
    try:
        body = json.loads(text)
    except ValueError:
        return {"success": False, "result": None, "message": "응답 파싱 실패", "raw": text[:500]}
    data = (body.get("DATA") or [{}])[0] if isinstance(body.get("DATA"), list) else {}
    result = str(body.get("RESULT"))
    return {
        "success": result == "0",
        "result": body.get("RESULT"),
        # 협회 영문 MSG 보다 코드 뜻이 쓸모 있다. 둘 다 남긴다.
        "message": RESULT_MESSAGES.get(result) or body.get("MSG") or "",
        "kapa_message": body.get("MSG") or "",
        "success_cnt": data.get("SUCCESS_CNT"),
        "already_cnt": data.get("ALREADY_CNT"),
    }


CHUNK_SIZE = 100  # 한 번에 보내는 최대 건수. 20건 실증(2026-09-07), 큰 묶음은 미검증이라 나눈다.


def submit_work_report(
    result: dict[str, Any], *, dry_run: bool = True, today: date | None = None, timeout: int = 30
) -> dict[str, Any]:
    """build_kapa_rows() 결과를 협회로 전송. dry_run이면 실제 호출 없이 페이로드만 돌려준다.

    협회 API 는 **행 단위 추가/덮어쓰기**다 — 명세의 ALREADY_CNT 가 '과거에 이미
    등록된 실적'이고, 실측(2026-09-07)에서도 A 만 등록된 회차에 B 만 보냈더니
    A 가 그대로 남고 2건이 됐다. 예전엔 '분기·월 자료를 통째 교체'로 잘못 알고
    기존 자료를 전부 합쳐 보냈는데, 그러느라 8월분이 488건까지 부풀었다.
    지금은 미등록분만 보낸다 — 기존 자료는 건드리지 않으므로 보존 문제가 없다.
    """
    settings = get_settings()
    if not settings.is_kapa_configured:
        raise KapaNotConfiguredError("협회 전송 계정(KAPA_LAWREP_USER/PW)이 설정되지 않았습니다.")
    requested_rows = result.get("rows", [])
    if not requested_rows:
        raise KapaQueryError("전송할 업무실적이 없습니다.")
    # 번호 없는 행과 요청 내부 중복을 네트워크 호출 전에 차단·정리한다.
    rows, _ = merge_registered_rows([], requested_rows)
    url = settings.kapa_lawrep_base_url.rstrip("/") + LAWREP_PATH

    def _form(part: list[dict[str, Any]]) -> dict[str, str]:
        return {
            "APPCODE": result["appcode"],
            "BUNGI": result["bungi"],
            "MON": str(result["month"]),
            "USERID": settings.kapa_lawrep_user,
            "PASSWD": settings.kapa_lawrep_pw.get_secret_value(),
            "AK": compute_ak(today or date.today()),
            "TYPE": "JSON",
            "DATAS": build_datas(part),
        }

    if dry_run:
        # 자격증명(USERID/PASSWD)은 절대 노출하지 않는다. 네트워크도 타지 않는다.
        form = _form(rows)
        return {
            "dry_run": True, "url": url, "count": len(rows),
            "appcode": form["APPCODE"], "bungi": form["BUNGI"], "mon": form["MON"],
            "datas_preview": form["DATAS"][:800],
        }

    registered = fetch_registered_doc_ids(
        result["appcode"], result["bungi"], result["month"],
        today=today, timeout=max(timeout, 40),
    )
    todo = [row for row in rows
            if str(row.get("ID_NUM") or "").strip() not in registered]
    if not todo:
        return {
            "success": True,
            "result": "NO_CHANGES",
            "message": "협회에 이미 등록된 건뿐이라 전송하지 않았습니다.",
            "dry_run": False,
            "count": 0,
            "requested_count": len(requested_rows),
            "preserved_count": len(registered),
            "added_count": 0,
            "http_status": None,
        }

    sent = success_cnt = already_cnt = 0
    parsed: dict[str, Any] = {}
    for index in range(0, len(todo), CHUNK_SIZE):
        part = todo[index:index + CHUNK_SIZE]
        try:
            response = requests.post(url, data=_form(part), timeout=timeout)
        except requests.RequestException as error:
            raise KapaQueryError(
                "협회 전송 응답을 받지 못했습니다. 재조회 후 등록 여부를 확인하세요: "
                f"{error}"
            ) from error
        parsed = _parse_response(response.text)
        parsed["http_status"] = response.status_code
        if not parsed["success"]:
            # 협회는 어느 행이 문제인지 말해 주지 않는다. 짚이는 행을 같이 돌려준다.
            parsed["suspects"] = suspect_rows(part)
            break
        sent += len(part)
        success_cnt += int(parsed.get("success_cnt") or 0)
        already_cnt += int(parsed.get("already_cnt") or 0)
    parsed.update({
        "dry_run": False,
        "count": sent,
        "requested_count": len(requested_rows),
        "preserved_count": len(registered),
        "added_count": sent,
        "chunks": (len(todo) + CHUNK_SIZE - 1) // CHUNK_SIZE,
    })
    if parsed.get("success"):
        parsed.update({"success_cnt": success_cnt, "already_cnt": already_cnt})
    else:
        parsed["failed_after"] = sent
    return parsed
