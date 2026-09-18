"""신한 담보 건을 자동으로 열어가며(navigate) 연속 검증 → 결과 요약.

BANK24 가 로그인돼 메인(TfrmMain)이 떠 있어야 한다. 문서를 하나씩 열어
(검색→작성폼) 읽고, `verify_live` 로직으로 원본과 대조한 뒤, 문제(❌/⚠️)만
모아 요약한다. 화면 조작은 '작성(열람)' 폼을 여는 것까지이며 값은 안 바꾼다.

    python tools/verify_batch.py 01-2608-3-2454 01-2608-3-2440 ...   # 지정 목록
    python tools/verify_batch.py --auto --limit 12                    # 최신 신한담보 자동
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.db import connect                  # noqa: E402
from bankon.ui import driver, navigate         # noqa: E402
import verify_live as V                        # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass


def shinhan_damb_docs(cfg, ym: str, limit: int) -> list[str]:
    """신한 담보 문서번호 목록(최신순). ym 예: '2608'."""
    with connect(cfg.source_sql, readonly=True) as s:
        c = s.cursor()
        c.execute(
            f"""SELECT DISTINCT DocID FROM apw_masterex
                WHERE DocID LIKE '01-{ym}-3-%'
                  AND CustName LIKE N'신한은행%' AND LWorkinfo = N'담보'
                ORDER BY DocID DESC""")
        docs = [r[0] for r in c.fetchall()]
    return docs[:limit] if limit else docs


def problems(rows) -> list[tuple]:
    return [r for r in rows if r[0].startswith("❌") or r[0].startswith("⚠️")]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="verify_batch")
    p.add_argument("doc_id", nargs="*")
    p.add_argument("--auto", action="store_true", help="신한담보 목록 자동조회")
    p.add_argument("--ym", default="2608")
    p.add_argument("--limit", type=int, default=12)
    p.add_argument("--env", default=None)
    p.add_argument("--log", default=None, help="출력을 이 파일에도 기록(관리자 실행용)")
    args = p.parse_args(argv)
    if args.log:
        sys.stdout = open(args.log, "w", encoding="utf-8", buffering=1)
        sys.stderr = sys.stdout
    cfg = load_config(args.env)

    mains = driver.find_windows(driver.MAIN_CLASS)
    if not mains:
        print("BANK24 메인창이 없습니다(로그인 필요).", file=sys.stderr)
        return 1
    session = navigate.Session(mains[0])

    docs = list(args.doc_id)
    if args.auto or not docs:
        docs = shinhan_damb_docs(cfg, args.ym, args.limit)
    print(f"대상 {len(docs)}건: {docs}\n" + "=" * 60)

    summary = []
    for i, doc in enumerate(docs, 1):
        line = f"[{i}/{len(docs)}] {doc}"
        try:
            navigate.open_document(session, doc)
        except Exception as e:
            print(f"{line}  ⛔ 열기실패: {str(e)[:60]}")
            summary.append((doc, "-", "-", "열기실패", []))
            continue
        form, msg = V.open_form()
        if form is None:
            print(f"{line}  ⏭  {msg[:50]}")
            summary.append((doc, "-", "-", "대상아님", []))
            continue
        try:
            meta, rows = V.build_rows(cfg, doc, form)
        except Exception as e:
            print(f"{line}  ⛔ 검증오류: {str(e)[:60]}")
            summary.append((doc, "-", "-", "검증오류", []))
            continue
        if meta["mismatch_doc"]:
            # 열린 화면이 요청 문서와 다름 → 비교 결과는 신뢰불가, 건너뜀
            print(f"{line}  ⛔ 열린문서 불일치(화면 본번지 {meta['screen_bun']} ≠ 문서 실제) — 건너뜀")
            summary.append((doc, meta["addr"][:18], meta["appraiser"], "다른문서열림", []))
            continue
        ok, warn, hold, base = V.counts(rows)
        probs = problems(rows)
        addr = (meta["addr"] or "")[:18]
        appr = meta["appraiser"]
        verdict = "이상없음" if not probs else f"확인 {len(probs)}"
        flag = "" if not probs else "  ⚠️"
        print(f"{line}  {addr:18} {appr:5} ✅{ok:2} ⚠️{warn} → {verdict}{flag}")
        for mark, lab, val, src in probs:
            print(f"        {mark} {lab}: 화면={val[:22]}  원본/DB={src[:22]}")
        summary.append((doc, addr, appr, verdict, probs))

    print("=" * 60 + "\n[요약]")
    clean = [s for s in summary if s[3] == "이상없음"]
    flagged = [s for s in summary if s[4]]
    skipped = [s for s in summary if s[3] in ("대상아님", "열기실패", "검증오류")]
    print(f"  이상없음 {len(clean)} / 확인필요 {len(flagged)} / 스킵 {len(skipped)}")
    if flagged:
        print("  --- 확인필요 건 ---")
        for doc, addr, appr, verdict, probs in flagged:
            plist = "; ".join(f"{m[1]}({m[2]}≠{m[3]})" for m in probs)
            print(f"    {doc} {addr} {appr}: {plist[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
