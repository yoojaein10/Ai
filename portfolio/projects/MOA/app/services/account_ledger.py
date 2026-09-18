"""계정별원장 — 계정 하나의 기간 내역을 아마란스 인쇄 양식대로 만든다.

각 지사 계정(1410002~1410022)의 원장을 뽑아 지사 담당자에게 보내는 용도다.
지금은 팩스로 출력해 보내고 있다 (2026-08-21 사용자 요청: 메일로 일괄 발송).

구성은 아마란스 화면과 같다.
    [전일이월]  기간 시작일 전까지의 차변·대변 누계와 그 잔액
     …내역…     전표일자·적요·거래처코드·거래처명·사업자번호·차변·대변·잔액
    [월  계]   기간 내 차변·대변 합계
    [누  계]   전일이월 + 월계

전일이월 = **전기이월 + 그 해 시작일부터 기간 전날까지의 누계** 다 (2026-08-21
아마란스 화면에서 직접 확인). 아마란스는 전기이월(작년 말 잔액)을 첫 줄
[전 기 이 월]로 찍고 차변 누계에 얹는다.

우리 전표 캐시는 2025-07-24 부터라 전기이월을 계산할 수 없다. 그래서
a10_account_opening 에 계정·연도별로 한 번 넣어 두고 읽는다.

검증(호남지사 1410011, 2026-08-19~20):
    우리 2026-01-01 누계 차변   890,704,075
    전기이월                   -46,529,401   ← 아마란스 [전 기 이 월]
                              ─────────────
                               844,174,674   = 아마란스 전일이월 차변 ✅
    대변 844,664,937 은 전기이월 없이 그대로 일치
    기간 내역 2줄(106,000·137,000)·월계 243,000 도 일치
"""

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# 지사 계정은 141 계열이다. 본사(1410001)·본지점(손익)(1410017)도 같은 계열이라
# 목록에는 넣되 부르는 쪽에서 고른다.
_ACCOUNT_SQL = """
SELECT account_code, MAX(account_name) AS account_name, COUNT(*) AS line_count
FROM dbo.a10_voucher_cache
WHERE division_code = CAST(:div AS varchar(10))
  AND account_code LIKE '141%'
GROUP BY account_code
ORDER BY account_code
"""

_CARRY_SQL = """
SELECT ISNULL(SUM(CASE WHEN debit_credit = '3' THEN amount ELSE 0 END), 0) AS debit,
       ISNULL(SUM(CASE WHEN debit_credit = '4' THEN amount ELSE 0 END), 0) AS credit
FROM dbo.a10_voucher_cache
WHERE division_code = CAST(:div AS varchar(10))
  AND account_code = CAST(:acct AS varchar(20))
  AND voucher_date >= :carry_from AND voucher_date < :date_from
"""

# 사업자번호는 전표 캐시에 없다 — 거래처 캐시(a10_partner_cache)에서 이어 붙인다.
# 캐시가 비어 있어도 원장은 나와야 하므로 LEFT JOIN 이다.
_LINES_SQL = """
SELECT v.voucher_date, v.voucher_no, v.line_no, v.remark,
       v.partner_code, v.partner_name, p.reg_no AS partner_reg_no,
       v.debit_credit, v.amount
FROM dbo.a10_voucher_cache v
LEFT JOIN dbo.a10_partner_cache p ON p.partner_code = v.partner_code
WHERE v.division_code = CAST(:div AS varchar(10))
  AND v.account_code = CAST(:acct AS varchar(20))
  AND v.voucher_date BETWEEN :date_from AND :date_to
ORDER BY v.voucher_date, v.voucher_no, v.line_no
"""


def list_accounts(db: Session, division_code: str = "1000") -> "list[dict[str, Any]]":
    """141 계열 계정 목록 (본사·지사)."""
    return [
        {
            "account_code": row["account_code"],
            "account_name": (row["account_name"] or "").strip(),
            "line_count": int(row["line_count"]),
        }
        for row in db.execute(text(_ACCOUNT_SQL), {"div": division_code}).mappings()
    ]


