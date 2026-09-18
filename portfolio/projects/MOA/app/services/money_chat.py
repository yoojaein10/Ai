"""회계(입금·미수) 조회 — 챗봇의 돈 질문 담당.

핵심 원칙: **숫자를 직접 계산하지 않는다.** 입금현황 화면이 쓰는
`ReceivableService.list()` 와 요약 재집계가 쓰는 `receivable_status_cte()` 를
그대로 불러서 합계·건별 값을 받는다. 챗봇이 화면과 다른 숫자를 말하는 순간
신뢰를 잃는다 — 미수금 기준(매출총액, 선수금 한 번만 차감, 2원 흡수)은
2026-08-04 에 재무팀과 맞춘 값이다.

기간 의미도 화면과 같다는 걸 숨기지 않는다:
- 미수금 질문의 기간은 화면과 같은 **최근 입금일** 기준이다. 마지막 입금이
  기간 앞인 옛 미수 건은 빠지므로, 그 사실을 답변에 밝히고 '전체 기간'으로
  다시 묻는 길을 안내한다 (2026-08-04 코드검토 확정 결함 #8).
- '들어온 돈'은 누적액이 아니라 **그 기간의 입금분**이다. 전표를 기간으로
  잘라 화면과 같은 입금 판정 규칙(현금 동반·부가세 역산)으로 센다 (#9).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
from typing import Any

import httpx
from sqlalchemy import text

from app.config import get_settings
from app.database import get_session_factory

# 돈 질문 판별. '수수료'는 넣지 않는다 — '수수료합계 1억 넘는 감정서'는 감정서 쪽이 담당한다.
MONEY_RE = re.compile(r"미수|입금|수금|과입|선수금|밀린|받을\s*돈|들어온\s*돈|완납|연체")
_DOC_ID_RE = re.compile(r"\b(\d{2}-\d{4}-[0-9A-Z]-\d{4}(?:-\d+)?)\b")

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_PROMPT = """감정평가법인 회계 조회 필터를 JSON으로만 반환하라. 설명 금지.
필드:
- intent: "outstanding"(미수금·밀린 돈) | "received"(입금액·들어온 돈) | "top"(미수 큰 순 목록)
- customer: 거래처명 (없으면 null)
- manager: 유치자(사람 이름) (없으면 null)
- date_from, date_to: YYYY-MM-DD. **사용자가 기간을 직접 말했을 때만** 채우고 아니면 null.
  '이번 달'은 이달 1일~오늘. '전체 기간'·'지금까지'·'전부'라고 말한 경우에만 date_from="2015-01-01".
  기간을 안 말한 질문에 임의로 기간을 지어내지 마라.
