"""보수기준 점검 전용 APWorks·JUN 근거 엔진."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from app.config import get_settings
from app.database import get_source_engine
from app.services.fee_basis_rules import FEE_CODE_LABELS


# ======================== JUN·APWorks 근거 검색 ========================

# 규칙을 바꾸면 반드시 올린다 — prepared 스냅숏 재사용 판정(is_fresh)이 이 값을 본다.
# /8: 문서 근거가 없을 때만 보는 계산 사유 2종 추가(소급감정·수수료차액발생).
# /9: 동일 지번 직전 감정서로 `N이내재평가` 판정 추가.
# /10: /9의 이전 감정서 조회가 실행되지 않던 결함 수정(빈 결과가 캐시돼 있었다).
# /11: 재평가 의견에 직전 감정서번호를 함께 적는다(재무팀 AB 관례).
# /12: 근거 강도를 구분한다.
#      재평가: 같은 지번 + 기간 구간이면 확정. 뒤집힘이 1개월을 넘으면 재평가확인.
#              (의뢰인·평가목적 일치는 조건이 아니라 근거 메모 — 재무팀 확정 4건 모두
#               의뢰인·목적이 달랐다.)
#      소급: 6개월 이상이면 소급감정 확정, 3~6개월은 소급감정확인.
#      JUN 문서가 없으면 담당자확인요청 대신 JUN문서없음.
#      AB에서 이전 감정서번호를 뺐다(내부 근거로만 보존).
KEYWORD_RULE_VERSION = "fee-opinion-ko/12"
# /4: /3의 파라미터 수 불일치로 페이지 검색이 통째로 실패했다(근거 0건). 그 사이
#     만들어진 스냅숏을 재사용하지 않도록 올린다.
SEARCH_ENGINE_VERSION = "jun-page-normalized-section/4"

FOUND = "FOUND"
NO_CASE = "NO_CASE"
NO_DOCUMENT = "NO_DOCUMENT"
DOCUMENT_NOT_READY = "DOCUMENT_NOT_READY"
MULTIPLE_CASES = "MULTIPLE_CASES"
EVIDENCE_ERROR = "EVIDENCE_ERROR"
NOT_ANALYZED = "NOT_ANALYZED"

DIRECT = "DIRECT"
CONTEXT_ONLY = "CONTEXT_ONLY"
STRUCTURED_CASE_SIGNAL = "STRUCTURED_CASE_SIGNAL"
AMBIGUOUS = "AMBIGUOUS"
NONE = "NONE"
# 계산·문서부재를 근거 없음(NONE)과 구분한다. CONTEXT_ONLY·CALCULATED는 법적 확정이 아니다.
CALCULATED = "CALCULATED"
NO_DOCUMENT_LEVEL = "NO_DOCUMENT"

_SPACE = re.compile(r"\s+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


@dataclass(frozen=True)
class ReasonRule:
    code: str
    label: str
    context_keywords: tuple[str, ...]
    document_keywords: tuple[str, ...]


RULES = (
    ReasonRule(
        "CONSULTING", "컨설팅·자문용역",
        ("컨설팅", "자문", "용역"),
        ("컨설팅", "자문용역", "자문 업무", "용역 업무"),
    ),
    ReasonRule(
        "COURT_AUCTION", "법원·경매 감정",
        ("민사소송", "법원감정", "법원", "경매", "소송"),
        ("감정명령", "사건번호", "법원", "경매", "민사소송"),
    ),
    ReasonRule(
        "RENT", "임료·임대료 감정",
        ("임료", "임대료", "임대사례"),
        ("임료", "임대료", "차임"),
    ),
    ReasonRule(
        "VOLUME", "종량제",
        ("종량", "종량제"),
        ("종량제", "종량"),
    ),
    ReasonRule(
        "DEVELOPMENT_LAND", "조성용지 매각·분양가격 산정",
        ("조성용지", "분양가격", "매각가격", "용지 매각"),
        ("조성용지", "분양가격", "매각가격"),
    ),
    ReasonRule(
        "ASSET_MANAGEMENT", "자산운용·리츠",
        ("자산운용", "리츠", "부동산투자회사", "펀드"),
        ("자산운용", "리츠", "부동산투자회사", "펀드"),
    ),
    ReasonRule(
        "ASSET_REVALUATION", "자산재평가",
        ("자산재평가",),
        ("자산재평가",),
    ),
    ReasonRule(
        "RETROSPECTIVE", "소급감정",
        ("소급", "과거시점"),
        ("소급감정", "소급 평가", "과거시점"),
    ),
    ReasonRule(
        "REAPPRAISAL", "재평가·재의뢰",
        ("재평가", "재의뢰"),
        ("재평가", "재의뢰", "종전 감정"),
    ),
    ReasonRule(
        "BUSINESS_PREMIUM", "영업권·이전비·업무량 할증",
        ("영업권", "이전비", "영업손실", "휴업보상"),
        ("영업권", "이전비", "영업손실", "휴업보상"),
    ),
    ReasonRule(
        "DISCOUNT_SURCHARGE", "할인·할증·적용요율",
        ("할인", "할증", "적용요율", "요율"),
        ("수수료 할인", "수수료 할증", "보수 할인", "보수 할증", "적용요율"),
    ),
    ReasonRule(
        "COMBINED_BILLING", "합산·분할·대표 청구",
        ("합산", "분할", "대표청구", "일괄청구"),
        ("합산 청구", "분할 청구", "대표 청구", "일괄 청구"),
    ),
)

_RULE_BY_CODE = {rule.code: rule for rule in RULES}
_DOCUMENT_TERMS = tuple(
    (rule.code, keyword)
    for rule in RULES
    for keyword in dict.fromkeys(rule.document_keywords)
)
_JUN_EVIDENCE_PER_REASON = 3

# APW_IW_SusuWhy.Code 45개를 화면용 짧은 사유로 정규화한다. 사건에는
# APW_IW_SuSuList.Code → SusuWhy.Docid로 연결되며, 여기의 display_code가 아래 키다.
_APW_CODE_LABELS: "dict[int, tuple[str, str]]" = {
    1: ("BASE_RATE", "기본 수수료 요율"),
    2: ("RETROSPECTIVE", "6개월 이상 소급감정"),
    3: ("SPECIAL_STRUCTURE", "특수용도 구축물"),
    4: ("STANDING_TIMBER", "입목 등 특수물건"),
    5: ("INACCESSIBLE_AREA", "도서·산림 등 통행불가 지역"),
    6: ("INDUSTRIAL_FACILITY", "산업체 시설 감정"),
    7: ("DISMANTLEMENT", "해체처분가격 감정"),
    8: ("ROAD_INCLUSION", "도로 편입 토지"),
    9: ("MINING_RIGHT", "광산·광업권·온천"),
    10: ("FISHERY_RIGHT", "어장·어업권"),
    11: ("EXPROPRIATION", "수용·재결평가"),
    12: ("POWER_LINE_LAND", "선하지 감정"),
    13: ("REAPPRAISAL", "3개월 이내 동일물건 재평가"),
    14: ("REAPPRAISAL", "3개월 이내 재평가"),
    15: ("REAPPRAISAL", "6개월 이내 재평가"),
    16: ("REAPPRAISAL", "1년 이내 재평가"),
    17: ("REAPPRAISAL", "2년 이내 재평가"),
    18: ("DEVELOPMENT_GAIN", "가치증감·개발이익환수"),
    19: ("MULTI_HOUSING", "10호 이상 공동주택"),
    20: ("DEVELOPMENT_LAND", "조성용지 매각"),
    21: ("ASSET_REVALUATION", "자산재평가"),
    22: ("SMALL_POINT", "소규모 지점단위 평가"),
    23: ("VOLUME", "보상평가 종량제"),
    24: ("CONSULTING", "상담·자문용역"),
    25: ("SPECIAL_CONTRACT", "보수 특약"),
    26: ("RETAINER", "착수금"),
    27: ("WITHDRAWAL", "의뢰·수임 철회"),
    28: ("MULTI_PROPERTY", "수개 물건 총액기준"),
    29: ("MULTI_PROPERTY", "수개 물건 건별기준"),
    30: ("ADMIN_AREA", "행정구역별 산정"),
    31: ("PROPERTY_RIGHTS", "광업권·어업권·영업권"),
    32: ("COURT_FEE", "대법원 예규 20% 적용"),
    33: ("COURT_FEE", "대법원 예규 아파트 30% 적용"),
    34: ("COURT_FEE", "대법원 예규 150% 할증"),
    35: ("RETROSPECTIVE", "대법원 소급감정 할증"),
    36: ("COURT_FEE_CAP", "대법원 감정료 상·하한"),
    37: ("OTHER_RULE", "기타 등록 보수사유"),
    38: ("COMPENSATION", "보상평가 종가"),
    39: ("RENT", "임료·임대료 감정"),
    40: ("COURT_AUCTION", "법원 소송평가"),
    41: ("ASSET_MANAGEMENT", "집합투자기구 편입재산"),
    42: ("ASSET_MANAGEMENT", "부동산투자회사 운용자산"),
    43: ("OFFICIAL_SURVEY", "공시업무 조사·검증"),
    44: ("APPRAISAL_REVIEW", "감정평가서 적정성 검토"),
    45: ("REAPPRAISAL", "1년 이내 재평가 할인"),
}

# APW_BILL.SusuGubun is CHAR(10). Only these two padded values have been
# verified against the current-case billing semantics. Other billing fields
# remain audit facts and must never create a reason on their own.
_APW_BILL_REASON_BY_SUSU_GUBUN: "dict[str, tuple[str, str, str]]" = {
    "1": ("COURT_AUCTION", "경매", "경매"),
    "2": ("VOLUME", "종량제", "종량제"),
}

# 근거가 약할 때 "무엇을 확인해야 하는지"를 알려주는 핵심어. 담당자확인요청은 최후값이다.
_CHECK_OPINION_BY_CODE = {
    "JUN_NO_DOCUMENT": "JUN문서없음",
    "REAPPRAISAL_CHECK": "재평가확인",
    "RETROSPECTIVE_CHECK": "소급감정확인",
    "SPECIAL_CONTRACT_CHECK": "보수특약확인",
    "FEE_SOURCE_CHECK": "수수료원천확인",
    "COMBINED_BILLING_CHECK": "합산청구확인",
}

_FINANCE_OPINION_BY_CODE = {
    "CONSULTING": "컨설팅",
    "RENT": "임료감정",
    "VOLUME": "종량제",
    "DEVELOPMENT_LAND": "조성용지매각",
    "ASSET_MANAGEMENT": "자산운용",
    "ASSET_REVALUATION": "자산재평가",
    "RETROSPECTIVE": "소급감정",
    "BUSINESS_PREMIUM": "영업권및이전비",
    "DISCOUNT_SURCHARGE": "할인/할증",
    "COMBINED_BILLING": "합산청구",
    "BASE_RATE": "기본요율",
    "SPECIAL_STRUCTURE": "특수용도구축물150%할증",
    "STANDING_TIMBER": "입목등150%할증",
    "INACCESSIBLE_AREA": "통행불가지역150%할증",
    "INDUSTRIAL_FACILITY": "산업체시설150%할증",
    "DISMANTLEMENT": "해체처분가격150%할증",
    "ROAD_INCLUSION": "도로편입토지150%할증",
    "MINING_RIGHT": "광산광업권온천150%할증",
    "FISHERY_RIGHT": "어장어업권150%할증",
    "EXPROPRIATION": "수용재결평가",
    "POWER_LINE_LAND": "선하지150%할증",
    "DEVELOPMENT_GAIN": "개발이익환수",
    "MULTI_HOUSING": "공동주택",
    "SMALL_POINT": "소규모지점단위",
    "SPECIAL_CONTRACT": "보수특약",
    "RETAINER": "착수금",
    "WITHDRAWAL": "의뢰철회",
    "MULTI_PROPERTY": "수개물건산정",
    "ADMIN_AREA": "시군구별계산",
    "PROPERTY_RIGHTS": "광업권어업권영업권",
    "COURT_FEE": "대법원예규",
    "COURT_FEE_CAP": "감정료상하한",
    "OTHER_RULE": "기타보수사유",
    "COMPENSATION": "보상평가종가",
    "OFFICIAL_SURVEY": "공시업무조사평가",
    "APPRAISAL_REVIEW": "적정성검토",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clean(value: Any, limit: int = 500) -> str:
    return _CONTROL.sub("", _SPACE.sub(" ", _text(value)))[:limit]


def _context_text(item: "dict[str, Any]") -> str:
    return " ".join(
        _text(item.get(key))
        for key in (
            "purpose_name", "purpose_code", "work_name", "work_code",
            "title",
        )
    ).casefold()


def _matching_rules(text: str, *, document: bool = False) -> "list[ReasonRule]":
    source = text.casefold()
    found = []
    for rule in RULES:
        # "자산재평가"는 법정 자산 재평가 목적이고, 동일물건 재의뢰 할인인
        # "재평가·재의뢰"와 다른 사유다. 문서 원문 후보는 보존하되 화면 문맥에서는
        # 포괄어 "재평가"의 부분문자열 중복을 제거한다.
        if (
            not document
            and rule.code == "REAPPRAISAL"
            and "자산재평가" in source
            and not any(token in source for token in ("재의뢰", "종전 감정", "동일물건", "재감정"))
        ):
            continue
        keywords = rule.document_keywords if document else rule.context_keywords
        if any(keyword.casefold() in source for keyword in keywords):
            found.append(rule)
    return found


def _apw_reason_identity(
    reason: "dict[str, Any]",
) -> "tuple[str, str] | None":
    """Return only a joined, specific APWorks reason."""
    try:
        storage_key = int(reason.get("storage_key"))
        display_code = int(reason.get("display_code"))
    except (TypeError, ValueError):
        return None
    if storage_key <= 0 or display_code == 1:
        return None
    return _APW_CODE_LABELS.get(display_code)


def _specific_apw_reasons(
    reasons: "Iterable[dict[str, Any]]",
) -> "list[dict[str, Any]]":
    return [
        reason for reason in reasons
        if _apw_reason_identity(reason) is not None
    ]


def _apw_bill_reason_identity(
    reason: "dict[str, Any]",
) -> "tuple[str, str, str] | None":
    raw = reason.get("susu_gubun")
    if not isinstance(raw, str):
        return None
    return _APW_BILL_REASON_BY_SUSU_GUBUN.get(raw.strip())


def _apw_reasons(doc_ids: "list[str]") -> "dict[str, list[dict[str, Any]]]":
    """APW_IW_SuSuList.Code → APW_IW_SusuWhy.Docid가 올바른 조인이다."""
    result: "dict[str, list[dict[str, Any]]]" = {}
    unique = list(dict.fromkeys(doc_id for doc_id in doc_ids if doc_id))
    if not unique:
        return result

    raw = get_source_engine().raw_connection()
    try:
        cursor = raw.cursor()
        for start in range(0, len(unique), 200):
            chunk = unique[start:start + 200]
            placeholders = ", ".join("CAST(? AS VARCHAR(30))" for _ in chunk)
            cursor.execute(
                f"""
                SELECT
                    RTRIM(sl.Docid) AS doc_id,
                    sl.Code AS storage_key,
                    sw.Code AS display_code,
                    RTRIM(ISNULL(sl.Bigo, '')) AS item_note,
                    RTRIM(ISNULL(sw.Contents, '')) AS contents,
                    RTRIM(ISNULL(sw.Bigo, '')) AS rule_note
                FROM APW_IW_SuSuList sl
                LEFT JOIN APW_IW_SusuWhy sw ON sw.Docid = sl.Code
                WHERE RTRIM(sl.Docid) IN ({placeholders})
                ORDER BY RTRIM(sl.Docid), sl.Code DESC
                """,
                chunk,
            )
            for doc_id, storage_key, display_code, item_note, contents, rule_note in cursor.fetchall():
                reason = {
                    "source": "APWORKS",
                    "storage_key": int(storage_key or 0),
                    "display_code": None if display_code is None else int(display_code),
                    "contents": _clean(contents, 180),
                    "item_note": _clean(item_note, 180),
                    "rule_note": _clean(rule_note, 180),
                }
                if _apw_reason_identity(reason) is None:
                    continue
                result.setdefault(_text(doc_id), []).append(reason)
    finally:
        raw.close()
    return result


def _apw_bill_reasons(
    doc_ids: "list[str]",
) -> "dict[str, list[dict[str, Any]]]":
    """Fetch every verified current-case billing signal without N+1 queries."""
    result: "dict[str, list[dict[str, Any]]]" = {}
    unique = list(dict.fromkeys(doc_id for doc_id in doc_ids if doc_id))
    if not unique:
        return result

    raw = get_source_engine().raw_connection()
    try:
        cursor = raw.cursor()
        for start in range(0, len(unique), 200):
            chunk = unique[start:start + 200]
            placeholders = ", ".join(
                "CAST(? AS VARCHAR(30))" for _ in chunk
            )
            cursor.execute(
                f"""
                SELECT
                    RTRIM(m.DocID) AS doc_id,
                    b.MasterID AS master_id,
                    b.SEQ AS seq,
                    b.SusuGubun AS susu_gubun,
                    b.ChargeGubun AS charge_gubun,
                    b.SusuRate AS susu_rate,
                    b.SusuDc AS susu_dc,
                    b.VolumeCharge AS volume_charge,
                    b.LandVolumeCharge AS land_volume_charge,
                    b.LandVolumeCharge_Origin AS land_volume_charge_origin,
                    b.BuildVolumeCharge AS build_volume_charge,
                    b.TreeVolumeCharge AS tree_volume_charge,
                    b.TreeVolumeCharge_Origin AS tree_volume_charge_origin,
                    b.StructureVolumeCharge AS structure_volume_charge,
                    b.BusinessVolumeCharge AS business_volume_charge,
                    b.MoveFeeVolumeCharge AS move_fee_volume_charge,
                    b.ResearchLandVolumeCharge AS research_land_volume_charge,
                    b.ResearchBuildVolumeCharge AS research_build_volume_charge,
                    b.ChargePartial AS charge_partial,
                    b.VolumeChargePartial AS volume_charge_partial,
                    b.ChargeRest AS charge_rest,
                    b.MixChargeTOTAL AS mix_charge_total
                FROM APW_MASTER m
                INNER JOIN APW_BILL b ON b.MasterID = m.MasterID
                WHERE RTRIM(m.DocID) IN ({placeholders})
                  AND RTRIM(ISNULL(b.SusuGubun, '')) IN ('1', '2')
                ORDER BY RTRIM(m.DocID), b.SEQ
                """,
                chunk,
            )
            for row in cursor.fetchall():
                raw_gubun = row[3]
                susu_gubun = (
                    raw_gubun.strip()
                    if isinstance(raw_gubun, str)
                    else ""
                )
                identity = _APW_BILL_REASON_BY_SUSU_GUBUN.get(susu_gubun)
                if identity is None:
                    continue
                reason_code, reason_label, _opinion = identity
                reason = {
                    "source": "APW_BILL",
                    "reason_code": reason_code,
                    "reason_label": reason_label,
                    "master_id": row[1],
                    "seq": row[2],
                    "susu_gubun": susu_gubun,
                    "charge_gubun": _clean(row[4], 10),
                    "susu_rate": row[5],
                    "susu_dc": row[6],
                    "volume_charge": row[7],
                    "land_volume_charge": row[8],
                    "land_volume_charge_origin": row[9],
                    "build_volume_charge": row[10],
                    "tree_volume_charge": row[11],
                    "tree_volume_charge_origin": row[12],
                    "structure_volume_charge": row[13],
                    "business_volume_charge": row[14],
                    "move_fee_volume_charge": row[15],
                    "research_land_volume_charge": row[16],
                    "research_build_volume_charge": row[17],
                    "charge_partial": row[18],
                    "volume_charge_partial": row[19],
                    "charge_rest": row[20],
                    "mix_charge_total": row[21],
                }
                result.setdefault(_text(row[0]), []).append(reason)
    finally:
        raw.close()
    return result


class JunEvidenceUnavailable(RuntimeError):
    pass


def _connection_from_file(path: Path, database: str) -> str:
    if not path.is_file():
        raise JunEvidenceUnavailable("JUN 연결 파일이 없습니다.")
    matches = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        value = raw.strip().strip('"').strip("'")
        upper = value.upper()
        if upper.startswith("DRIVER={") and "SERVER=" in upper and "DATABASE=" in upper:
            matches.append(value)
    wanted = f"DATABASE={database}".casefold()
    for value in matches:
        if wanted in value.casefold():
            return value
    if matches:
        return re.sub(
            r"(?i)(DATABASE=)[^;]+",
            lambda match: match.group(1) + database,
            matches[0],
            count=1,
        )
    raise JunEvidenceUnavailable("JUN 연결 문자열을 찾지 못했습니다.")


def _resolve_jun_connection_string() -> str:
    settings = get_settings()
    direct = (
        settings.jun_sql_connection_string.get_secret_value()
        or os.environ.get("JUN_SQL_CONNECTION_STRING", "")
    ).strip()
    if direct:
        return direct

    configured = settings.jun_sql_connection_file or os.environ.get(
        "JUN_SQL_CONNECTION_FILE", ""
    )
    candidates = [Path(configured)] if configured else []
    if not candidates:
        candidates.append(Path("D:/JunPdf/jun_sql_connection.txt"))
        candidates.extend(sorted(Path("D:/JunPdf").glob("APW_MASTEREX_*.txt")))
    for path in candidates:
        if path.is_file():
            return _connection_from_file(path, settings.jun_sql_database)
    raise JunEvidenceUnavailable(
        "JUN_SQL_CONNECTION_STRING 또는 JUN_SQL_CONNECTION_FILE 설정이 필요합니다."
    )


def _connect_jun():
    try:
        import pyodbc
    except ImportError as exc:  # pragma: no cover - 배포 이미지 의존
        raise JunEvidenceUnavailable("JUN 조회용 pyodbc가 설치되어 있지 않습니다.") from exc
    try:
        return pyodbc.connect(
            _resolve_jun_connection_string(), autocommit=True, timeout=15
        )
    except Exception as exc:
        # ODBC 예외에는 서버/계정 정보가 섞일 수 있으므로 외부로 원문을 내보내지 않는다.
        raise JunEvidenceUnavailable("JUN 데이터베이스에 연결하지 못했습니다.") from exc


def _target_values_sql(targets: "list[tuple[str, str]]") -> "tuple[str, list[Any]]":
    values = ", ".join(
        "(CAST(? AS VARCHAR(32)), CAST(? AS VARCHAR(8)))" for _ in targets
    )
    params: "list[Any]" = []
    for normalized, branch in targets:
        params.extend((normalized, branch))
    return values, params


def _branch_code(item: "dict[str, Any]") -> str:
    normalized = _text(item.get("doc_id_normalized"))
    return normalized[:2] if len(normalized) >= 2 and normalized[:2].isdigit() else ""


def _sentence(text: str, keywords: Iterable[str]) -> str:
    clean = _clean(text, 10_000)
    folded = clean.casefold()
    positions = [
        folded.find(keyword.casefold())
        for keyword in keywords
        if folded.find(keyword.casefold()) >= 0
    ]
    if not positions:
        return clean[:180]
    at = min(positions)
    left = max(
        clean.rfind(".", 0, at),
        clean.rfind("。", 0, at),
        clean.rfind("다.", 0, at),
        clean.rfind("\n", 0, at),
    )
    right_candidates = [
        pos for pos in (
            clean.find(".", at + 1),
            clean.find("。", at + 1),
            clean.find("다.", at + 1),
            clean.find("\n", at + 1),
        ) if pos >= 0
    ]
    right = min(right_candidates) + 2 if right_candidates else min(len(clean), at + 130)
    return clean[max(0, left + 1):right].strip()[:220]


def _fetch_jun(items: "list[dict[str, Any]]") -> "dict[str, dict[str, Any]]":
    targets = list(dict.fromkeys(
        (item["doc_id_normalized"], _branch_code(item))
        for item in items
        if item.get("doc_id_normalized") and _branch_code(item)
    ))
    if not targets:
        return {}

    cases: "dict[str, list[dict[str, Any]]]" = {}
    documents: "dict[str, list[dict[str, Any]]]" = {}
    connection = _connect_jun()
    try:
        cursor = connection.cursor()
        for start in range(0, len(targets), 80):
            chunk = targets[start:start + 80]
            values, params = _target_values_sql(chunk)
            common = (
                "WITH targets(normalized_doc_id, branch_code) AS ("
                "SELECT normalized_doc_id, branch_code "
                f"FROM (VALUES {values}) AS v(normalized_doc_id, branch_code)"
                ") "
            )
            cursor.execute(
                common
                + """
                SELECT cm.doc_id, cm.normalized_doc_id, cm.master_id,
                       cm.sub_no, cm.branch_code
                FROM jun.case_master cm
                JOIN targets t
                  ON t.normalized_doc_id = cm.normalized_doc_id
                 AND t.branch_code = cm.branch_code
                """,
                params,
            )
            for row in cursor.fetchall():
                normalized = _text(row[1]).upper()
                cases.setdefault(normalized, []).append({
                    "doc_id": _text(row[0]), "master_id": row[2],
                    "sub_no": row[3], "branch_code": _text(row[4]),
                })

            cursor.execute(
                common
                + """
                SELECT cm.normalized_doc_id, cm.master_id, cm.sub_no,
                       dv.document_version_id, dv.file_name, dv.file_role,
                       dv.status, dv.is_current, dv.sha256, dv.processed_at
                FROM jun.case_master cm
                JOIN targets t
                  ON t.normalized_doc_id = cm.normalized_doc_id
                 AND t.branch_code = cm.branch_code
                LEFT JOIN jun.logical_document ld
                  ON ld.master_id = cm.master_id AND ld.status = N'active'
                LEFT JOIN jun.document_version dv
                  ON dv.logical_document_id = ld.logical_document_id
                 AND dv.is_current = 1
                """,
                params,
            )
            for row in cursor.fetchall():
                normalized = _text(row[0]).upper()
                documents.setdefault(normalized, []).append({
                    "master_id": row[1], "sub_no": row[2],
                    "document_version_id": row[3],
                    "file_name": _clean(row[4], 220),
                    "file_role": _clean(row[5], 40),
                    "status": _text(row[6]).lower(),
                    "is_current": bool(row[7]),
                    "sha256": _text(row[8]),
                    "processed_at": None if row[9] is None else str(row[9]),
                })

        result: "dict[str, dict[str, Any]]" = {}
        version_to_doc: "dict[int, str]" = {}
        version_meta: "dict[int, dict[str, Any]]" = {}
        for normalized, _branch in targets:
            case_group = cases.get(normalized, [])
            unique_cases = {
                (case.get("master_id"), case.get("sub_no")) for case in case_group
            }
            if not case_group:
                result[normalized] = {"search_state": NO_CASE, "evidence": []}
                continue
            if len(unique_cases) > 1:
                result[normalized] = {"search_state": MULTIPLE_CASES, "evidence": []}
                continue
            docs = [
                doc for doc in documents.get(normalized, [])
                if doc.get("document_version_id") is not None
            ]
            if not docs:
                result[normalized] = {"search_state": NO_DOCUMENT, "evidence": []}
                continue
            ready = [doc for doc in docs if doc["status"] == "done" and doc["is_current"]]
            if not ready:
                result[normalized] = {
                    "search_state": DOCUMENT_NOT_READY, "evidence": []
                }
                continue
            result[normalized] = {"search_state": FOUND, "evidence": []}
            for doc in ready:
                version = int(doc["document_version_id"])
                version_to_doc[version] = normalized
                version_meta[version] = doc

        versions = list(version_to_doc)
        for start in range(0, len(versions), 40):
            chunk = versions[start:start + 40]
            ids = ", ".join("CAST(? AS BIGINT)" for _ in chunk)
            term_values = ", ".join(
                "(CAST(? AS VARCHAR(40)), CAST(? AS NVARCHAR(100)))"
                for _ in _DOCUMENT_TERMS
            )
            params: "list[Any]" = []
            for reason_code, keyword in _DOCUMENT_TERMS:
                params.extend((reason_code, keyword))
            # `{ids}`는 page_text와 page_section에서 각각 쓰인다. 한 번만 넘기면
            # 파라미터 수가 어긋나 조회가 통째로 실패하고 JUN 근거가 0건이 된다.
            params.extend(chunk)
            params.extend(chunk)
            cursor.execute(
                f"""
                WITH terms(reason_code, keyword) AS (
                    SELECT reason_code, keyword
                    FROM (VALUES {term_values}) AS v(reason_code, keyword)
                ),
                page_text AS (
                    -- 정규화 텍스트(OCR 교정본)를 우선 본다. 실측 670,115쪽 전부가
                    -- is_published=1 이고 그중 401,199쪽은 원문과 다르다(corrected).
                    -- 정규화가 없는 쪽만 원문으로 떨어진다.
                    SELECT p.document_version_id, p.page_id, p.page_no, p.confidence,
                           COALESCE(n.search_text_content, p.text_content) AS search_text,
                           CASE WHEN n.search_text_content IS NULL THEN 0 ELSE 1 END
                               AS is_normalized
                    FROM jun.page p
                    OUTER APPLY (
                        SELECT TOP 1 ptn.search_text_content
                        FROM jun.page_text_normalization ptn
                        WHERE ptn.page_id = p.page_id
                          AND ptn.is_published = 1
                          AND ptn.search_text_content IS NOT NULL
                        ORDER BY ptn.page_text_normalization_id DESC
                    ) n
                    WHERE p.document_version_id IN ({ids})
                ),
                page_section AS (
                    -- 쪽이 속한 섹션 종류. 실측 section_type 최다값은 etc(859,468)이고
                    -- calculation_basis(28,282)처럼 의미 있는 종류가 따로 있다.
                    -- 섹션이 붙어 있는데 전부 etc면 표지·목차일 가능성이 커서
                    -- 직접근거로 승격하지 않는다(5B). 섹션 자체가 없는 쪽은 '약한 근거'가
                    -- 아니라 '분류 안 됨'이라 종전 confidence 규칙을 그대로 쓴다
                    -- (실측: 670,115쪽 중 현재 섹션이 붙은 쪽 325,697, 그중 etc 아닌 쪽 88,490).
                    SELECT sp.page_id, 1 AS has_any_section,
                           MAX(CASE WHEN s.section_type <> N'etc' THEN 1 ELSE 0 END)
                               AS has_typed_section,
                           MAX(CASE WHEN s.section_type = N'calculation_basis'
                                    THEN 1 ELSE 0 END) AS has_fee_section
                    FROM jun.section_span sp
                    JOIN jun.section s
                      ON s.section_id = sp.section_id
                     AND s.is_current = 1
                    WHERE sp.document_version_id IN ({ids})
                    GROUP BY sp.page_id
                ),
                matched_pages AS (
                    SELECT DISTINCT pt.document_version_id, pt.page_id, pt.page_no,
                           pt.confidence, t.reason_code, pt.is_normalized,
                           COALESCE(ps.has_any_section, 0) AS has_any_section,
                           COALESCE(ps.has_typed_section, 0) AS has_typed_section,
                           COALESCE(ps.has_fee_section, 0) AS has_fee_section
                    FROM page_text pt
                    JOIN terms t
                      ON pt.search_text LIKE N'%' + t.keyword + N'%'
                    LEFT JOIN page_section ps
                      ON ps.page_id = pt.page_id
                ),
                ranked_hits AS (
                    SELECT document_version_id, page_id, page_no, reason_code,
                           is_normalized, has_any_section, has_typed_section,
                           has_fee_section,
                           ROW_NUMBER() OVER (
                               PARTITION BY document_version_id, reason_code
                               ORDER BY
                                   -- 보수 산정 근거 섹션을 먼저 본다.
                                   CASE WHEN has_fee_section = 1 THEN 0 ELSE 1 END,
                                   CASE WHEN has_typed_section = 1 THEN 0 ELSE 1 END,
                                   CASE
                                       WHEN confidence >= 0.80 THEN 0
                                       ELSE 1
                                   END,
                                   page_no, page_id
                           ) AS rn
                    FROM matched_pages
                )
                SELECT h.document_version_id, h.page_id, h.page_no,
                       h.reason_code, p.text_content, p.text_checksum,
                       p.ocr_model, p.ocr_model_version, p.confidence,
                       h.is_normalized, h.has_typed_section, h.has_fee_section,
                       h.has_any_section
                FROM ranked_hits h
                JOIN jun.page p
                  ON p.document_version_id = h.document_version_id
                 AND p.page_id = h.page_id
                WHERE h.rn <= {_JUN_EVIDENCE_PER_REASON}
                ORDER BY h.document_version_id, h.reason_code,
                         h.page_no, h.page_id
                """,
                params,
            )
            for row in cursor.fetchall():
                version = int(row[0])
                normalized = version_to_doc.get(version)
                if not normalized:
                    continue
                rule = _RULE_BY_CODE.get(_text(row[3]).upper())
                if rule is None:
                    continue
                text = _text(row[4])
                confidence = None if row[8] is None else float(row[8])
                doc = version_meta[version]
                result[normalized]["evidence"].append({
                    "source": "JUN",
                    "reason_code": rule.code,
                    "reason_label": rule.label,
                    "document_version_id": version,
                    "file_name": doc["file_name"],
                    "file_role": doc["file_role"],
                    "document_sha256": doc["sha256"],
                    "document_processed_at": doc["processed_at"],
                    "page_id": row[1],
                    "page_no": row[2],
                    "evidence_sentence": _sentence(text, rule.document_keywords),
                    "text_checksum": _text(row[5]),
                    "ocr_model": _text(row[6]),
                    "ocr_model_version": _text(row[7]),
                    "confidence": confidence,
                    "is_normalized_text": bool(row[9]),
                    "section_typed": bool(row[10]),
                    "section_fee_basis": bool(row[11]),
                    "section_known": bool(row[12]),
                    # 5B: 섹션이 붙어 있는데 전부 etc면 표지·목차일 가능성이 커서
                    # 신뢰도가 높아도 직접근거로 승격하지 않는다. 섹션이 아예 없는 쪽은
                    # 분류가 안 된 것일 뿐이라 종전 confidence 규칙을 유지한다.
                    "direct_candidate": (
                        confidence is not None and confidence >= 0.80
                        and (bool(row[10]) or not bool(row[12]))
                    ),
                })
        return result
    finally:
        connection.close()


def _finance_opinion(
    item: "dict[str, Any]",
    reason_code: str,
    reason_label: str,
) -> str:
    """재무팀 AB열 관례에 맞춘 핵심어만 반환한다."""
    if reason_code == "REAPPRAISAL":
        match = re.search(r"(\d+(?:개월|년))\s*이내", reason_label)
        return f"{match.group(1)}이내재평가" if match else "재평가"
    if reason_code == "COURT_AUCTION":
        context = _context_text(item)
        if "경매" in context or "타경" in context:
            return "경매"
        if "소송" in context:
            return "소송건"
        return "법원감정"
    check = _CHECK_OPINION_BY_CODE.get(reason_code)
    if check:
        return check
    mapped = _FINANCE_OPINION_BY_CODE.get(reason_code)
    if mapped:
        return mapped
    if reason_code == "MULTIPLE":
        return "복수사유확인"
    if reason_code == "MANUAL_REQUIRED":
        state = item.get("comparability")
        if state == "ZERO_FEE_REVIEW":
            return "합산청구확인"
        if state == "MISSING_FEE":
            return "보수미입력"
        if state == "EXPENSE_ONLY":
            return "실비만"
        return "담당자확인요청"
    return re.sub(r"[\s·]+", "", _clean(reason_label, 40)) or "담당자확인요청"


def _as_date(value: Any) -> "date | None":
    """날짜 문자열·datetime을 date로. 파싱 실패는 None(판정에 쓰지 않는다)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


