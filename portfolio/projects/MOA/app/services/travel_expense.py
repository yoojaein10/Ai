"""출장비 (2026-09-10) — APWorks 델파이 '출장비프로그램'(출장비입력·남직원출장리스트·출장분기리스트)의 MOA 이식.

사용자 확정: 델파이와 **같이 쓴다** → 같은 APWorks 테이블(apw_yji_manculjang·apw_iw_cull_yebi·
apw_yji_culbill_approve·apw_iw_cull_bungi)을 쓰고, 저장·결재·잠금은 기존 프로시저를 그대로 호출해
동작이 갈라지지 않게 한다. 분기는 월 단위('202609'), 결재는 3단계(작성자 제출 0→1→2→3→완료 4,
P2 팀은 1차 생략 — 프로시저 안 규칙) 그대로.

조회만 MOA 방식이다 — 델파이 리스트 프로시저(SP_IW_S_CULBILLLIST)는 한 달 615행에 20초라
(apw_masterex 뷰 통째 조인) 출장비 행을 먼저 뽑고 그 감정서만 뷰에서 IN 으로 붙인다(0.8초 실측).

규칙(델파이 원본 그대로):
  - 기준 출장비는 소재지 지역코드(REG 5자리)로 apw_yji_manculamt 에서 찾고, 서울(REG '11')은 시내,
    아니면 시외 칸에 100/80/50/20% 중 고른 값을 넣는다.
  - 내 감정서 목록 = 조사자(Charge)에 내 이름이 있는 본사 2024년 이후 감정서 중 내가 아직 안 적었고
    적힌 합계가 기준액에 못 미치는 것.
  - 수정·삭제는 미상신(0) 상태의 내 것만. 제출은 미상신 내 것, 결재는 내 등급과 상태가 같은 것,
    반려는 내 등급과 같은 상태(3급은 완료도) — 사유 필수.
"""

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings

STATE_LABELS = {0: "미상신", 1: "1차결재", 2: "2차결재", 3: "3차결재", 4: "완료"}
RATIOS = (100, 80, 50, 20)
AMOUNT_FIELDS = ("cul_in", "cul_out", "regis_copy", "toji_use", "toji_dae", "build_dae", "jijuck", "mul_amt")
BILL_FIELDS = ("yebi", "muljosabi", "tojosabi", "gongbu", "silbi", "yongyeuk")
HEAD_OFFICE = "10"
_CHUNK = 500


class TravelExpenseError(ValueError):
    pass


def _db() -> str:
    name = get_settings().mssql_source_db
    if not name.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return f"[{name}]"


# ── 순수 규칙 ──────────────────────────────────────────────────────────────


def month_key(value: "date | str") -> str:
    """분기(Bungi) 값 — 월 단위 'YYYYMM' (2026-09-10 사용자 확정)."""
    if isinstance(value, date):
        return f"{value.year:04d}{value.month:02d}"
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) < 6:
        raise TravelExpenseError("분기(월) 값이 올바르지 않습니다.")
    return digits[:6]


def is_seoul(reg: Any) -> bool:
    return str(reg or "").strip()[:2] == "11"


def default_amounts(reg: Any, rate: "dict[str, Any]", ratio: int) -> "tuple[int, int]":
    """기준 출장비 → (시내, 시외). 서울은 시내, 그 밖은 시외. 비율 없는 칸(PAMT_50 없음)은 기준액×비율."""
    base = int(float(rate.get("ManCul_Amt") or 0))
    key = {80: "PAMT_80", 50: "PAMT_50", 20: "PAMT_20"}.get(int(ratio))
    amount = base
    if key:
        stored = rate.get(key)
        amount = int(float(stored)) if stored not in (None, "") else int(round(base * int(ratio) / 100))
    return (amount, 0) if is_seoul(reg) else (0, amount)


def totals(row: "dict[str, Any]") -> "dict[str, int]":
    """델파이 CalculHap — 출장비 소계·공부 소계·합계·감정서 여비 합계."""
    num = lambda k: int(float(row.get(k) or 0))  # noqa: E731
    cul = num("cul_in") + num("cul_out")
    gong = sum(num(k) for k in ("regis_copy", "toji_use", "toji_dae", "build_dae", "jijuck", "mul_amt"))
    gam = sum(num(k) for k in BILL_FIELDS)
    return {"cul_total": cul, "gong_total": gong, "amount_total": cul + gong, "bill_total": gam}


