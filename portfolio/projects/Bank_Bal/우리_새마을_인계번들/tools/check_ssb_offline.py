"""수협 매핑 오프라인 회귀검사 — EXPECT(실폼 확인값) 대조 + 불변식 검사.

live 로 화면 대조한 문서는 EXPECT 에 정답값을 박아 자동 대조하고, 나머지 전건은
크래시·물건구분·법정동·금액정합 같은 **불변식**으로 훑는다. 캐시(output/<doc>)가 있으면
재추출 없이 쓰고, 없으면 FTP 로 받아 추출한다(--no-fetch 면 캐시만).

    python tools/check_ssb_offline.py <문서…>            # 배치
    python tools/check_ssb_offline.py --expect-only       # EXPECT 4건만
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import Counter
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.gam_bridge import load_extracted    # noqa: E402
from bankon.mapping import ssb                   # noqa: E402
import verify_form as vf                          # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent

# 실폼으로 확인한 정답값(화면). 키는 ssb.build 의 필드명.
EXPECT = {
    "01-2608-3-2637": {"평가사명": "유승민", "실   비": "56000", "순수수료": "12136080",
                       "부가세": "1219200", "감정수수료": "13411200", "물건구분코드": "토지",
                       "본번지": "36", "부번지": "1", "용도지역": "3종일주", "공부면적": "722.00",
                       "사정면적": "722.00", "평가단가": "30500000",
                       "감정평가액": "22021000000", "등기번호": "11441996072170"},
    "01-2608-3-2641": {"평가사명": "김기석", "실   비": "124900", "순수수료": "933957",
                       "부가세": "105800", "감정수수료": "1163800", "물건구분코드": "토지",
                       "본번지": "91", "부번지": "8", "용도지역": "1종일주", "공부면적": "146.10",
                       "사정면적": "146.10", "평가단가": "2900000",
                       "감정평가액": "423690000", "등기번호": "12471996083902"},
    "01-2608-3-2609": {"평가사명": "유승민", "실   비": "61500", "순수수료": "588800",
                       "부가세": "65000", "감정수수료": "715000",
                       "물건구분코드": "집합물건(건물)", "본번지": "135", "부번지": "8",
                       "감정평가액": "435000000", "등기번호": "24012006002717"},
    "01-2608-3-2583": {"평가사명": "성지연", "실   비": "66000", "순수수료": "1271098",
                       "부가세": "133700", "감정수수료": "1470700", "물건구분코드": "토지",
                       "본번지": "424", "부번지": "5", "용도지역": "일반상업", "공부면적": "73.10",
                       "사정면적": "73.10", "평가단가": "19200000",
                       "감정평가액": "1403520000", "등기번호": "11031996514426"},
    # 라이브 확인(2026-09-01)
    "01-2604-3-1068": {"평가사명": "최병산", "실   비": "67000", "순수수료": "2894335",
                       "부가세": "296100", "감정수수료": "3257100", "물건구분코드": "토지",
                       "본번지": "309", "부번지": "13", "용도지역": "2종일주", "공부면적": "450.60",
                       "사정면적": "450.60", "평가단가": "4130000", "감정평가액": "1860978000"},
    "01-2604-3-1066": {"평가사명": "정우종", "실   비": "76400", "순수수료": "2593200",
                       "부가세": "266900", "감정수수료": "2935900",
                       "물건구분코드": "집합물건(건물)", "본번지": "915", "부번지": "3",
                       "건물면적": "143.66", "감정평가액": "1010000000"},
}
KINDS = {"토지", "집합물건(건물)", "건물"}


def norm(value) -> str:
    text = unicodedata.normalize("NFKC", str(value) if value is not None else "")
    return re.sub(r"\(\d+\)\s*$", "", text).replace(",", "").replace(" ", "").strip()


def _seqs(context):
    rows = [r for r in context.details if r.is_land or r.is_building]
    seen, out = set(), []
    for r in rows:
        s = r.seq_no
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out or ["1"]


def invariants(doc: str, values: dict) -> list[str]:
    """스크린 정답 없이도 잡히는 자기모순."""
    bad = []
    kind = values.get("물건구분코드")
    if kind is not None and kind not in KINDS:
        bad.append(f"물건구분코드 이상값:{kind!r}")
    sgg = values.get("법정동코드시군구@본번지~상세주소[0]")
    emd = values.get("법정동코드읍면동@본번지~상세주소[1]")
    if (sgg is None) != (emd is None):
        bad.append("법정동 반쪽")
    for part in (sgg, emd):
        if part is not None and not (part.isdigit() and len(part) == 5):
            bad.append(f"법정동 5자리 아님:{part!r}")
    if not values.get("평가사명"):
        bad.append("평가사명 없음")
    # 토지: 감정평가액 ≈ 사정면적 × 평가단가 (일단지·소분은 오차 허용)
    if kind == "토지":
        try:
            area = Decimal(norm(values.get("사정면적")) or "0")
            unit = Decimal(norm(values.get("평가단가")) or "0")
            amt = Decimal(norm(values.get("감정평가액")) or "0")
            if area and unit and amt:
                calc = area * unit
                if abs(calc - amt) > amt * Decimal("0.02"):
                    bad.append(f"토지금액정합 {amt} vs 면적×단가 {calc}")
        except Exception:
            pass
    # 집합물건: 면적·단가·용도는 비어 있어야(수협 관례)
    if kind == "집합물건(건물)":
        for f in ("공부면적", "사정면적", "평가단가", "용도지역"):
            if values.get(f):
                bad.append(f"집합물건인데 {f} 채움:{values.get(f)!r}")
    return bad


def expect_check(doc: str, values: dict) -> tuple[int, int, list[str]]:
    exp = EXPECT.get(doc)
    if not exp:
        return (0, 0, [])
    ok = miss = 0
    fails = []
    for k, want in exp.items():
        got = norm(values.get(k))
        if got == norm(want):
            ok += 1
        else:
            miss += 1
            fails.append(f"{k}: 기대={want!r} 실제={values.get(k)!r}")
    return (ok, miss, fails)


def analyze(cfg, doc: str, allow_fetch: bool) -> dict:
    out = ROOT / "output" / doc
    try:
        if out.is_dir():
            gam = load_extracted(str(out))
        elif allow_fetch:
            gam, _, _ = vf.fetch_gam(cfg, doc)
        else:
            return {"doc": doc, "skip": "추출물없음"}
        context = vf.build_context(cfg, doc, gam.tables, vf.sections_from_gam(gam))
    except BaseException as e:                       # SystemExit(.gam없음) 포함
        return {"doc": doc, "error": f"{type(e).__name__}:{str(e)[:60]}"}
    kinds, viol, exp_ok, exp_miss, exp_fail = Counter(), [], 0, 0, []
    for seq in _seqs(context):
        try:
            v = ssb.build(context, seq)
        except Exception as e:
            viol.append(f"[{seq}] 크래시 {type(e).__name__}:{str(e)[:50]}")
            continue
        kinds[v.get("물건구분코드")] += 1
        for b in invariants(doc, v):
            viol.append(f"[{seq}] {b}")
        if seq in ("1", _seqs(context)[0]) and doc in EXPECT:
            o, m, f = expect_check(doc, v)
            exp_ok, exp_miss, exp_fail = o, m, f
    return {"doc": doc, "kinds": dict(kinds), "viol": viol,
            "exp_ok": exp_ok, "exp_miss": exp_miss, "exp_fail": exp_fail}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="check_ssb_offline")
    p.add_argument("doc_id", nargs="*")
    p.add_argument("--expect-only", action="store_true")
    p.add_argument("--no-fetch", action="store_true", help="캐시만(FTP 안 씀)")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env or str(ROOT / ".env"))

    docs = list(EXPECT) if args.expect_only else (args.doc_id or list(EXPECT))
    tally = Counter()
    kind_total = Counter()
    for doc in docs:
        r = analyze(cfg, doc, allow_fetch=not args.no_fetch)
        if r.get("skip"):
            print(f"  {doc}: — {r['skip']}"); tally["skip"] += 1; continue
        if r.get("error"):
            print(f"  {doc}: ⛔ {r['error']}"); tally["error"] += 1; continue
        kind_total.update(r["kinds"])
        exp = ""
        if doc in EXPECT:
            exp = f" · EXPECT ✅{r['exp_ok']}/❌{r['exp_miss']}"
            tally["exp_ok"] += r["exp_ok"]; tally["exp_miss"] += r["exp_miss"]
        flag = "⚠️" if r["viol"] else "✅"
        print(f"  {flag} {doc}: {r['kinds']}{exp}")
        for f in r.get("exp_fail", []):
            print(f"        ❌ {f}")
        for b in r["viol"]:
            print(f"        ⚠️ {b}")
        tally["viol"] += len(r["viol"])
        tally["ok"] += 1

    print(f"\n[합계] 문서 {len(docs)} · 정상 {tally['ok']} · 스킵 {tally['skip']} · "
          f"오류 {tally['error']} · 불변식위반 {tally['viol']} · "
          f"EXPECT ✅{tally['exp_ok']}/❌{tally['exp_miss']}")
    print("물건유형 분포:", dict(kind_total))
    return 1 if (tally["error"] or tally["exp_miss"] or tally["viol"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