# 기준시점이 접수일보다 이만큼 과거면 소급감정으로 본다. 상한을 두는 이유는
# base_date가 1900년대로 들어온 원천 오류(실측 46,000일 초과 2건)를 사유로
# 오인하지 않기 위해서다.
_RETROSPECTIVE_MIN_DAYS = 90
_RETROSPECTIVE_MAX_DAYS = 3650
# 보수기준 할증 대상 소급 기준(6개월). 이 선을 넘으면 날짜만으로 확정한다.
_RETROSPECTIVE_SURCHARGE_DAYS = 180

# 넘어선 경계 대비 이 비율(또는 최소 금액) 이내면 '차액만 확인'으로 본다.
_FEE_GAP_MINOR_RATIO = 0.005
_FEE_GAP_MINOR_FLOOR = 100_000.0


# 동일 물건 재평가 기간 구간. 재무팀 AB 표기와 같은 단위를 쓴다.
_REAPPRAISAL_BANDS = (
    (31, "1개월"), (93, "3개월"), (186, "6개월"), (366, "1년"), (731, "2년"),
)


def _prior_reappraisals(
    doc_ids: "list[str]",
) -> "dict[str, tuple[str, int]]":
    """같은 지번(법정 시군구·읍면동·구분·본번·부번)의 직전 감정서를 찾는다.

    반환: {현재 감정서번호: (이전 감정서번호, 이전 발송일 ISO)}
    price가 없는 행(미완·취소)은 이전 평가로 보지 않는다. 발송일이 같은 건도 포함하는데,
    같은 물건을 같은 날 목적만 달리해 두 번 평가한 사례가 실제로 있다(실측 01-2602-3-0644
    ↔ 01-2602-4-0060). 의뢰인 동일 여부는 조건에 넣지 않는다 — 재무팀 실측에서 의뢰인이
    바뀐 건도 재평가로 처리했고, 할인 근거는 물건을 다시 조사하지 않는다는 점이기 때문이다.
    """
    unique = list(dict.fromkeys(doc_id for doc_id in doc_ids if doc_id))
    if not unique:
        return {}
    latest: "dict[str, tuple[str, Any]]" = {}
    raw = get_source_engine().raw_connection()
    try:
        cursor = raw.cursor()
        for start in range(0, len(unique), 200):
            chunk = unique[start:start + 200]
            placeholders = ", ".join("CAST(? AS VARCHAR(30))" for _ in chunk)
            cursor.execute(
                f"""
                SELECT RTRIM(c.DocID), RTRIM(p.DocID), p.SendDate,
                       CASE WHEN RTRIM(ISNULL(p.CustID,'')) <> ''
                             AND RTRIM(ISNULL(p.CustID,'')) = RTRIM(ISNULL(c.CustID,''))
                            THEN 1 ELSE 0 END AS same_client,
                       CASE WHEN RTRIM(ISNULL(p.GUBUN_CODE,'')) <> ''
                             AND RTRIM(ISNULL(p.GUBUN_CODE,'')) = RTRIM(ISNULL(c.GUBUN_CODE,''))
                            THEN 1 ELSE 0 END AS same_purpose,
                       CASE WHEN p.SendDate < c.SendDate THEN 1 ELSE 0 END AS strictly_before
                FROM APW_MASTEREX c
                JOIN APW_MASTEREX p
                  ON p.Office = c.Office AND p.REG = c.REG AND p.EUB = c.EUB
                 AND p.SAN = c.SAN AND p.BUN1 = c.BUN1 AND p.BUN2 = c.BUN2
                 AND p.DocID <> c.DocID
                 AND p.SendDate IS NOT NULL AND p.SendDate <= c.SendDate
                 AND p.price IS NOT NULL
                WHERE RTRIM(c.DocID) IN ({placeholders})
                  AND c.SendDate IS NOT NULL AND c.REG IS NOT NULL
                """,
                chunk,
            )
            for row in cursor.fetchall():
                current, prior_doc, sent = row[0], row[1], row[2]
                same_client, same_purpose, strictly_before = row[3], row[4], row[5]
                key = _text(current)
                previous = latest.get(key)
                if previous is None or sent > previous["sent"]:
                    latest[key] = {
                        "prior_doc": _text(prior_doc),
                        "sent": sent,
                        "same_client": bool(same_client),
                        "same_purpose": bool(same_purpose),
                        "strictly_before": bool(strictly_before),
                    }
    finally:
        raw.close()
    for value in latest.values():
        sent = value["sent"]
        value["sent"] = (
            sent.date().isoformat() if hasattr(sent, "date") else str(sent)[:10]
        )
    return latest