def can_edit(row: "dict[str, Any]", user: str) -> bool:
    """미상신(0) 상태의 내 것만 고치거나 지운다 (델파이 N2·N3)."""
    return int(row.get("appro_state") or 0) == 0 and str(row.get("write_name") or "").strip() == user.strip()


def approval_allowed(action: str, state: int, grade: "int | None", is_own: bool) -> bool:
    """결재 동작 허용 규칙 (델파이 Save(1)·Save(2)·Unit1 반려).

    submit  작성자가 미상신(0) 내 것을 올린다 (등급 무관).
    approve 내 등급과 상태가 같을 때 — 1급은 1차결재(1), 2급은 2차(2), 3급은 3차(3).
    reject  내 등급과 상태가 같을 때, 3급은 완료(4)도 되돌릴 수 있다.
    """
    state = int(state)
    if action == "submit":
        return state == 0 and is_own
    if grade is None or grade <= 0:
        return False
    if action == "approve":
        return state == grade
    if action == "reject":
        return state == grade or (grade == 3 and state == 4)
    return False


def month_options(today: "date | None" = None, before: int = 6, after: int = 1) -> "list[str]":
    """월 선택지 — 이번 달 앞뒤."""
    today = today or date.today()
    y, m = today.year, today.month
    result = []
    for delta in range(-before, after + 1):
        yy, mm = y, m + delta
        while mm < 1:
            yy, mm = yy - 1, mm + 12
        while mm > 12:
            yy, mm = yy + 1, mm - 12
        result.append(f"{yy:04d}{mm:02d}")
    return result


# ── 권한·기준 ───────────────────────────────────────────────────────────────


def approver_grade(db: Session, name: str) -> "int | None":
    """결재자 명단(apw_yji_approman, CULBILL)의 등급. 명단에 없으면 None(일반 작성자)."""
    row = db.execute(
        text(f"SELECT TOP 1 ApproGrade FROM {_db()}.dbo.apw_yji_approman WHERE ApproModul = 'CULBILL' AND ApproNAME = :n"),
        {"n": name},
    ).first()
    return int(row[0]) if row else None


def rate_for(db: Session, reg: Any) -> "dict[str, Any]":
    row = db.execute(
        text(f"SELECT TOP 1 Region, Reg, ManCul_Amt, PAMT_80, PAMT_50, PAMT_20 FROM {_db()}.dbo.apw_yji_manculamt WHERE Reg = :r"),
        {"r": str(reg or "").strip()[:5]},
    ).mappings().first()
    return dict(row) if row else {}


# ── 입력 ────────────────────────────────────────────────────────────────────


def my_docs(db: Session, name: str) -> "list[dict[str, Any]]":
    """내가 아직 출장비를 안 적은(또는 기준액 미달) 담당 감정서 — 델파이 SP_IW_S_CULLIST 재현."""
    # 뷰(apw_masterex)는 조사자 이름 검색 한 번만(1.3초 실측) — 합계·기준액은 작은 표에서 따로 붙인다.
    # 뷰에 GROUP BY·NOT IN 을 같이 걸면 5초가 걸렸다.
    docs = db.execute(
        text(f"""
            SET NOCOUNT ON;
            SELECT M.DocID AS doc_id, M.Address AS address, M.LStatus AS status, M.Manager AS manager, M.REG AS reg,
                   CONVERT(varchar(10), M.ReceiptDate, 23) AS receipt_date
            FROM {_db()}.dbo.apw_masterex M
            WHERE M.ReceiptDate > '2024-01-01' AND M.Office = :office AND M.Charge LIKE '%' + :n + '%'
            ORDER BY M.ReceiptDate DESC
        """),
        {"office": HEAD_OFFICE, "n": name},
    ).mappings().all()
    if not docs:
        return []
    ids = [str(r["doc_id"]).strip() for r in docs]
    placeholders = ",".join(f"CAST(:d{i} AS VARCHAR(30))" for i in range(len(ids)))
    params = {f"d{i}": v for i, v in enumerate(ids)}
    entered = db.execute(
        text(f"""
            SELECT Docid, SUM(ISNULL(Cul_In, 0) + ISNULL(Cul_Out, 0)) AS total,
                   SUM(CASE WHEN Write_Name = :n THEN 1 ELSE 0 END) AS mine
            FROM {_db()}.dbo.apw_yji_manculjang WHERE Docid IN ({placeholders}) GROUP BY Docid
        """),
        {**params, "n": name},
    ).all()
    sums = {str(r[0]).strip(): (int(float(r[1] or 0)), int(r[2] or 0)) for r in entered}
    rates = {str(r[0]).strip(): int(float(r[1] or 0)) for r in db.execute(
        text(f"SELECT Reg, ManCul_Amt FROM {_db()}.dbo.apw_yji_manculamt")
    ).all()}
    result = []
    for r in docs:
        doc = str(r["doc_id"]).strip()
        total, mine = sums.get(doc, (0, 0))
        base = rates.get(str(r["reg"] or "").strip()[:5], 0)
        if mine or total >= base:
            continue
        result.append({
            "doc_id": doc, "address": (r["address"] or "").strip(), "status": r["status"], "manager": r["manager"],
            "receipt_date": r["receipt_date"], "total": total, "base_amount": base,
        })
    return result


