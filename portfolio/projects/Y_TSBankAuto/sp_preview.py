# -*- coding: utf-8 -*-
"""SP 파라미터 미리보기 (지시 §13).

- 각 파라미터의 출처를 구분한다: NULL / 고정값 / PDF 파생값 / DB 조회값.
- PII·내부 식별자는 마스킹한다(원문 값 미노출).
- provisional·미pin 경고를 표시한다.
- SP 실행 버튼은 만들지 않으며 execute_enabled 는 항상 False.
- 이 모듈은 sp_spec(스펙/빌더)만 import 한다. execute_sp/commit 을 import·참조하지 않는다.

format_preview_lines() 는 tkinter 없이 단위 테스트 가능한 순수 함수다.
"""
from __future__ import annotations

import sp_spec

# 출처 라벨
SRC_NULL = "NULL"
SRC_FIXED = "고정값"
SRC_PDF = "PDF"
SRC_DB = "DB조회"


def _classify_source(name: str, value) -> str:
    if value is None or value == "":
        return SRC_NULL
    if name in sp_spec.FIXED_PARAMS:
        return SRC_FIXED
    if name in sp_spec.DB_DERIVED_PARAMS:
        return SRC_DB
    return SRC_PDF


def _display_value(name: str, value, source: str) -> str:
    """미리보기 표시값. 원문 PII 미노출.

    - NULL: 'NULL'
    - 고정값(비PII 상수): 실제 값 표시(Office/AppCode/Jun_Master/Score)
    - 그 외(PDF/DB): 마스킹 표시('‹값 있음›') — 내용·길이 미노출
    """
    if source == SRC_NULL:
        return "NULL"
    if source == SRC_FIXED:
        return str(value)          # 비PII 상수만 노출
    return "‹값 있음(마스킹)›"


def build_preview(params: dict | None, *, metadata_verified: bool = False,
                  sp_definition_source: str | None = None) -> dict:
    """params(dict, 이름→값) → 마스킹·출처 태깅 미리보기 구조.

    params 가 None(비적격) 이면 rows 는 비고, 경고만 담는다.
    """
    src_def = (sp_definition_source
               if sp_definition_source is not None else sp_spec.SP_DEFINITION_SOURCE)

    rows = []
    if params is not None:
        specs = {s.name: s for s in sp_spec.INPUT_PARAM_SPECS}
        for name in sp_spec.INPUT_PARAM_NAMES:
            value = params.get(name)
            source = _classify_source(name, value)
            spec = specs[name]
            rows.append({
                "name": name,
                "sqltype": spec.sqltype,
                "length": spec.length,
                "required": spec.required,
                "forced": spec.forced,
                "source": source,
                "display": _display_value(name, value, source),
            })

    warnings = []
    pinned = (src_def == "metadata") and metadata_verified
    if not pinned:
        warnings.append("SP 메타데이터 미검증(provisional/미pin) — 실행 차단")
    warnings.append("SP 실행 버튼 없음(영구 비활성). 저장/COMMIT 미연결.")

    # 출처별 개수 요약(값 미노출)
    counts = {SRC_NULL: 0, SRC_FIXED: 0, SRC_PDF: 0, SRC_DB: 0}
    for r in rows:
        counts[r["source"]] += 1

    return {
        "rows": rows,
        "counts": counts,
        "warnings": warnings,
        "provisional": not pinned,
        "sp_name": sp_spec.SP_NAME,
        "sp_definition_source": src_def,
        "execute_enabled": False,      # 항상 False (실행 경로 미연결)
        "param_count": len(rows),
    }


def format_preview_lines(preview: dict) -> list[str]:
    """미리보기 구조 → GUI/로그 표시 라인(마스킹). 원문 미포함."""
    lines = [f"SP: {preview['sp_name']} (정의출처: {preview['sp_definition_source']})"]
    c = preview["counts"]
    lines.append(
        f"파라미터 {preview['param_count']}개 — "
        f"고정 {c[SRC_FIXED]} / PDF {c[SRC_PDF]} / DB조회 {c[SRC_DB]} / NULL {c[SRC_NULL]}")
    for w in preview["warnings"]:
        lines.append(f"※ {w}")
    for r in preview["rows"]:
        req = "필수" if r["required"] else "선택"
        forced = f" [{r['forced']}]" if r["forced"] else ""
        lines.append(f"  - {r['name']} ({r['sqltype']}, {req}): "
                     f"[{r['source']}] {r['display']}{forced}")
    return lines
