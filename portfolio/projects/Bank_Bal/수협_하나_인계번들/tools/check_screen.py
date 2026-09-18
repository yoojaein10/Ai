"""매핑값 ↔ **실화면 정답지** 전건 대조 — 라이브 폼도 FTP 도 없이. 은행 공용.

`recon_form.py --values-out recon/<은행>_screen.json` 이 실폼에서 떠 둔 화면값과, 캐시된
추출물을 매핑에 통과시킨 결과를 필드별로 맞춰 본다. EXPECT 를 손으로 적을 필요가 없다.

라벨이 없거나 겹치는 칸(위치 표기)은 `screen_band` 가 라이브와 **같은 규칙**으로 푼다.

    python tools/check_screen.py --bank ibk
    python tools/check_screen.py --bank nh --detail
    python tools/check_screen.py --bank ibk 01-2608-3-2683 --detail
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

from bankon.config import load_config           # noqa: E402
from bankon.gam_bridge import load_extracted     # noqa: E402
from bankon.mapping import ibk, kookmin, nh      # noqa: E402
from bankon.ui import form as form_mod           # noqa: E402
import screen_band                               # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_ibk as VI                     # noqa: E402
import verify_fill_kb as VK                      # noqa: E402
import verify_fill_nh as VN                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent

# 은행 → (정답지 파일, 매핑모듈, 순번정합 함수, 0패딩 비교 함수)
BANKS = {
    "ibk": ("ibk_screen.json", ibk, VI.resolve_seq, VI.compare_text),
    "kb": ("kb_screen.json", kookmin,
           lambda ctx, screen, seq=None: VK._resolve_seq(ctx, screen, seq), VK.compare_text),
    "nh": ("nh_screen.json", nh, VN.resolve_seq, VN.compare_text),
}

_CODE = re.compile(r"\((\d+)\)\s*$")


def norm(value) -> str:
    """비교용 정규화 — 콤보 코드·콤마·공백·전각을 없앤다."""
    text = unicodedata.normalize("NFKC", str(value) if value is not None else "")
    return _CODE.sub("", text).replace(",", "").replace(" ", "").strip()


def screen_map(record: dict) -> dict[str, str]:
    """화면 라벨 → 값. 같은 라벨이 여러 칸이면 **첫 칸**(`verify_form.screen_values` 규칙).

    값이 **자기 라벨과 같은** 칸은 뺀다 — 그건 값이 아니라 **열 머리**다. 국민 토지탭에
    `물건종류`·`평가방법` 같은 머리 칸이 입력칸으로 잡혀, 163건 전건이 가짜 불일치로
    올라오고 있었다(우리 `구분소유물건(거례사례)` / 화면 `평가방법`).
    """
    values: dict[str, str] = {}
    for field in record["fields"]:
        label = field["label"]
        value = str(field["value"]).strip() if field["value"] is not None else ""
        if label and field["db_bound"] and value and value != label.strip():
            values.setdefault(label, value)
    return values


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="check_screen")
    p.add_argument("--bank", choices=tuple(BANKS), required=True)
    p.add_argument("doc_id", nargs="*")
    p.add_argument("--detail", action="store_true", help="필드별 전부 출력")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env or str(ROOT / ".env"))

    filename, mapping, resolve_seq, compare_text = BANKS[args.bank]
    path = ROOT / "recon" / filename
    if not path.exists():
        print(f"정답지가 없습니다 — {path}")
        print("  (관리자) python tools/recon_form.py <문서…> "
              f"--values-out recon/{filename}")
        return 1
    screens = json.loads(path.read_text(encoding="utf-8"))
    docs = args.doc_id or list(screens)

    tally = Counter()
    per_label = Counter()
    for doc in docs:
        record = screens.get(doc)
        if record is None:
            print(f"\n===== {doc} — 화면값 없음"); continue
        # 추출물 캐시가 없으면 **크래시가 아니라 건너뛴다** — 인계본처럼 표본만 받은
        # 환경에서 없는 문서가 전부 크래시로 잡히면 진짜 크래시가 묻힌다.
        if not (ROOT / "output" / doc).is_dir():
            tally["캐시없음"] += 1
            print(f"\n===== {doc} — 추출물 없음(output/{doc}/) → 건너뜀"); continue
        try:
            gam = load_extracted(str(ROOT / "output" / doc))
            context = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
            screen = screen_map(record)
            mine = mapping.build(context, resolve_seq(context, screen))
        except Exception as error:
            tally["크래시"] += 1
            print(f"\n===== {doc} =====\n  ⛔ {type(error).__name__}: {str(error)[:80]}")
            continue

        screen_band.add_positional(screen, record, mine)
        rows = []
        for label in sorted(set(mine) | set(screen), key=str):
            name = form_mod.display_label(label)
            ours = norm(compare_text(name, str(mine.get(label) or "")))
            theirs = norm(compare_text(name, str(screen.get(label) or "")))
            if not ours and not theirs:
                continue
            mark = ("✅" if ours == theirs else "❌") if (ours and theirs) else \
                   ("🖊" if ours else "📄")
            rows.append((mark, name, ours or "-", theirs or "-"))
            tally[mark] += 1
            if mark == "❌":
                per_label[name] += 1
        counts = Counter(r[0] for r in rows)
        print(f"\n===== {doc} ({len(record['fields'])}칸) "
              f"✅{counts['✅']} ❌{counts['❌']} 🖊{counts['🖊']} 📄{counts['📄']}")
        order = {"❌": 0, "🖊": 1, "📄": 2, "✅": 3}
        for mark, name, ours, theirs in sorted(rows, key=lambda r: (order[r[0]], r[1])):
            if mark == "✅" and not args.detail:
                continue
            print(f"   [{mark}] {name[:16]:18} 우리={ours[:26]:28} 화면={theirs[:26]}")

    skipped = f" · 캐시없음 {tally['캐시없음']}" if tally["캐시없음"] else ""
    print(f"\n[합계] 문서 {len(docs)} · ✅{tally['✅']} ❌{tally['❌']} "
          f"🖊{tally['🖊']}(우리만) 📄{tally['📄']}(화면만) · 크래시 {tally['크래시']}{skipped}")
    if per_label:
        print("불일치 필드: " + " · ".join(f"{k}×{v}" for k, v in per_label.most_common()))
    return 1 if tally["크래시"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
