"""수협·하나·우리·새마을 매핑 오프라인 회귀검사 — 인계본 실폼 덤프(recon/<bank>_screen.json, 폼 1장)와 대조.

농협판(check_nh_offline: 문서별 정답지)과 달리 인계본 덤프는 **폼 한 장**(문서번호 미기록)이라, 문서번호를 주면
그 문서의 매핑값을 덤프와 대조한다. 덤프가 어느 문서인지 모르면 후보를 여러 개 줘서 ✅ 가 가장 많은 것을 찾는다.
문서번호만 있고 덤프가 없는 은행/문서도 `--build-only` 로 전 물건 매핑을 돌려 크래시·불변식만 본다.

    python tools/check_screen_offline.py --bank hnb 01-2609-3-2751 01-2608-3-2746
    python tools/check_screen_offline.py --bank mgb --build-only 01-2609-3-2762 01-2608-3-2568
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
from bankon.mapping import hnb, mgb, ssb, wrb   # noqa: E402
from bankon.ui import form as form_mod           # noqa: E402
import screen_band                               # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_hnb as VH                     # noqa: E402
import verify_fill_mgb as VM                     # noqa: E402
import verify_fill_ssb as VS                     # noqa: E402
import verify_fill_wrb as VW                     # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
BANKS = {
    "ssb": (ssb, VS, "수협"), "hnb": (hnb, VH, "하나"), "wrb": (wrb, VW, "우리"), "mgb": (mgb, VM, "새마을"),
}
_CODE = re.compile(r"\((\d+)\)\s*$")


def norm(value) -> str:
    text = unicodedata.normalize("NFKC", str(value) if value is not None else "")
    return _CODE.sub("", text).replace(",", "").replace("-", "").replace(" ", "").strip()


def screen_map(record: dict) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in record["fields"]:
        label = field["label"]
        if label and field["db_bound"] and str(field["value"]).strip():
            values.setdefault(label, str(field["value"]).strip())
    return values


def _context(cfg, doc: str):
    out = ROOT / "output" / doc
    if out.is_dir():
        gam = load_extracted(str(out))
    else:
        got = vf.fetch_gam(cfg, doc)
        gam = got[0] if isinstance(got, tuple) else got
    return vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))


def _seqs(context) -> list[str]:
    rows = [r for r in context.details if r.is_land or r.is_building]
    seen, out = set(), []
    for r in rows:
        if r.seq_no and r.seq_no not in seen:
            seen.add(r.seq_no)
            out.append(r.seq_no)
    return out or ["1"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="check_screen_offline")
    p.add_argument("--bank", choices=tuple(BANKS), required=True)
    p.add_argument("doc_id", nargs="+")
    p.add_argument("--build-only", action="store_true", help="덤프 대조 없이 전 물건 매핑만(크래시 검사)")
    p.add_argument("--detail", action="store_true")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env or str(ROOT / ".env"))
    mapping, verify, name = BANKS[args.bank]
    dump_path = ROOT / "recon" / f"{args.bank}_screen.json"
    record = json.loads(dump_path.read_text(encoding="utf-8")) if (dump_path.exists() and not args.build_only) else None

    worst = 0
    for doc in args.doc_id:
        try:
            ctx = _context(cfg, doc)
        except BaseException as error:  # noqa: BLE001  (SystemExit(.gam 없음) 포함)
            print(f"\n===== {doc} — ⛔ 추출 실패 {type(error).__name__}: {str(error)[:80]}")
            worst = 1
            continue
        seqs = _seqs(ctx)
        print(f"\n===== {doc} ({name}) 물건 {len(seqs)}개 {seqs[:8]} · gam_category={ctx.gam_category!r}")
        for seq in seqs:
            try:
                values = mapping.build(ctx, seq if len(seqs) > 1 else None)
            except Exception as error:  # noqa: BLE001
                print(f"  [{seq}] ⛔ 크래시 {type(error).__name__}: {str(error)[:80]}")
                worst = 1
                continue
            filled = {form_mod.display_label(k): v for k, v in values.items() if v not in (None, "")}
            print(f"  [{seq}] 채움 {len(filled)}칸: " + " · ".join(f"{k}={str(v)[:14]}" for k, v in list(filled.items())[:10]))
            reasons = verify.guard_reasons(ctx, values, seq if len(seqs) > 1 else None)
            if reasons:
                print(f"  [{seq}] ⚠ 실입력 보류 사유: {'; '.join(reasons)}")
        if record is None:
            continue
        screen = screen_map(record)
        resolved = verify.resolve_seq(ctx, screen)
        mine = mapping.build(ctx, resolved if len(seqs) > 1 else None)
        screen_band.add_positional(screen, record, mine)
        tally = Counter()
        rows = []
        for label in sorted(set(mine) | set(screen)):
            shown = form_mod.display_label(label)
            ours, theirs = norm(mine.get(label)), norm(screen.get(label))
            if not ours and not theirs:
                continue
            mark = ("✅" if ours == theirs else "❌") if (ours and theirs) else ("🖊" if ours else "📄")
            tally[mark] += 1
            rows.append((mark, shown, ours or "-", theirs or "-"))
        print(f"  ── 덤프 대조(화면 순번 {resolved}): ✅{tally['✅']} ❌{tally['❌']} 🖊{tally['🖊']} 📄{tally['📄']}")
        order = {"❌": 0, "🖊": 1, "📄": 2, "✅": 3}
        for mark, label, ours, theirs in sorted(rows, key=lambda r: (order[r[0]], r[1])):
            if mark == "✅" and not args.detail:
                continue
            print(f"     [{mark}] {label[:16]:18} 우리={ours[:26]:28} 화면={theirs[:26]}")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