def draft(db: Session, doc_id: str, seq: int = 0) -> "dict[str, Any]":
    """입력 폼 — 델파이 SP_IW_S_CULBILL (LIST/SUSU 공통). seq=0 이면 새 입력, 아니면 그 행."""
    row = db.execute(
        text(f"SET NOCOUNT ON; EXEC {_db()}.dbo.SP_IW_S_CULBILL :doc, :seq, :gubun"),
        {"doc": doc_id.strip(), "seq": int(seq), "gubun": "LIST" if seq else "SUSU"},
    ).mappings().first()
    if row is None:
        raise TravelExpenseError("감정서를 찾을 수 없습니다.")
    r = dict(row)
    def num(k): return int(float(r.get(k) or 0))  # noqa: E306
    return {
        "seq": int(r["SEQ"]) if r.get("SEQ") else 0, "doc_id": doc_id.strip(),
        "manager": r.get("Manager"), "address": r.get("ADDR"),
        "send_date": r["Senddate"].date().isoformat() if r.get("Senddate") else None,
        "cul_date": r["Cul_Date"].date().isoformat() if r.get("Cul_Date") else None,
        "reg": r.get("REG"), "is_seoul": is_seoul(r.get("REG")),
        "rate": {"ManCul_Amt": num("ManCul_Amt"), "PAMT_80": num("PAMT_80"), "PAMT_50": num("PAMT_50") or None, "PAMT_20": num("PAMT_20")},
        "cul_in": num("Cul_In"), "cul_out": num("Cul_Out"), "regis_copy": num("Regis_Copy"), "toji_use": num("Toji_Use"),
        "toji_dae": num("Toji_Dae"), "build_dae": num("Build_Dae"), "jijuck": num("jijuck"),
        "mul_remark": (r.get("Mul_Remark") or "").strip(), "mul_amt": num("Mul_Amt"),
        "yebi": num("yebi"), "muljosabi": num("MulJoSaBi"), "tojosabi": num("ToJoSaBi"),
        "gongbu": num("GongBu"), "silbi": num("Silbi"), "yongyeuk": num("YongYeuk"),
        "bungi": (r.get("Bungi") or "").strip(), "total_result": (r.get("TotalResult") or "").strip(),
        "bigo": (r.get("Bigo") or "").strip(),
    }


def _row_state(db: Session, seq: int, doc_id: str) -> "dict[str, Any] | None":
    row = db.execute(
        text(f"SELECT Seq, Docid, Write_Name, ApproState, TotalResult, Bungi FROM {_db()}.dbo.apw_yji_manculjang WHERE Seq = :s AND Docid = :d"),
        {"s": int(seq), "d": doc_id},
    ).mappings().first()
    return dict(row) if row else None


