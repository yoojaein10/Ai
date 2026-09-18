# -*- coding: utf-8 -*-
"""DBA ONE 챗봇 평가 하네스 (v0.17 §8).

실행 중인 앱(http://127.0.0.1:8400)에 고정 평가셋을 보내 경로 분류·테이블 선택·
SQL 유효성·재질문 적절성·응답시간·토큰을 측정한다.

원칙:
  - 생성된 SQL은 실행하지 않는다 (사용자 승인 게이트 존중 — 결과 정답률은 수동 검증)
  - 후속(followup_of) 질문은 부모 직후 리셋 없이, 그 외는 /api/chat/reset 후 실행
  - 결과는 eval/results/에 저장 (gitignore — 답변에 스키마 정보가 담기므로 미커밋)

사용:  python eval/run_eval.py --label v0.16-baseline [--only 1,2,3] [--sleep 1]
"""
import argparse
import json
import re
import statistics
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

EVAL_DIR = Path(__file__).resolve().parent
PROTO_DIR = EVAL_DIR.parent
METRICS = PROTO_DIR / "metrics.jsonl"


def http(base: str, path: str, body: dict | None = None, nonce: str = "") -> str:
    req = urllib.request.Request(base + path, method="POST" if body is not None else "GET")
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.add_header("X-DBAONE-Nonce", nonce)
        req.data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read().decode("utf-8")


def get_nonce(base: str) -> str:
    m = re.search(r'DBAONE_NONCE="([^"]+)"', http(base, "/"))
    if not m:
        raise SystemExit("nonce를 찾지 못했습니다 — 앱이 실행 중인지 확인하세요.")
    return m.group(1)


def metrics_offset() -> int:
    return METRICS.stat().st_size if METRICS.exists() else 0


def metrics_since(offset: int) -> dict | None:
    """offset 이후 추가된 chat 계측 레코드 중 마지막 것."""
    if not METRICS.exists():
        return None
    with open(METRICS, "r", encoding="utf-8") as f:
        f.seek(offset)
        recs = []
        for line in f:
            try:
                r = json.loads(line)
                if r.get("event") == "chat":
                    recs.append(r)
            except Exception:
                pass
    return recs[-1] if recs else None


def judge(q: dict, res: dict) -> dict:
    """기대치 대비 채점. None = 해당 없음."""
    exp = q.get("expect", {})
    s: dict = {}
    s["route_ok"] = res.get("route") in exp.get("route", []) if exp.get("route") else None

    if exp.get("tables"):
        got = {t.lower() for t in (res.get("tables") or [])}
        s["tables_ok"] = all(t.lower() in got for t in exp["tables"])
    else:
        s["tables_ok"] = None

    if res.get("route") == "data" and res.get("sql"):
        s["sql_valid"] = not res.get("invalid_reason")
    else:
        s["sql_valid"] = None

    if exp.get("clarify"):
        # 재질문이 필요한 문항에서 caveat를 붙인 추측 SQL은 통과시키지 않는다.
        # SQL 없이 구체화 답변/오류를 반환해야 실제로 추측을 멈춘 것으로 인정한다.
        asked = not res.get("sql") and bool((res.get("answer") or res.get("error") or "").strip())
        s["clarify_ok"] = asked
    elif exp.get("clarify_or_sql"):
        asked = not res.get("sql") and bool((res.get("answer") or res.get("error") or "").strip())
        allowed = {t.lower() for t in exp.get("acceptable_tables", [])}
        got = {t.lower() for t in (res.get("tables") or [])}
        scoped_sql = bool(res.get("sql")) and not res.get("invalid_reason") \
            and (not allowed or bool(got & allowed))
        s["clarify_ok"] = asked or scoped_sql
    else:
        s["clarify_ok"] = None

    if exp.get("nonexistent"):
        # 합격: SQL을 만들지 않았거나(테이블 못 찾음), caveat으로 부재를 경고
        s["nonexistent_ok"] = (not res.get("sql")) or bool((res.get("caveat") or "").strip())
    else:
        s["nonexistent_ok"] = None
    return s


