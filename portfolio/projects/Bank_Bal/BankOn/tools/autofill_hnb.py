"""하나은행 담보 폼(TBNKHNB24DAMB) 자동입력 — 화면이 보고 있는 물건 슬롯 하나(몸통은 autofill_slot).

    (화면에 하나 담보폼 열어둔 상태)
    python tools/autofill_hnb.py 01-2609-3-2751            # 드라이런
    python tools/autofill_hnb.py 01-2609-3-2751 --live     # 실제 입력(연습건에서만!)
미지원 가드: 물건종류가 토지·건물이 아니면(기계기구·특수부동산) 실입력 보류(exit 4).
매핑 근거: 인계본 수협_하나_인계번들(2026-09-07, 라이브 22건+ ✅18~20, 실입력 2352 12칸 실측) → 이식 2026-09-10.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.mapping import hnb                  # noqa: E402
import autofill_slot                             # noqa: E402
import verify_fill_hnb as VH                     # noqa: E402

FORM_CLASS = VH.FORM_CLASS
SPEC = autofill_slot.Spec(bank="하나", form_class=FORM_CLASS, mapping=hnb, verify=VH, kind_field="물건종류")
LAST_ALIGN = SPEC.last_align
EXIT_UNALIGNED = autofill_slot.EXIT_UNALIGNED
EXIT_UNSUPPORTED = autofill_slot.EXIT_UNSUPPORTED


def main(argv=None) -> int:
    return autofill_slot.run(SPEC, argv)


if __name__ == "__main__":
    raise SystemExit(main())
