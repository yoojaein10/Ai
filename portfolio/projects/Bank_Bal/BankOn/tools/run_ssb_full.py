"""★실서버 쓰기★ 수협 한 건 통합 러너(관리자 권한, 콘솔 숨김 필수) — 몸통은 bank_runner.

    작성(A) 입력(autofill_ssb, 화면 슬롯 하나) → 저장 → 감정서 PDF → 현장조사서(E) PDF만(폼 미정찰). 옵션은 bank_runner 참조.
    Start-Process python -ArgumentList '"...\\tools\\run_ssb_full.py" <from> <to> <doc> [옵션]' -Verb RunAs -WindowStyle Hidden -Wait
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import bank_runner                              # noqa: E402
import autofill_ssb                              # noqa: E402

SPEC = bank_runner.RunnerSpec(bank="수협", write_class="TBNKSSB24DAMB", survey_class="TBNKSSB24Hyun", autofill=autofill_ssb)

if __name__ == "__main__":
    raise SystemExit(bank_runner.run(SPEC))