def run(args):
    base = args.base
    nonce = get_nonce(base)
    health = json.loads(http(base, "/api/health"))
    if not health.get("ai"):
        raise SystemExit("AI 비활성화 상태 — GEMINI_API_KEY 설정 후 다시 실행하세요.")
    print(f"대상: db={health.get('db')} model={health.get('model')} env={health.get('env_label')}")

    qs = json.loads((EVAL_DIR / "questions.json").read_text(encoding="utf-8"))["questions"]
    only = {int(x) for x in args.only.split(",")} if args.only else None

    # 실행 순서: 부모(비후속) 순서대로, 각 부모 직후에 그 후속 질문
    by_parent: dict = {}
    roots = []
    for q in qs:
        if q.get("followup_of"):
            by_parent.setdefault(q["followup_of"], []).append(q)
        else:
            roots.append(q)
    ordered = []
    for q in roots:
        ordered.append(q)
        ordered.extend(by_parent.get(q["id"], []))

    results = []
    for q in ordered:
        if only and q["id"] not in only and not (q.get("followup_of") in only if q.get("followup_of") else False):
            continue
        if not q.get("followup_of"):
            http(base, "/api/chat/reset", {}, nonce)  # 문맥 격리
        off = metrics_offset()
        t0 = time.perf_counter()
        try:
            res = json.loads(http(base, "/api/chat", {"question": q["question"]}, nonce))
        except Exception as e:
            res = {"ok": False, "error": f"호출 실패: {type(e).__name__}"}
        client_ms = round((time.perf_counter() - t0) * 1000)
        tele = metrics_since(off) or {}
        score = judge(q, res)
        row = {"id": q["id"], "type": q["type"], "question": q["question"],
               "route_expected": q.get("expect", {}).get("route"),
               "route_got": res.get("route"), **score,
               "ok": res.get("ok"), "error": res.get("error"),
               "tables": res.get("tables"), "sql": res.get("sql"),
               "caveat": res.get("caveat"), "answer": (res.get("answer") or "")[:500],
               "client_ms": client_ms, "total_ms": tele.get("total_ms"),
               "route_ms": tele.get("route_ms"), "pick_ms": tele.get("pick_ms"),
               "generation_ms": tele.get("generation_ms"),
               "calls": tele.get("calls"), "tokens_in": tele.get("tokens_in"),
               "tokens_out": tele.get("tokens_out")}
        results.append(row)
        marks = " ".join(f"{k}={'O' if v else 'X'}" for k, v in score.items() if v is not None)
        print(f"[{q['id']:>2}] {q['type']:<14} route={res.get('route') or '-':<9}"
              f" {client_ms/1000:5.1f}s  {marks}")
        time.sleep(args.sleep)

    # ── 요약
    def rate(key):
        vals = [r[key] for r in results if r.get(key) is not None]
        return (sum(1 for v in vals if v), len(vals))

    lat = sorted(r["client_ms"] for r in results)
    p50 = lat[len(lat) // 2] if lat else 0
    p95 = lat[min(len(lat) - 1, round(len(lat) * 0.95) - 1)] if lat else 0
    calls = [r["calls"] for r in results if r.get("calls")]
    tin = sum(r.get("tokens_in") or 0 for r in results)
    tout = sum(r.get("tokens_out") or 0 for r in results)
    summary = {
        "label": args.label, "ts": datetime.now().isoformat(timespec="seconds"),
        "n": len(results),
        "route_acc": rate("route_ok"), "table_recall": rate("tables_ok"),
        "sql_valid": rate("sql_valid"), "clarify_ok": rate("clarify_ok"),
        "nonexistent_ok": rate("nonexistent_ok"),
        "latency_ms": {"p50": p50, "p95": p95,
                       "mean": round(statistics.mean(lat)) if lat else 0},
        "calls_per_q": round(statistics.mean(calls), 2) if calls else None,
        "tokens_in_total": tin, "tokens_out_total": tout,
    }
    print("\n== 요약 ==")
    for k in ("route_acc", "table_recall", "sql_valid", "clarify_ok", "nonexistent_ok"):
        ok, n = summary[k]
        print(f"{k:<15} {ok}/{n}" + (f" ({ok / n * 100:.0f}%)" if n else ""))
    print(f"latency p50/p95  {p50 / 1000:.1f}s / {p95 / 1000:.1f}s")
    print(f"질문당 AI 호출   {summary['calls_per_q']}")
    print(f"토큰 입력/출력   {tin:,} / {tout:,}")

    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{args.label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps({"summary": summary, "results": results},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8400")
    ap.add_argument("--label", default="eval")
    ap.add_argument("--only", default="", help="질문 id 목록 (예: 1,2,3)")
    ap.add_argument("--sleep", type=float, default=0.5, help="질문 간 대기 초")
    run(ap.parse_args())
