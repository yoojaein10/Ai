"""bonus-calc.js(지급액 미리보기)가 파이썬 엔진과 같은 답을 내는지 — node 가 있으면 실제로 돌려 본다."""

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from app.services.bonus.engine import Row, associate_person, shareholder_person

ROOT = Path(__file__).resolve().parents[1]
CALC = ROOT / "desktop" / "ui" / "bonus-calc.js"
NODE = shutil.which("node")


def _js_preview(report, person, items):
    script = f"""
global.window = {{}};
require({json.dumps(str(CALC))});
const out = window.BonusCalc.preview({json.dumps(report, default=str)}, {json.dumps(person)}, {json.dumps(items)});
process.stdout.write(JSON.stringify(out));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_주주_미리보기는_엔진과_같다():
    rows = [
        Row(doc_id="01-2604-1-0252", person="강무진", work_type="정비사업", fee=59_392_881, rate=40, block_from=date(2021, 3, 1)),
        Row(doc_id="01-2606-3-1998", person="강무진", work_type="담보", fee=20_000_000, rate=30, block_from=date(2022, 7, 1), survey_fee=20_000),
    ]
    applied = [{"kind": "WREATH", "amount": 20_000}, {"kind": "DOC_EXPENSE", "amount": 40_000}]
    base = shareholder_person(rows, variable_auto=3_125_744, carry_in=0, deductions=applied)
    report = {"shareholders": [{"name": "강무진", "retired": False, **base}], "common": [], "associates": [], "deductions": {"강무진": applied}}
    for items in (
        applied,
        applied + [{"kind": "ADVANCE_PAID", "amount": 20_000_000}],
        [{"kind": "WREATH", "amount": 80_000}, {"kind": "OTHER_DEDUCT", "amount": 214_600}, {"kind": "UNPAID_CARRY", "amount": 3_586_150}],
        [{"kind": "VARIABLE_CREDIT", "amount": 3_289_000}, {"kind": "HANDLING", "amount": 500_000}],
        [{"kind": "ADVANCE_PAID", "amount": 60_000_000}],           # 지급액 음수
    ):
        expected = shareholder_person(rows, variable_auto=3_125_744, carry_in=0, deductions=items)["totals"]["payment"]
        got = _js_preview(report, "강무진", items)
        assert abs(got["payment"] - expected) < 0.5, (items, got, expected)
        assert abs(got["server"] - base["totals"]["payment"]) < 0.5


@pytest.mark.skipif(NODE is None, reason="node 가 없다")
def test_소속_공통건_미리보기는_엔진과_같다():
    rows = [Row(doc_id="01-2508-4-0279", person="이영은", kind="COMMON", work_type="일반거래", fee=9_166_600, rate=10)]
    base = associate_person(rows, pay_ratio=0.7, tax_rate=0.30)
    report = {"shareholders": [], "common": [], "associates": [{"name": "이영은", "retired": False, **base}], "deductions": {}}
    for items in ([], [{"kind": "WREATH", "amount": 100_000}], [{"kind": "OTHER_DEDUCT", "amount": 50_000}, {"kind": "HANDLING", "amount": 30_000}]):
        expected = associate_person(rows, pay_ratio=0.7, tax_rate=0.30, deductions=items)["totals"]["payment"]
        got = _js_preview(report, "이영은", items)
        assert abs(got["payment"] - expected) < 0.5, (items, got, expected)
