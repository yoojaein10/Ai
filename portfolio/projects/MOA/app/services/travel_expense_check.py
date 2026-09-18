"""출장비 '같은 날 여러 곳' 청구 규칙 점검 (2026-09-11).

입력은 직원들이 델파이(APWorks)에서 하고, MOA 리스트는 규칙에 어긋난 줄만 빨간색으로 표시하고
비고에 이유를 적는다 (사용자 결정 2026-09-11). 규칙은 최병천 님 하나은행 NPL 정산 엑셀
(01-2510-7-0057, 42건)에서 읽은 것이고 여비표(2014.4.16)에는 없다 — 40,000 은 서울 시내 기준액,
60,000 은 표에 없는 관행값이라 근거 확인이 남아 있다.

작성자·출장일 묶음 안에서:
  1. 기준액이 가장 큰 지역 한 건은 전액 (델파이 선택지 80·50·20% 도 허용)
  2. 같은 날 다른 시·군은 그곳 기준액의 50%, 하한 60,000 (기준액이 그보다 작으면 기준액 — 서울 40,000)
  3. 이미 간 시·군(광역시·서울은 전체) 의 추가 물건은 40,000
지역 단위는 요율표 Region 이름(창원시 여러 구 = 창원시, 부산 모든 구 = 부산광역시).
소재지는 감정서 대표 물건(APW_Inventory Top) 지역코드라 한 감정서에 물건이 여럿인 NPL 건은 이 점검으로 못 잡는다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.travel_expense import _CHUNK, _db

SAME_REGION_EXTRA = 40_000   # 같은 시·군 추가 물건
OTHER_REGION_MIN = 60_000    # 같은 날 다른 시·군 하한


def rate_table(db: Session) -> "dict[str, dict[str, Any]]":
    rows = db.execute(text(f"SELECT Region, Reg, ManCul_Amt, PAMT_80, PAMT_50, PAMT_20 FROM {_db()}.dbo.apw_yji_manculamt")).mappings().all()
    num = lambda v: int(float(v)) if v not in (None, "") else 0  # noqa: E731
    return {str(r["Reg"]).strip(): {"region": str(r["Region"] or "").strip(), "base": num(r["ManCul_Amt"]),
                                     "p80": num(r["PAMT_80"]), "p50": num(r["PAMT_50"]), "p20": num(r["PAMT_20"])}
            for r in rows}


def region_rate(reg: Any, rates: "dict[str, dict[str, Any]]") -> "dict[str, Any] | None":
    code = str(reg or "").strip()
    return rates.get(code[:5]) or rates.get(code[:2] + "000")


def other_region_amount(rate: "dict[str, Any]") -> int:
    half = rate["p50"] or round(rate["base"] / 2)
    return min(max(half, OTHER_REGION_MIN), rate["base"])


def check_day(rows: "list[dict[str, Any]]", rates: "dict[str, dict[str, Any]]") -> "dict[int, str]":
    """한 작성자의 하루치 행(seq·reg·amount) → 어긋난 seq 마다 비고 문구. 금액 0·요율 없는 행은 건너뛴다."""
    groups: "dict[tuple[str, str], tuple[dict[str, Any], list[dict[str, Any]]]]" = {}
    for row in rows:
        rate = region_rate(row.get("reg"), rates)
        if not rate or int(row.get("amount") or 0) <= 0:
            continue
        key = (str(row.get("reg") or "")[:2], rate["region"])
        groups.setdefault(key, (rate, []))[1].append(row)
    notes: "dict[int, str]" = {}
    for idx, (rate, group) in enumerate(sorted(groups.values(), key=lambda v: -v[0]["base"])):
        group.sort(key=lambda r: -int(r["amount"]))
        head, rest = group[0], group[1:]
        amount = int(head["amount"])
        region = rate["region"]
        if idx == 0:
            allowed = {rate["base"], rate["p80"], rate["p50"], rate["p20"]} - {0}
            if amount not in allowed:
                notes[int(head["seq"])] = f"출장비 {amount:,}원 → 그날 첫 지역({region})은 기준액 {rate['base']:,}원"
        else:
            expected = other_region_amount(rate)
            if amount != expected:
                why = (f"기준액 {rate['base']:,}의 50%, 하한 {OTHER_REGION_MIN:,}" if rate["base"] > OTHER_REGION_MIN
                       else f"기준액 {rate['base']:,}")   # 서울처럼 기준액이 하한보다 작으면 기준액 그대로
                notes[int(head["seq"])] = f"출장비 {amount:,}원 → 같은 날 다른 시·군({region})은 {expected:,}원 ({why})"
        for row in rest:
            extra = int(row["amount"])
            if extra != SAME_REGION_EXTRA:
                notes[int(row["seq"])] = f"출장비 {extra:,}원 → 같은 지역({region}) 추가 물건은 {SAME_REGION_EXTRA:,}원"
    return notes


def attach_checks(db: Session, rows: "list[dict[str, Any]]") -> None:
    """리스트 행마다 check_note 를 붙인다. 조회 조건과 무관하게 그 작성자·그날의 행 전부를 읽어 판정한다
    (감정서번호로 한 줄만 조회해도 같은 날 다른 건과 같이 봐야 맞다)."""
    for row in rows:
        row["check_note"] = ""
    dated = [r for r in rows if r.get("cul_date") and r.get("write_name")]
    if not dated:
        return
    writers = sorted({str(r["write_name"]) for r in dated})
    lo, hi = min(r["cul_date"] for r in dated), max(r["cul_date"] for r in dated)
    rates = rate_table(db)
    day_rows: "dict[tuple[str, str], list[dict[str, Any]]]" = {}
    for start in range(0, len(writers), _CHUNK):
        chunk = writers[start:start + _CHUNK]
        placeholders = ",".join(f"CAST(:w{i} AS VARCHAR(12))" for i in range(len(chunk)))
        params: "dict[str, Any]" = {f"w{i}": v for i, v in enumerate(chunk)}
        params.update(lo=lo, hi=hi)
        found = db.execute(
            text(f"""
                SET NOCOUNT ON;
                SELECT a.Seq, a.Write_Name, CONVERT(varchar(10), a.Cul_Date, 23) AS cul_date,
                       ISNULL(a.Cul_In, 0) + ISNULL(a.Cul_Out, 0) AS amount, i.REG AS reg
                FROM {_db()}.dbo.apw_yji_manculjang a
                LEFT JOIN {_db()}.dbo.APW_Master m ON m.DocID = a.Docid
                LEFT JOIN {_db()}.dbo.APW_Inventory i ON i.MasterID = m.MasterID AND i.SEQ = m.TopInventorySEQ
                WHERE a.Write_Name IN ({placeholders}) AND a.Cul_Date >= :lo AND a.Cul_Date < DATEADD(day, 1, :hi)
            """),
            params,
        ).mappings().all()
        for r in found:
            key = (str(r["Write_Name"] or "").strip(), str(r["cul_date"]))
            day_rows.setdefault(key, []).append({"seq": int(r["Seq"]), "reg": r["reg"], "amount": int(float(r["amount"] or 0))})
    wanted = {(str(r["write_name"]), str(r["cul_date"])) for r in dated}
    notes: "dict[int, str]" = {}
    for key in wanted:
        notes.update(check_day(day_rows.get(key, []), rates))
    for row in rows:
        row["check_note"] = notes.get(int(row["seq"]), "")