def save(db: Session, name: str, payload: "dict[str, Any]") -> "dict[str, Any]":
    """저장 — 델파이 SP_IW_IU_CULBILL 호출(NEW/EDIT). 분기는 출장일의 월."""
    doc_id = str(payload.get("doc_id") or "").strip()
    seq = int(payload.get("seq") or 0)
    cul_date = payload.get("cul_date")
    if not doc_id or not cul_date:
        raise TravelExpenseError("감정서번호와 출장일자는 필수입니다.")
    if seq:
        current = _row_state(db, seq, doc_id)
        if current is None:
            raise TravelExpenseError("수정할 출장비 행이 없습니다.")
        if not can_edit({"appro_state": current["ApproState"], "write_name": current["Write_Name"]}, name):
            raise TravelExpenseError("미상신 상태의 본인 건만 수정할 수 있습니다.")
    amounts = {k: int(payload.get(k) or 0) for k in AMOUNT_FIELDS}
    if any(v < 0 for v in amounts.values()):
        raise TravelExpenseError("금액은 0 이상이어야 합니다.")
    if amounts["cul_in"] + amounts["cul_out"] <= 0 and sum(amounts.values()) <= 0:
        raise TravelExpenseError("출장비나 공부발급비를 하나는 적어야 합니다.")
    bills = {k: int(payload.get(k) or 0) for k in BILL_FIELDS}
    bungi = month_key(date.fromisoformat(str(cul_date)[:10]))
    db.execute(
        text(f"""
            SET NOCOUNT ON;
            EXEC {_db()}.dbo.SP_IW_IU_CULBILL :seq, :doc, :cul_date, :cul_in, :cul_out, :regis_copy, :toji_use, :toji_dae,
                 :build_dae, :jijuck, :mul_remark, :mul_amt, :writer, :yebi, :muljosabi, :tojosabi, :gongbu, :silbi,
                 :yongyeuk, :bungi, :gubun, :bigo
        """),
        {
            "seq": seq, "doc": doc_id, "cul_date": str(cul_date)[:10], **amounts,
            "mul_remark": str(payload.get("mul_remark") or "")[:30], "writer": name[:12], **bills,
            "bungi": bungi, "gubun": "EDIT" if seq else "NEW", "bigo": str(payload.get("bigo") or "")[:200],
        },
    )
    db.commit()
    if not seq:
        seq = int(db.execute(
            text(f"SELECT MAX(Seq) FROM {_db()}.dbo.apw_yji_manculjang WHERE Docid = :d AND Write_Name = :n"),
            {"d": doc_id, "n": name[:12]},
        ).scalar() or 0)
    return {"seq": seq, "doc_id": doc_id, "bungi": bungi}


def delete(db: Session, name: str, seq: int, doc_id: str) -> None:
    """삭제 — 미상신 내 것만 (델파이 N3 와 같은 조건의 DELETE)."""
    current = _row_state(db, seq, doc_id)
    if current is None:
        raise TravelExpenseError("삭제할 출장비 행이 없습니다.")
    if not can_edit({"appro_state": current["ApproState"], "write_name": current["Write_Name"]}, name):
        raise TravelExpenseError("미상신 상태의 본인 건만 삭제할 수 있습니다.")
    db.execute(
        text(f"DELETE FROM {_db()}.dbo.apw_yji_manculjang WHERE Seq = :s AND Docid = :d AND Write_Name = :n"),
        {"s": int(seq), "d": doc_id, "n": name[:12]},
    )
    db.commit()


# ── 리스트·결재 ─────────────────────────────────────────────────────────────


def _master_info(db: Session, doc_ids: "list[str]") -> "dict[str, dict[str, Any]]":
    """감정서 뷰에서 필요한 열만, 감정서번호 IN 으로 (한 달 600건 0.8초 실측)."""
    result: "dict[str, dict[str, Any]]" = {}
    ids = sorted({d for d in doc_ids if d})
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start:start + _CHUNK]
        placeholders = ",".join(f"CAST(:d{i} AS VARCHAR(50))" for i in range(len(chunk)))
        params = {f"d{i}": v for i, v in enumerate(chunk)}
        rows = db.execute(
            text(f"""
                SET NOCOUNT ON;
                SELECT b.DocID, CONVERT(varchar(10), b.ReceiptDate, 23) AS receipt_date, b.LStatus, b.Manager,
                       CONVERT(varchar(10), b.SendDate, 23) AS send_date, e.Name AS result_name,
                       (ISNULL(d.As1,'') + ' ' + ISNULL(d.As2,'') + ' ' + ISNULL(d.As3,'')) AS addr,
                       b.[여비] AS yebi, b.[물건조사비] AS muljosabi, b.[토지조사비] AS tojosabi,
                       b.[공부발급비] AS gongbu, b.[기타실비] AS silbi, b.[특별용역비] AS yongyeuk
                FROM {_db()}.dbo.apw_masterex b
                LEFT JOIN {_db()}.dbo.APW_RegHist d ON d.Eub = b.Eub AND d.Reg = b.Reg AND d.Fuse = 1
                LEFT JOIN {_db()}.dbo.Apw_Result e ON e.Code = b.Result
                WHERE b.DocID IN ({placeholders})
            """),
            params,
        ).mappings().all()
        for r in rows:
            result[str(r["DocID"]).strip()] = dict(r)
    return result


