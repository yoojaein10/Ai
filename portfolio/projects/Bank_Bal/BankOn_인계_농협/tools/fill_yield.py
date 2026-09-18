"""**빈 폼 자동입력 수율** 측정 — 우리가 실제로 몇 칸을 쓸 수 있나.

실전은 사람이 아무것도 안 넣은 폼에 우리가 채우는 것이다. 그런데 지금까지의 검증은
'사람이 이미 채운 화면과 값이 같은가'만 봤다. 값이 맞아도 **콤보라 자동선택을 안 하거나
(수동), 라벨로 칸을 못 짚으면(미발견) 실제로는 못 채운다.**

`ui.form.plan_field` 의 판정 중 `수동(선택형)`·`미발견` 은 폼이 차 있든 비어 있든 같다.
그래서 열려 있는(=사람이 채운) 폼으로도 **빈 폼 수율을 그대로 잴 수 있다.**

    ✅ 쓸수있음 = 채움 + 덮어씀 + 일치     ← 빈 폼이었다면 우리가 썼을 칸
    ⌨ 수동     = 콤보·라디오              ← v2: 콤보 자동선택
    ✗ 미발견   = 라벨로 못 짚음            ← v2: 위치기반 타겟팅
    · 값없음   = 우리 값이 None

화면엔 **쓰지 않는다**(드라이런). 관리자 권한 필요.

    python tools/fill_yield.py --bank nh  01-2608-3-2625 01-2608-3-2616
    python tools/fill_yield.py --bank ibk 01-2608-3-2683 01-2608-3-2526
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.ui import driver, navigate         # noqa: E402
from verify_grid_loop import BANKS, FILLERS    # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent

WRITABLE = ("채움", "덮어씀", "일치")
BUCKET = {"채움": "✅쓸수있음", "덮어씀": "✅쓸수있음", "일치": "✅쓸수있음",
          "수동(선택형)": "⌨수동(콤보)", "미발견": "✗미발견", "빈값": "·값없음",
          "순번(안건드림)": "·앵커"}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="fill_yield")
    p.add_argument("doc_id", nargs="+")
    p.add_argument("--bank", choices=tuple(FILLERS), required=True)
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env or str(ROOT / ".env"))

    mains = [m for m in driver.find_windows(driver.MAIN_CLASS)
             if driver.by_class(m.handle, "TcxGridSite")]
    if not mains:
        print("그리드 있는 BANK24 메인창이 없습니다 — 감정서조회 화면을 띄우세요.")
        return 1
    session = navigate.Session(mains[0])
    filler = FILLERS[args.bank]
    expected = BANKS[args.bank]["cls"]

    per_field: dict[str, Counter] = defaultdict(Counter)
    per_doc = []
    for doc_id in args.doc_id:
        print(f"\n=== {doc_id} 여는 중 …")
        try:
            form = navigate.open_document(session, doc_id)
        except Exception as error:
            print(f"    ⛔ 열기 실패: {type(error).__name__}: {str(error)[:80]}")
            continue
        if form.class_name != expected:
            print(f"    ⏭ {form.class_name} — {BANKS[args.bank]['name']} 담보 폼이 아닙니다")
            navigate.close_forms(session)
            continue
        try:
            results, _align = filler(cfg, doc_id, form, live=False)   # 드라이런
        except (Exception, SystemExit) as error:
            print(f"    ⛔ {type(error).__name__}: {str(error)[:80]}")
            navigate.close_forms(session)
            continue

        counts = Counter()
        for r in results:
            bucket = BUCKET.get(r.action.split("(")[0] if r.action.startswith("거부")
                                else r.action, "·기타")
            counts[bucket] += 1
            per_field[r.label][bucket] += 1
        total = sum(counts.values())
        writable = counts["✅쓸수있음"]
        per_doc.append((doc_id, form.class_name, len(results), writable, counts))
        print(f"    칸 {total} → " + " · ".join(f"{k} {v}" for k, v in counts.most_common()))
        print(f"    **빈 폼이면 {writable}칸 자동입력** "
              f"({writable / total * 100:.0f}% of 매핑 {total}칸)")
        for r in sorted(results, key=lambda x: x.label):
            mark = BUCKET.get(r.action, r.action)
            if mark != "✅쓸수있음":
                print(f"       {mark:12} {r.label[:18]:20} 우리={r.ours[:24]}")
        navigate.close_forms(session)

    if not per_doc:
        return 1
    print("\n" + "=" * 60)
    print(f"[{BANKS[args.bank]['name']}] 문서 {len(per_doc)}건")
    for doc_id, cls, total, writable, counts in per_doc:
        print(f"  {doc_id}  매핑 {total}칸 → 자동입력 {writable}칸 "
              f"(수동 {counts['⌨수동(콤보)']} · 미발견 {counts['✗미발견']} · "
              f"값없음 {counts['·값없음']})")

    print("\n--- 막히는 칸 (v2 우선순위) ---")
    for label, counts in sorted(per_field.items(),
                                key=lambda kv: -(kv[1]["✗미발견"] + kv[1]["⌨수동(콤보)"])):
        blocked = counts["✗미발견"] + counts["⌨수동(콤보)"]
        if not blocked:
            continue
        why = "미발견" if counts["✗미발견"] >= counts["⌨수동(콤보)"] else "콤보"
        print(f"  {blocked:2}건  {label[:20]:22} ({why})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
