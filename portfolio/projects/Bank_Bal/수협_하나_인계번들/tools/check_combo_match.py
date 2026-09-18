"""우리가 내는 콤보 값이 **화면 목록에 실제로 있는가** — 자동선택을 켜기 전 관문. 오프라인.

`recon_combos.py` 가 실폼에서 모아 둔 `recon/combo_<폼클래스>.md` 와, 캐시된 문서를
매핑에 통과시킨 결과를 대조한다. 목록에 없는 값은 `--select` 를 켜도 **절대 못 고른다** —
`select_item` 이 ESC 로 취소하고 `못찾음(목록)` 을 남긴다(틀린 항목을 고르진 않는다).

즉 여기서 ❌ 가 나오면 "위험"이 아니라 "그 칸은 여전히 사람이 고른다"는 뜻이다.
❌ 를 줄이는 게 자동화율을 올리는 길이다.

    python tools/check_combo_match.py --bank ibk
    python tools/check_combo_match.py --bank nh --detail
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config             # noqa: E402
from bankon.gam_bridge import load_extracted      # noqa: E402
from bankon.mapping import ibk, kookmin, nh       # noqa: E402
from bankon.ui import combos                      # noqa: E402
from bankon.ui import form as form_mod            # noqa: E402
from bankon.ui.driver import combo_text           # noqa: E402
import verify_form as vf                          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent

# 은행 → (폼클래스, 매핑모듈, cover0.custpart 에서 찾을 말)
BANKS = {
    "kb": ("TBNKKBB24DAMB", kookmin, "국민은행"),
    "ibk": ("TBNKKIB24DAMB", ibk, "기업은행"),
    "nh": ("TBNKNHB24DAMB", nh, "농협"),
}


def docs_for(marker: str) -> list[Path]:
    """캐시된 추출 폴더 중 그 은행 건 — `cover0.json` 의 `custpart` 로 가른다."""
    found = []
    for folder in sorted((ROOT / "output").iterdir()):
        cover = folder / "cover0.json" if folder.is_dir() else None
        if cover is None or not cover.exists():
            continue
        try:
            rows = json.loads(cover.read_text(encoding="utf-8"))
        except Exception:
            continue
        if rows and marker in (rows[0].get("custpart") or ""):
            found.append(folder)
    return found


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="check_combo_match")
    p.add_argument("--bank", choices=tuple(BANKS), required=True)
    p.add_argument("--detail", action="store_true", help="문서별로 전부 출력")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env or str(ROOT / ".env"))

    form_class, mapping, marker = BANKS[args.bank]
    table = combos.for_form(form_class)
    if not table:
        print(f"수집된 콤보 목록이 없습니다 — recon/combo_{form_class}.md")
        print("  (관리자) python tools/recon_combos.py --bank "
              f"{args.bank} --doc <문서번호>")
        return 1

    print(f"=== {form_class} 콤보 목록 {len(table)}개 ===")
    for label, items in table.items():
        print(f"  {label[:18]:20} {len(items):3}개  예: {', '.join(items[:4])}")

    folders = docs_for(marker)
    print(f"\n=== 캐시 문서 {len(folders)}건으로 대조 ===")
    tally = Counter()
    hits: dict[str, Counter] = defaultdict(Counter)
    misses: dict[str, Counter] = defaultdict(Counter)
    crashed = 0

    for folder in folders:
        try:
            gam = load_extracted(str(folder))
            context = vf.build_context(cfg, folder.name, gam.tables, vf.sections_from_gam(gam))
            values = mapping.build(context)
        except Exception as error:
            crashed += 1
            if args.detail:
                print(f"  ⛔ {folder.name} {type(error).__name__}: {str(error)[:60]}")
            continue
        for key, value in values.items():
            # 위치 표기 키는 라벨이 아니라 **자리**로 짚는다 — 같은 이름의 콤보 목록과는
            # 무관하다(실측 기업 `물건종류`: 우리는 텍스트칸을 짚고, 콤보는 다른 뜻이다).
            if form_mod.POSITIONAL.match(str(key)):
                continue
            label = form_mod.display_label(key)
            items = table.get(label)
            if items is None or value in (None, ""):
                continue
            wanted = combo_text(str(value))
            if any(combo_text(item) == wanted for item in items):
                tally["✅있음"] += 1
                hits[label][str(value)] += 1
            else:
                tally["❌없음"] += 1
                misses[label][str(value)] += 1

    for mark, count in tally.most_common():
        print(f"  {mark} {count}")
    if crashed:
        print(f"  ⛔ 크래시 {crashed}")

    print("\n--- 칸별 ---")
    for label in sorted(set(hits) | set(misses)):
        good, bad = sum(hits[label].values()), sum(misses[label].values())
        state = "✅ 전부 있음" if not bad else ("❌ 전부 없음" if not good else "△ 일부만")
        print(f"  {label[:18]:20} 있음 {good:4} · 없음 {bad:4}   {state}")
        for value, count in misses[label].most_common(8 if not args.detail else 100):
            print(f"        없음 ×{count:<4} {value!r}")

    # 목록은 있는데 우리가 아무 값도 안 내는 칸 — 자동화 여지
    idle = [label for label in table if label not in hits and label not in misses]
    if idle:
        print("\n--- 우리가 값을 안 내는 콤보(사람이 고른다) ---")
        print("  " + " · ".join(idle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
