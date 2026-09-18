"""★실서버 쓰기★ 하나은행 한 건 통합 러너(관리자 권한, 콘솔 숨김 필수) — 몸통은 bank_runner.

    작성(A) 입력(autofill_hnb, 화면 슬롯 하나) → 저장 → 감정서 PDF → 현장조사서(E) PDF만(폼 미정찰). 옵션은 bank_runner 참조.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import bank_runner                              # noqa: E402
import autofill_hnb                              # noqa: E402

SPEC = bank_runner.RunnerSpec(bank="하나", write_class="TBNKHNB24DAMB", survey_class="TBNKHNB24Hyun", autofill=autofill_hnb)

if __name__ == "__main__":
    raise SystemExit(bank_runner.run(SPEC))