def _reappraisal_reason(
    item: "dict[str, Any]",
    prior: "dict[str, Any] | None",
) -> "tuple[str, str, str] | None":
    """직전 평가와의 간격을 기간 구간으로 바꾼다.

    확정 조건은 '같은 법정 지번 + 기간 구간 안'이다. 의뢰인·평가목적 일치는 조건이
    아니라 근거 메모로만 남긴다. 실측 근거: 재무팀이 확정한 4건(01-2602-3-0636,
    01-2603-4-0131, 01-2602-3-0644, 01-2602-4-0060) 모두 의뢰인·평가목적이 달랐다.
    보수기준의 재평가 할인은 '같은 물건을 다시 조사하지 않는다'는 사실에 근거하므로
    의뢰인이 바뀌어도 성립한다.

    간격은 절대값으로 본다. 같은 날이거나 며칠 뒤집혀 들어온 쌍(실측 0644↔0060은
    발송일이 같다)도 서로 1개월 구간 안이라는 사실은 방향과 무관하게 참이다.
    다만 뒤집힘이 최소 구간(1개월)을 넘으면 원천 선후관계를 신뢰할 수 없어
    확정하지 않고 `재평가확인`으로 남긴다.

    AB에는 이전 감정서번호를 넣지 않는다(내부 근거로만 보존).
    """
    if not prior:
        return None
    prior_doc = prior.get("prior_doc") or ""
    base = _as_date(item.get("base_date"))
    sent = _as_date(prior.get("sent"))
    if base is None or sent is None:
        return None
    gap_days = (base - sent).days
    span_days = abs(gap_days)
    band = next(
        (name for limit, name in _REAPPRAISAL_BANDS if span_days <= limit), None
    )
    if band is None:
        return None

    smallest_band_limit = _REAPPRAISAL_BANDS[0][0]
    if gap_days < 0 and span_days > smallest_band_limit:
        return (
            "REAPPRAISAL_CHECK",
            f"동일 지번 이전 감정서 있음 · 기준시점이 직전 발송보다 "
            f"{span_days}일 앞서 선후관계 불명확 (직전 {prior_doc})",
            "재평가확인",
        )

    memo = []
    if prior.get("same_client"):
        memo.append("의뢰인 일치")
    if prior.get("same_purpose"):
        memo.append("평가목적 일치")
    if not prior.get("strictly_before"):
        memo.append("발송일 동일")
    detail = f" · {' / '.join(memo)}" if memo else ""
    return (
        "REAPPRAISAL",
        f"{band} 이내 동일물건 재평가{detail} (직전 {prior_doc})",
        f"{band}이내재평가",
    )