def list_rows(
    db: Session, *, viewer: str, is_approver: bool, bungi: str = "", emp: str = "", doc_id: str = "",
    state: "int | None" = None, date_kind: str = "", date_from: "date | None" = None, date_to: "date | None" = None,
) -> "list[dict[str, Any]]":
    """출장비 리스트 — 결재자는 전체, 아니면 내 것만. 기간은 분기(월)·출장일·접수일·발송일 중 하나."""
    conditions = ["1 = 1"]
    params: "dict[str, Any]" = {}
    join = ""
    if not is_approver:
        emp = viewer
    if emp:
        conditions.append("a.Write_Name = :emp"); params["emp"] = emp
    if doc_id.strip():
        conditions.append("a.Docid = CAST(:doc AS varchar(30))"); params["doc"] = doc_id.strip()
    elif date_kind == "cul" and date_from and date_to:
        conditions.append("a.Cul_Date >= :df AND a.Cul_Date < DATEADD(day, 1, :dt)"); params.update(df=date_from, dt=date_to)
    elif date_kind in ("receipt", "send") and date_from and date_to:
        # 접수일·발송일은 감정서 쪽 날짜 — 원표(APW_Master)에 붙여 SQL 에서 거른다(전체 4.5만 행 스캔 방지)
        column = "ReceiptDate" if date_kind == "receipt" else "SendDate"
        join = f"INNER JOIN {_db()}.dbo.APW_Master m ON m.DocID = a.Docid"
        conditions.append(f"m.{column} >= :df AND m.{column} < DATEADD(day, 1, :dt)"); params.update(df=date_from, dt=date_to)
    elif bungi:
        conditions.append("LEFT(a.Bungi, 6) = :bungi"); params["bungi"] = month_key(bungi)
    else:
        raise TravelExpenseError("월·기간·감정서번호 중 하나는 있어야 합니다.")
    if state is not None and 0 <= int(state) <= 4:
        conditions.append("a.ApproState = :state"); params["state"] = int(state)
    rows = db.execute(
        text(f"""
            SET NOCOUNT ON;
            SELECT a.Seq, a.Docid, a.Write_Name, a.ApproState, a.TotalResult, CONVERT(varchar(10), a.Cul_Date, 23) AS cul_date,
                   a.Cul_In, a.Cul_Out, a.Regis_Copy, a.Toji_Use, a.Toji_Dae, a.Build_Dae, a.Jijuck, a.Mul_Remark, a.Mul_Amt,
                   a.Bungi, a.Bigo, CONVERT(varchar(16), a.Write_Date, 120) AS write_date
            FROM {_db()}.dbo.apw_yji_manculjang a
            {join}
            WHERE {' AND '.join(conditions)}
            ORDER BY a.Cul_Date, a.Write_Name, a.Docid   -- 출장일 순 (2026-09-11 사용자 요청, 예전엔 작성자별)
        """),
        params,
    ).mappings().all()
    info = _master_info(db, [str(r["Docid"]).strip() for r in rows])
    result = []
    for r in rows:
        doc = str(r["Docid"]).strip()
        m = info.get(doc, {})
        item = {
            "seq": int(r["Seq"]), "doc_id": doc, "write_name": (r["Write_Name"] or "").strip(),
            "appro_state": int(r["ApproState"] or 0), "state_label": STATE_LABELS.get(int(r["ApproState"] or 0), str(r["ApproState"])),
            "total_result": (r["TotalResult"] or "").strip(), "cul_date": r["cul_date"], "bungi": (r["Bungi"] or "").strip(),
            "bigo": (r["Bigo"] or "").strip(), "write_date": r["write_date"],
            "receipt_date": m.get("receipt_date"), "status": m.get("LStatus"), "manager": m.get("Manager"),
            "send_date": m.get("send_date") or m.get("result_name"), "address": (m.get("addr") or "").strip(),
            "cul_in": int(float(r["Cul_In"] or 0)), "cul_out": int(float(r["Cul_Out"] or 0)),
            "regis_copy": int(float(r["Regis_Copy"] or 0)), "toji_use": int(float(r["Toji_Use"] or 0)),
            "toji_dae": int(float(r["Toji_Dae"] or 0)), "build_dae": int(float(r["Build_Dae"] or 0)),
            "jijuck": int(float(r["Jijuck"] or 0)), "mul_remark": (r["Mul_Remark"] or "").strip(), "mul_amt": int(float(r["Mul_Amt"] or 0)),
        }
        for k in BILL_FIELDS:
            item[k] = int(float(m.get(k) or 0))
        item.update(totals(item))
        item["editable"] = can_edit(item, viewer)
        result.append(item)
    # 같은 날 여러 곳 청구 규칙 점검 — 어긋난 줄에 check_note (2026-09-11, travel_expense_check)
    from app.services.travel_expense_check import attach_checks
    attach_checks(db, result)
    return result