def build_ledger(
    db: Session,
    account_code: str,
    date_from: date,
    date_to: date,
    division_code: str = "1000",
    carry_from: "date | None" = None,
) -> "dict[str, Any]":
    """계정 하나의 원장. carry_from 부터 기간 시작 전날까지를 전일이월로 잡는다.

    carry_from 을 안 주면 그 해 1월 1일이다 (회계연도 기준).
    """
    carry_start = carry_from or date(date_from.year, 1, 1)
    params = {
        "div": division_code, "acct": account_code,
        "carry_from": carry_start, "date_from": date_from, "date_to": date_to,
    }
    carry = db.execute(text(_CARRY_SQL), params).mappings().one()
    # 전기이월(작년 말 잔액)을 얹는다 — 아마란스가 [전 기 이 월] 줄로 찍는 값이다.
    # 없으면 0 으로 두고 원장은 그대로 낸다(fail-open) — 기간 내역은 어차피 맞는다.
    opening = db.execute(
        text(
            "SELECT debit, credit FROM dbo.a10_account_opening "
            "WHERE account_code = CAST(:acct AS varchar(20)) AND fiscal_year = :yr"
        ),
        {"acct": account_code, "yr": carry_start.year},
    ).mappings().first()
    opening_debit = float(opening["debit"] or 0) if opening else 0.0
    opening_credit = float(opening["credit"] or 0) if opening else 0.0

    carry_debit = float(carry["debit"] or 0) + opening_debit
    carry_credit = float(carry["credit"] or 0) + opening_credit

    balance = carry_debit - carry_credit
    items: "list[dict[str, Any]]" = []
    period_debit = period_credit = 0.0
    for row in db.execute(text(_LINES_SQL), params).mappings():
        debit = float(row["amount"] or 0) if str(row["debit_credit"]) == "3" else 0.0
        credit = float(row["amount"] or 0) if str(row["debit_credit"]) == "4" else 0.0
        period_debit += debit
        period_credit += credit
        balance += debit - credit
        items.append({
            "date": row["voucher_date"].isoformat(),
            "voucher_no": (row["voucher_no"] or "").strip(),
            "remark": (row["remark"] or "").strip(),
            "partner_code": (row["partner_code"] or "").strip(),
            "partner_name": (row["partner_name"] or "").strip(),
            "partner_reg_no": (row["partner_reg_no"] or "").strip(),
            "debit": debit,
            "credit": credit,
            "balance": balance,
        })

    account = next(
        (a for a in list_accounts(db, division_code) if a["account_code"] == account_code),
        {"account_code": account_code, "account_name": ""},
    )
    return {
        "account_code": account_code,
        "account_name": account["account_name"],
        "division_code": division_code,
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "carry_from": carry_start.isoformat(),
        "opening": {
            "debit": opening_debit, "credit": opening_credit,
            "known": opening is not None,
        },
        "carry": {
            "debit": carry_debit, "credit": carry_credit,
            "balance": carry_debit - carry_credit,
        },
        "items": items,
        "period_total": {"debit": period_debit, "credit": period_credit},
        "grand_total": {
            "debit": carry_debit + period_debit,
            "credit": carry_credit + period_credit,
        },
    }


def _won(value: float) -> str:
    return f"{round(value):,}" if value else ""


def _reg_no(value: str) -> str:
    """사업자번호 10자리를 3-2-5 로 끊는다. 주민번호(13자리)는 그대로 둔다."""
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"
    return str(value or "")