def _calculated_reason(
    item: "dict[str, Any]",
) -> "tuple[str, str, str] | None":
    """행 데이터 자체가 근거인 사유. (code, label, 재무 AB 문구)

    APWorks 사유·JUN 원문·업무문맥이 하나도 없을 때만 마지막에 본다. 날짜와 금액은
    문서를 찾지 못해도 그 자체로 확인 근거이므로 `담당자확인요청`보다 구체적이다.
    실측(2026-05 상반 130행)에서 이 위치에 두면 이미 사유가 붙은 행을 덮지 않는다.
    """
    base = _as_date(item.get("base_date"))
    receipt = _as_date(item.get("receipt_date"))
    if base is not None and receipt is not None:
        gap_days = (receipt - base).days
        if _RETROSPECTIVE_MIN_DAYS <= gap_days <= _RETROSPECTIVE_MAX_DAYS:
            # 보수기준 할증 대상은 '6개월 이상 소급'(APW_IW_SusuWhy.Code=2)이다.
            # 그 선을 넘으면 날짜만으로도 확정할 수 있고, 3~6개월 구간은 할증 대상이
            # 아닐 수 있어 확인 후보로만 남긴다.
            if gap_days >= _RETROSPECTIVE_SURCHARGE_DAYS:
                return (
                    "RETROSPECTIVE",
                    f"기준시점이 접수일보다 {gap_days}일 이전 · 6개월 이상 소급",
                    "소급감정",
                )
            return (
                "RETROSPECTIVE_CHECK",
                f"기준시점이 접수일보다 {gap_days}일 이전 · 6개월 미만 (날짜 계산)",
                "소급감정확인",
            )

    # 하한 미만·상한 초과지만 넘은 폭이 미미한 건. 재무팀은 사유 대신 차액을 적는다.
    gap = item.get("gap_amount")
    direction = _text(item.get("deviation_direction"))
    bound = item.get("upper_fee") if "초과" in direction else item.get("lower_fee")
    try:
        gap_abs = abs(float(gap))
        bound_value = abs(float(bound))
    except (TypeError, ValueError):
        return None
    if gap_abs <= 0 or bound_value <= 0:
        return None
    threshold = max(_FEE_GAP_MINOR_FLOOR, bound_value * _FEE_GAP_MINOR_RATIO)
    if gap_abs <= threshold:
        # 차액은 동결 원천 금액에서 정확히 나오는 값이라 확인 후보가 아니라 사실이다.
        # 재무팀 표기도 '수수료차액발생 {금액}'이다(실측 01-2603-4-0100).
        return (
            "FEE_GAP_MINOR",
            f"기준 경계 대비 차액 {round(gap_abs):,}원",
            f"수수료차액발생 {round(gap_abs):,}",
        )
    return None


