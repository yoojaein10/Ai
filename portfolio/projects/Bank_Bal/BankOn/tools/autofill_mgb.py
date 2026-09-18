"""새마을금고 담보 폼(TBNKMGB24DAMB) 자동입력 — 화면이 보고 있는 물건 슬롯 하나(몸통은 autofill_slot).

    (화면에 새마을 담보폼 열어둔 상태)
    python tools/autofill_mgb.py 01-2609-3-2762            # 드라이런
    python tools/autofill_mgb.py 01-2609-3-2762 --live     # 실제 입력(연습건에서만!)
인계본에는 verify_fill_mgb(검증)만 있고 autofill_mgb 는 없었다("우리 패턴 복제로 추가") — 이 계통에서 신규(2026-09-10).
매핑 근거: 인계본 우리_새마을_인계번들(2026-09-08, 자동순회 73건, 드라이런 대조 2762 ✅29/0).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.mapping import mgb                  # noqa: E402
import autofill_slot                             # noqa: E402
import verify_fill_mgb as VM                     # noqa: E402

FORM_CLASS = VM.FORM_CLASS
SPEC = autofill_slot.Spec(bank="새마을", form_class=FORM_CLASS, mapping=mgb, verify=VM, kind_field="물건종류")
LAST_ALIGN = SPEC.last_align
EXIT_UNALIGNED = autofill_slot.EXIT_UNALIGNED
EXIT_UNSUPPORTED = autofill_slot.EXIT_UNSUPPORTED


def main(argv=None) -> int:
    return autofill_slot.run(SPEC, argv)


if __name__ == "__main__":
    raise SystemExit(main())
