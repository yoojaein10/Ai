# -*- coding: utf-8 -*-
"""SP 메타데이터 정규화·fingerprint·pin·구조 diff (지시 §10, §11).

- READ_SP_METADATA 조회 행을 정규화한다(실제 레코드 값 미포함).
- 정규화 항목으로 SHA-256 fingerprint 를 계산한다.
  포함: schema/객체명, parameter_id/이름, 입출력 방향, 사용자/기반 타입, 길이/정밀도/스케일.
  제외: 서버명/로그인/자격증명/연결 문자열/실제 레코드/PII.
- 기대 fingerprint 는 사람이 diff 검토 후 커밋한 상수로만 pin 한다(자동 pin 금지).
  pin 이 없으면 provisional 로만 보고하고 metadata_verified=true 로 만들지 않는다.
- 현재 ts_db_writer 정의와 정규화된 구조 diff 를 만든다(레코드 값 미포함). SP 는 실행하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import ro_query
import ts_db_writer

# 사람이 diff 검토 후 커밋할 상수. None 이면 미pin(provisional). 자동 갱신 금지.
PINNED_FINGERPRINT: str | None = None

# READ_SP_METADATA 컬럼 인덱스
(_C_PID, _C_NAME, _C_ISOUT, _C_TYPE, _C_ISUDT,
 _C_BASETYPE, _C_MAXLEN, _C_PREC, _C_SCALE) = range(9)


@dataclass(frozen=True)
class NormalizedParam:
    parameter_id: int
    name: str
    is_output: bool
    type_name: str
    is_user_defined: bool
    base_type_name: str
    max_length: int | None
    precision: int | None
    scale: int | None


def _to_int_or_none(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def normalize_rows(rows) -> list[NormalizedParam]:
    """카탈로그 행 → 정규화 파라미터 목록(parameter_id 오름차순)."""
    out = []
    for r in rows or []:
        out.append(NormalizedParam(
            parameter_id=_to_int_or_none(r[_C_PID]) or 0,
            name=(r[_C_NAME] or "").strip().lstrip("@"),
            is_output=bool(r[_C_ISOUT]),
            type_name=(r[_C_TYPE] or "").strip(),
            is_user_defined=bool(r[_C_ISUDT]),
            base_type_name=(r[_C_BASETYPE] or "").strip(),
            max_length=_to_int_or_none(r[_C_MAXLEN]),
            precision=_to_int_or_none(r[_C_PREC]),
            scale=_to_int_or_none(r[_C_SCALE]),
        ))
    out.sort(key=lambda p: p.parameter_id)
    return out


def _canonical(schema: str, obj: str, params: list[NormalizedParam]) -> str:
    """fingerprint 대상 정규화 문자열. 결정적 직렬화."""
    payload = {
        "schema": schema,
        "object": obj,
        "params": [
            {
                "parameter_id": p.parameter_id,
                "name": p.name,
                "is_output": p.is_output,
                "type_name": p.type_name,
                "is_user_defined": p.is_user_defined,
                "base_type_name": p.base_type_name,
                "max_length": p.max_length,
                "precision": p.precision,
                "scale": p.scale,
            }
            for p in params
        ],
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"))


def compute_fingerprint(params: list[NormalizedParam],
                        *, schema: str = ro_query.SP_SCHEMA,
                        obj: str = ro_query.SP_OBJECT) -> str:
    """정규화 파라미터로 SHA-256 fingerprint 계산(hex)."""
    canonical = _canonical(schema, obj, params)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evaluate_pin(computed: str, *, allowlist_target_ok: bool,
                 pinned: str | None = PINNED_FINGERPRINT) -> dict:
    """pin 정책 평가.

    - pinned 없음 → status='provisional', metadata_verified=False.
    - pinned 있고 (computed==pinned) 이고 allowlist 대상 DB 이면 → verified.
    - 불일치 → status='mismatch', metadata_verified=False.
    """
    if pinned is None:
        return {"status": "provisional", "metadata_verified": False,
                "computed": computed}
    if computed == pinned and allowlist_target_ok:
        return {"status": "verified", "metadata_verified": True,
                "computed": computed}
    return {"status": "mismatch", "metadata_verified": False,
            "computed": computed}


# ───────────────────────────── 구조 diff (vs provisional 정의) ─────────────────────────────
def _code_side_params() -> list[dict]:
    """ts_db_writer 의 provisional 정의를 비교용으로 정규화(이름/방향/순서)."""
    params = []
    pid = 0
    for spec in ts_db_writer.INPUT_PARAM_SPECS:
        pid += 1
        params.append({"parameter_id": pid, "name": spec.name,
                       "is_output": False, "provisional_type": spec.sqltype,
                       "provisional_len": spec.length})
    for spec in ts_db_writer.OUTPUT_PARAM_SPECS:
        pid += 1
        params.append({"parameter_id": pid, "name": spec.name,
                       "is_output": True, "provisional_type": spec.sqltype,
                       "provisional_len": spec.length})
    return params


def structure_diff(db_params: list[NormalizedParam]) -> dict:
    """DB 카탈로그 파라미터 vs 코드측 provisional 정의의 구조 diff.

    레코드 값은 포함하지 않는다. NULL 허용/기본값처럼 카탈로그만으로 확정 불가한
    의미는 unknown/provisional 로 표시한다.
    """
    code = _code_side_params()
    code_names = [c["name"] for c in code]
    db_names = [p.name for p in db_params]
    code_set, db_set = set(code_names), set(db_names)

    only_in_db = [n for n in db_names if n not in code_set]
    only_in_code = [n for n in code_names if n not in db_set]

    # 방향 불일치(공통 이름에 한해)
    code_dir = {c["name"]: c["is_output"] for c in code}
    db_dir = {p.name: p.is_output for p in db_params}
    direction_mismatch = sorted(
        n for n in (code_set & db_set) if code_dir[n] != db_dir[n])

    # 순서 diff (공통 이름의 상대 순서)
    common_code_order = [n for n in code_names if n in db_set]
    common_db_order = [n for n in db_names if n in code_set]
    order_matches = common_code_order == common_db_order

    return {
        "db_param_count": len(db_names),
        "code_param_count": len(code_names),
        "only_in_db": only_in_db,
        "only_in_code": only_in_code,
        "direction_mismatch": direction_mismatch,
        "order_matches": order_matches,
        # 카탈로그만으로 확정 불가 — 사람이 검토
        "unknown_semantics": ["nullability", "default_value"],
        "type_comparison": "provisional (code side is provisional_report)",
    }
