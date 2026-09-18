"""국민 매핑 오프라인 회귀검사 — 라이브 폼 없이 캐시된 .gam 으로 검증.

verify_fill_kb 는 화면 폼이 열려 있어야 하지만, 이 스크립트는 work/<doc>/<doc>.gam
을 다시 gamexport 로 풀어 build_context→kookmin.build 만 돌리고, 사람이 화면에서
읽어 확인해 둔 '정답 화면값'(EXPECT) 과 대조한다. 매핑 수정 전후 회귀 확인용.

    python tools/check_kb_offline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.gam_bridge import process_gam       # noqa: E402
from bankon.mapping import kookmin              # noqa: E402
import verify_form as vf                         # noqa: E402
import verify_fill_kb as VK                       # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

# 화면에서 직접 읽어 확인해 둔 값(정답). None = 화면 빈칸이어야 함.
EXPECT: dict[str, dict[str, str | None]] = {
    "01-2502-3-0636": {  # 군포 당정동, 신라테크노빌, 구분건물 단일
        "감정평가액": "656000000", "사정면적": "383.50", "본번지": "1128",
        "건물구조": "철근콘크리트구조", "건물명": "신라테크노빌",
        "건물 층수": "7", "호": "704-1", "심사자": "김형식",
    },
    "01-2502-3-0658": {  # 평택 모곡동, 평택제이에이치타워, 구분건물 단일
        "감정평가액": "435000000", "사정면적": "94.92", "본번지": "438",
        "건물구조": "철근콘크리트구조", "건물명": "평택제이에이치타워",
        "건물 층수": "4", "호": "414", "심사자": "김태우",
    },
    "01-2502-3-0668": {  # 안산 팔곡이동. 감정평가액/사정은 잔여(등기합병=head A1,
        # 공부스캔 필요, .gam만으론 판별불가 → 여기선 검사 제외). 나머지는 정상.
        "본번지": "368", "건물명": None,
        "표준지소재지": "팔곡이동 372-1", "표준지공시지가": "1161000",
        "공시기준일": "2025-01-01",
    },
    # 묶음머리는 **머리 필지 단독값**(AREA1, AREA1×단가). 1344 는 화면이 묶음 합계인
    # 소수 4건 중 하나라 우리 값과 다르다 — 다수 15건을 맞추는 쪽을 골랐다(kookmin 주석 참조).
    "01-2604-3-1344": {"감정평가액": "330000000", "사정면적": "132.00"},
    "01-2604-3-1258": {"감정평가액": "1242120000", "사정면적": "440.00"},  # 소분블록 합산
    "01-2601-3-0358": {"감정평가액": "1660730000", "사정면적": "7550.00"}, # 소분합산(외 제외)
    "01-2605-3-1582": {"감정평가액": "2649200000", "사정면적": "895.00",   # 단일토지 무회귀
                       "본번지": "96"},
    "01-2605-3-1629": {"감정평가액": "2526990000", "사정면적": "3930.00",  # 사정≠공부 무회귀
                       "본번지": "137"},
    "01-2502-3-0629": {  # 서울 광진구 자양동, 토지 대지
        "감정평가액": "2353200000", "사정면적": "159.00", "본번지": "251",
        "평가단가": "14800000", "건물명": None,
    },
    "01-2502-3-0625": {  # 남양주 별내동, 토지 대지, 표준지 2후보 비고'-'→첫행
        "감정평가액": "851400000", "본번지": "2184", "심사자": "김태우",
        "표준지소재지": "별내동 2184-11", "표준지공시지가": "1092000",
    },
    "01-2605-3-1674": {  # 파주 율곡리 대지, 표준지 2후보 비고'-'→첫행(두포리 261)
        "감정평가액": "557864000", "사정면적": "1096.00", "본번지": "203",
        "심사자": "김형수", "표준지소재지": "두포리 261", "표준지공시지가": "204100",
    },
    "01-2605-3-1642": {  # 청라에이스하이테크시티, 구분상가 2유닛 → 물건①(가)=207호
        "감정평가액": "221000000", "사정면적": "63.35", "호": "3-207",
        "건물구조": "철근콘크리트구조", "건물명": "청라에이스하이테크시티",
    },
    "01-2605-3-1704": {  # 예식장 복합(집계형 rollup, 8개호 aggregated) → 총액 오기입 금지
        "감정평가액": None, "사정면적": None, "호": None,
    },
    "01-2604-3-1214": {  # 집계형 구분건물(명세앵커=총액) → KB_Con 물건①
        "감정평가액": "54777100000", "사정면적": "798.50",
    },
    "01-2605-3-1563": {  # 집계형(앵커=비준가액≠총액) → gam_info.price(총액)
        "감정평가액": "398000000", "사정면적": "82.59",
    },
}


def norm(t):
    return (t or "").replace(",", "").strip()


def build(cfg, doc: str) -> dict:
    gam = process_gam(cfg.gamexport_exe, str(VK.fetch_gam_local(cfg, doc)),
                      str(Path("output") / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    return kookmin.build(ctx)


def main() -> int:
    cfg = load_config()
    total_ok = total_bad = 0
    for doc, expect in EXPECT.items():
        mine = build(cfg, doc)
        print(f"\n===== {doc} =====")
        for label, want in expect.items():
            got = mine.get(label)
            got_n, want_n = norm(got), norm(want)
            ok = got_n == want_n
            total_ok += ok
            total_bad += not ok
            mark = "✅" if ok else "❌"
            print(f"  {mark} {label:12} 우리={str(got)[:24]:26} 기대={want}")
    print(f"\n[합계] ✅{total_ok} / ❌{total_bad}")
    return 1 if total_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