def render_html(ledger: "dict[str, Any]", company: str = "1000. (주)대화감정평가법인") -> str:
    """아마란스 인쇄 양식(계정별원장) 그대로 HTML 로 만든다 — 메일 본문에 그대로 넣는다.

    메일 프로그램은 <style> 을 자주 지우므로 표 모양은 태그마다 직접 박는다.
    다만 용지 방향은 인라인 스타일로 지정할 수 없어 @page 를 함께 넣는다.
    지원하는 메일/브라우저에서는 A4 가로로 열리고, 지원하지 않아도 본문 표는
    기존 인라인 스타일 덕분에 무너지지 않는다.
    """
    def cell(text_: str, align: str = "left", bold: bool = False) -> str:
        weight = "font-weight:bold;" if bold else ""
        return (f'<td style="border:1px solid #333;padding:3px 5px;'
                f'text-align:{align};{weight}white-space:nowrap">{text_}</td>')

    head = "".join(
        f'<th style="border:1px solid #333;padding:4px 5px;background:#f2f2f2;'
        f'font-weight:bold;text-align:center">{name}</th>'
        for name in ("날짜", "적    요", "거래처코드", "거래처명",
                     "사업자(주민)번호", "차    변", "대    변", "잔    액")
    )
    carry = ledger["carry"]
    rows = [
        "<tr>" + cell("") + cell("[ 전일이월 ]", "center", True) + cell("") + cell("")
        + cell("") + cell(_won(carry["debit"]), "right")
        + cell(_won(carry["credit"]), "right") + cell(_won(carry["balance"]), "right")
        + "</tr>"
    ]
    for item in ledger["items"]:
        rows.append(
            "<tr>"
            + cell(item["date"].replace("-", "/"), "center")
            + cell(item["remark"])
            + cell(item["partner_code"], "center")
            + cell(item["partner_name"])
            + cell(_reg_no(item["partner_reg_no"]), "center")
            + cell(_won(item["debit"]), "right")
            + cell(_won(item["credit"]), "right")
            + cell(_won(item["balance"]), "right")
            + "</tr>"
        )
    for label, total in (("[ 월  계 ]", ledger["period_total"]),
                         ("[ 누  계 ]", ledger["grand_total"])):
        rows.append(
            "<tr>" + cell("") + cell(label, "center", True) + cell("") + cell("") + cell("")
            + cell(_won(total["debit"]), "right", True)
            + cell(_won(total["credit"]), "right", True) + cell("") + "</tr>"
        )
    period = ledger["period"]
    title_period = (f"{period['from'][:4]}년 {period['from'][5:7]}월 {period['from'][8:]}일"
                    f" ~ {period['to'][:4]}년 {period['to'][5:7]}월 {period['to'][8:]}일")
    return f"""<style>
@page {{ size: A4 landscape; margin: 10mm; }}
@media print {{
  html, body {{ margin: 0 !important; padding: 0 !important; }}
  .moa-ledger-sheet {{
    width: 277mm !important; max-width: 277mm !important;
    transform: none !important; writing-mode: horizontal-tb !important;
  }}
  .moa-ledger-sheet table {{ width: 100% !important; page-break-inside: auto; }}
  .moa-ledger-sheet thead {{ display: table-header-group; }}
  .moa-ledger-sheet tr {{ page-break-inside: avoid; }}
}}
</style>
<div class="moa-ledger-sheet" style="width:100%;max-width:277mm;margin:0 auto;font-family:'맑은 고딕',Malgun Gothic,sans-serif;font-size:12px;color:#000;transform:none;writing-mode:horizontal-tb">
  <h2 style="text-align:center;margin:0 0 6px;font-size:19px">계정별원장( 현재 )</h2>
  <p style="text-align:center;margin:0 0 14px;font-size:12px">기 간 : {title_period}</p>
  <table style="width:100%;margin-bottom:8px;font-size:12px">
    <tr><td>회 사 : {company}</td>
        <td style="text-align:right">계정과목 : {ledger['account_code']}.{ledger['account_name']}</td></tr>
    <tr><td>회계단위 : {company}</td><td></td></tr>
  </table>
  <table style="width:100%;border-collapse:collapse;font-size:11px">
    <thead><tr>{head}</tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</div>"""