def summarize(rows: "list[dict[str, Any]]") -> "dict[str, Any]":
    """작성자별 소계와 총계 (델파이 그룹 합계·Sum)."""
    keys = list(AMOUNT_FIELDS) + list(BILL_FIELDS) + ["cul_total", "gong_total", "amount_total", "bill_total"]
    def empty(): return {k: 0 for k in keys} | {"count": 0}  # noqa: E306
    by_writer: "dict[str, dict[str, int]]" = {}
    grand = empty()
    for row in rows:
        bucket = by_writer.setdefault(row["write_name"], empty())
        for k in keys:
            bucket[k] += int(row.get(k) or 0); grand[k] += int(row.get(k) or 0)
        bucket["count"] += 1; grand["count"] += 1
    return {"by_writer": by_writer, "grand": grand}


def approve(
    db: Session, *, name: str, grade: "int | None", action: str, targets: "list[dict[str, Any]]", bigo: str = "",
) -> "dict[str, Any]":
    """제출·결재·반려 — 델파이 SP_IW_CULBILLLIST_IUD('In'/'Cancel') 호출 뒤 분기 잠금 갱신."""
    if action not in ("submit", "approve", "reject"):
        raise TravelExpenseError("동작은 submit·approve·reject 중 하나입니다.")
    if action == "reject" and not bigo.strip():
        raise TravelExpenseError("반려 사유를 적어야 합니다.")
    done, skipped, bungis = [], [], set()
    for t in targets:
        seq, doc = int(t.get("seq") or 0), str(t.get("doc_id") or "").strip()
        current = _row_state(db, seq, doc)
        if current is None:
            skipped.append({"seq": seq, "doc_id": doc, "reason": "행 없음"}); continue
        state = int(current["ApproState"] or 0)
        is_own = str(current["Write_Name"] or "").strip() == name.strip()
        if not approval_allowed(action, state, grade, is_own):
            skipped.append({"seq": seq, "doc_id": doc, "reason": f"{STATE_LABELS.get(state, state)} 상태는 처리할 수 없음"}); continue
        flag = "Cancel" if action == "reject" else "In"
        appro_grade = 0 if action == "submit" else int(grade or 0)
        db.execute(
            text(f"SET NOCOUNT ON; EXEC {_db()}.dbo.SP_IW_CULBILLLIST_IUD :flag, :seq, :doc, :name, :grade, :result, :bigo"),
            {"flag": flag, "seq": seq, "doc": doc, "name": name[:10], "grade": appro_grade,
             "result": "N" if action == "reject" else "Y", "bigo": bigo.strip()[:250]},
        )
        done.append({"seq": seq, "doc_id": doc})
        bungis.add(month_key(current["Bungi"] or date.today()))
    for b in bungis:
        db.execute(text(f"SET NOCOUNT ON; EXEC {_db()}.dbo.SP_IW_IU_CULL_BUNGI :b"), {"b": b})
    db.commit()
    return {"action": action, "done": done, "skipped": skipped}


# ── 월별 현황 ───────────────────────────────────────────────────────────────


