"""화면값이 **소스 어디서 오는지** 역추적한다 — 새 은행 매핑의 출발점.

`recon_form.py --values-out` 이 모아 둔 문서별 화면값을 받아, 같은 문서의 `.gam` 테이블·
의견서 개요·명세행·APW DB 를 전부 뒤져 **그 값과 같은 소스 경로**를 찾는다. 여러 문서에서
같은 경로가 반복해서 맞으면 그게 매핑 규칙이다.

사람이 표를 눈으로 맞추는 것보다 정확하다 — 값이 같은 곳을 빠짐없이 훑고, 몇 건에서
맞았는지 세어 준다. 후보가 여럿이면 사람이 고르면 된다.

    python tools/trace_values.py recon/nh_screen.json
    python tools/trace_values.py recon/nh_screen.json --label 감정평가액 --detail
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.gam_bridge import load_extracted    # noqa: E402
import verify_form as vf                         # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent

_CODE = re.compile(r"\((\d+)\)\s*$")          # 콤보 표시값 뒤의 내부코드 `박용준(3056)`
_DATE = re.compile(r"^(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\.?$")
_US_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def norm(value) -> str:
    """비교용 정규화 — 콤마·공백·전각·콤보코드를 없애고, 숫자·날짜는 표준형으로."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = _CODE.sub("", text).strip()
    text = text.replace(",", "").replace(" ", "")
    if not text:
        return ""
    match = _DATE.match(text) or None
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    us = _US_DATE.match(text)
    if us:                                     # gamexport 가 로캘에 따라 8/12/2026 로 찍는다
        month, day, year = (int(g) for g in us.groups())
        if month > 12:
            month, day = day, month
        return f"{year:04d}-{month:02d}-{day:02d}"
    try:                                        # 318.00 == 318 로 보게
        number = Decimal(text)
    except InvalidOperation:
        return text
    return format(number.normalize(), "f")


def source_index(cfg, doc: str) -> dict[str, list[str]]:
    """이 문서에서 뽑을 수 있는 **모든 소스 값** → {경로: [값…]}.

    경로는 사람이 읽고 바로 코드로 옮길 수 있게 적는다(`land_list0.PRICE`, `outline.zone`,
    `db.jibun.bun1`, `fee.expense_net` …).
    """
    gam = load_extracted(str(ROOT / "output" / doc))
    index: dict[str, list[str]] = defaultdict(list)

    for table, rows in gam.tables.items():
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            for column, value in row.items():
                text = norm(value)
                if text:
                    index[f"{table}.{column}"].append(text)

    context = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))

    def add(path: str, value) -> None:
        text = norm(value)
        if text:
            index[path].append(text)

    outline = context.outline
    for field in ("address", "road_address", "zone", "usage", "category", "building_use",
                  "struct", "floors_text", "approval_date", "area_exclusive", "area_common",
                  "area_supply", "area_land_right", "area_total", "area_land", "unit_count",
                  "public_price"):
        add(f"outline.{field}", getattr(outline, field, None))
    add("outline.ground_floors", outline.ground_floors)
    add("outline.basement_floors", outline.basement_floors)

    add("context.site_address", context.site_address)
    add("context.price_point_date", context.price_point_date)
    add("context.survey_date", context.survey_date)
    add("context.total_amount", context.total_amount)
    add("context.business_number", context.business_number)

    fee = context.fee
    for field in ("net", "vat", "subtotal", "total", "expense_base", "expense_extra"):
        add(f"fee.{field}", getattr(fee, field, None))
    add("fee.expense_net", fee.expense_net)
    add("fee.expense_with_vat", fee.expense_with_vat)

    parties = context.parties
    add("db.parties.boss", parties.boss)
    add("db.parties.reviewer", parties.reviewer)
    for i, name in enumerate(parties.appraisers):
        add(f"db.parties.appraiser{i}", name)

    jibun = context.jibun
    if jibun is not None:
        for field in ("reg", "eub", "san", "bun1", "bun2"):
            add(f"db.jibun.{field}", getattr(jibun, field, None))
        add("db.jibun.legal_code", jibun.legal_code)
        add("db.jibun.jibun_kind", jibun.jibun_kind)
    if context.account is not None:
        add("db.account.number", context.account.number)
        add("db.account.holder", context.account.holder)

    standard = context.standard_land
    for field in ("address", "price", "base_date"):
        add(f"standard_land.{field}", getattr(standard, field, None))

    for i, row in enumerate(context.details):
        for field in ("seq_no", "mark", "location", "jibun", "category", "zone", "struct",
                      "note", "area_public", "area_assessed", "unit_price", "amount",
                      "unit_kind"):
            add(f"detail.{field}", getattr(row, field, None))
            if i == 0:
                add(f"detail[0].{field}", getattr(row, field, None))
    for row in context.gongbu:
        for field in ("kind", "registry_no", "seq_no"):
            add(f"gongbu.{field}", getattr(row, field, None))
    return index


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="trace_values")
    p.add_argument("screen_json", help="recon_form --values-out 산출물")
    p.add_argument("--label", action="append", default=None, help="이 라벨만(여러 번 가능)")
    p.add_argument("--detail", action="store_true", help="문서별 값까지 보여준다")
    p.add_argument("--top", type=int, default=6, help="라벨당 후보 경로 수")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env or str(ROOT / ".env"))

    screens = json.loads(Path(args.screen_json).read_text(encoding="utf-8"))
    indexes = {}
    for doc in screens:
        try:
            indexes[doc] = source_index(cfg, doc)
        except Exception as error:
            print(f"⚠ {doc} 소스 적재 실패: {type(error).__name__}: {str(error)[:70]}")

    # 라벨 → {경로: 맞은 문서 수}, 그리고 값이 있었던 문서 수
    hits: dict[str, Counter] = defaultdict(Counter)
    seen: Counter = Counter()
    samples: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for doc, record in screens.items():
        index = indexes.get(doc)
        if index is None:
            continue
        for field in record["fields"]:
            label = field["label"] or f"(라벨없음 @{field['left']},{field['top']})"
            value = norm(field["value"])
            if not value:
                continue
            seen[label] += 1
            samples[label].append((doc.split("-")[-1], value))
            for path, values in index.items():
                if value in values:
                    hits[label][path] += 1

    labels = args.label or sorted(seen, key=lambda k: -seen[k])
    for label in labels:
        if label not in seen:
            print(f"\n=== {label} — 화면에 값이 없음")
            continue
        distinct = len({value for _, value in samples[label]})
        # 값이 한 종류뿐이면(대개 0) 어느 경로에나 걸린다 — 일치 건수가 의미 없다.
        weak = " ⚠값이 한 종류뿐이라 경로 일치는 우연일 수 있음" if distinct <= 1 else ""
        print(f"\n=== {label}  (값 있는 문서 {seen[label]}건 · 서로 다른 값 {distinct}종){weak}")
        ranked = hits[label].most_common(args.top)
        if not ranked:
            print("    ✗ 소스에서 같은 값을 못 찾음 — 사람 입력이거나 계산이 필요")
        for path, count in ranked:
            flag = "★" if count == seen[label] else " "
            print(f"   {flag} {count:2}/{seen[label]:<2} {path}")
        if args.detail:
            for doc, value in samples[label]:
                print(f"        {doc}: {value[:48]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
