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
import unicodedata
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
from bankon.ui import form as form_mod         # noqa: E402
import verify_form as vf                       # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = "TBNKKBB24DAMB"
_CODE = re.compile(r"\((\d+)\)\s*$")


def norm(t: str) -> str:
    """비교용 정규화 — 콤보 코드·콤마·공백·전각을 없앤다(기업·농협과 같은 규칙).

    국민만 전각·공백 정규화가 빠져 있어 같은 값이 불일치로 뜨고 있었다.
    """
    folded = unicodedata.normalize("NFKC", t or "")
    return _CODE.sub("", folded.replace(",", "")).replace(" ", "").strip()


# 화면이 원본 그대로 0을 채워 넣는 칸 — `0098` 과 `98` 은 같은 지번이다.
# 국민 폼은 좌패널(0패딩)과 토지탭(패딩 없음)이 **같은 지번을 다르게** 보여 준다
# (실측 163건 중 본번 14·부번 13건). 어느 칸을 읽느냐로 불일치가 나면 안 된다.
ZERO_PADDED = ("본번지", "부번지")


def compare_text(label: str, text: str) -> str:
    """필드별 비교 표기 — 지번은 앞의 0을 무시한다."""
    value = norm(text)
    if label in ZERO_PADDED and value.isdigit():
        return value.lstrip("0") or "0"
    return value


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


def seq_alignment(ctx, screen, seq=None) -> dict:
    """다물건 순번 정합 정보.

    반환: total(물건 수)·screen_seq(화면 일련번호)·resolved(우리가 채울 물건 순번)·
    by(정합 근거)·safe(채워도 안전한가). 단일물건은 항상 safe. 다물건은 화면 감정평가액이
    우리 물건과 일치(금액매칭)하거나 화면 일련번호가 유효할 때만 safe.
    """
    anchors = [r for r in ctx.details if r.amount is not None]
    total = len(anchors)
    screen_seq = norm(screen.get("일련번호", ""))
    resolved = _resolve_seq(ctx, screen, seq)
    if total < 2:
        return {"total": total, "screen_seq": screen_seq or "1",
                "resolved": resolved or "1", "by": "단일물건", "safe": True}
    idx = (int(resolved) - 1) if (resolved and resolved.isdigit()) else 0
    our_amt = str(int(anchors[idx].amount)) if 0 <= idx < total else ""
    scr_amt = norm(screen.get("감정평가액", ""))
    if scr_amt and scr_amt == our_amt:
        by, safe = "금액매칭", True                       # 화면 물건 = 우리 물건 확정
    elif screen_seq.isdigit() and 1 <= int(screen_seq) <= total:
        by, safe = "일련번호", True                        # 빈 폼: 슬롯 번호로 정합
    else:
        by, safe = "불명확", False                         # 어느 물건인지 확신 못함 → 채우면 위험
    return {"total": total, "screen_seq": screen_seq, "resolved": resolved or "1",
            "our_amount": our_amt, "screen_amount": scr_amt, "by": by, "safe": safe}


def fill_kb(cfg, doc: str, form, *, live: bool = False, overwrite: bool = False,
            select: bool = False, seq=None):
    """국민 담보 폼에 매핑값을 채운다(기본 드라이런). 자동순회 채우기 모드용.

    화면 감정평가액으로 물건 정합 후 kookmin 값을 form.fill 로 넣는다.
    """
    gam = process_gam(cfg.gamexport_exe, str(fetch_gam_local(cfg, doc)), str(Path("output") / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form)
    align = seq_alignment(ctx, screen, seq)
    resolved = None if (align["resolved"] == "1" and align["total"] < 2) else align["resolved"]
    values = kookmin.build(ctx, resolved)
    # 다물건인데 어느 물건인지 확신 못하면 실입력 금지(드라이런 계획만) — 순번 오채움 방지.
    do_live = live and align["safe"]
    return form_mod.fill(form, values, live=do_live, overwrite=overwrite, select=select), align


def build_fill_kb(cfg, doc: str, form, seq=None):
    gam = process_gam(cfg.gamexport_exe, str(fetch_gam_local(cfg, doc)), str(Path("output") / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    screen = vf.screen_values(form)
    mine = kookmin.build(ctx, _resolve_seq(ctx, screen, seq))
    # 라벨이 없거나 겹쳐서 `screen_values` 가 못 담은 칸은 **위치로 직접** 읽는다.
    for label in mine:
        if form_mod.POSITIONAL.match(str(label)):
            screen[label] = form_mod.read_field(form, label)
            screen.pop(form_mod.display_label(label), None)
    rows = []
    for label in sorted(set(mine) | set(screen), key=str):
        name = form_mod.display_label(label)
        ours = compare_text(name, str(mine.get(label) or ""))
        theirs = compare_text(name, str(screen.get(label) or ""))
        if not ours and not theirs:
            continue
        if ours and theirs:
            mark = "❌불일치" if ours != theirs else "✅일치"
        elif ours:
            mark = "🖊우리채움"
        else:
            mark = "📄화면만"
        rows.append((mark, name, ours or "-", theirs or "-"))
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