def months(db: Session, name: str, is_approver: bool, today: "date | None" = None) -> "list[dict[str, Any]]":
    """월별 건수·상태별 건수·잠금 — 결재자는 전체, 아니면 내 것만."""
    keys = month_options(today)
    placeholders = ",".join(f":m{i}" for i in range(len(keys)))
    params: "dict[str, Any]" = {f"m{i}": k for i, k in enumerate(keys)}
    own = ""
    if not is_approver:
        own = "AND a.Write_Name = :n"; params["n"] = name
    rows = db.execute(
        text(f"""
            SET NOCOUNT ON;
            SELECT LEFT(a.Bungi, 6) AS bungi, a.ApproState, COUNT(*) AS n
            FROM {_db()}.dbo.apw_yji_manculjang a WHERE LEFT(a.Bungi, 6) IN ({placeholders}) {own}
            GROUP BY LEFT(a.Bungi, 6), a.ApproState
        """),
        params,
    ).all()
    locks = {str(r[0]).strip()[:6]: (str(r[1] or "").strip(), str(r[2] or "").strip()) for r in db.execute(
        text(f"SELECT BUNGI, LOCKED, Lockeddate FROM {_db()}.dbo.apw_iw_cull_bungi WHERE LEFT(BUNGI, 6) IN ({','.join(f':m{i}' for i in range(len(keys)))})"),
        {f"m{i}": k for i, k in enumerate(keys)},
    ).all()}
    counts: "dict[str, dict[int, int]]" = {k: {} for k in keys}
    for bungi, state, n in rows:
        counts.setdefault(str(bungi).strip(), {})[int(state or 0)] = int(n)
    return [{
        "bungi": k, "label": f"{k[:4]}-{k[4:]}", "count": sum(counts[k].values()),
        "by_state": {STATE_LABELS.get(s, str(s)): n for s, n in sorted(counts[k].items())},
        "locked": locks.get(k, ("N", "-"))[0] == "Y", "locked_date": locks.get(k, ("N", "-"))[1],
    } for k in keys]


def writers(db: Session, bungi: str) -> "list[str]":
    rows = db.execute(
        text(f"SELECT DISTINCT Write_Name FROM {_db()}.dbo.apw_yji_manculjang WHERE LEFT(Bungi, 6) = :b ORDER BY Write_Name"),
        {"b": month_key(bungi)},
    ).all()
    return [str(r[0]).strip() for r in rows if r[0]]


# ── 인쇄 (델파이 CulJangList.fr3 양식: 작성자별 '시내·외 출장비 및 공부발급비 청구서') ──

_KOR_DIGITS = "영일이삼사오육칠팔구"
_KOR_UNITS = ("", "십", "백", "천")
_KOR_GROUPS = ("", "만", "억", "조")


