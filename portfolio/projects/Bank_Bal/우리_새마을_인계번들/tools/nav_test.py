"""하나 물건/담보 순번 네비게이션 테스트 — 채우기 없이, **주소(번지·건물명)** 로 행 이동 확인.

빈 폼은 감정평가액이 비어 순번/금액으로 못 가리므로, 자동 채워진 **번지·건물명**을 읽어
그리드 DOWN 이 다른 행으로 넘어가는지 본다. 값은 안 건드린다.
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
import verify_fill_hnb as VH                     # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass


def _snap(form):
    sc = vf.screen_values(form)
    return (VH._screen_seq(sc), sc.get("번지"), sc.get("건물명"),
            sc.get("감정평가액"), sc.get("등기부고유번호"))


def main() -> int:
    forms = [f for f in driver.find_windows(driver.FORM_CLASS_PREFIX)
             if f.class_name == "TBNKHNB24DAMB"]
    if not forms:
        print("하나폼 안 열림"); return 1
    form = forms[0]
    grids = [c for c in driver.descendants(form.handle)
             if c.element_info.class_name == "TcxGridSite"]
    print(f"그리드 {len(grids)}개. 각 그리드로 행 이동 시도(번지·건물명 관찰):")
    for g in sorted(grids, key=lambda c: -c.rectangle().left):
        left = g.rectangle().left
        print(f"\n--- 그리드@{left} ---")
        try:
            g.set_focus(); time.sleep(0.25)
            send_keys("^{HOME}"); time.sleep(0.35)
            snaps = [_snap(form)]
            print(f"  Home: 순번={snaps[0][0]} 번지={snaps[0][1]} 건물명={snaps[0][2]} 금액={snaps[0][3]}")
            for i in range(5):
                g.set_focus(); time.sleep(0.1)
                send_keys("{DOWN}"); time.sleep(0.35)
                s = _snap(form)
                print(f"  DOWN#{i+1}: 순번={s[0]} 번지={s[1]} 건물명={str(s[2])[:14]} 금액={s[3]} 등기={s[4]}")
                snaps.append(s)
            # 번지 or 건물명 or 등기가 바뀌면 행 이동한 것
            moved = len({(x[1], x[2], x[4]) for x in snaps}) > 1
            print(f"  ▶ 행 이동함? {'✅ 예' if moved else '❌ 아니오(단일행/이 그리드 아님)'}")
        except Exception as e:
            print(f"  오류: {type(e).__name__} {str(e)[:50]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
