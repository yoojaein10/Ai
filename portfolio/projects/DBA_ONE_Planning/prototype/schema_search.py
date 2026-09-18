# -*- coding: utf-8 -*-
"""로컬 스키마 검색 (v0.17 §1) — SQLite FTS5 한글 하이브리드 검색.

질문과 관련된 테이블 상위 N개를 로컬에서 골라 LLM 프롬프트를 줄인다.
순수 trigram은 3글자 미만 질의에 매치되지 않으므로(접수·건수 등 2글자 핵심어)
다음 조합을 쓴다:
  1) 이름·동의어·설명 정확/부분 일치 (LIKE ? 바인딩, 1~2글자 용어 포함)  — 가중치 최고
  2) unicode61 FTS (띄어쓰기 기반 토큰)                                  — 중간
  3) trigram FTS (3글자 이상 부분 문자열, 런타임 지원 시에만)             — 보조
가중치·조합은 평가셋 Recall@5/10으로 조정한다 (§8).

보안 (v0.17 §1·§3):
  - 사용자 질문을 MATCH에 직접 넣지 않는다 — 앱이 토큰화해 각 토큰을 큰따옴표
    구문("" 이스케이프)으로 만들고 명시적 OR로 조합한 문자열만 MATCH ?에 바인딩
  - 색인 대상은 객체명·컬럼명·MS_Description·용어집 등 메타데이터만
    (데이터 값·과거 SQL 리터럴은 색인하지 않는다)
  - search.db는 민감한 파생 데이터 — DATA_DIR에 두고 config.json과 동일 취급
"""
from __future__ import annotations

import contextlib
import re
import sqlite3
from pathlib import Path

# 검색 신뢰 임계 — 미만이면 후보 확대·재질문 트리거 (§6)
LOW_SCORE = 1.0
# 영문·숫자 run과 한글 run을 분리해 토큰화 — 'BANK_KB_PROCESS에'처럼 조사가 붙어도
# 영문 객체명이 온전한 토큰으로 잡힌다
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[가-힣]+")
_STOPWORDS = {
    # 조사·일반어 — 검색 변별력 없는 토큰
    "테이블", "건수", "개수", "행수", "행", "수", "몇", "몇건", "알려줘", "보여줘",
    "알려", "보여", "줘", "해줘", "세어줘", "총", "전체", "기준", "현재", "지금",
    "오늘", "어제", "이번", "지난", "최근", "일자별", "월별", "년도별", "달",
    "그럼", "그리고", "에서", "에는", "은", "는", "이", "가", "을", "를", "의",
    "and", "or", "not", "near", "the", "select", "from", "where", "dbo", "sys",
}


def tokenize(question: str) -> list[str]:
    """질문을 검색 토큰으로 분해 — 스크립트 분리, 1글자·불용어·FTS 연산자 제거."""
    out, seen = [], set()
    for t in _TOKEN_RE.findall(question or ""):
        low = t.lower()
        if len(low) < 2 or low in _STOPWORDS or low in seen:
            continue
        seen.add(low)
        out.append(low)
    return out[:20]  # 폭주 방지


def fts_query(tokens: list[str], min_len: int = 2) -> str:
    """안전한 FTS5 MATCH 문자열 생성 — 각 토큰을 ""로 감싸고 내부 "는 ""로.
    연산자(NEAR·NOT·col: 등)는 따옴표 구문 안에서 리터럴로만 취급된다."""
    quoted = ['"' + t.replace('"', '""') + '"' for t in tokens if len(t) >= min_len]
    return " OR ".join(quoted)