- top_n: 목록 개수 (기본 5, 최대 20)
오늘: {today}
질문: {question}"""


# 지사 범위 — 사용자 소속(a10_office_map)의 라벨(LOffice)과 감정서번호 접두사.
# 본사(10)→('본사','01'). 챗봇은 소속 데이터만 보여준다 (2026-08-05 사용자 확정).
_OFFICE_CACHE: dict[str, tuple[str, str]] = {}


def office_scope(office_code: "str | None") -> tuple[str, str]:
    """지사 코드 → (LOffice 라벨, 감정서번호 접두사). 모르면 본사로 좁힌다.

    'all'(전체)은 다른 조회 화면과 같은 규약이다 — 범위를 안 좁힌다는 뜻으로
    빈 값을 돌려준다 (receivables 라우터의 `None if office_code == "all"` 과 동일).
    """
    if (office_code or "").strip() == "all":
        return "", ""
    code = (office_code or "10").strip() or "10"
    hit = _OFFICE_CACHE.get(code)
    if hit:
        return hit
    from app.models.office_map import OfficeMap  # noqa: PLC0415

    db = get_session_factory()()
    try:
        row = db.get(OfficeMap, code)
        scope = (row.office_name, row.docid_prefix) if row else ("본사", "01")
    finally:
        db.close()
    _OFFICE_CACHE[code] = scope
    return scope


def is_money_question(question: str) -> bool:
    return bool(MONEY_RE.search(question or ""))


def doc_in(question: str) -> "str | None":
    match = _DOC_ID_RE.search(question or "")
    return match.group(1) if match else None


def _won(value: Any) -> str:
    return format(float(value or 0), ",.0f")


def _year_start() -> dt.date:
    today = dt.date.today()
    return dt.date(today.year, 1, 1)


def _as_str(value: Any) -> "str | None":
    """Gemini 가 배열·숫자를 돌려줘도 죽지 않게 문자열로 굳힌다 (#4)."""
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _as_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_date(value: Any) -> "dt.date | None":
    try:
        return dt.date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


# 추출 캐시 — 같은 날 같은 질문이면 Gemini 왕복(~1초)을 아낀다. 키에 날짜를 넣어
# '이번 달'류가 자정을 넘겨 낡지 않게 한다. 규칙 폴백 결과는 캐시하지 않는다
# (Gemini 순단이 그날 내내 눌러앉으면 안 된다).
_XCACHE: dict[tuple[str, str], dict[str, Any]] = {}
_XCACHE_MAX = 200


async def _extract(question: str) -> dict[str, Any]:
    """돈 질문에서 거래처·기간·의도를 뽑는다. 실패하면 규칙으로 어림한다."""
    cache_key = (question, dt.date.today().isoformat())
    hit = _XCACHE.get(cache_key)
    if hit is not None:
        return dict(hit)
    # 환경변수는 감정서 경로가 먼저 열렸을 때만 차 있다 — 설정에서 직접도 읽는다 (#3).
    key = os.getenv("GEMINI_API_KEY") or get_settings().gemini_api_key.get_secret_value()
    model = os.getenv("GAMJUN_EXTRACT_MODEL", "gemini-2.5-flash-lite")
    if key:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.post(
                    _GEMINI_URL.format(model=model),
                    params={"key": key},
                    json={
                        "contents": [{"parts": [{"text": _PROMPT.format(
                            today=dt.date.today().isoformat(), question=question
                        )}]}],
                        "generationConfig": {"response_mime_type": "application/json"},
                    },
                )
                response.raise_for_status()
                raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                spec = json.loads(raw)
                if isinstance(spec, dict):
                    if len(_XCACHE) >= _XCACHE_MAX:
                        _XCACHE.clear()
                    _XCACHE[cache_key] = dict(spec)
                    return spec
        except Exception:
            pass  # 아래 규칙 어림으로
    if re.search(r"큰\s*(거|것|순)|상위|top", question, re.I):
        intent = "top"
    elif re.search(r"입금|들어온", question):
        intent = "received"
    else:
        intent = "outstanding"
    return {"intent": intent}


def _list_sync(**kwargs: Any) -> dict[str, Any]:
    """입금현황 화면과 같은 서비스 호출. 동기 SQLAlchemy 라 스레드에서 돈다."""
    from app.services.receivables import ReceivableService  # noqa: PLC0415 (import 비용을 첫 돈 질문으로 미룬다)

    db = get_session_factory()()
    try:
        return ReceivableService(db).list(**kwargs)
    finally:
        db.close()


def _inflow_sync(date_from: dt.date, date_to: dt.date, office_code: str = "10") -> dict[str, Any]:
    """기간에 실제로 들어온 돈. 전표를 기간으로 잘라 요약 재집계와 같은 CTE 로 센다.

    '마지막 입금일이 기간 안인 감정서의 누적 입금액'(요약 테이블 합)과 다르다 —
    그건 분납 건의 과거 입금분까지 합쳐 과대다 (#9). 여기서는 입금 판정 규칙
    (현금 동반 전표만·부가세 ×1.1 역산)을 receivable_status_cte 로 재사용한다.
    """
    from app.services.office_lookup import docid_prefixes  # noqa: PLC0415
    from app.services.receivables import (  # noqa: PLC0415
        management_no_filter,
        receivable_status_cte,
    )

    db = get_session_factory()()
    try:
        prefixes = docid_prefixes(db, office_code) or ["01"]
        prefix_sql, prefix_params = management_no_filter(prefixes, column="management_no")
        sql = receivable_status_cte(
            f"{prefix_sql} AND voucher_date >= :period_from AND voucher_date <= :period_to"
        ) + (
            " SELECT COALESCE(SUM(b.received_amount), 0) AS inflow,"
            " COUNT(CASE WHEN b.received_amount > 0 THEN 1 END) AS docs FROM b"
        )
        row = db.execute(
            text(sql),
            {**prefix_params, "period_from": date_from, "period_to": date_to},
        ).mappings().first()
        return {"inflow": float(row["inflow"] or 0), "docs": int(row["docs"] or 0)}
    finally:
        db.close()


def _tax_sync(doc_id: str) -> dict[str, Any]:
    from app.services.receivables import _tax_invoice_totals  # noqa: PLC0415

    db = get_session_factory()()
    try:
        return _tax_invoice_totals(db, [{"doc_id": doc_id}]).get(doc_id, {})
    finally:
        db.close()


def _status_of(item: dict[str, Any]) -> str:
    from app.routers.receivables import _status_label  # noqa: PLC0415

    return _status_label(dict(item))


async def doc_money_brief(doc_id: str, office_code: str = "10") -> "str | None":
    """감정서 카드에 끼워 넣을 입금 요약 한 줄 — 입금현황 화면과 같은 숫자.

    카드만 보고 돈 이력은 또 물어야 했던 걸 줄인다 (2026-08-05 카드 개선).
    실패하면 조용히 생략한다 — 카드 본문이 죽으면 안 된다.
    """
    try:
        data = await asyncio.to_thread(
            _list_sync, mode="received", office_code=office_code, doc_id=doc_id,
            page=1, page_size=50, force_meta_join=True,
        )
        items = [i for i in data.get("items", []) if str(i.get("doc_id")) == doc_id]
        if items:
            item = items[0]
            # 한 줄로 욱여넣지 않고 입금현황 화면과 같은 항목을 표로 편다
            # (2026-08-05 요청: 상세도 회계 행으로, 가독성 좋게).
            rows = [
                ("순수수료", item.get("base_fee")),
                ("여비·기타실비", item.get("travel_expense")),
                ("매출액", item.get("sales_amount")),
                ("부가세", item.get("vat_amount")),
                ("**매출총액**", item.get("invoice_total")),
                ("선수금 받은 금액", item.get("advance_received")),
                ("입금액", item.get("received_amount")),
                ("선수금 잔액", item.get("advance_amount")),
                ("**미수금**", item.get("outstanding_amount")),
            ]
            lines = ["", "**회계 (입금현황과 같은 기준)**", "",
                     "| 구분 | 금액 |", "|---|---|"]
            for label, value in rows:
                if value is None:
                    continue
                lines.append("| %s | %s원 |" % (label, _won(value)))
            tail = f"- **입금 상태**: {_status_of(item)}"
            if item.get("last_received_date"):
                tail += f" · 최근 입금일 {item['last_received_date']}"
            return "\n".join(lines + ["", tail])
        # 입금 이력이 아직 없는 건(발송대기 등)도 빈손보다는 청구액이라도 보여준다.
        data = await asyncio.to_thread(
            _list_sync, mode="outstanding", office_code=office_code, doc_id=doc_id,
            page=1, page_size=50,
        )
        items = [i for i in data.get("items", []) if str(i.get("doc_id")) == doc_id]
        if not items:
            return None
        item = items[0]
        return ("- **입금 상태**: 미입금 · 청구액 %s원 (미수금현황 기준, 입금 이력 없음)"
                % _won(item.get("billed_amount")))
    except Exception:
        return None


async def doc_money(doc_id: str, office_code: str = "10") -> dict[str, Any]:
    """감정서 한 건의 돈 이력 — 입금현황 화면의 그 행과 같은 숫자다."""
    # 서비스의 번호 검색은 부분일치라 자식 번호(-2 등)가 많으면 5건에 안 들 수 있다 (#6).
    data = await asyncio.to_thread(
        _list_sync, mode="received", office_code=office_code, doc_id=doc_id,
        page=1, page_size=50, force_meta_join=True,
    )
    items = [i for i in data.get("items", []) if str(i.get("doc_id")) == doc_id]
    if not items:
        # 입금 이력이 없으면 미수금현황(원장 뿌리)에서 찾아본다.
        data = await asyncio.to_thread(
            _list_sync, mode="outstanding", office_code=office_code, doc_id=doc_id,
            page=1, page_size=50,
        )
        items = [i for i in data.get("items", []) if str(i.get("doc_id")) == doc_id]
        if not items:
            return {"answer": "", "note": f"{doc_id} 의 전표·입금 이력을 찾지 못했습니다.",
                    "spec": {"doc_id": doc_id}}
        item = items[0]
        lines = [
            f"## {doc_id} 입금 이력",
            "",
            f"- **거래처**: {item.get('customer_name') or '-'}",
            f"- **청구액(전표)**: {_won(item.get('billed_amount'))}원",
            f"- **입금액**: {_won(item.get('received_amount'))}원",
            f"- **미수금(미수금현황 기준)**: {_won(item.get('outstanding_amount'))}원",
            "",
            "> 아직 입금 이력이 없어 미수금현황(청구금액 기준)에서 찾았습니다.",
        ]
        return {"answer": "\n".join(lines), "note": "", "spec": {"doc_id": doc_id}}

    item = items[0]
    tax = await asyncio.to_thread(_tax_sync, doc_id)
    received = float(item.get("received_amount") or 0)
    settled = float(item.get("settled_advance") or 0)
    lines = [
        f"## {doc_id} 입금 이력",
        "",
        "| 구분 | 금액 |",
        "|---|---|",
        f"| 매출총액 | {_won(item.get('invoice_total'))}원 |",
        f"| 선수금 받은 금액 | {_won(item.get('advance_received'))}원 |",
        f"| 입금액 | {_won(received)}원 |",
    ]
    if settled > 0:
        lines.append(f"| 입금액에 안 잡힌 선수금 | {_won(settled)}원 |")
    lines += [
        f"| 선수금 잔액 | {_won(item.get('advance_amount'))}원 |",
        f"| 미수금 | {_won(item.get('outstanding_amount'))}원 |",
        f"| 과입금 | {_won(item.get('overpaid_amount'))}원 |",
    ]
    tax_total = float(tax.get("tax_total") or 0)
    if tax_total > 0:
        lines.append(f"| 세금계산서 발행액 | {_won(tax_total)}원 |")
    lines += [
        "",
        f"- **상태**: {_status_of(item)}"
        + (f" · 최근 입금일 {item.get('last_received_date')}" if item.get("last_received_date") else ""),
        f"- **거래처**: {item.get('customer_name') or '-'}",
        "",
        "> 입금현황 화면과 같은 기준(매출총액·선수금 1회 차감)입니다.",
    ]
    return {"answer": "\n".join(lines), "note": "", "spec": {"doc_id": doc_id}}


async def ask(question: str, office_code: str = "10") -> dict[str, Any]:
    """돈 질문 하나에 답한다. 감정서번호가 있으면 그 건의 돈 이력으로 간다."""
    label, prefix = office_scope(office_code)
    doc_id = doc_in(question)
    if doc_id:
        if not doc_id.startswith(prefix + "-"):
            return {"answer": "", "spec": {"doc_id": doc_id},
                    "note": f"소속({label}) 감정서만 조회할 수 있습니다 — {doc_id} 는 다른 지사 번호입니다."}
        return await doc_money(doc_id, office_code)

    spec = await _extract(question)
    intent = _as_str(spec.get("intent")) or "outstanding"
    customer = _as_str(spec.get("customer"))
    manager = _as_str(spec.get("manager"))
    explicit_from = _parse_date(spec.get("date_from"))
    explicit_to = _parse_date(spec.get("date_to"))
    date_from = explicit_from or _year_start()
    date_to = explicit_to or dt.date.today()
    if date_from > date_to:  # 뒤집힌 기간으로 '0원'을 확신조로 답하면 안 된다 (#7)
        date_from, date_to = date_to, date_from
    top_n = max(1, min(_as_int(spec.get("top_n"), 5), 20))

    common = dict(office_code=office_code, customer_name=customer, manager=manager,
                  date_from=date_from, date_to=date_to)
    who = " · ".join(b for b in (
        customer and f"거래처 {customer}", manager and f"유치 {manager}", label,
    ) if b)

    # ── 들어온 돈: 기간 입금분을 전표에서 직접 센다 ──────────────────────────
    if intent == "received":
        period = f"{date_from.isoformat()} ~ {date_to.isoformat()}"
        if not customer and not manager:
            flow = await asyncio.to_thread(_inflow_sync, date_from, date_to, office_code)
            lines = [
                f"**{period} · {label}에 들어온 돈**",
                "",
                f"- **입금액**: {_won(flow['inflow'])}원",
                f"- 입금이 있었던 감정서: {format(flow['docs'], ',')}건",
                "",
                "> 그 기간 전표의 입금분만 센 값입니다 (입금현황 화면과 같은 입금 판정 규칙).",
            ]
            return {"answer": "\n".join(lines), "note": "", "spec": spec, "rows": flow["docs"]}
        # 거래처·유치자 조건이 붙으면 전표에 거래처가 없어 기간 입금분을 못 가른다 —
        # 요약 기준 수치를 주되 무엇인지 정확히 말한다.
        data = await asyncio.to_thread(_list_sync, mode="received", page=1, page_size=1, **common)
        sums = data.get("sums", {})
        lines = [
            f"**{who} · 최근 입금일 {period}**",
            "",
            f"- 이 기간에 마지막 입금이 있었던 감정서 {format(int(data.get('total') or 0), ',')}건의 "
            f"**누적 입금액**: {_won(sums.get('received_amount'))}원",
            f"- 매출총액 {_won(sums.get('invoice_total'))}원 · 미수금 {_won(sums.get('outstanding_amount'))}원",
            "",
            "> 분납 건은 과거 입금분까지 합친 누적액입니다 — 그 기간에 들어온 돈만은 아닙니다.",
        ]
        return {"answer": "\n".join(lines), "note": "", "spec": spec,
                "rows": int(data.get("total") or 0)}

    # ── 미수금: 화면과 같은 기간 의미(최근 입금일) — 밝히고 안내한다 (#8) ────
    period_note = (
        f"기간은 화면과 같은 **최근 입금일 {date_from.isoformat()} ~ {date_to.isoformat()}** 기준입니다. "
        f"마지막 입금이 {date_from.isoformat()} 이전인 옛 미수 건과 입금 이력이 아예 없는 건은 "
        "이 합계에 없습니다 — '전체 기간 미수금'으로 물으면 옛 건까지 포함됩니다."
    )

    if intent == "top":
        data = await asyncio.to_thread(
            _list_sync, mode="received", page=1, page_size=top_n,
            sort_by="outstanding_amount", sort_order="desc",
            force_meta_join=True, **common,
        )
        rows = data.get("items", [])
        lines = [f"**미수금 큰 순 {len(rows)}건** — {who}", "",
                 "| 감정서번호 | 거래처 | 매출총액 | 입금액 | 미수금 |", "|---|---|---|---|---|"]
        for r in rows:
            lines.append("| %s | %s | %s | %s | **%s** |" % (
                r.get("doc_id"), (r.get("customer_name") or "-"),
                _won(r.get("invoice_total")), _won(r.get("received_amount")),
                _won(r.get("outstanding_amount"))))
        lines += ["", f"> {period_note}"]
        return {"answer": "\n".join(lines), "note": "", "spec": spec, "rows": len(rows)}

    # 합계와 '미수 큰 건' 목록은 서로 독립 — 동시에 돌려 체감 시간을 절반으로 줄인다
    # (정렬 목록이 무거운 날은 이 경로가 10초를 넘겼다).
    data, top = await asyncio.gather(
        asyncio.to_thread(_list_sync, mode="received", page=1, page_size=1, **common),
        asyncio.to_thread(
            _list_sync, mode="received", page=1, page_size=5,
            sort_by="outstanding_amount", sort_order="desc",
            outstanding_from=1.0, force_meta_join=True, **common,
        ),
    )
    sums = data.get("sums", {})
    total = int(data.get("total") or 0)
    lines = [
        f"**{who}** — 감정서 **{format(total, ',')}건**",
        "",
        f"- **미수금 합계**: {_won(sums.get('outstanding_amount'))}원",
        f"- 매출총액 {_won(sums.get('invoice_total'))}원 · 입금액 {_won(sums.get('received_amount'))}원",
        f"- 과입금 {_won(sums.get('overpaid_amount'))}원 · 선수금 잔액 {_won(sums.get('advance_amount'))}원",
    ]
    rows = [r for r in top.get("items", []) if float(r.get("outstanding_amount") or 0) > 0]
    if rows:
        lines += ["", "미수 큰 건:", "", "| 감정서번호 | 거래처 | 미수금 |", "|---|---|---|"]
        for r in rows:
            lines.append("| %s | %s | %s |" % (
                r.get("doc_id"), (r.get("customer_name") or "-"),
                _won(r.get("outstanding_amount"))))
    lines += ["", f"> {period_note}"]
    return {"answer": "\n".join(lines), "note": "", "spec": spec, "rows": total}
