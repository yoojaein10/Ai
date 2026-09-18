"""농협 매핑 오프라인 회귀검사 — 화면값(recon/nh_screen.json)과 직접 대조.

기업판(`check_ibk_offline.py`)과 달리 **정답지가 파일로 있다** — `recon_form.py --values-out`
이 실폼에서 읽어 둔 문서별 화면값이다. 그래서 EXPECT 를 손으로 적을 필요 없이 전 필드를
자동 대조한다. 라이브 폼도 FTP 도 필요 없다.

    python tools/check_nh_offline.py                 # 전건 요약
    python tools/check_nh_offline.py --detail        # 필드별 전부
    python tools/check_nh_offline.py 01-2608-3-2625 --detail
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.gam_bridge import load_extracted    # noqa: E402
from bankon.mapping import nh                   # noqa: E402
from bankon.ui import form as form_mod           # noqa: E402
import screen_band                               # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_nh as VN                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
SCREEN = ROOT / "recon" / "nh_screen.json"

_CODE = re.compile(r"\((\d+)\)\s*$")


def norm(value) -> str:
    """비교용 정규화 — 콤보 코드·콤마·공백·전각을 없앤다."""
    text = unicodedata.normalize("NFKC", str(value) if value is not None else "")
    return _CODE.sub("", text).replace(",", "").replace(" ", "").strip()


def screen_map(record: dict) -> dict[str, str]:
    """화면 라벨 → 값. 같은 라벨이 여러 칸이면 **첫 칸**(verify_form.screen_values 와 같은 규칙)."""
    values: dict[str, str] = {}
    for field in record["fields"]:
        label = field["label"]
        if label and field["db_bound"] and str(field["value"]).strip():
            values.setdefault(label, str(field["value"]).strip())
    return values


def band_values(record: dict, above: str, below: str) -> list[str]:
    """두 라벨 사이 칸들의 값 — 순서 확인용(대조는 `screen_band.add_positional` 이 한다)."""
    return [str(f["value"] if f["value"] is not None else "").strip()
            for f in screen_band.band(record, above, below)]


# 위치 표기 풀이는 `screen_band` 한 곳에만 둔다 — 라이브(`ui.form`)와 규칙이 갈리면 안 된다.
add_positional = screen_band.add_positional


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="check_nh_offline")
    p.add_argument("doc_id", nargs="*")
    p.add_argument("--detail", action="store_true", help="필드별 전부 출력")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env or str(ROOT / ".env"))

    screens = json.loads(SCREEN.read_text(encoding="utf-8"))
    docs = args.doc_id or list(screens)

    tally = Counter()
    per_label = Counter()
    for doc in docs:
        record = screens.get(doc)
        if record is None:
            print(f"\n===== {doc} — 화면값 없음(recon_form --values-out 으로 먼저 수집)")
            continue
        if not (ROOT / "output" / doc).is_dir():
            print(f"\n===== {doc} — 추출물 없음(output/{doc}/) → 건너뜀")
            continue
        try:
            gam = load_extracted(str(ROOT / "output" / doc))
            context = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
            screen_now = screen_map(record)
            # 라이브 도구와 같은 순번 정합을 쓴다 — 다물건이면 화면이 보고 있는 물건을 골라야
            # 대조가 성립한다(실측 2645: 감정평가표 2장, 화면은 두 번째 물건).
            mine = nh.build(context, VN.resolve_seq(context, screen_now))
        except Exception as error:
            tally["크래시"] += 1
            print(f"\n===== {doc} =====\n  ⛔ {type(error).__name__}: {str(error)[:80]}")
            continue

        screen = screen_map(record)
        add_positional(screen, record, mine)
        rows = []
        for label in sorted(set(mine) | set(screen)):
            name = form_mod.display_label(label)
            ours, theirs = norm(mine.get(label)), norm(screen.get(label))
            if not ours and not theirs:
                continue
            mark = ("✅" if ours == theirs else "❌") if (ours and theirs) else \
                   ("🖊" if ours else "📄")
            rows.append((mark, name, ours or "-", theirs or "-"))
            tally[mark] += 1
            if mark == "❌":
                per_label[name] += 1
        counts = Counter(r[0] for r in rows)
        variant = "지역농협" if len(record["fields"]) > 60 else \
                  ("건물형" if len(record["fields"]) == 55 else "토지형")
        print(f"\n===== {doc} ({variant}) "
              f"✅{counts['✅']} ❌{counts['❌']} 🖊{counts['🖊']} 📄{counts['📄']}")
        order = {"❌": 0, "🖊": 1, "📄": 2, "✅": 3}
        for mark, label, ours, theirs in sorted(rows, key=lambda r: (order[r[0]], r[1])):
            if mark == "✅" and not args.detail:
                continue
            print(f"   [{mark}] {label[:16]:18} 우리={ours[:26]:28} 화면={theirs[:26]}")

    print(f"\n[합계] 문서 {len(docs)} · ✅{tally['✅']} ❌{tally['❌']} "
          f"🖊{tally['🖊']}(우리만) 📄{tally['📄']}(화면만) · 크래시 {tally['크래시']}")
    if per_label:
        print("불일치 필드: " + " · ".join(f"{k}×{v}" for k, v in per_label.most_common()))
    return 1 if tally["크래시"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