class SchemaSearch:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.trigram_ok = self._detect_trigram()
        self._init_schema()

    @contextlib.contextmanager
    def _connect(self):
        # sqlite3의 with는 커밋만 하고 close는 안 하므로(Windows 파일 잠금 잔류) 직접 닫는다
        con = sqlite3.connect(self.db_path)
        try:
            # 삭제된 색인 데이터가 파일에 잔류하지 않도록 (민감 파생 데이터, v0.17 §3)
            con.execute("PRAGMA secure_delete=ON")
            with con:
                yield con
        finally:
            con.close()

    def _detect_trigram(self) -> bool:
        """trigram 토크나이저 지원 여부를 실제 테이블 생성으로 확인 (SQLite 3.34+)."""
        try:
            with sqlite3.connect(":memory:") as c:
                c.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
            return True
        except sqlite3.OperationalError:
            return False

    def _init_schema(self):
        with self._connect() as c:
            # 파생 캐시라 스키마가 달라지면 통째로 재생성 (색인은 다음 질문 때 재구축됨)
            cols = {r[1] for r in c.execute("PRAGMA table_info(items)").fetchall()}
            if cols and "syn_l" not in cols:
                c.executescript("DROP TABLE IF EXISTS items;"
                                " DROP TABLE IF EXISTS fts_uni; DROP TABLE IF EXISTS fts_tri;"
                                " DROP TABLE IF EXISTS build_meta;")
            c.execute("CREATE TABLE IF NOT EXISTS items"
                      " (id INTEGER PRIMARY KEY, target TEXT, obj TEXT, kind TEXT,"
                      "  name_l TEXT, nospace_l TEXT, syn_l TEXT, words TEXT)")
            c.execute("CREATE INDEX IF NOT EXISTS ix_items ON items(target, obj)")
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts_uni USING fts5"
                      "(words, content='items', content_rowid='id',"
                      " tokenize='unicode61 remove_diacritics 2')")
            if self.trigram_ok:
                c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts_tri USING fts5"
                          "(words, content='items', content_rowid='id',"
                          " tokenize='trigram')")
            c.execute("CREATE TABLE IF NOT EXISTS build_meta"
                      " (target TEXT PRIMARY KEY, built_ts TEXT, n_items INTEGER,"
                      "  schema_sig TEXT)")

    # ── 색인 구축 ──────────────────────────────
    def rebuild(self, target: str, entries: list[dict], built_ts: str, schema_sig: str = ""):
        """대상(target_id)의 색인을 재구축한다.
        entries: [{obj: 'dbo.APW_Master', kind: 'U', words: '색인 텍스트'}]
        words에는 메타데이터만 담을 것 (호출부 책임: 이름·컬럼·설명·동의어)."""
        with self._connect() as c:
            old = [r[0] for r in c.execute(
                "SELECT id FROM items WHERE target=?", (target,)).fetchall()]
            for rid in old:
                c.execute("INSERT INTO fts_uni(fts_uni, rowid, words)"
                          " SELECT 'delete', id, words FROM items WHERE id=?", (rid,))
                if self.trigram_ok:
                    c.execute("INSERT INTO fts_tri(fts_tri, rowid, words)"
                              " SELECT 'delete', id, words FROM items WHERE id=?", (rid,))
            c.execute("DELETE FROM items WHERE target=?", (target,))
            for e in entries:
                name = e["obj"].split(".")[-1]
                cur = c.execute(
                    "INSERT INTO items(target, obj, kind, name_l, nospace_l, syn_l, words)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (target, e["obj"], e.get("kind", ""), name.lower(),
                     re.sub(r"\s+", "", e.get("words", "")).lower(),
                     "|".join(s.lower() for s in e.get("syns", [])),
                     e.get("words", "")))
                rid = cur.lastrowid
                c.execute("INSERT INTO fts_uni(rowid, words) VALUES (?,?)",
                          (rid, e.get("words", "")))
                if self.trigram_ok:
                    c.execute("INSERT INTO fts_tri(rowid, words) VALUES (?,?)",
                              (rid, e.get("words", "")))
            c.execute("INSERT INTO build_meta(target, built_ts, n_items, schema_sig)"
                      " VALUES (?,?,?,?) ON CONFLICT(target) DO UPDATE SET"
                      " built_ts=excluded.built_ts, n_items=excluded.n_items,"
                      " schema_sig=excluded.schema_sig",
                      (target, built_ts, len(entries), schema_sig))

    def build_info(self, target: str) -> dict | None:
        with self._connect() as c:
            r = c.execute("SELECT built_ts, n_items, schema_sig FROM build_meta"
                          " WHERE target=?", (target,)).fetchone()
        return {"built_ts": r[0], "n_items": r[1], "schema_sig": r[2]} if r else None

    # ── 검색 ──────────────────────────────────
    def search(self, target: str, question: str, top_n: int = 10) -> dict:
        """관련 객체 상위 top_n + 신뢰 판정.
        반환: {results: [{obj, kind, score, why}], low_confidence: bool, tokens: [...]}"""
        tokens = tokenize(question)
        scores: dict[str, float] = {}
        why: dict[str, set] = {}

        def add(obj: str, pts: float, reason: str):
            scores[obj] = scores.get(obj, 0.0) + pts
            why.setdefault(obj, set()).add(reason)

        with self._connect() as c:
            # 1) 이름·동의어 정확/부분 일치 — 1~2글자 용어도 여기서 잡힌다
            rows = c.execute("SELECT obj, name_l, nospace_l, syn_l FROM items"
                             " WHERE target=?", (target,)).fetchall()
            for t in tokens:
                for obj, name_l, nospace_l, syn_l in rows:
                    if name_l == t:
                        add(obj, 4.0, f"이름 정확 일치({t})")
                    elif syn_l and t in syn_l.split("|"):
                        add(obj, 3.5, f"동의어 일치({t})")
                    elif t in name_l:
                        add(obj, 2.0, f"이름 부분 일치({t})")
                    elif len(t) >= 2 and t in nospace_l:
                        add(obj, 1.2, f"텍스트 포함({t})")

            # 2) unicode61 FTS — bm25는 음수일수록 좋은 매치 → 0.6~2.0 범위로 정규화
            q_uni = fts_query(tokens, min_len=2)
            if q_uni:
                try:
                    for obj, rank in c.execute(
                            "SELECT i.obj, bm25(fts_uni) FROM fts_uni"
                            " JOIN items i ON i.id = fts_uni.rowid"
                            " WHERE i.target=? AND fts_uni MATCH ?"
                            " ORDER BY bm25(fts_uni) LIMIT 50", (target, q_uni)):
                        rel = max(-rank, 0.0)
                        add(obj, 1.5 * (0.4 + rel / (rel + 3.0)), "단어 일치")
                except sqlite3.OperationalError:
                    pass  # 토큰이 전부 특수문자 등 — 검색 생략
            # 3) trigram FTS — 3글자 이상 부분 문자열, 0.4~1.3 범위
            if self.trigram_ok:
                q_tri = fts_query(tokens, min_len=3)
                if q_tri:
                    try:
                        for obj, rank in c.execute(
                                "SELECT i.obj, bm25(fts_tri) FROM fts_tri"
                                " JOIN items i ON i.id = fts_tri.rowid"
                                " WHERE i.target=? AND fts_tri MATCH ?"
                                " ORDER BY bm25(fts_tri) LIMIT 50", (target, q_tri)):
                            rel = max(-rank, 0.0)
                            add(obj, 1.0 * (0.4 + rel / (rel + 3.0)), "부분 문자열 일치")
                    except sqlite3.OperationalError:
                        pass

        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:top_n]
        kinds = {}
        if ranked:
            with self._connect() as c:
                marks = ",".join("?" * len(ranked))
                kinds = dict(c.execute(
                    f"SELECT obj, kind FROM items WHERE target=? AND obj IN ({marks})",
                    [target] + [o for o, _ in ranked]).fetchall())
        results = [{"obj": o, "kind": kinds.get(o, ""), "score": round(s, 2),
                    "why": sorted(why[o])[:3]} for o, s in ranked]
        top = results[0]["score"] if results else 0.0
        second = results[1]["score"] if len(results) > 1 else 0.0
        # 강한 근거 = 이름 또는 동의어 일치. 설명 텍스트 포함만으로는 특정 못 한 것으로 본다
        strong_top = bool(results) and any(
            w.startswith(("이름", "동의어")) for w in results[0]["why"])
        low_confidence = (not results) or top < LOW_SCORE \
            or (not strong_top and top < 3.0) \
            or (len(results) > 1 and top - second < 0.3 and top < 3.0)
        return {"results": results, "low_confidence": low_confidence,
                "tokens": tokens, "trigram": self.trigram_ok}
