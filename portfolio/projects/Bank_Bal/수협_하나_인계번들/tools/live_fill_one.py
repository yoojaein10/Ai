"""**한 건만** 실제로 채워 보고 폼을 열어 둔다 — '믿고쓰기 관문' 시험용.

그리드를 훑어 그 은행 담보 폼을 찾고, **빈칸이 많은 건**(= 실전과 같은 미작성 건)을 골라
매핑값을 넣는다. 넣은 뒤 **폼을 닫지 않는다** — 사람이 화면으로 확인하고 직접 판단한다.

    저장은 절대 하지 않는다. `저 장` 버튼을 누르는 코드가 없다.
    닫기도 하지 않는다 — 확인 후 사람이 '닫 기'(저장 안 함)를 누르면 원상복구된다.

    (관리자) python tools/live_fill_one.py --bank nh                 # 계획만(드라이런)
    (관리자) python tools/live_fill_one.py --bank nh --live --select # 실제 입력 + 콤보 선택
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pywinauto.keyboard import send_keys            # noqa: E402

from bankon.config import load_config               # noqa: E402
from bankon.ui import driver, navigate              # noqa: E402
from bankon.ui import form as form_mod              # noqa: E402
from verify_grid_loop import BANKS, FILLERS, identify, read_form_id  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent


def blank_ratio(form, values: dict) -> tuple[int, int]:
    """(우리 값이 있는 칸 중 화면이 **빈칸**인 수, 전체). 미작성 건일수록 크다."""
    blank = total = 0
    for label, value in values.items():
        if value in (None, ""):
            continue
        action, current, _control = form_mod.plan_field(form, label, value)
        if action in ("미발견", "빈값"):
            continue
        total += 1
        if not current:
            blank += 1
    return blank, total


def next_row(session) -> None:
    grid = navigate._grid(session)
    grid.set_focus()
    time.sleep(0.3)
    send_keys("{DOWN}")
    time.sleep(0.3)


def open_current(session):
    before = navigate._menu_handles()
    send_keys("+{F10}")
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not (navigate._menu_handles() - before):
        time.sleep(0.3)
    if not (navigate._menu_handles() - before):
        return None
    send_keys("a")
    try:
        return driver.wait_for_window(driver.FORM_CLASS_PREFIX, pid=session.pid, timeout=15)
    except Exception:
        navigate.close_context_menu()
        return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="live_fill_one")
    p.add_argument("--bank", choices=tuple(FILLERS), required=True)
    p.add_argument("--live", action="store_true", help="실제 입력(기본은 계획만)")
    p.add_argument("--select", action="store_true", help="콤보도 자동선택")
    p.add_argument("--max", type=int, default=25, help="후보를 찾으려 훑을 그리드 행 수")
    p.add_argument("--min-blank", type=int, default=8,
                   help="이만큼 빈칸이 있는 폼을 고른다(실전과 같은 미작성 건)")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env or str(ROOT / ".env"))

    driver.require_desktop()

    mains = [m for m in driver.find_windows(driver.MAIN_CLASS)
             if driver.by_class(m.handle, "TcxGridSite")]
    if not mains:
        print("그리드 있는 BANK24 메인창이 없습니다."); return 1
    session = navigate.Session(mains[0])
    navigate.close_forms(session)

    bank = BANKS[args.bank]
    filler = FILLERS[args.bank]
    grid = navigate._grid(session)
    grid.set_focus()
    time.sleep(0.4)
    send_keys("^{HOME}")
    time.sleep(0.4)

    best = None                                   # (blank, total, form, doc, values)
    for index in range(args.max):
        form = open_current(session)
        if form is None:
            print(f"[{index}] 폼 안열림 — 종료"); break
        if form.class_name != bank["cls"]:
            print(f"[{index}] {form.class_name} 건너뜀")
            navigate.close_forms(session); next_row(session); continue
        fid = read_form_id(form)
        doc, status = identify(cfg, fid, bank.get("cust_like") or bank["cust"])
        if doc is None:
            print(f"[{index}] 식별실패({status})")
            navigate.close_forms(session); next_row(session); continue
        try:
            results, _align = filler(cfg, doc, form, live=False)     # 드라이런으로 상태만
        except (Exception, SystemExit) as error:
            print(f"[{index}] {doc} ⛔ {str(error)[:50]}")
            navigate.close_forms(session); next_row(session); continue
        blank = sum(1 for r in results if r.action in ("채움", "고름"))
        filled = sum(1 for r in results if r.action in ("일치", "덮어씀", "고름(덮어씀)"))
        print(f"[{index}] {doc}  빈칸 {blank} · 이미채워짐 {filled}")
        if blank >= args.min_blank:
            best = (blank, form, doc)
            break
        navigate.close_forms(session)
        next_row(session)

    if best is None:
        print(f"\n빈칸 {args.min_blank}개 이상인 폼을 못 찾았습니다. "
              f"--min-blank 를 낮추거나 --max 를 늘리세요.")
        return 1

    blank, form, doc = best
    mode = "🔴 실제 입력" if args.live else "🟢 드라이런(화면 안 건드림)"
    print(f"\n===== {doc} — {mode}{' + 콤보선택' if args.select else ''} =====")
    print(f"  대상: {form.class_name} · 빈칸 {blank}개")
    results, align = filler(cfg, doc, form, live=args.live, select=args.select)

    order = {"거부": 0, "못찾음(목록)": 1, "미발견": 2, "채움": 3, "고름": 4,
             "덮어씀": 5, "고름(덮어씀)": 6, "수동(선택형)": 7, "일치": 8, "빈값": 9}
    for r in sorted(results, key=lambda x: (order.get(x.action, 0), x.label)):
        if r.action == "빈값":
            continue
        mark = ("✍" if r.wrote else "") + r.action
        print(f"  [{mark:14}] {r.label[:18]:20} 값={r.ours[:26]:28} 이전={r.current[:20]}")

    wrote = sum(1 for r in results if r.wrote)
    picked = sum(1 for r in results if r.wrote and r.action.startswith("고름"))
    bad = [r for r in results if r.action.startswith("거부") or r.action == "못찾음(목록)"]
    print(f"\n  입력 {wrote}칸(그중 콤보 {picked}) · 문제 {len(bad)}")
    for r in bad:
        print(f"    ⚠ {r.label}: {r.action}")
    if align.get("total", 0) >= 2:
        print(f"  물건 순번: {align['resolved']}/{align['total']} ({align['by']})")

    print("\n" + "=" * 60)
    print("폼을 **열어 둔 채로** 끝냅니다. 화면에서 값을 확인하세요.")
    print("확인이 끝나면 **'닫 기'(저장하지 않음)** 를 눌러 원상복구하세요.")
    print("이 도구는 '저 장' 을 누르지 않으며, 닫지도 않습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
