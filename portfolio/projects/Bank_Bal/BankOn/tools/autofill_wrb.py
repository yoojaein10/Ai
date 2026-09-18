"""우리은행 담보 폼(TBNKWRB24DAMB) 자동입력 — 화면이 보고 있는 물건 슬롯 하나(몸통은 autofill_slot).

    (화면에 우리 담보폼 열어둔 상태)
    python tools/autofill_wrb.py 01-2608-3-2668            # 드라이런
    python tools/autofill_wrb.py 01-2608-3-2668 --live     # 실제 입력(연습건에서만!)
미지원 가드: 세부물건종류가 대지/건물이 아니거나 물건종류가 선박·어업권·차량·기계기구면 실입력 보류(exit 4).
법정동코드·소재지(라벨 없는 칸)는 매핑에서 제외 — 주소검색 자동생성 칸이고 물건 2세트라 위치로 못 짚는다(인계본 감사).
매핑 근거: 인계본 우리_새마을_인계번들(2026-09-08, 자동순회 20건 매핑버그 0) → 이식 2026-09-10.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.mapping import wrb                  # noqa: E402
import autofill_slot                             # noqa: E402
import verify_fill_wrb as VW                     # noqa: E402

FORM_CLASS = VW.FORM_CLASS
SPEC = autofill_slot.Spec(bank="우리", form_class=FORM_CLASS, mapping=wrb, verify=VW, kind_field="물건종류")
LAST_ALIGN = SPEC.last_align
EXIT_UNALIGNED = autofill_slot.EXIT_UNALIGNED
EXIT_UNSUPPORTED = autofill_slot.EXIT_UNSUPPORTED


def main(argv=None) -> int:
    return autofill_slot.run(SPEC, argv)


if __name__ == "__main__":
    raise SystemExit(main())