def _mark_selected_evidence(
    evidence: "list[dict[str, Any]]",
    selected: "dict[str, Any]",
) -> "list[dict[str, Any]]":
    marked = list(evidence)
    for index, candidate in enumerate(marked):
        if candidate is selected:
            marked[index] = {**candidate, "selected": True}
            break
    return marked


def _public_evidence(
    evidence: "list[dict[str, Any]]", limit: int = 12
) -> "list[dict[str, Any]]":
    selected = [item for item in evidence if item.get("selected")]
    remaining = [item for item in evidence if not item.get("selected")]
    return (selected + remaining)[:limit]


def _suggestion(
    item: "dict[str, Any]",
    apw: "list[dict[str, Any]]",
    jun: "dict[str, Any]",
    apw_bill: "list[dict[str, Any]] | None" = None,
    prior: "tuple[str, str] | None" = None,
) -> "tuple[str, str, str, str, list[dict[str, Any]]]":
    context_rules = _matching_rules(_context_text(item))
    specific_apw = _specific_apw_reasons(apw)
    specific_bill = [
        reason for reason in (apw_bill or [])
        if _apw_bill_reason_identity(reason) is not None
    ]
    structured_reasons = [*specific_apw, *specific_bill]
    evidence = list(structured_reasons)
    jun_evidence = list(jun.get("evidence") or [])
    evidence.extend(jun_evidence)

    context_codes = {rule.code for rule in context_rules}
    direct = [
        ev for ev in jun_evidence
        if ev.get("direct_candidate")
        and (
            ev.get("reason_code") in context_codes
            or ev.get("reason_code") in {
                "DISCOUNT_SURCHARGE", "COMBINED_BILLING", "VOLUME"
            }
        )
    ]
    direct_codes = list(dict.fromkeys(ev["reason_code"] for ev in direct))
    context_direct_codes = [
        code for code in direct_codes if code in context_codes
    ]
    if structured_reasons:
        canonical_reasons: (
            "dict[tuple[str, str], tuple[dict[str, Any], str, str]]"
        ) = {}
        for candidate in structured_reasons:
            bill_identity = _apw_bill_reason_identity(candidate)
            if bill_identity is not None:
                code, label, short_opinion = bill_identity
            else:
                identity = _apw_reason_identity(candidate)
                if identity is None:  # pragma: no cover - filtered above
                    continue
                code, label = identity
                short_opinion = _finance_opinion(item, code, label)

            # Bill types 1/2 and their SuSuList equivalents are the same core
            # current-case reason. Reappraisal periods remain distinct.
            qualifier = (
                ""
                if code in {"COURT_AUCTION", "VOLUME"}
                else short_opinion
            )
            key = (code, qualifier)
            previous = canonical_reasons.get(key)
            if (
                previous is None
                or (
                    candidate.get("source") == "APW_BILL"
                    and previous[0].get("source") != "APW_BILL"
                )
            ):
                canonical_reasons[key] = (
                    candidate, label, short_opinion
                )
        if len(canonical_reasons) > 1:
            return (
                "MULTIPLE",
                "복수 사유",
                AMBIGUOUS,
                _finance_opinion(item, "MULTIPLE", "복수 사유"),
                evidence,
            )
        (code, _qualifier), (picked, label, short_opinion) = next(
            iter(canonical_reasons.items())
        )
        return (
            code,
            label,
            STRUCTURED_CASE_SIGNAL,
            short_opinion,
            _mark_selected_evidence(evidence, picked),
        )
    # 보고서에는 할인·할증·합산 같은 보조 문구가 함께 잡히기 쉽다. 평가목적·건명과
    # 일치하는 직접 사유가 하나면 그것을 재무팀 AB열의 대표 핵심어로 사용한다.
    if len(context_direct_codes) == 1:
        code = context_direct_codes[0]
        picked = next(ev for ev in direct if ev["reason_code"] == code)
        label = picked["reason_label"]
        return (
            code,
            label,
            DIRECT,
            _finance_opinion(item, code, label),
            _mark_selected_evidence(evidence, picked),
        )
    if len(context_direct_codes) > 1 or len(direct_codes) > 1:
        labels = ", ".join(_RULE_BY_CODE[code].label for code in direct_codes)
        return (
            "MULTIPLE",
            "복수 사유",
            AMBIGUOUS,
            _finance_opinion(item, "MULTIPLE", labels),
            evidence,
        )
    if direct:
        picked = direct[0]
        label = picked["reason_label"]
        return (
            picked["reason_code"],
            label,
            DIRECT,
            _finance_opinion(item, picked["reason_code"], label),
            _mark_selected_evidence(evidence, picked),
        )
    if context_rules:
        picked = context_rules[0]
        return (
            picked.code,
            picked.label,
            CONTEXT_ONLY,
            _finance_opinion(item, picked.code, picked.label),
            evidence,
        )
    # 계산 사유는 구체적인 순서로 본다. 차액이 재평가보다 앞인 이유: 실측
    # 01-2603-4-0100은 직전 평가(55일)도 있으나 재무팀은 차액만 적었다.
    calculated = _calculated_reason(item) or _reappraisal_reason(item, prior)
    if calculated is not None:
        code, label, opinion = calculated
        return (code, label, CALCULATED, opinion, evidence)

    # 근거를 못 찾은 이유가 'JUN 문서가 없어서'인 것과 '문서는 있는데 단서가 없어서'인 것을
    # 구분한다. 전자는 담당자가 문서 확보부터 해야 한다.
    if jun.get("search_state") in (NO_CASE, NO_DOCUMENT, DOCUMENT_NOT_READY):
        return (
            "JUN_NO_DOCUMENT",
            "JUN 현재 완료 문서 없음",
            NO_DOCUMENT_LEVEL,
            _finance_opinion(item, "JUN_NO_DOCUMENT", "JUN 문서 없음"),
            evidence,
        )
    return (
        "MANUAL_REQUIRED",
        "기타 확인",
        NONE,
        _finance_opinion(item, "MANUAL_REQUIRED", "기타 확인"),
        evidence,
    )