def korean_amount(amount: int) -> str:
    """금액 → 한글 갖은자 표기. 델파이 인쇄물 그대로 '일백칠십오만칠천육백원정' (1,757,600)."""
    n = int(amount or 0)
    if n <= 0:
        return "영원정"
    parts = []
    group = 0
    while n > 0:
        chunk = n % 10000
        if chunk:
            text_chunk = ""
            for pos in range(3, -1, -1):
                d = (chunk // (10 ** pos)) % 10
                if d:
                    text_chunk += _KOR_DIGITS[d] + _KOR_UNITS[pos]
            parts.append(text_chunk + _KOR_GROUPS[group])
        n //= 10000
        group += 1
    return "".join(reversed(parts)) + "원정"


def _positions(db: Session, names: "list[str]") -> "dict[str, str]":
    """작성자 직급 — 델파이 인쇄물 '직 급' 칸(좌석표 Ugrade)."""
    names = sorted({n for n in names if n})
    if not names:
        return {}
    placeholders = ",".join(f":n{i}" for i in range(len(names)))
    rows = db.execute(
        text(f"SELECT Uname, Ugrade FROM {_db()}.dbo.seat_userinfo WHERE Uname IN ({placeholders})"),
        {f"n{i}": v for i, v in enumerate(names)},
    ).all()
    return {str(r[0]).strip(): str(r[1] or "").strip() for r in rows}


def _approvals(db: Session, seqs: "list[int]") -> "dict[int, dict[int, str]]":
    """행(Seq)별 등급별 마지막 승인자 이름 — 결재란에 적는다."""
    if not seqs:
        return {}
    placeholders = ",".join(f":s{i}" for i in range(len(seqs)))
    rows = db.execute(
        text(f"""
            SELECT MasterID, ApproGrade, ApproName, ApproResult FROM {_db()}.dbo.apw_yji_culbill_approve
            WHERE MasterID IN ({placeholders}) ORDER BY Seq
        """),
        {f"s{i}": v for i, v in enumerate(seqs)},
    ).all()
    result: "dict[int, dict[int, str]]" = {}
    for master_id, grade, name, res in rows:
        by = result.setdefault(int(master_id), {})
        if str(res or "").strip() == "Y":
            by[int(grade or 0)] = str(name or "").strip()
        else:
            by.pop(int(grade or 0), None)   # 반려는 그 등급 승인 취소
    return result


def print_data(db: Session, rows: "list[dict[str, Any]]", today: "date | None" = None) -> "dict[str, Any]":
    """작성자별 청구서 묶음 — 출장일 순 행, 합계, 비고(※), 한글 금액, 직급, 결재란 이름."""
    today = today or date.today()
    positions = _positions(db, [r["write_name"] for r in rows])
    approvals = _approvals(db, [int(r["seq"]) for r in rows])
    writers: "dict[str, list[dict[str, Any]]]" = {}
    for r in rows:
        writers.setdefault(r["write_name"], []).append(r)
    summary = summarize(rows)
    result = []
    for name in sorted(writers):
        items = sorted(writers[name], key=lambda r: (str(r.get("cul_date") or ""), r["doc_id"]))
        signers: "dict[int, str]" = {}
        for grade in (0, 1, 2, 3):
            names = {approvals.get(int(r["seq"]), {}).get(grade, "") for r in items}
            names.discard("")
            signers[grade] = names.pop() if len(names) == 1 else ""
        totals_row = summary["by_writer"][name]
        result.append({
            "name": name, "position": positions.get(name, ""),
            "rows": items, "totals": totals_row,
            "korean_total": korean_amount(totals_row["amount_total"]),
            "notes": [r["bigo"] for r in items if r.get("bigo")],
            "signers": {"writer": signers[0] or name, "first": signers[1], "second": signers[2], "third": signers[3]},
        })
    return {"date": today.isoformat(), "date_label": f"{today.year}년 {today.month:02d}월 {today.day:02d}일", "writers": result}


# ── 총괄표 (월별 작성자 집계, 2026-09-10 사용자 양식: 성명·시내·시외·공부발급비·기타정산·계·비고 + 합계) ──


def recent_writers(db: Session, bungi: str, months: int = 6) -> "list[str]":
    """총괄표 명단 — 그 달을 포함해 최근 N개월에 출장비를 적은 사람 전부(그 달에 없어도 '-'로 한 줄)."""
    key = month_key(bungi)
    y, m = int(key[:4]), int(key[4:6])
    keys = []
    for delta in range(months):
        yy, mm = y, m - delta
        while mm < 1:
            yy, mm = yy - 1, mm + 12
        keys.append(f"{yy:04d}{mm:02d}")
    placeholders = ",".join(f":m{i}" for i in range(len(keys)))
    rows = db.execute(
        text(f"SELECT DISTINCT Write_Name FROM {_db()}.dbo.apw_yji_manculjang WHERE LEFT(Bungi, 6) IN ({placeholders})"),
        {f"m{i}": k for i, k in enumerate(keys)},
    ).all()
    return sorted(str(r[0]).strip() for r in rows if r[0])


def summary_sheet(rows: "list[dict[str, Any]]", roster: "list[str]", title: str) -> "dict[str, Any]":
    """총괄표 — 명단 순서대로 시내·시외·공부발급비·계, 맨 아래 합계. 기타정산·비고는 수기 칸(빈칸)."""
    by = summarize(rows)["by_writer"]
    names = sorted(set(roster) | set(by))
    items = []
    total = {"cul_in": 0, "cul_out": 0, "gong_total": 0, "amount_total": 0, "count": 0}
    for name in names:
        s = by.get(name, {})
        item = {"name": name, "cul_in": int(s.get("cul_in", 0)), "cul_out": int(s.get("cul_out", 0)),
                "gong_total": int(s.get("gong_total", 0)), "amount_total": int(s.get("amount_total", 0)), "count": int(s.get("count", 0))}
        for k in total:
            total[k] += item[k]
        items.append(item)
    return {"title": title, "items": items, "total": total}


def summary_title(bungi: str = "", date_kind: str = "", date_from: "date | None" = None, date_to: "date | None" = None) -> str:
    if bungi and not date_kind:
        key = month_key(bungi)
        return f"{key[:4]}.{int(key[4:6])}월 총괄표"
    if date_from and date_to:
        label = {"cul": "출장일", "receipt": "접수일", "send": "발송일"}.get(date_kind, "")
        return f"{date_from.isoformat()} ~ {date_to.isoformat()} {label} 총괄표".replace("  ", " ")
    return "출장비 총괄표"
