# -*- coding: utf-8 -*-
"""SP_IW_S_TaskStats_Mon 결과 컬럼 정의 (데이터 계약).

컬럼 순서가 연도 분기에 따라 다르므로 반드시 이름 기준으로 매핑한다.
'HF' 표시명은 임시(HFDocid 400 분기) — 업무 확정 시 여기만 수정.
"""

# kind: "time" = 시간/금액 쌍(시간은 "시:분" 문자열), "count" = 건수/금액 쌍
GROUPS = [
    {
        "key": "manpower",
        "label": "인력 투입",
        "kind": "time",
        "items": [
            {"label": "남직원",     "qty": "M1Time",  "price": "M1Price"},
            {"label": "수습남",     "qty": "SMTime",  "price": "SMPrice"},
            {"label": "소속평가사", "qty": "SoPTime", "price": "SoPPrice"},
            {"label": "수습평가사", "qty": "SuPTime", "price": "SuPrice"},
        ],
    },
    {
        "key": "basic",
        "label": "기본 처리",
        "kind": "count",
        "items": [
            {"label": "접수", "qty": "JubC", "price": "JubP"},
            {"label": "발송", "qty": "BalC", "price": "BalP"},
            {"label": "심사", "qty": "SimC", "price": "SimP"},
        ],
    },
    {
        "key": "desk",
        "label": "탁상 업무",
        "kind": "count",
        "items": [
            {"label": "탁상접수",    "qty": "TSJubC",  "price": "TSJubP"},
            {"label": "탁상접수 HF", "qty": "TSJubC2", "price": "TSJubP2"},
            {"label": "탁상감정",    "qty": "TSC",     "price": "TSP"},
            {"label": "탁상감정 HF", "qty": "TSC2",    "price": "TSP2"},
        ],
    },
    {
        "key": "special",
        "label": "특수 업무",
        "kind": "count",
        "items": [
            {"label": "Visio",      "qty": "VISIC",  "price": "VISIP"},
            {"label": "수습 Visio", "qty": "SVISIC", "price": "SVISIP"},
            {"label": "시조위",     "qty": "SIJOC",  "price": "SIJOP"},
            {"label": "검산",       "qty": "CHKC",   "price": "CHKP"},
            {"label": "약식",       "qty": "YAKC",   "price": "YAKP"},
            {"label": "KB 약식",    "qty": "KBYAKC", "price": "KBYAKP"},
        ],
    },
    {
        "key": "cost",
        "label": "비용·기타",
        "kind": "count",
        "items": [
            {"label": "협회심사비",          "qty": "HSIMC",      "price": "HSIMP"},
            {"label": "감정서경비(문서없음)", "qty": "GamX_Cnt",   "price": "GamX_Price"},
            {"label": "감정서경비(문서있음)", "qty": "GamO_Cnt",   "price": "GamO_Price"},
            {"label": "HUG 탁상접수",        "qty": "HugJup_Cnt", "price": "HugJup_Price"},
            {"label": "HUG 탁상감정",        "qty": "HugGam_Cnt", "price": "HugGam_Price"},
        ],
    },
]

# 검산(CHKC/CHKP)은 현재 프로시저에서 항상 0 (집계 로직 주석 처리 상태)
ALWAYS_ZERO = {"CHKC", "CHKP"}


def all_columns():
    """Manager를 제외한 데이터 컬럼 이름 전체 (그룹 순서대로)."""
    cols = []
    for g in GROUPS:
        for it in g["items"]:
            cols.append(it["qty"])
            cols.append(it["price"])
    return cols
