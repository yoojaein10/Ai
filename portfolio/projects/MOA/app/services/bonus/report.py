"""리포트 조립 — 지급월 하나의 상여를 후보 → 행 → 사람별 합계로 만든다 (bonus_report_v2).

원천 함수는 Readers 로 묶어 주입한다 — 시험은 가짜로 바꾸고, 운영은 기본값(실제 DB)을 쓴다.
CLOSED 인 달은 계산하지 않고 스냅샷(a10_bonus_result)을 돌려준다 — 전표 캐시가 계속
바뀌므로 지급한 숫자는 다시 계산하면 안 된다.

행의 순수수료 = apw_masterex 기초수수료 − 절사금액 (엑셀 F 와 7/7 일치). 전표 4010001 은
여비·실비까지 든 수수료합계라 후보 판정에만 쓴다. 담당자 '공(이름)' 은 지분을 나누지 않고
전액 × 공통건 요율을 따로 받는다('윤도,공(장재원)' → 윤도 100%, 장재원 공통건).
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from app.services.bonus import closing, deduction_items, engine, ledger, persons, schedule, shares, sources, sources_apw
from app.services.bonus.rules import (
    SIGNING_MAX_PCT, SIMPLE_APPRAISAL, WOORI_JOINT_PCT, channel_owner, common_rate_rule, extract_doc_ids, is_woori,
    manager_entries, simple_appraisal_doc_id, survey_payout, travel_shortfall, unwrap_common,
)
from app.services.bonus.shares import ShareHit
from app.services.bonus.schedule import rate_for
from app.services.bonus.shares import match_note_names, parse_share_note, resolve_share
from app.services.bonus.summary import summarize

_EMPTY_META: "dict[str, Any]" = {
    "receipt_date": None, "work_type": "", "customer_name": "", "manager": "", "investigator": "",
    "base_fee": 0.0, "cut_fee": 0.0, "land_fee": 0.0, "travel_billed": 0.0, "travel_claimed": 0.0,
    "survey_fee": 0.0, "ratio_names": None, "ratio_values": None,
}
ASSOCIATE_DEFAULTS = (1.0, 0.15)   # 소속 파라미터가 없을 때 (지급률, 소득세율)


@dataclass
class Readers:
    candidate_docs: Callable = sources.candidate_docs
    simple_appraisal: Callable = sources.simple_appraisal_total
    voucher_expenses: Callable = sources.voucher_expenses      # 2026-08-27부터 리포트는 안 쓴다 (호환용)
    voucher_expense_rows: Callable = sources.voucher_expense_rows
    sync_voucher_candidates: Callable = deduction_items.sync_voucher_candidates
    doc_meta: Callable = sources_apw.doc_meta
    gaprice_allocations: Callable = sources_apw.gaprice_allocations
    booking_shares: Callable = sources_apw.booking_shares
    survey_claims: Callable = sources_apw.survey_claims
    variable_costs: Callable = sources_apw.variable_costs
    active_names: Callable = sources_apw.active_names
    dept_by_name: Callable = sources_apw.dept_by_name
    load_shares: Callable = shares.load_shares
    load_schedule: Callable = schedule.load_schedule
    list_persons: Callable = persons.list_persons
    already_paid: Callable = closing.already_paid
    carry_in: Callable = closing.carry_in
    close_status: Callable = closing.close_status
    load_result: Callable = closing.load_result
    load_deductions: Callable = ledger.load_deductions
    pending_deductions: Callable = lambda db: deduction_items.pending_by_person(db)
    load_overrides: Callable = ledger.load_overrides


@dataclass
class _Context:
    """한 달치 원천을 한 번에 읽어 둔 것."""
    perf_from: Any
    perf_to: Any
    overrides: dict
    meta: dict
    gaprice: dict
    booking: dict
    manual: dict
    claims: dict
    expenses: dict
    people: dict
    depts: dict
    active: set
    sched: dict
    paid: dict
    carry: dict
    variable: dict
    deductions: dict
    warnings: list = field(default_factory=list)
    held: list = field(default_factory=list)


@dataclass
class _DocPeople:
    split: "set[str]"            # 지분을 나누는 사람
    common: "set[str]"           # 공통건(전액 × 요율) 사람
    managers: "list[str]"        # 균등 지분의 분모가 되는 담당자
    booking: "dict[str, float]"  # 공통건을 뺀 뒤 다시 100 으로 맞춘 Booking 지분
    woori: "set[str]" = field(default_factory=set)   # 우리은행 공(X) → 50% 주주 지분으로 옮긴 사람


def _select_docs(cands, overrides, perf_to, held, warnings) -> "dict[str, dict[str, Any]]":
    """후보를 포함/보류로 가르고, 오버라이드 INCLUDE 를 반영한다."""
    include_docs = {doc for (doc, _), acts in overrides.items() if "INCLUDE" in acts}
    included: "dict[str, dict[str, Any]]" = {}
    for cand in cands:
        status, flags = sources.classify_candidate(cand, perf_to=perf_to)
        if status == "INCLUDED":
            included[cand["doc_id"]] = {**cand, "flags": flags}
        elif cand["doc_id"] in include_docs:
            included[cand["doc_id"]] = {**cand, "flags": flags + ["INCLUDED_BY_OVERRIDE"]}
        else:
            held.append({
                "doc_id": cand["doc_id"], "reason": status, "fee_total": cand["fee_total"],
                "outstanding": cand["outstanding"], "last_received_date": cand["last_received_date"],
            })
    for doc in sorted(include_docs - set(included)):
        included[doc] = {"doc_id": doc, "fee_total": 0.0, "sources": [], "flags": ["INCLUDED_BY_OVERRIDE", "NO_CANDIDATE"]}
    return included


def _meta_with_fallback(db, readers, docs, warnings) -> "dict[str, dict[str, Any]]":
    meta = dict(readers.doc_meta(db, docs))
    missing = [doc for doc in docs if doc not in meta]
    parents = {doc: (extract_doc_ids(doc) or [None])[0] for doc in missing}
    parent_ids = sorted({p for doc, p in parents.items() if p and p != doc})
    parent_meta = readers.doc_meta(db, parent_ids) if parent_ids else {}
    for doc, parent in parents.items():
        if parent in parent_meta:
            meta[doc] = {**parent_meta[parent], "meta_source": "PARENT"}
        else:
            meta[doc] = {**_EMPTY_META, "meta_source": "NONE"}
            warnings.append(f"{doc}: 감정서 정보를 찾지 못했습니다 — 접수일·담당자 없이 계산합니다.")
    return meta


def _fee_basis(cand: "dict[str, Any]", meta: "dict[str, Any]") -> float:
    """순수수료 = 기초수수료 − 절사금액. 마스터에 없으면 전표 순액."""
    fee = float(meta.get("base_fee") or 0) - float(meta.get("cut_fee") or 0)
    return fee if fee > 0 else float(cand["fee_total"])


def _person_kind(ctx: _Context, person: str) -> "tuple[str, float, float]":
    """(구분, 지급률, 소득세율). 사람 표 > 부서코드('so'=소속) 폴백."""
    entry = ctx.people.get(person)
    if entry:
        return entry["kind"], float(entry["pay_ratio"]), float(entry["tax_rate"])
    kind = "ASSOCIATE" if ctx.depts.get(person) == "so" else "SHAREHOLDER"
    ctx.warnings.append(f"{person}: 사람 표에 없어 부서코드로 {'소속' if kind == 'ASSOCIATE' else '주주'}로 봤습니다.")
    return kind, ASSOCIATE_DEFAULTS[0], (ASSOCIATE_DEFAULTS[1] if kind == "ASSOCIATE" else 0.30)


def _doc_people(ctx: _Context, doc: str, fee_basis: float) -> _DocPeople:
    """감정서 한 건에 누가 어떤 자격으로 붙는가."""
    entries = manager_entries(ctx.meta[doc]["manager"])
    managers = [name for name, common in entries if not common]
    common = {name for name, is_common in entries if is_common}
    ga_split: "dict[str, float]" = {}
    for name, amount in ctx.gaprice.get(doc, {}).items():
        plain, is_common = unwrap_common(name)
        if is_common:
            common.add(plain)
        else:
            ga_split[plain] = ga_split.get(plain, 0.0) + amount
    bk_split: "dict[str, float]" = {}
    for name, pct in ctx.booking.get(doc, {}).items():
        plain, is_common = unwrap_common(name)
        if is_common:
            common.add(plain)
        else:
            bk_split[plain] = bk_split.get(plain, 0.0) + pct
    if bk_split:
        total = sum(bk_split.values()) or 100.0
        bk_split = {name: pct * 100 / total for name, pct in bk_split.items()}
    manual = set(ctx.manual.get(doc, {}))
    if ga_split and fee_basis > 0 and sum(ga_split.values()) >= fee_basis * 0.99:
        split = set(ga_split)                  # 승인 배분이 전부면 그것이 정답
    else:
        split = set(ga_split) | manual | set(bk_split) | set(managers)
    common -= manual                            # 지분표가 있으면(우리은행 공동유치 50%) 지분 사람이다
    common -= split
    woori = {name for name in common if is_woori(ctx.meta[doc]["customer_name"])}   # 유치자 공(주주이사) + 우리은행 → 순수수료 50%
    common -= woori
    split |= woori
    owner = channel_owner(ctx.meta[doc]["customer_name"])
    if owner and common and owner[0] in split:
        # KDB 건은 담당이 '윤도,공(장재원)' 꼴 — 윤도는 지분 행이 아니라 채널 23% 공통건 행으로 (_rows 가 만든다)
        split.discard(owner[0])
        managers = [name for name in managers if name != owner[0]]
    for (d, person), acts in ctx.overrides.items():
        if d != doc:
            continue
        if "INCLUDE" in acts and person not in common:
            split.add(person)
        if "EXCLUDE" in acts:
            split.discard(person)
            common.discard(person)
    return _DocPeople(split=split, common=common, managers=managers, booking=bk_split, woori=woori)


def _share_for(ctx: _Context, doc: str, person: str, fee_basis: float, people: _DocPeople, note_map, acts):
    manual = ctx.manual.get(doc, {}).get(person)
    if person in people.woori and manual is None and acts.get("SHARE") is None:
        return ShareHit(WOORI_JOINT_PCT, "WOORI")
    if doc.startswith("KB약식-") and acts.get("SHARE") is None:
        return ShareHit(SIMPLE_APPRAISAL["share_pct"], "SIMPLE")
    manual_pct = acts["SHARE"] if acts.get("SHARE") is not None else (
        manual["share_pct"] if manual and manual["source"] == "MANUAL" else None
    )
    seed_pct = manual["share_pct"] if manual and manual["source"] != "MANUAL" else None
    ga = {unwrap_common(n)[0]: v for n, v in ctx.gaprice.get(doc, {}).items() if not unwrap_common(n)[1]}
    return resolve_share(
        person, in_price=ga.get(person, 0.0), fee_total=fee_basis,
        manual=manual_pct, seed=seed_pct, booking=people.booking.get(person),
        charge_idx=sources_apw.charge_ratio(ctx.meta[doc], person), note=note_map, names=people.managers,
    )


def _row_kind(ctx: _Context, person: str, receipt_date: "date | None", acts) -> "tuple[str, float | None, date | None, str, list[str]]":
    """접수일과 요율 스케줄로 그 행이 주주 행인지 소속 행인지 정한다.
    소속인데 구간에 들면 주주(막 주주가 된 사람), 주주인데 첫 구간 전 접수면 소속(그때는 소속이었다)."""
    kind, _, _ = _person_kind(ctx, person)
    blocks = ctx.sched.get(person, [])
    rate, block_from, source = rate_for(blocks, receipt_date)
    flags: "list[str]" = []
    if kind == "ASSOCIATE":
        if source != "SCHEDULE":
            return "ASSOCIATE", None, None, "", flags
        kind = "SHAREHOLDER"
    elif not blocks:
        # 요율표가 아예 없는 주주(윤도처럼 평·동 시트 '주주 합계'로만 나오는 사람) — 소속 누진으로 계산하고 알린다
        ctx.warnings.append(f"{person}: 요율표가 없어 소속(누진)으로 계산했습니다 — 상여 설정에서 요율을 넣으세요.")
        return "ASSOCIATE", None, None, "", ["NO_SCHEDULE"]
    elif source == "FALLBACK_LATEST" and receipt_date is not None:
        earliest = min((b.from_date for b in blocks if b.from_date), default=None)
        if earliest and receipt_date < earliest:
            ctx.warnings.append(f"{person}: 첫 요율 구간({earliest}) 전에 접수된 건은 소속(누진)으로 계산했습니다.")
            return "ASSOCIATE", None, None, "", ["FORMER_ASSOCIATE"]
    if acts.get("RATE") is not None:
        rate, source = float(acts["RATE"]), "OVERRIDE"
    return kind, rate, block_from, source, flags


def _person_common_rate(ctx: _Context, person: str) -> "float | None":
    entry = ctx.people.get(person)
    return float(entry["common_rate"]) if entry and entry.get("common_rate") is not None else None


def _signing(ctx: _Context, doc: str, person: str) -> "tuple[bool, float]":
    """지분표 합이 100 을 넘는 감정서(캡스톤 김정원 100 + 안창덕 2.5) → (서명료 행인가, 주인의 지분 차감 %)."""
    shares = {p: float(v["share_pct"]) for p, v in ctx.manual.get(doc, {}).items()}
    if not shares or sum(shares.values()) <= 100.5:
        return False, 0.0
    signers = {p: pct for p, pct in shares.items() if pct <= SIGNING_MAX_PCT}
    if person in signers:
        return True, 0.0
    if signers and person == max(shares, key=shares.get):
        return False, sum(signers.values())
    return False, 0.0


def _build_row(ctx: _Context, cand, person: str, people: _DocPeople, note_map, *, common: bool, rate_override: "float | None" = None) -> "engine.Row | None":
    doc = cand["doc_id"]
    meta = ctx.meta[doc]
    acts = ctx.overrides.get((doc, person), {})
    fee_basis = _fee_basis(cand, meta)
    if common:
        pct, share_source = 100.0, "COMMON"
    else:
        hit = _share_for(ctx, doc, person, fee_basis, people, note_map, acts)
        pct, share_source = hit.pct, hit.source
    fee = float(acts["FEE"]) if acts.get("FEE") is not None else fee_basis * pct / 100
    flags = list(cand.get("flags", []))
    signing, signing_paid = (False, 0.0) if common else _signing(ctx, doc, person)
    if signing:
        flags.append("SIGNING_FEE")
    elif signing_paid:
        flags.append("SIGNING_PAID")
    prior = ctx.paid.get((doc, person), 0.0)
    if prior:
        if abs(fee - prior) < 1:
            ctx.held.append({"doc_id": doc, "person": person, "reason": "ALREADY_PAID", "fee": prior})
            return None
        fee, flags = fee - prior, flags + ["ADJUST"]
    if person not in ctx.active and "INCLUDE" not in acts:
        ctx.held.append({"doc_id": doc, "person": person, "reason": "RETIRED", "fee": fee})
        return None
    min_bonus = 0.0
    if common:
        row_kind, block_from = "COMMON", None
        rate, min_bonus, rate_source = common_rate_rule(meta["work_type"], meta["customer_name"], _person_common_rate(ctx, person))
        if rate_override is not None:
            rate, min_bonus, rate_source = float(rate_override), 0.0, "CHANNEL"
        if acts.get("RATE") is not None:
            rate, min_bonus, rate_source = float(acts["RATE"]), 0.0, "OVERRIDE"
    else:
        row_kind, rate, block_from, rate_source, kind_flags = _row_kind(ctx, person, meta["receipt_date"], acts)
        flags += kind_flags
        if row_kind == "SHAREHOLDER" and rate_source not in ("SCHEDULE", "OVERRIDE"):
            ctx.warnings.append(
                f"{person}: {doc} 접수일 {meta['receipt_date'] or '없음'} — 요율 구간 밖"
                + (f", 가장 최근 블록 {rate:g}% 적용" if rate is not None else ", 요율 없음(상여 미계산)")
            )
    ratio = pct / 100
    survey = (
        survey_payout(meta["survey_fee"], ctx.claims.get(doc), people.managers)
        if people.managers and person == people.managers[0] else 0.0
    )
    return engine.Row(
        doc_id=doc, person=person, kind=row_kind, work_type=meta["work_type"],
        # 서명료 지분은 주인의 토지조사비에서 뺀다 (엑셀 G = −2.5%·F) — 주인의 K·P 는 전액 F 기준 그대로
        fee=fee, land_fee=float(meta["land_fee"]) * ratio - fee_basis * signing_paid / 100,
        travel_fee=travel_shortfall(float(meta["travel_billed"]), float(meta["travel_claimed"])) * ratio,
        # 당월감정서경비는 전표를 자동으로 빼지 않는다(2026-08-27) — 전표는 대장의 대기 후보가 되고, 적용된 것만 빠진다
        survey_fee=survey, expense_fee=0.0,
        rate=rate, block_from=block_from, customer_name=meta["customer_name"],
        receipt_date=meta["receipt_date"], share_pct=pct, share_source=share_source,
        rate_source=rate_source, flags=tuple(flags), signing=signing, min_bonus=min_bonus,
    )


def _rows(ctx: _Context, included) -> "tuple[dict, dict, dict]":
    """사람별 행 묶음: 주주 행 / 주주의 공통건 / 소속(소속 행 + 공통건)."""
    share_rows, common_rows, assoc_rows = defaultdict(list), defaultdict(list), defaultdict(list)
    for doc in sorted(included):
        cand, meta = included[doc], ctx.meta[doc]
        fee_basis = _fee_basis(cand, meta)
        people = _doc_people(ctx, doc, fee_basis)
        note = parse_share_note(meta["customer_name"])
        note_map = match_note_names(note.shares, sorted(people.split)) if note else None
        for person in sorted(people.split | people.common):
            row = _build_row(ctx, cand, person, people, note_map, common=person in people.common)
            if row is None:
                continue
            person_kind, _, _ = _person_kind(ctx, person)
            if row.kind == "SHAREHOLDER":
                share_rows[person].append(row)
            elif row.kind == "COMMON" and person_kind != "ASSOCIATE":
                common_rows[person].append(row)
            else:
                assoc_rows[person].append(row)
        owner = channel_owner(meta["customer_name"])                     # KDB 건: 담당 공(X) 4% + 윤도 23%
        if owner and people.common and owner[0] not in (people.split | people.common):
            row = _build_row(ctx, cand, owner[0], people, note_map, common=True, rate_override=owner[1])
            if row is not None:
                target = assoc_rows if _person_kind(ctx, owner[0])[0] == "ASSOCIATE" else common_rows
                target[owner[0]].append(row)
    return share_rows, common_rows, assoc_rows


def _associate_params(ctx: _Context, person: str) -> "tuple[float, float]":
    kind, pay_ratio, tax_rate = _person_kind(ctx, person)
    return (pay_ratio, tax_rate) if kind == "ASSOCIATE" else ASSOCIATE_DEFAULTS


_REMARK_NAMES = re.compile(r"[-–]\s*([가-힣]{2,4}(?:\s*[,·/]\s*[가-힣]{2,4})*)\s*$")


def _remark_names(ctx: _Context, remark: Any) -> "list[str]":
    match = _REMARK_NAMES.search(str(remark or ""))
    if not match:
        return []
    known = set(ctx.people) | set(ctx.active)
    return [n.strip() for n in re.split(r"[,·/]", match.group(1)) if n.strip() in known]


def _voucher_people(ctx: _Context, voucher_rows) -> "list[dict[str, Any]]":
    """감정서번호 없는 전표에 적요 끝의 이름을 붙인다('… 수입인지-김형식' → persons=['김형식'])."""
    return [
        {**row, "persons": _remark_names(ctx, row.get("remark"))} if not row.get("doc_ids") else row
        for row in voucher_rows
    ]


def _voucher_ratios(ctx: _Context, r: Readers, db, voucher_rows, ratios: "dict[tuple[str, str], float]") -> "dict[tuple[str, str], float]":
    """전표의 감정서가 이번 달 행에 없으면 적요 끝의 이름('…수입인지-강무진,정인수'), 없으면 감정서 담당자에게 균등.

    엑셀 감정서관련비용공제내역은 감정서가 그 달 상여에 없어도 담당자에게 공제했다 — 같은 규칙.
    """
    known = set(ctx.people) | set(ctx.active)
    have = {doc for doc, _ in ratios}
    extra = sorted({doc for row in voucher_rows for doc in row.get("doc_ids", []) if doc not in have})
    meta = r.doc_meta(db, extra) if extra else {}
    result = dict(ratios)
    for row in voucher_rows:
        named = _remark_names(ctx, row.get("remark"))
        for doc in row.get("doc_ids", []):
            if doc in have:
                continue
            people = named or [name for name, _ in manager_entries(str((meta.get(doc) or {}).get("manager") or ""))]
            people = [p for p in people if p in known] or people
            for name in dict.fromkeys(people):
                result[(doc, name)] = 100.0 / len(set(people))
    return result


def bonus_report_v2(db, period: str, *, scope_person: "str | None" = None, readers: "Readers | None" = None) -> "dict[str, Any]":
    r = readers or Readers()
    perf_from, perf_to = closing.period_bounds(period)
    status = r.close_status(db, period)
    if status == "CLOSED":
        snapshot = closing.snapshot_from_rows(period, r.load_result(db, period))
        if scope_person:   # 스냅샷도 개인 범위는 본인 것만 — 계산 경로와 같은 울타리
            for group in ("shareholders", "common", "associates", "summary"):
                snapshot[group] = [entry for entry in snapshot[group] if entry["name"] == scope_person]
            snapshot["held"] = [h for h in snapshot["held"] if h.get("person") in (None, scope_person)]
        return snapshot

    warnings: "list[str]" = []
    held: "list[dict[str, Any]]" = []
    overrides = r.load_overrides(db, period)
    included = _select_docs(r.candidate_docs(db, perf_from, perf_to), overrides, perf_to, held, warnings)
    docs = sorted(included)
    meta = _meta_with_fallback(db, r, docs, warnings)
    # 국민약식: 관리번호 400* 는 APW 마스터에 없다 — 입금월 전표 합의 50% 를 김형수 가격자문 한 줄로 (엑셀 '국민약식')
    simple_total, simple_count = r.simple_appraisal(db, perf_from, perf_to)
    if simple_total > 0:
        simple_doc = simple_appraisal_doc_id(f"{perf_from:%Y%m}")
        included[simple_doc] = {"doc_id": simple_doc, "fee_total": simple_total, "sources": ["SIMPLE"], "flags": ["SIMPLE_APPRAISAL"]}
        meta[simple_doc] = {
            **_EMPTY_META, "work_type": SIMPLE_APPRAISAL["work_type"], "manager": SIMPLE_APPRAISAL["owner"],
            "customer_name": f"국민은행 약식평가 {simple_count}건 (전표 {simple_total:,.0f}원의 {SIMPLE_APPRAISAL['share_pct']:g}%)",
            "receipt_date": perf_to, "base_fee": simple_total, "meta_source": "SIMPLE",
        }
    for doc, cand in included.items():
        # 수기로 포함한 감정서 — APW 마스터에 기초수수료가 있으면 그것을 쓴다. 그것도 없을 때만 FEE 오버라이드를 요구한다.
        if "NO_CANDIDATE" in cand.get("flags", []) and _fee_basis(cand, meta[doc]) <= 0 \
                and not any(acts.get("FEE") for (d, _), acts in overrides.items() if d == doc):
            warnings.append(f"{doc}: 후보가 아닌 감정서를 포함했는데 수수료를 찾지 못했습니다 — FEE 오버라이드가 없으면 0원입니다.")
    for (doc, _), acts in overrides.items():          # 수기 행(국민약식 등)의 업무분류
        if acts.get("WORK") and doc in meta:
            meta[doc] = {**meta[doc], "work_type": str(acts["WORK"])}
    voucher_rows = r.voucher_expense_rows(db, perf_from, perf_to)
    # 감정서번호가 없는 경비 전표는 후보가 못 되니 참고 목록으로 (사람 몫이면 공제 대장에 직접 올린다)
    expenses: "dict[str, float]" = {}
    carry = r.carry_in(db, period)
    if carry is None:
        warnings.append(f"전월({closing.prev_period(period)}) 마감이 없어 미납비이월을 0으로 두었습니다 — 필요하면 UNPAID_CARRY 공제로 넣으세요.")
        carry = {}
    ctx = _Context(
        perf_from=perf_from, perf_to=perf_to, overrides=overrides, meta=meta,
        gaprice=r.gaprice_allocations(db, docs), booking=r.booking_shares(db, docs),
        manual=r.load_shares(db, docs), claims=r.survey_claims(db, docs), expenses=expenses,
        people={p["person"]: p for p in r.list_persons(db)}, depts=r.dept_by_name(db),
        active=set(r.active_names(db)), sched=r.load_schedule(db), paid=r.already_paid(db, docs),
        carry=carry, variable=r.variable_costs(db, f"{perf_from:%Y-%m}"), deductions=r.load_deductions(db, period),
        warnings=warnings, held=held,
    )
    share_rows, common_rows, assoc_rows = _rows(ctx, included)
    voucher_rows = _voucher_people(ctx, voucher_rows)
    # 감정서번호도 사람 이름도 없는 경비 전표(주민세·국민연금 같은 회사 비용)는 후보가 못 되니 참고 목록으로
    expense_notes = [
        {"voucher_date": row["voucher_date"].isoformat() if row.get("voucher_date") else None,
         "account_name": row.get("account_name"), "amount": row.get("amount"), "remark": row.get("remark")}
        for row in voucher_rows if not row.get("doc_ids") and not row.get("persons")
    ]
    if scope_person is None:
        # 경비 전표 → 그 감정서 사람들의 대기 후보 (지분대로 나눔). 개인 범위 조회에서는 만들지 않는다.
        ratios = {
            (row.doc_id, row.person): row.share_pct
            for group in (share_rows, common_rows, assoc_rows) for rows in group.values() for row in rows
        }
        # 감정서 관련 공제는 감정서번호와 상관없이 전부 뺀다(재무팀 규칙 1) → 전표 후보를 이 달에 바로 적용
        r.sync_voucher_candidates(db, voucher_rows, _voucher_ratios(ctx, r, db, voucher_rows, ratios), apply_period=period)

    # 행이 없어도 가변비·이월·공제가 있는 주주는 빈 블록을 만든다 — 단 요율표가 있는 진짜 주주만
    # (윤도처럼 평·동 '주주 합계'로만 나오는 사람은 공통건 합계에서 공제한다)
    shareholder_names = set(share_rows) | {
        name for name, entry in ctx.people.items()
        if entry["kind"] == "SHAREHOLDER" and ctx.sched.get(name)
        and (ctx.variable.get(name) or ctx.carry.get(name) or ctx.deductions.get(name))
    }
    shareholders = []
    for name in sorted(shareholder_names):
        result = engine.shareholder_person(
            share_rows.get(name, []), variable_auto=ctx.variable.get(name, 0.0),
            carry_in=ctx.carry.get(name, 0.0), deductions=ctx.deductions.get(name, []),
        )
        warnings.extend(f"{name}: {w}" for w in result.pop("warnings", []))
        shareholders.append({"name": name, "retired": name not in ctx.active, **result})
    common = []
    for name in sorted(common_rows):
        _, _, tax_rate = _person_kind(ctx, name)
        # 주주 블록이 따로 없는 사람(윤도)의 공제는 여기서 뺀다 — 엑셀 평·동 AC
        result = engine.associate_person(
            common_rows[name], pay_ratio=1.0, tax_rate=tax_rate,
            deductions=ctx.deductions.get(name, []) if name not in shareholder_names else [],
        )
        result["kind"] = "COMMON"
        common.append({"name": name, "retired": name not in ctx.active, **result})
    associates = []
    for name in sorted(assoc_rows):
        pay_ratio, tax_rate = _associate_params(ctx, name)
        result = engine.associate_person(
            assoc_rows[name], pay_ratio=pay_ratio, tax_rate=tax_rate,
            deductions=ctx.deductions.get(name, []) if name not in shareholder_names else [],
        )
        associates.append({"name": name, "retired": name not in ctx.active, **result})

    if scope_person:
        shareholders = [p for p in shareholders if p["name"] == scope_person]
        common = [p for p in common if p["name"] == scope_person]
        associates = [p for p in associates if p["name"] == scope_person]
        held = [h for h in held if h.get("person") in (None, scope_person)]
    return {
        "period": period, "perf_month": f"{perf_from:%Y%m}", "status": status or "OPEN",
        "shareholders": shareholders, "common": common, "associates": associates,
        "held": held, "warnings": sorted(set(warnings), key=warnings.index), "expense_notes": expense_notes[:200],
        "summary": summarize(shareholders, common, associates),
        # 화면 인라인 편집의 현재 값 — 공제는 사람별, 오버라이드는 (감정서, 사람)별
        "deductions": ctx.deductions if scope_person is None else {k: v for k, v in ctx.deductions.items() if k == scope_person},
        "overrides": [
            {"doc_id": doc, "person": person, "actions": acts}
            for (doc, person), acts in sorted(overrides.items()) if scope_person in (None, person)
        ],
        # 공제 대장에서 아직 안 쓴 항목 — 다이얼로그에서 골라 적용한다
        "pending_deductions": {
            name: items for name, items in r.pending_deductions(db).items() if scope_person in (None, name)
        },
    }
