"""하나 매핑 오프라인 회귀검사 — 라이브 폼 없이 캐시된 추출물로 검증(국민·기업판과 같은 꼴).

정답지 = **담당자 완성본 화면값**(01-2609-3-2871, 2026-09-16 읽기전용 덤프 reports/dump_2871_*.log).
하나 관례가 다 들어 있는 건이다: 토지 1행 + 건물 **단가별 3행** + **평가외(옥탑) 1행**.

    python tools/check_hnb_offline.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.gam_bridge import load_extracted    # noqa: E402
from bankon.mapping import hnb                  # noqa: E402
import verify_form as vf                         # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

DOC = "01-2609-3-2871"
# 화면이 관리하는 앵커라 매핑이 안 내는 칸(순번). 대조에서 뺀다.
SKIP = {"일련번호"}
COMMON = {
    "평가사명": "김기석", "기준시점": "2026-09-15", "감정일자": "2026-09-15",
    "계좌번호": "10391001691404", "총감정평가액": "8,348,214,360", "순수수료": "5,441,000",
    "시도": "서울특별시", "구군": "송파구", "읍면동": "잠실동", "번지": "184-20",
}
BUILDING = {"물건종류": "건물", "건물용도": "여관", "내용연수": "50",
            "준공/제작일자": "2003-05-27", "등기부고유번호": "11622003004104"}
EXPECT = {
    1: {**COMMON, "물건종류": "토지", "감정평가액": "7,769,100,000", "평가단가": "47,000,000",
        "사정면적": "165.30", "공부면적": "165.30", "공부상지목": "대", "실제지목": "대",
        "등기부고유번호": "11621996029624"},
    2: {**COMMON, **BUILDING, "감정평가액": "16,750,800", "평가단가": "540,000",
        "사정면적": "31.02", "공부면적": "31.02"},
    3: {**COMMON, **BUILDING, "감정평가액": "514,337,040", "평가단가": "756,000",
        "사정면적": "680.34", "공부면적": "680.34"},      # 2~9층 층별 공부면적 합
    4: {**COMMON, **BUILDING, "감정평가액": "48,026,520", "평가단가": "486,000",
        "사정면적": "98.82", "공부면적": "98.82"},
    5: {**COMMON, **BUILDING, "감정평가액": "0", "평가단가": "1",                 # ★평가외(옥탑)
        "사정면적": "12.25", "공부면적": "12.25"},
}


def norm(value) -> str:
    return re.sub(r"[,\s]", "", str(value or ""))


def main() -> int:
    cfg = load_config(None)
    gam = load_extracted(str(Path("output") / DOC))
    ctx = vf.build_context(cfg, DOC, gam.tables, vf.sections_from_gam(gam))
    total = len(hnb.slots(ctx))
    print(f"{DOC} — 화면 물건 {total}개 (기대 {len(EXPECT)}개)")
    ok = bad = 0
    if total != len(EXPECT):
        bad += 1
        print(f"  ❌ 물건 수 {total} ≠ {len(EXPECT)}")
    for seq in sorted(EXPECT):
        mine = hnb.build(ctx, str(seq))
        print(f"\n=== {seq}행")
        for label, want in EXPECT[seq].items():
            if label in SKIP:
                continue
            ours = mine.get(label)
            if norm(ours) == norm(want):
                ok += 1
                print(f"  ✅ {label:12} {ours}")
            else:
                bad += 1
                print(f"  ❌ {label:12} 우리={ours!r} 기대={want!r}")
        extra = [k for k, v in mine.items()
                 if v not in (None, "") and k not in EXPECT[seq] and k not in SKIP]
        if extra:
            print(f"  🖊 화면에 없던 칸(담당자 확인): {', '.join(extra)}")
    print(f"\n[합계] ✅{ok} / ❌{bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
