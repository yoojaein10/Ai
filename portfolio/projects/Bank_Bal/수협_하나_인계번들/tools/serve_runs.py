"""BankOn 처리 내역 API — 로그를 읽어 JSON 으로 돌려준다. **DB 를 쓰지 않는다.**

    python tools/serve_runs.py --reports "C:\\BankOn_배포_20260831\\reports"
    python tools/serve_runs.py --reports … --port 8787 --host 0.0.0.0

엔드포인트 (전부 GET · JSON · UTF-8)

    /api/summary            총 누적 · 금일 누적
    /api/banks              은행별
    /api/daily?days=30      일자별 × 은행별 (그래프용)
    /api/runs?limit=50      최근 처리 내역 (어떤 걸 했는지)
        &since=2026-09-01   그 날짜부터
        &bank=국민           은행 필터
        &result=실패         결과 필터
    /api/health             살아 있나 · 로그 몇 개 읽고 있나

읽기 전용이다 — 로그 파일도 **읽기만** 하고 아무것도 쓰지 않는다.
로그가 바뀌었을 때만 다시 파싱한다(mtime 확인). 대시보드가 자주 불러도 부담이 없다.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon import runlog                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass


class Cache:
    """로그가 바뀌었을 때만 다시 읽는다."""

    def __init__(self, folders: list[Path]):
        self.folders = folders
        self._lock = threading.Lock()
        self._stamp: tuple | None = None
        self._runs: list[runlog.Run] = []

    def _fingerprint(self) -> tuple:
        marks = []
        for folder in self.folders:
            for path in sorted(folder.glob("gui_*.log")):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                marks.append((str(path), stat.st_mtime_ns, stat.st_size))
        return tuple(marks)

    def runs(self) -> list[runlog.Run]:
        with self._lock:
            stamp = self._fingerprint()
            if stamp != self._stamp:
                self._runs = runlog.collect(*self.folders)
                self._stamp = stamp
            return self._runs


def _json(value) -> bytes:
    def fallback(obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        raise TypeError(type(obj))
    return json.dumps(value, ensure_ascii=False, indent=1,
                      default=fallback).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    cache: Cache = None            # type: ignore[assignment]
    server_version = "BankOnRuns/1.0"

    def log_message(self, fmt, *args):          # 접속마다 콘솔을 더럽히지 않는다
        pass

    def _send(self, payload, status: int = 200) -> None:
        body = _json(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")   # 대시보드가 다른 서버다
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:               # 브라우저 프리플라이트
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        url = urlparse(self.path)
        query = parse_qs(url.query)

        def one(name, default=None):
            values = query.get(name)
            return values[0] if values else default

        try:
            runs = self.cache.runs()
        except Exception as error:              # 로그를 못 읽어도 서버는 살아 있어야 한다
            self._send({"error": f"{type(error).__name__}: {error}"}, 500)
            return

        path = url.path.rstrip("/") or "/"
        if path in ("/", "/api"):
            self._send({"endpoints": ["/api/summary", "/api/banks", "/api/daily",
                                      "/api/runs", "/api/health"]})
        elif path == "/api/health":
            self._send({
                "ok": True,
                "reports": [str(f) for f in self.cache.folders],
                "로그파일": sum(len(list(f.glob("gui_*.log"))) for f in self.cache.folders),
                "내역건수": len(runs),
                "미분류": sorted({r.raw for r in runs if r.result == "기타"}),
                "지금": datetime.now().isoformat(timespec="seconds"),
            })
        elif path == "/api/summary":
            self._send(runlog.summary(runs))
        elif path == "/api/banks":
            self._send(runlog.by_bank(runs))
        elif path == "/api/daily":
            try:
                days = max(1, min(365, int(one("days", "30"))))
            except ValueError:
                days = 30
            self._send(runlog.daily(runs, days))
        elif path == "/api/runs":
            picked = list(reversed(runs))       # 최신 먼저
            if one("bank"):
                picked = [r for r in picked if r.bank == one("bank")]
            if one("result"):
                picked = [r for r in picked if r.result == one("result")]
            if one("since"):
                try:
                    floor = datetime.strptime(one("since"), "%Y-%m-%d").date()
                    picked = [r for r in picked if r.at.date() >= floor]
                except ValueError:
                    pass
            try:
                limit = max(1, min(2000, int(one("limit", "50"))))
            except ValueError:
                limit = 50
            self._send({"건수": len(picked),
                        "내역": [r.as_json() for r in picked[:limit]]})
        else:
            self._send({"error": "없는 주소입니다", "path": url.path}, 404)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="serve_runs")
    p.add_argument("--reports", action="append", required=True,
                   help="배포본의 reports 폴더(여러 대면 여러 번)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8787)
    args = p.parse_args(argv)

    folders = [Path(r) for r in args.reports]
    missing = [f for f in folders if not f.is_dir()]
    if missing:
        print("폴더가 없습니다: " + " · ".join(str(f) for f in missing))
        return 1

    Handler.cache = Cache(folders)
    runs = Handler.cache.runs()
    print(f"내역 {len(runs)}건 읽음 — " + " · ".join(str(f) for f in folders))
    unknown = sorted({r.raw for r in runs if r.result == "기타"})
    if unknown:
        print("⚠ 못 알아본 결과 표현(원문 그대로 나갑니다):")
        for text in unknown:
            print("   ", text[:90])

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"\nhttp://{args.host}:{args.port}/api/summary  (Ctrl+C 로 종료)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