def enrich_items(
    items: "list[dict[str, Any]]", *, include_jun: bool = True
) -> "dict[str, Any]":
    """행을 제자리에서 보강하고 근거 조회 요약을 반환한다."""
    targets = [item for item in items if item.get("review_target")]
    doc_ids = [_text(item.get("doc_id")) for item in targets]

    apw_error = None
    try:
        apw = _apw_reasons(doc_ids)
        apw = {
            doc_id: _specific_apw_reasons(reasons)
            for doc_id, reasons in apw.items()
        }
    except Exception:
        apw = {}
        apw_error = "APWorks 수수료 사유 조회에 실패했습니다."

    apw_bill_error = None
    try:
        apw_bill = _apw_bill_reasons(doc_ids)
    except Exception:
        apw_bill = {}
        apw_bill_error = "APWorks 청구구분 조회에 실패했습니다."

    prior_error = None
    try:
        prior_reappraisal = _prior_reappraisals(doc_ids)
    except Exception:
        prior_reappraisal = {}
        prior_error = "동일물건 이전 감정서 조회에 실패했습니다."

    jun_error = None
    if include_jun:
        try:
            jun = _fetch_jun(targets)
        except Exception:
            jun = {}
            jun_error = "JUN 근거 조회를 사용할 수 없습니다."
    else:
        jun = {}

    for item in items:
        if not item.get("review_target"):
            item.update({
                "suggested_reason_code": "",
                "suggested_reason_label": "",
                "suggested_opinion": "",
                "suggested_opinion_level": NONE,
                "search_state": NOT_ANALYZED,
                "evidence_level": NONE,
                "evidence": [],
                "evidence_summary": "기준 내 — 의견 대상 아님",
            })
            continue

        doc_id = _text(item.get("doc_id"))
        normalized = _text(item.get("doc_id_normalized"))
        jun_item = jun.get(normalized, {
            "search_state": EVIDENCE_ERROR if jun_error else NOT_ANALYZED,
            "evidence": [],
        })
        reason_code, reason_label, level, opinion, evidence = _suggestion(
            item,
            apw.get(doc_id, []),
            jun_item,
            apw_bill.get(doc_id, []),
            prior_reappraisal.get(doc_id),
        )
        item.update({
            "suggested_reason_code": reason_code,
            "suggested_reason_label": reason_label,
            "suggested_opinion": opinion,
            "suggested_opinion_level": level,
            "search_state": jun_item.get("search_state", NOT_ANALYZED),
            "evidence_level": level,
            "evidence": _public_evidence(evidence),
            "evidence_summary": (
                f"APWorks {sum(ev.get('source') == 'APWORKS' for ev in evidence)}건 · "
                f"APW_BILL {sum(ev.get('source') == 'APW_BILL' for ev in evidence)}건 · "
                f"JUN {sum(ev.get('source') == 'JUN' for ev in evidence)}건 · {level}"
            ),
        })
        item.setdefault("source_row_json", {})["AB"] = opinion

    levels = [item.get("evidence_level") for item in targets]
    states = [item.get("search_state") for item in targets]
    return {
        "target_count": len(targets),
        "apw_found": sum(bool(apw.get(doc_id)) for doc_id in doc_ids),
        "apw_bill_found": sum(
            bool(apw_bill.get(doc_id)) for doc_id in doc_ids
        ),
        "jun_found": states.count(FOUND),
        "direct": levels.count(DIRECT),
        "structured": levels.count(STRUCTURED_CASE_SIGNAL),
        "context_only": levels.count(CONTEXT_ONLY),
        "ambiguous": levels.count(AMBIGUOUS),
        "manual_required": levels.count(NONE),
        "prior_found": sum(
            bool(prior_reappraisal.get(doc_id)) for doc_id in doc_ids
        ),
        "apw_error": apw_error,
        "apw_bill_error": apw_bill_error,
        "prior_error": prior_error,
        "jun_error": jun_error,
        "keyword_rule_version": KEYWORD_RULE_VERSION,
        "search_engine_version": SEARCH_ENGINE_VERSION,
    }


# ======================== 보수기준 코드 연결 ========================

# 우리 사유코드 → 운영 보수기준 코드 목록. _APW_CODE_LABELS를 뒤집어 만든다.
# 하드코딩하지 않는 이유: 같은 표를 두 곳에 적으면 한쪽만 고쳐져 어긋난다.
REASON_TO_FEE_CODES: "dict[str, tuple[int, ...]]" = {}
for _code, (_reason, _label) in sorted(_APW_CODE_LABELS.items()):
    REASON_TO_FEE_CODES.setdefault(_reason, ())
    REASON_TO_FEE_CODES[_reason] += (_code,)

