"""수협 담보 폼(TBNKSSB24DAMB) 자동입력 — 화면이 보고 있는 물건 슬롯 하나(몸통은 autofill_slot).

    (화면에 수협 담보폼 열어둔 상태)
    python tools/autofill_ssb.py 01-2608-3-2637            # 드라이런
    python tools/autofill_ssb.py 01-2608-3-2637 --live     # 실제 입력(연습건에서만!)
    --seq N      우리 물건 순번을 직접 지정(정합 건너뜀)
미지원 가드: 선박·어업권 등 부동산 아닌 물건구분, 집계형(rollup)·일단지 묶음머리는 실입력 보류(exit 4).
매핑 근거: 인계본 수협_하나_인계번들(2026-09-07, 라이브 40건+ 전필드 일치) → 이식 2026-09-10.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.mapping import ssb                  # noqa: E402
import autofill_slot                             # noqa: E402
import verify_fill_ssb as VS                     # noqa: E402

FORM_CLASS = VS.FORM_CLASS
SPEC = autofill_slot.Spec(bank="수협", form_class=FORM_CLASS, mapping=ssb, verify=VS, kind_field="물건구분코드")
LAST_ALIGN = SPEC.last_align
EXIT_UNALIGNED = autofill_slot.EXIT_UNALIGNED
EXIT_UNSUPPORTED = autofill_slot.EXIT_UNSUPPORTED


def main(argv=None) -> int:
    return autofill_slot.run(SPEC, argv)


if __name__ == "__main__":
    raise SystemExit(main())
