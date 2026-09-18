"""국민은행 담보(TBNKKBB24DAMB) — 정품추출 → kookmin 매핑 → "채울값 ↔ 화면" 대조.

신한용 verify_fill 의 국민판. 국민은 폼도 매핑(`kookmin.py`)도 신한과 다르다
(물건종류·평가방법·공부지목·용도지역·現기준시점·표준지 등). mullist 대신
명세표(land_list/section_build)가 물건 출처.

  화면에 국민 담보폼 열어둔 상태에서:
    python tools/verify_fill_kb.py 01-2504-2-XXXX

읽기 전용.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.db import connect                  # noqa: E402
from bankon.downloader import download_to, ftp_session  # noqa: E402
from bankon.resolver import resolve_document   # noqa: E402
from bankon.gam_bridge import process_gam      # noqa: E402
from bankon.mapping import kookmin             # noqa: E402
from bankon.ui import driver                   # noqa: E402
import verify_form as vf                       # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = "TBNKKBB24DAMB"
_CODE = re.compile(r"\((\d+)\)\s*$")


def norm(t: str) -> str:
    return _CODE.sub("", (t or "").replace(",", "")).strip()


def fetch_gam_local(cfg, doc: str) -> Path:
    dest = Path("work") / doc / f"{doc}.gam"
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    with connect(cfg.source_sql, readonly=True) as s, ftp_session(cfg.ftp) as ftp:
        remote = resolve_document(s, doc).remote("gam")
        if not remote:
            raise SystemExit(f"{doc}: .gam 원격경로 없음")
        return download_to(ftp, remote, dest)


def _resolve_seq(ctx, screen, seq):
    """다물건이면 화면 감정평가액(또는 호)으로 우리 물건을 정합해 순번을 정한다.

    명세표 NO('가'/'나')와 화면 일련번호(1/2)가 달라, 화면이 보는 물건을 금액으로
    찾는다(금액은 유닛마다 유일). 단일물건이면 None(기존 동작).
    """
    if seq:
        return str(seq)
    anchors = [r for r in ctx.details if r.amount is not None]
    if len(anchors) < 2:
        return None
    amt = norm(screen.get("감정평가액", ""))
    if amt.isdigit():
        for i, r in enumerate(anchors, 1):
            if str(int(r.amount)) == amt:
                return str(i)                          # 금액 = 확정키
    ho = norm(screen.get("호", "")).replace(" ", "")
    if ho:
        for i, r in enumerate(anchors, 1):
            if (r.location or "").replace(" ", "").endswith(ho + "호"):
                return str(i)
    scr = norm(screen.get("일련번호", ""))
    return scr if scr.isdigit() else None               # 폴백: 화면 일련번호 서수


def build_fill_kb(cfg, doc: str, form, seq=None):
    gam = process_gam(cfg.gamexport_exe, str(fetch_gam_local(cfg, doc)), str(Path("output") / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form)
    mine = kookmin.build(ctx, _resolve_seq(ctx, screen, seq))
    rows = []
    for label in sorted(set(mine) | set(screen)):
        ours = norm(mine.get(label) or "")
        theirs = norm(screen.get(label) or "")
        if not ours and not theirs:
            continue
        if ours and theirs:
            mark = "❌불일치" if ours != theirs else "✅일치"
        elif ours:
            mark = "🖊우리채움"
        else:
            mark = "📄화면만"
        rows.append((mark, label, ours or "-", theirs or "-"))
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="verify_fill_kb")
    p.add_argument("doc_id")
    p.add_argument("--seq", default=None, help="물건 일련번호(기본=첫 물건)")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)

    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX) if f.class_name == FORM_CLASS]
    if not forms:
        others = [f.class_name for f in driver.find_windows(driver.FORM_CLASS_PREFIX)]
        print(f"국민 담보 화면(TBNKKBB24DAMB)이 안 열려 있습니다. (열린 폼: {others or '없음'})",
              file=sys.stderr)
        return 1
    rows = build_fill_kb(cfg, args.doc_id, forms[0], args.seq)
    print(f"===== {args.doc_id} — 국민 auto-fill 채울 값 ↔ 화면 =====")
    order = {"❌불일치": 0, "🖊우리채움": 1, "📄화면만": 2, "✅일치": 3}
    for mark, label, ours, theirs in sorted(rows, key=lambda r: (order[r[0]], r[1])):
        print(f"  [{mark:6}] {label[:20]:22} 채울값={ours[:26]:28} 화면={theirs[:24]}")
    same = sum(1 for r in rows if r[0] == "✅일치")
    diff = sum(1 for r in rows if r[0] == "❌불일치")
    fill = sum(1 for r in rows if r[0] == "🖊우리채움")
    scr = sum(1 for r in rows if r[0] == "📄화면만")
    print(f"\n일치 {same} · 불일치 {diff} · 🖊우리채움 {fill} · 화면만 {scr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