# 재평가는 기간 구간마다 조문·할인율이 다르다. AB 핵심어의 구간을 코드로 되돌린다.
# 13(3월내·시점동일 90%)은 시점 동일 여부를 우리가 판별하지 못해 쓰지 않는다.
REAPPRAISAL_BAND_CODES = {
    "1개월": 14,   # 제6조 할인-재평가 3월내(70%)
    "3개월": 14,
    "6개월": 15,   # 제6조 할인-재평가 6월내(50%)
    "1년": 16,     # 제6조 할인-재평가 1년내(30%)
    "2년": 17,     # 제6조 할인-재평가 2년내(10%)
}

# 소급은 일반(제5조)과 법원(대법원예규 §32)이 다르다. 법원 문맥이 아니면 제5조다.
RETROSPECTIVE_CODE = 2
RETROSPECTIVE_COURT_CODE = 35
# 법원 계열은 방향이 정반대다 — 소송은 150% 할증, 경매는 20~30% 할인.
COURT_LITIGATION_CODE = 40   # 제5조제2항제11호 법원 소송평가(150% 할증)
COURT_AUCTION_CODE = 32      # 대법원예규 §31-1 본문(20%). 아파트면 33이나 여기선 못 가른다.

# 운영 45개 코드 체계에 대응하는 코드가 없는 우리 사유. 억지로 붙이면 오탐이 된다.
# 코드 없이 AB 핵심어만 참고로 싣는다.
UNMAPPED_REASONS = ("BUSINESS_PREMIUM", "DISCOUNT_SURCHARGE", "COMBINED_BILLING")

# 보수기준 사유가 아닌 내부 상태. 후보 목록에 넣지 않는다 — 어느 조문을 적용했는지에
# 대한 답이 아니라 우리가 근거를 못 찾았다는 사실이다.
NON_REASON_CODES = ("JUN_NO_DOCUMENT", "MANUAL_REQUIRED", "MULTIPLE")

# 우리 근거 등급 → 운영 화면 출처 표기. 어느 판정을 믿을지 담당자가 알 수 있게 한다.
SOURCE_BY_LEVEL = {
    "STRUCTURED_CASE_SIGNAL": "APWorks사건",
    "DIRECT": "본문(교정본)",
    "CONTEXT_ONLY": "목적",
    "CALCULATED": "계산",
    "NO_DOCUMENT": "문서없음",
    "AMBIGUOUS": "복수사유",
    "NONE": "확인필요",
}


def fee_codes_for(reason_code: str, ab_keyword: str = "") -> "tuple[int, ...]":
    """우리 사유코드를 운영 보수기준 코드로 바꾼다.

    재평가·소급은 사유코드 하나에 여러 조문이 걸려 있어 AB 핵심어의 기간 구간까지 본다.
    법원 계열도 하나가 아니다 — 소송만 150% 할증이고 경매는 할인, 공매는 조문이 없다.
    """
    reason = str(reason_code or "")
    keyword = str(ab_keyword or "")

    if reason == "COURT_AUCTION":
        # COURT_AUCTION 은 '법원·경매 감정' 이라는 한 덩어리라 그대로 코드40(제5조
        # 소송평가 150% 할증)에 붙이면 정반대 조문이 된다. 실측(2026-04~07): 코드40
        # 58건 중 공매(NPL) 43건·법원경매 9건이 오분류였고 진짜 소송은 6건뿐이었다.
        # 경매는 대법원예규 §31-1(20%, 아파트 30%) 할인이고 공매(NPL)는 국세징수법
        # 수수료라 SusuWhy 코드가 없다.
        if "소송" in keyword:
            return (COURT_LITIGATION_CODE,)
        if "경매" in keyword:
            return (COURT_AUCTION_CODE,)
        # 공매를 포함해 무엇인지 특정 못 하면 코드를 고르지 않는다(참고로만 남는다).
        return ()
    if reason == "REAPPRAISAL":
        for band, code in REAPPRAISAL_BAND_CODES.items():
            if keyword.startswith(band):
                return (code,)
        # 구간을 못 읽으면 확정 코드를 고르지 않는다.
        return ()
    if reason == "RETROSPECTIVE":
        return (RETROSPECTIVE_CODE,)
    if reason in UNMAPPED_REASONS:
        return ()
    return REASON_TO_FEE_CODES.get(reason, ())


def to_candidates(item: "dict[str, Any]") -> "list[dict[str, Any]]":
    """보수기준 검토 행 하나를 운영 화면의 후보 목록 형식으로 바꾼다.

    운영 Candidate 형식: {code, label, source, evidence, page}
    여기에 grade(근거 등급)와 ab_keyword(재무팀 AB 열)를 덧붙인다.
    """
    reason = str(item.get("suggested_reason_code") or "")
    if not reason:
        return []
    ab_keyword = str(item.get("suggested_opinion") or "")
    level = str(item.get("evidence_level") or "NONE")
    label_detail = str(item.get("suggested_reason_label") or "")
    source = SOURCE_BY_LEVEL.get(level, "확인필요")

    # 우리가 고른 대표 근거의 페이지를 그대로 넘긴다(감사 추적).
    page = None
    for evidence in item.get("evidence") or []:
        if evidence.get("selected") and evidence.get("page_no"):
            page = evidence.get("page_no")
            break

    # 보수기준 사유가 아닌 것은 후보로 만들지 않는다. 'JUN 문서 없음'·'기타 확인'은
    # 어느 조문을 적용했는지에 대한 답이 아니라 우리가 못 찾았다는 사실일 뿐이다.
    # 후보로 넣으면 화면에 `문서없음(코드없음)` 같은 줄이 대표로 올라온다.
    if reason in NON_REASON_CODES:
        return []

    codes = fee_codes_for(reason, ab_keyword)
    if not codes:
        # 코드가 없는 사유는 후보로 확정하지 않고 참고로만 남긴다.
        return [{
            "code": None,
            "label": label_detail or ab_keyword,
            "source": f"{source}(코드없음)",
            "evidence": label_detail,
            "page": page,
            "grade": level,
            "ab_keyword": ab_keyword,
        }]
    return [
        {
            "code": code,
            "label": FEE_CODE_LABELS.get(code, f"코드 {code}"),
            "source": source,
            "evidence": label_detail,
            "page": page,
            "grade": level,
            "ab_keyword": ab_keyword,
        }
        for code in codes
    ]


def ab_keyword_for(code: "int | None") -> str:
    """운영 보수기준 코드를 재무팀 AB 핵심어로 바꾼다(엑셀을 계속 쓸 경우).

    재평가는 코드마다 기간이 달라 구간을 붙여 돌려준다.
    """
    if code is None:
        return ""
    mapped = _APW_CODE_LABELS.get(int(code))
    if mapped is None:
        return ""
    reason, label = mapped
    if reason == "REAPPRAISAL":
        for band, band_code in REAPPRAISAL_BAND_CODES.items():
            if band_code == int(code):
                return f"{band}이내재평가"
        return "재평가"
    return (
        _FINANCE_OPINION_BY_CODE.get(reason)
        or _CHECK_OPINION_BY_CODE.get(reason)
        or label
    )

DEVIATION_MISSING = "수수료 미입력"
DEVIATION_BELOW = "하한 미만"
DEVIATION_ABOVE = "상한 초과"


# ======================== 점검 후보 병합 ========================

# JUN 조회 키는 구분기호를 제거한 영문·숫자 대문자다. 이 작은 정규화 때문에
# 재무 엑셀 전용 canonical → fee_review → work_report_month 전체를 배포하지 않는다.
_DOC_ID_STRIP = re.compile(r"[^0-9A-Za-z]")


def normalize_doc_id(value: Any) -> str:
    return _DOC_ID_STRIP.sub("", str(value or "")).upper()


# 우리 판정임을 화면에서 구분할 수 있게 붙인다.
ORIGIN = "보수검토"

# 사유를 특정하지 못한 행의 의견. `JUN문서없음`·`담당자확인요청`처럼 우리 내부 사정을
# 적으면 담당자가 무엇을 해야 할지 알기 어렵다. 운영 화면에서는 한 마디로 통일한다.
NEEDS_CHECK = "확인필요"

# 우리 내부 상태 코드 — 보수기준 사유가 아니다. 이 값이 그대로 의견이 되면 안 된다.
_NON_REASON = ("JUN_NO_DOCUMENT", "MANUAL_REQUIRED", "MULTIPLE")


def _adapter_item(item: "dict[str, Any]") -> "dict[str, Any]":
    """보수기준 점검 행을 보수기준 검토 엔진이 읽는 모양으로 바꾼다.

    review_target을 True로 두는 이유: 운영 화면의 목적이 미입력 보수기준을 메꾸는
    것이라서(실측 상반 137건 중 128건 미입력) 전 행을 근거 탐색 대상으로 본다.
    """
    doc_id = str(item.get("doc_id") or "")
    return {
        "doc_id": doc_id,
        "doc_id_normalized": normalize_doc_id(doc_id),
        "source_row_number": item.get("source_row_number"),
        # 문맥 판정용. 운영 행의 업무·세부목적·거래처를 그대로 넘긴다.
        # 의뢰처명(cust_name)은 넣지 않는다 — 상호에 '자산운용'이 들어가도 그 업무라고
        # 볼 수 없어서 규칙상 사유 판정에서 제외한다.
        "purpose_name": item.get("purpose") or "",
        "work_name": item.get("work") or "",
        "title": "",
        "receipt_date": item.get("receipt_date"),
        # 운영 행에는 기준시점이 없다. 파싱 DB의 AppraisalDate가 있으면 그것을 쓴다.
        "base_date": item.get("appraisal_date"),
        "review_target": True,
        "comparability": "COMPARABLE",
        "deviation_direction": item.get("deviation_direction") or "",
        "gap_amount": _gap_amount(item),
        "lower_fee": item.get("lower_fee"),
        "upper_fee": item.get("upper_fee"),
    }


