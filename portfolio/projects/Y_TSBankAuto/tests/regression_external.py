# -*- coding: utf-8 -*-
"""외부 회귀 (읽기 전용): Y_BankAuto\\탁상 의 37건으로 파서/조립 검증.

- PDF 를 신규 프로젝트로 복사하지 않는다(외부 경로 직접 읽기).
- 6/9/40 제외, 나머지 37건.
- 출력: 성공 여부와 필드 존재율만. 원문 정답/PII 는 출력/저장하지 않는다.
- 실행 내 중복 의뢰번호 검사 포함.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline  # noqa: E402
from parsers import base  # noqa: E402

DEFAULT_DIR = r"D:\AI\Claude\Y_BankAuto\탁상"
EXCLUDE = {6, 9, 40}
PRESENCE_FIELDS = ["request_no", "request_datetime", "branch", "staff_name",
                   "branch_phone", "property_type", "building_structure",
                   "building_year"]


def run(pdf_dir: str = DEFAULT_DIR) -> dict:
    if not os.path.isdir(pdf_dir):
        return {"available": False, "dir": pdf_dir}

    nums = sorted(int(m.group(1)) for f in os.listdir(pdf_dir)
                  if (m := re.match(r"(\d+)\.pdf$", f)))
    nums = [n for n in nums if n not in EXCLUDE]

    per_bank: dict[str, dict] = {}
    presence: dict[str, list] = {f: [0, 0] for f in PRESENCE_FIELDS}
    eligible_count = 0
    parse_fail = 0
    request_nos: dict[str, int] = {}
    dup_request = []

    for n in nums:
        path = os.path.join(pdf_dir, f"{n}.pdf")
        try:
            lines = base.extract_lines(path, allowed_roots=[pdf_dir], use_worker=False)
            pr = pipeline.prepare(lines)
        except Exception as e:
            parse_fail += 1
            print(f"  {n}.pdf PARSE-FAIL {type(e).__name__}")
            continue
        bank = pr.model.bank or "?"
        b = per_bank.setdefault(bank, {"total": 0, "eligible": 0})
        b["total"] += 1
        if pr.eligible:
            b["eligible"] += 1
            eligible_count += 1
        # 필드 존재율
        fp = pr.model.field_presence()
        for f in PRESENCE_FIELDS:
            present = fp.get(f, False)
            presence[f][1] += 1
            if present:
                presence[f][0] += 1
        # 중복 의뢰번호 (실행 내)
        rn = pr.model.request_no
        if rn:
            request_nos[rn] = request_nos.get(rn, 0) + 1
            if request_nos[rn] == 2:
                dup_request.append("(중복감지)")

    return {
        "available": True,
        "total": len(nums),
        "eligible": eligible_count,
        "parse_fail": parse_fail,
        "per_bank": per_bank,
        "presence": presence,
        "dup_request_count": len(dup_request),
    }


def main():
    pdf_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR
    r = run(pdf_dir)
    if not r["available"]:
        print(f"[건너뜀] 외부 PDF 디렉터리 없음: {r['dir']}")
        return
    print(f"[회귀] 대상 {r['total']}건  적격 {r['eligible']}  파싱실패 {r['parse_fail']}")
    print("[은행별 적격률]")
    for bank, b in sorted(r["per_bank"].items()):
        print(f"  {bank:<8} {b['eligible']}/{b['total']}")
    print("[필드 존재율]")
    for f, (got, tot) in r["presence"].items():
        pct = (100 * got / tot) if tot else 0
        print(f"  {f:<20} {got}/{tot}  ({pct:.0f}%)")
    print(f"[실행 내 중복 의뢰번호 감지] {r['dup_request_count']}건")


if __name__ == "__main__":
    main()
