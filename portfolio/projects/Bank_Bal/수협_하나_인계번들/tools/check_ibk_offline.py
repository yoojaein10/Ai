"""기업 매핑 오프라인 회귀검사 — 라이브 폼도 FTP도 없이 캐시 추출물로 검증.

`output/<문서번호>/` 에 남아 있는 gamexport 추출물을 그대로 읽어 build_context →
ibk.build 만 돌린다. .gam 다운로드도 gamexport 재실행도 없어서 29건이 몇 초에 끝난다.
매핑을 고칠 때마다 **먼저 이걸 돌려** 크래시·값 변화를 확인하고, 그 다음에 라이브
그리드 순회로 화면 대조하는 순서가 안전하다.

    python tools/check_ibk_offline.py              # 전건 요약 + EXPECT 대조
    python tools/check_ibk_offline.py --detail     # 문서별 전체 필드
    python tools/check_ibk_offline.py 01-2608-3-2516 --detail
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.gam_bridge import load_extracted    # noqa: E402
from bankon.mapping import ibk                  # noqa: E402
from bankon.ui import form as form_mod           # noqa: E402
import verify_form as vf                         # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent

def pick(values: dict, label: str):
    """이름으로 값 꺼내기 — 위치 표기 키(`소재지@…[왼쪽]`)도 이름으로 찾게 해 준다."""
    if label in values:
        return values[label]
    for key, value in values.items():
        if form_mod.display_label(key) == label:
            return value
    return None


# 화면/원본에서 확인해 둔 값(정답). None = 비어 있어야 함.
# 금액 3분리는 명세표를 사람이 읽어 합산한 값이다(인계문서 실측치 포함).
EXPECT: dict[str, dict[str, str | None]] = {
    "01-2608-3-2531": {   # 토지 2필지 + 공장 3개층 + 성형기 — 3분리 실측
        "토지평가금액": "3283780000", "건물평가금액": "425487100",
        "기계기구평가금액": "69400000", "기타평가금액": "0",
        "부동산구분": "토지", "공부지목": "공장용지",
    },
    "01-2608-3-2516": {   # NO=1 '대' 필지의 접도구역 소분행(111,780,000)은 **토지**
        # 토지 2,354,418,000 + 111,780,000 + 2,714,985,000
        # 건물   508,200,000 + 855,400,000 + 217,800,000 + 471,900,000
        "토지평가금액": "5181183000", "건물평가금액": "2053300000",
        "부동산구분": "토지",
    },
    "01-2608-3-2452": {   # land_list 인데 토지 없음 — 단독주택(NO=가) 뿐
        "토지평가금액": "0", "건물평가금액": "1690604000",
        "부동산구분": "건물", "공부지목": None,
    },
    "01-2608-3-2471": {   # 모터보트 — 기타평가금액
        "기타평가금액": "552232000", "토지평가금액": "0", "건물평가금액": "0",
    },
    # 구분건물(지식산업센터) — 아래 값은 **실폼 대조로 확인**(2026-08-27, ✅22 일치).
    "01-2608-3-2526": {
        "부동산구분": "집합건물", "건물평가금액": "4033000000", "토지평가금액": "0",
        "건 물 명": "서울숲엘타워", "건물구조": "철근콘크리트구조",
        "공부면적(전용면적)": "116.30", "사정면적": "116.30", "공부면적": None,
        "소재지": "서울특별시 성동구 성수동1가", "법정동코드": "1120011400",
        "감정평가액": "2024000000", "순수수료": "2947120", "부가세": "303500",
        "감정수수료": "3338500", "실   비": "88100", "기준시점": "2026-08-12",
        "등기소기준 고유번호": "24012016000698", "평가사명": "유승민",
    },
    "01-2608-3-2683": {   # 순회 ✅23 기준건 — 무회귀 확인용
        "부동산구분": "토지", "공부지목": "대지", "본번지": "461", "부번지": "17",
        "소재지": "서울특별시 강남구 수서동",     # 인계문서에 기록된 화면값
        "건 물 명": None, "건물구조": None, "준공일자": None,
    },
    # 아래는 2026-08-27 무인순회에서 **불일치로 잡혔다가 고친** 값들(화면값 = 순회 로그).
    "01-2608-3-2682": {"건물구조": "철근콘크리트조"},      # 기업 화면은 원문 표기
    "01-2608-3-2665": {"건물구조": "철근콘크리트구조"},     # 표제부 조각 '철근'+'콘크리트구조'
    "01-2608-3-2664": {"건물구조": "철근콘크리트구조"},
    "01-2608-3-2561": {"공부면적": "277.70", "사정면적": "267.75",  # 공부≠사정
                       "용도지역": "제2종일반주거지역"},
    "01-2608-3-2546": {"용도지역": "제2종일반주거지역"},    # 명세 조각 '제2종'+'일반주거지역'
}


def ibk_docs() -> list[str]:
    """캐시 추출물 중 기업은행 담보 문서(cover0.custpart 로 판별)."""
    found = []
    for d in sorted((ROOT / "output").iterdir()):
        cover = d / "cover0.json" if d.is_dir() else None
        if cover is None or not cover.exists():
            continue
        try:
            rows = json.loads(cover.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if rows and "기업은행" in (rows[0].get("custpart") or ""):
            found.append(d.name)
    return found


def build(cfg, doc: str) -> dict:
    gam = load_extracted(str(ROOT / "output" / doc))
    ctx = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    return ibk.build(ctx)


def norm(text) -> str:
    return (str(text) if text is not None else "").replace(",", "").strip()


SUMMARY = ("부동산구분", "공부지목", "토지평가금액", "건물평가금액",
           "기계기구평가금액", "기타평가금액", "총감정평가액")

SPLIT = ("토지평가금액", "건물평가금액", "기계기구평가금액", "기타평가금액")


def split_matches_total(mine: dict) -> tuple[bool, int, int]:
    """평가금액 4분리 합 == 총감정평가액 인가.

    분리는 명세행에서, 총액은 `gam_info.price` 에서 온다 — **서로 다른 소스**라 두
    값이 맞으면 분류가 한 행도 새지 않았다는 뜻이다(실측 29건 전건 성립). 명세행에
    금액이 없는 문서는 검사에서 뺀다.
    """
    def value(label: str) -> int:
        text = norm(pick(mine, label))
        return int(text) if text.lstrip("-").isdigit() else 0

    parts = sum(value(label) for label in SPLIT)
    total = value("총감정평가액")
    return (parts == total, parts, total)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="check_ibk_offline")
    p.add_argument("doc_id", nargs="*", help="생략하면 캐시된 기업 문서 전건")
    p.add_argument("--detail", action="store_true", help="문서별 전체 필드 출력")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env or str(ROOT / ".env"))

    docs = args.doc_id or ibk_docs()
    ok = bad = crash = leak = 0
    for doc in docs:
        try:
            mine = build(cfg, doc)
        except Exception as error:            # 크래시는 회귀신호 — 세고 계속 간다
            crash += 1
            print(f"\n===== {doc} =====\n  ⛔ {type(error).__name__}: {str(error)[:80]}")
            continue
        filled = sum(1 for v in mine.values() if v not in (None, ""))
        print(f"\n===== {doc} =====  채움 {filled}칸")
        if args.detail:
            for label, value in mine.items():
                print(f"    {label:16} {str(value)[:40]}")
        else:
            print("   " + " · ".join(f"{k}={norm(pick(mine, k)) or '-'}" for k in SUMMARY))
        balanced, parts, total = split_matches_total(mine)
        if total and not balanced:
            leak += 1
            print(f"    ❗분리합 {parts:,} ≠ 총감정평가액 {total:,} (차 {parts - total:,})"
                  f" — 물건행 분류가 샜습니다")
        for label, want in EXPECT.get(doc, {}).items():
            got = norm(pick(mine, label))
            good = got == norm(want)
            ok, bad = (ok + good, bad + (not good))
            print(f"    {'✅' if good else '❌'} {label:14} 우리={got or '-':22} 기대={norm(want) or '-'}")

    print(f"\n[합계] 문서 {len(docs)} · 크래시 {crash} · 분리합불일치 {leak} · EXPECT ✅{ok} ❌{bad}")
    return 1 if (bad or crash or leak) else 0


if __name__ == "__main__":
    raise SystemExit(main())
