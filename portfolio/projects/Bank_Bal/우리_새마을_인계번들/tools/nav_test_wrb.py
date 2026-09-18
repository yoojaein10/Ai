"""우리은행 물건 순번 네비게이션 실측 — 채우기 없이 그리드로 물건이 넘어가는지 확인.

승격(관리자) 세션에서 실행. 그리드마다 Ctrl+Home→DOWN 하며 일련번호·본번·감정평가액을
읽어 물건이 1→2→3 넘어가는지 본다. 값은 안 건드린다(마지막 Ctrl+Home 복원).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.ui import driver                    # noqa: E402
from pywinauto.keyboard import send_keys        # noqa: E402
import verify_form as vf                         # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass


def _snap(form):
    sc = vf.screen_values(form)
    return (sc.get("일련번호"), f"{sc.get('본번지') or ''}-{sc.get('부번지') or ''}",
            sc.get("감정평가액"))


def main() -> int:
    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX)
             if f.class_name == "TBNKWRB24DAMB"]
    if not forms:
        print("우리폼 안 열림"); return 1
    form = forms[0]
    grids = [c for c in driver.descendants(form.handle)
             if c.element_info.class_name == "TcxGridSite"]
    print(f"그리드 {len(grids)}개. 각 그리드로 물건 이동 시도:")
    winner = None
    for g in sorted(grids, key=lambda c: c.rectangle().left):
        left = g.rectangle().left
        print(f"\n--- 그리드@{left} ---")
        try:
            g.set_focus(); time.sleep(0.25)
            send_keys("^{HOME}"); time.sleep(0.35)
            snaps = [_snap(form)]
            print(f"  Home: 순번={snaps[0][0]} 본번={snaps[0][1]} 금액={snaps[0][2]}")
            for i in range(5):
                g.set_focus(); time.sleep(0.1)
                send_keys("{DOWN}"); time.sleep(0.35)
                s = _snap(form)
                print(f"  DOWN#{i+1}: 순번={s[0]} 본번={s[1]} 금액={s[2]}")
                snaps.append(s)
            moved = len({(x[1], x[2]) for x in snaps}) > 1
            print(f"  ▶ 물건 이동함? {'✅ 예 (이 그리드가 물건 selector)' if moved else '❌ 아니오'}")
            if moved and winner is None:
                winner = left
            send_keys("^{HOME}"); time.sleep(0.3)   # 복원
        except Exception as e:
            print(f"  오류: {type(e).__name__} {str(e)[:50]}")
    print(f"\n=== 물건 selector 그리드: {winner if winner is not None else '못 찾음'} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