def _gap_amount(item: "dict[str, Any]") -> "float | None":
    """넘어선 경계 대비 차액. 계산 사유(수수료차액발생) 판정에 쓰인다.

    경계를 넘지 않은 행은 None이다. 기준 내 행에 하한 대비 차액을 넘기면
    `수수료차액발생 0`처럼 뜻 없는 사유가 붙는다(실측 상반 137건 중 54건).
    """
    direction = str(item.get("deviation_direction") or "")
    if direction not in (DEVIATION_BELOW, DEVIATION_ABOVE):
        return None
    actual = item.get("actual_fee")
    bound = (
        item.get("upper_fee")
        if direction == DEVIATION_ABOVE
        else item.get("lower_fee")
    )
    if actual is None or bound is None:
        return None
    try:
        return float(actual) - float(bound)
    except (TypeError, ValueError):
        return None


def _needs_opinion(item: "dict[str, Any]") -> bool:
    """의견이 필요한 행인지. 금액이 이탈했거나 비교 자체가 불가한 행이다."""
    if str(item.get("fee_state") or ""):
        return True
    return str(item.get("deviation_direction") or "") in (
        DEVIATION_BELOW,
        DEVIATION_ABOVE,
        DEVIATION_MISSING,
    )


# 대표 후보 선정 순위. 후보가 여러 개면 화면·엑셀이 같은 하나를 써야 한다.
# 근거 등급이 강한 쪽이 이긴다. 등급이 같으면 어디서 나온 근거인지로 가른다.
_GRADE_RANK = {
    "STRUCTURED_CASE_SIGNAL": 0,   # APWorks 사건에 등록된 실제 보수사유
    "DIRECT": 1,                   # 감정서 원문(교정본) + 섹션 문맥
    "CALCULATED": 2,               # 날짜·금액 계산
    "CONTEXT_ONLY": 3,             # 평가목적·업무구분 정황
    "NO_DOCUMENT": 4,
    "AMBIGUOUS": 5,
    "NONE": 6,
}
_SOURCE_RANK = (
    "APWorks사건", "본문(교정본)", "본문", "이력", "시점", "목적", "계산",
)
# 기본 요율체계는 "특이 신호 없음"이라는 뜻이다. 다른 후보가 있으면 대표가 될 수 없다.
BASE_RATE_CODE = 1


def _candidate_rank(candidate: "dict[str, Any]") -> "tuple[int, ...]":
    source = str(candidate.get("source") or "")
    grade = str(candidate.get("grade") or "NONE")
    # 양쪽 규칙이 같은 결론이면 교차검증된 것이라 가장 믿을 만하다.
    corroborated = 0 if f"+{ORIGIN}" in source else 1
    base_rate = 1 if candidate.get("code") == BASE_RATE_CODE else 0
    source_rank = next(
        (index for index, name in enumerate(_SOURCE_RANK) if name in source),
        len(_SOURCE_RANK),
    )
    # 코드가 없는 후보는 조문을 특정하지 못한 것이라 뒤로 보낸다.
    codeless = 0 if candidate.get("code") is not None else 1
    # 조문 코드를 특정한 후보가 등급보다 먼저다 — 자동판별은 보수기준을 가리는 일이고,
    # 코드가 없으면 화면의 일치/불일치 판정에 쓰이지 못한다.
    return (
        base_rate, corroborated, codeless, _GRADE_RANK.get(grade, 6), source_rank,
    )


def pick_primary(
    candidates: "list[dict[str, Any]]",
) -> "dict[str, Any] | None":
    """후보 여러 개에서 대표 하나를 고른다.

    입력된 보수기준 코드(entered_code)는 순위에 넣지 않는다. 넣으면 담당자가 고른 값이
    항상 대표가 되어 코드 불일치가 화면에서 사라진다.
    """
    if not candidates:
        return None
    return min(candidates, key=_candidate_rank)


def _merge_candidates(
    existing: "list[dict[str, Any]]",
    ours: "list[dict[str, Any]]",
) -> "list[dict[str, Any]]":
    """같은 코드는 합치고 새 코드는 뒤에 붙인다. 운영 후보를 지우지 않는다."""
    merged = [dict(candidate) for candidate in existing]
    by_code = {
        candidate.get("code"): candidate
        for candidate in merged
        if candidate.get("code") is not None
    }
    for candidate in ours:
        code = candidate.get("code")
        target = by_code.get(code) if code is not None else None
        if target is not None:
            # 같은 결론이면 근거만 보강한다. 어느 쪽이 봤는지 남긴다.
            target["source"] = f"{target['source']}+{ORIGIN}"
            extra = str(candidate.get("evidence") or "").strip()
            if extra and extra not in str(target.get("evidence") or ""):
                target["evidence"] = f"{target.get('evidence') or ''} / {extra}".strip(" /")
            target.setdefault("grade", candidate.get("grade"))
            target.setdefault("ab_keyword", candidate.get("ab_keyword"))
            continue
        merged.append({
            **candidate,
            "source": f"{ORIGIN}:{candidate.get('source') or ''}".rstrip(":"),
        })
    return merged


def attach_review_evidence(
    items: "list[dict[str, Any]]",
    *,
    include_jun: bool = True,
) -> "dict[str, Any]":
    """행 목록에 보수기준 검토 판정을 후보 형식으로 덧붙인다(제자리 수정).

    반환: 근거 조회 요약. jun_error·apw_error가 담기므로 화면에 실패를 알릴 수 있다.
    행은 절대 지우지 않는다 — 근거를 못 찾아도 목록에서 빠지면 안 된다.
    """
    if not items:
        return {}
    adapters = [_adapter_item(item) for item in items]
    summary = enrich_items(adapters, include_jun=include_jun)

    by_row = {
        adapter.get("source_row_number"): adapter for adapter in adapters
    }
    for item in items:
        adapter = by_row.get(item.get("source_row_number"))
        if adapter is None:
            continue
        reason = str(adapter.get("suggested_reason_code") or "")
        keyword = str(adapter.get("suggested_opinion") or "")
        # 사유를 특정하지 못한 행. 우리 내부 사정(JUN 문서 없음 등)을 의견에 적지 않는다.
        # 조치가 필요한 행이면 `확인필요`, 기준 내 정상 행이면 공란이다 — 기준 내 행까지
        # 확인 큐에 넣으면 실측 63건이 노이즈가 된다.
        if reason in _NON_REASON:
            keyword = NEEDS_CHECK if _needs_opinion(item) else ""

        ours = to_candidates(adapter) if keyword else []
        merged = _merge_candidates(item.get("candidates") or [], ours)
        item["candidates"] = merged
        # 대표 후보 하나. 화면은 이 한 줄만 보여주고 나머지는 감사 근거로 남는다.
        primary = pick_primary(merged)
        item["primary_candidate"] = primary
        item["primary_label"] = str((primary or {}).get("label") or "")
        item["primary_source"] = str((primary or {}).get("source") or "")
        item["primary_code"] = (primary or {}).get("code")

        # 의견 초기값을 대표 후보와 같은 값으로 맞춘다. 두 값이 다르면 담당자가
        # 어느 쪽이 맞는지 알 수 없다.
        # 대표 후보가 기본 요율체계가 아니면 '기준 내' 행이라도 조문 사유를 적는다.
        # 확인 큐(_needs_opinion)는 그대로 둔다 — 여기서 채우는 건 '확인필요'가 아니라
        # 조문 이름이라 노이즈가 되지 않는다. 실측 49건이 이 조건으로 채워지고
        # 전부 ab_keyword 가 나온다(산업체시설 할증·소급감정·재평가 등, AB 없음 0건).
        _primary_code = (primary or {}).get("code")
        _has_special = bool(_primary_code) and _primary_code != BASE_RATE_CODE
        if keyword or _needs_opinion(item) or _has_special:
            code = _primary_code
            derived = (
                ""
                if code == BASE_RATE_CODE
                else str((primary or {}).get("ab_keyword") or "")
                or ab_keyword_for(code)
            )
            # 대표 후보에서 뽑을 수 있으면 그것을 쓴다 — 운영 규칙이 찾은 사유도
            # 여기서 의견으로 채워진다(우리가 못 찾아도 최대한 메꾼다).
            keyword = derived or keyword
            # 그래도 비어 있고 조치가 필요한 행이면 무엇을 할지 한 마디로 남긴다.
            if not keyword and _needs_opinion(item):
                keyword = NEEDS_CHECK
        # 재무팀 엑셀을 계속 쓰는 경우를 위해 AB 핵심어와 등급을 행에도 남긴다.
        item["ab_keyword"] = keyword
        item["evidence_grade"] = str(adapter.get("evidence_level") or "")
        item["jun_search_state"] = str(adapter.get("search_state") or "")
        # 자동 제안은 저장된 의견을 덮지 않는다(select_view의 우선순위 참조).
        item["suggested_opinion"] = keyword
    return summary
