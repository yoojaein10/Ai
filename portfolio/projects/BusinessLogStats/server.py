# -*- coding: utf-8 -*-
"""업무일지 통계 통합 화면 — 공통 통계 API + 화면 서버 (1차: SP_IW_S_TaskStats_Mon).

실행:  uvicorn server:app --host 127.0.0.1 --port 8630
DB 접속은 Y_SqlMcp/db.py 의 프로파일을 재사용한다(자격증명 중복 보관 금지).
"""

import os
import re
import sys
import logging
import configparser
from decimal import Decimal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(BASE), "Y_SqlMcp"))
import db  # noqa: E402

import columns  # noqa: E402

SP_NAME = "dbo.SP_IW_S_TaskStats_Mon"
YM_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# ---- 설정 ------------------------------------------------------------------

def _load_config():
    cp = configparser.ConfigParser()
    cp.read(os.path.join(BASE, "config.ini"), encoding="utf-8")
    return cp

CFG = _load_config()
AUTH_MODE = CFG.get("auth", "mode", fallback="dev")          # dev | token | session
DEV_USER = CFG.get("auth", "dev_user", fallback="")          # dev 모드에서만 사용
VIEW_SCOPE = CFG.get("policy", "view_scope", fallback="all")  # all | self (임시 결정: all)
DB_PROFILE = CFG.get("db", "profile", fallback="") or db.default_profile()

# ---- 감사 로그 (사용자, 조회 월, 결과 상태만 — 토큰/PII 금지) ---------------

audit = logging.getLogger("audit")
audit.setLevel(logging.INFO)
_h = logging.FileHandler(os.path.join(BASE, "access.log"), encoding="utf-8")
_h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
audit.addHandler(_h)

# ---- 사용자 컨텍스트 --------------------------------------------------------

def resolve_user(request: Request):
    """진입 경로별 식별값을 서버 측 사용자 컨텍스트로 변환한다.

    dev    : config.ini 의 dev_user 를 사용 (로컬 개발 전용)
    token  : 데스크톱 EXE 토큰 인증 — 인증 방식 확정 후 구현
    session: 모바일 웹 세션 — 세션 저장 위치 확정 후 구현
    파라미터로 받은 식별값은 어떤 모드에서도 신뢰하지 않는다(fail-closed).
    """
    if AUTH_MODE == "dev":
        if not DEV_USER:
            raise HTTPException(503, "dev_user가 설정되지 않았습니다.")
        return {"user": DEV_USER, "scope": VIEW_SCOPE}
    raise HTTPException(501, "인증 방식(%s)이 아직 구현되지 않았습니다." % AUTH_MODE)

# ---- SP 호출 및 변환 --------------------------------------------------------

def _minutes(v):
    """'시:분' 문자열(또는 '0'/None)을 분으로 변환."""
    if v is None:
        return 0
    s = str(v).strip()
    if ":" in s:
        h, _, m = s.partition(":")
        try:
            return int(h) * 60 + int(m)
        except ValueError:
            return 0
    try:
        return int(float(s)) * 60
    except ValueError:
        return 0


def _num(v):
    if v is None:
        return 0
    if isinstance(v, Decimal):
        return float(v)
    return v


def fetch_stats(ym: str):
    """SP를 실행해 담당자별 행을 이름 기준 dict 로 반환한다."""
    conn = db.connect(DB_PROFILE)
    try:
        cur = conn.cursor()
        cur.execute(
            "SET NOCOUNT ON; EXEC %s @F_Date=?, @Manager=?" % SP_NAME,
            (ym + "-01", ""),
        )
        names = [d[0] for d in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchall()]
    finally:
        conn.close()

    out = []
    for r in rows:
        row = {"Manager": r.get("Manager", "")}
        summary = {"time_min": 0, "time_price": 0.0, "count": 0, "count_price": 0.0}
        for g in columns.GROUPS:
            for it in g["items"]:
                q, p = it["qty"], it["price"]
                price = _num(r.get(p))
                if g["kind"] == "time":
                    row[q] = str(r.get(q) or "0:00")
                    summary["time_min"] += _minutes(r.get(q))
                    summary["time_price"] += price
                else:
                    row[q] = int(_num(r.get(q)))
                    summary["count"] += row[q]
                    summary["count_price"] += price
                row[p] = price
        summary["total_price"] = summary["time_price"] + summary["count_price"]
        row["_summary"] = summary
        out.append(row)
    return out

# ---- API -------------------------------------------------------------------

app = FastAPI(title="업무일지 통계", docs_url=None, redoc_url=None)


@app.get("/api/stats")
def api_stats(request: Request, ym: str = Query(...)):
    user = resolve_user(request)
    if not YM_RE.match(ym):  # 형식 검증 = LIKE 와일드카드(%,_,[) 차단을 겸한다
        audit.info("user=%s ym=%s status=bad_request", user["user"], ym[:20])
        raise HTTPException(400, "조회 월은 YYYY-MM 형식이어야 합니다.")
    try:
        rows = fetch_stats(ym)
    except Exception:
        audit.info("user=%s ym=%s status=db_error", user["user"], ym)
        logging.exception("SP 실행 실패")
        raise HTTPException(500, "통계 조회 중 오류가 발생했습니다.")

    if user["scope"] == "self":
        rows = [r for r in rows if r["Manager"] == user["user"]]

    audit.info("user=%s ym=%s status=ok rows=%d", user["user"], ym, len(rows))
    return {
        "ym": ym,
        "user": user["user"],
        "scope": user["scope"],
        "groups": columns.GROUPS,
        "always_zero": sorted(columns.ALWAYS_ZERO),
        "rows": rows,
    }


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "app.html"))
