"""BankOn 이 남기는 처리 로그를 읽어 **처리 내역**으로 만든다.

배포본(`BankOn.exe`)은 `reports/` 아래에 두 종류를 남긴다.

    gui_20260901.log            감시 루프 — 건별 결과 한 줄씩
    full_20260831_161345.log    러너 한 번 실행 — 모드·실패사유

건별 결과 줄이 우리가 원하는 전부다:

    [16:13:45] Send#12290 01-2608-3-2711 [국민] 의뢰 2026-08-26 요청 08-31 15:47
               (왕성진) APW=완료처리(발송)/10 → 실패 exit=1 reports/full_20260831_161345.log

**날짜 다루기** — 줄에는 시각만 있고 날짜가 없다(파일명이 시작일로 고정돼 자정을 넘겨도
같은 파일에 계속 쌓인다). 그래서 파일명 날짜에서 출발해 **시각이 거꾸로 가면 다음 날**로
넘긴다. 실패 줄은 `full_YYYYMMDD_HHMMSS.log` 를 달고 있어 그 값으로 시각을 정확히 잡는다.

여기서는 **읽기만** 한다 — 어디에도 쓰지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

LINE = re.compile(
    r"^\[(?P<time>\d{2}:\d{2}:\d{2})\]\s*"
    r"Send#(?P<seq>\d+)\s+"
    r"(?P<doc>\d{2}-\d{4}-\d-\d{4})\s+"
    r"\[(?P<bank>[^\]]+)\]"
    r"(?:\s*의뢰\s*(?P<order>\d{4}-\d{2}-\d{2}))?"
    r"(?:\s*요청\s*(?P<req>\d{2}-\d{2}\s+\d{2}:\d{2}))?"
    r"(?:\s*\((?P<who>[^)]*)\))?"
    r"(?:\s*APW=(?P<apw>\S+))?"
    r"\s*→\s*(?P<result>.+?)\s*$"
)
CLOCK = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]")
GUI_DATE = re.compile(r"gui_(?P<ymd>\d{8})\.log$", re.I)
FULL_REF = re.compile(r"full_(?P<stamp>\d{8}_\d{6})\.log")
RUN_MODE = re.compile(r"모드=(?P<mode>\S+)")
# `re.M` 이 있어야 `$` 가 **줄 끝**을 뜻한다. 없으면 문자열 끝만 봐서 중간 줄을 못 잡는다.
RUN_ERR = re.compile(r"\[runner\]\s*실패\s*(?P<err>.+?)(?:\s*/\s*\[요약\]|$)", re.M)

# 로그 표현 → 분류. `실행 LIVE` 는 시작 표시일 뿐이라 버린다(None).
# ⚠️ **성공 표현은 아직 실물을 못 봤다** — 로그 구간에 성공이 0건이었다.
#    못 알아본 표현은 `기타` 로 남고 `raw` 에 원문이 그대로 있으니, 실물이 나오면 여기 추가한다.
_RULES = (("실패", "실패"), ("성공", "성공"), ("완료", "성공"), ("등록", "성공"),
          ("제외", "제외"), ("보류", "보류"), ("실행", None))

DONE = ("성공", "실패")        # 실제로 시도한 것
SKIPPED = ("제외", "보류")     # 건드리지 않고 넘긴 것


def classify(raw: str) -> str | None:
    for needle, label in _RULES:
        if raw.startswith(needle):
            return label
    return "기타"


@dataclass(frozen=True)
class Run:
    """처리 한 건."""

    key: str                       # 같은 줄을 두 번 세지 않기 위한 고유값
    at: datetime                   # 처리 시각
    doc_id: str
    bank: str
    result: str                    # 성공 / 실패 / 제외 / 보류 / 기타
    raw: str                       # 로그 원문
    send_seq: int | None = None
    apw_status: str | None = None
    requester: str | None = None
    order_date: date | None = None
    requested_at: datetime | None = None
    mode: str | None = None
    error: str | None = None

    def as_json(self) -> dict:
        data = asdict(self)
        for field in ("at", "requested_at", "order_date"):
            value = data.get(field)
            data[field] = value.isoformat() if value is not None else None
        return data


def _full_details(reports: Path, stamp: str) -> tuple[str | None, str | None]:
    path = reports / f"full_{stamp}.log"
    if not path.exists():
        return None, None
    text = path.read_text(encoding="utf-8", errors="replace")
    mode = RUN_MODE.search(text)
    error = RUN_ERR.search(text)
    return (mode.group("mode") if mode else None,
            error.group("err")[:400] if error else None)


def parse_gui_log(path: Path, reports: Path | None = None) -> list[Run]:
    """gui 로그 하나 → 처리 내역들."""
    stamp = GUI_DATE.search(path.name)
    if not stamp:
        return []
    reports = reports or path.parent
    day = datetime.strptime(stamp.group("ymd"), "%Y%m%d").date()
    previous: str | None = None
    runs: list[Run] = []

    for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        text = line.strip()
        tick = CLOCK.match(text)
        if tick:                                   # 자정 넘김 판정은 모든 시각줄로
            if previous and tick.group(1) < previous:
                day += timedelta(days=1)
            previous = tick.group(1)
        found = LINE.match(text)
        if not found:
            continue
        label = classify(found.group("result"))
        if label is None:
            continue

        raw = found.group("result")
        at = datetime.combine(day, datetime.strptime(found.group("time"), "%H:%M:%S").time())
        mode = error = None
        ref = FULL_REF.search(raw)
        if ref:                                    # 실패 줄 — 정확한 시각을 알 수 있다
            key = f"full_{ref.group('stamp')}.log"
            at = datetime.strptime(ref.group("stamp"), "%Y%m%d_%H%M%S")
            mode, error = _full_details(reports, ref.group("stamp"))
        else:
            key = f"{path.name}:{number}"

        requested = None
        if found.group("req"):
            try:
                requested = datetime.strptime(f"{day.year}-{found.group('req')}",
                                              "%Y-%m-%d %H:%M")
            except ValueError:
                requested = None

        runs.append(Run(
            key=key, at=at, doc_id=found.group("doc"), bank=found.group("bank").strip(),
            result=label, raw=raw[:200], send_seq=int(found.group("seq")),
            apw_status=found.group("apw"), requester=found.group("who") or None,
            order_date=(datetime.strptime(found.group("order"), "%Y-%m-%d").date()
                        if found.group("order") else None),
            requested_at=requested, mode=mode, error=error))
    return runs


def collect(*folders: Path) -> list[Run]:
    """여러 `reports` 폴더를 훑어 시간순 내역으로. 같은 `key` 는 한 번만."""
    unique: dict[str, Run] = {}
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("gui_*.log")):
            for run in parse_gui_log(path, folder):
                unique[run.key] = run
    return sorted(unique.values(), key=lambda run: run.at)


# ── 집계 ────────────────────────────────────────────────────────────────────
# **작성건수 = 성공한 문서 수(중복 제거).** 실행 횟수를 그대로 쓰면 부풀어 보인다 —
# 같은 건을 10분마다 재시도하기 때문이다(실측: 보류 100건이 전부 같은 문서 1건).

def _docs(runs, results, day: date | None = None) -> set[str]:
    return {r.doc_id for r in runs
            if r.result in results and (day is None or r.at.date() == day)}


def _count(runs, results, day: date | None = None) -> int:
    return sum(1 for r in runs
               if r.result in results and (day is None or r.at.date() == day))


def summary(runs: list[Run], today: date | None = None) -> dict:
    today = today or date.today()
    return {
        "총작성건수": len(_docs(runs, ("성공",))),
        "금일작성건수": len(_docs(runs, ("성공",), today)),
        "총시도": _count(runs, DONE),
        "총성공": _count(runs, ("성공",)),
        "총실패": _count(runs, ("실패",)),
        "총실패문서": len(_docs(runs, ("실패",))),
        "총스킵": _count(runs, SKIPPED),
        "총문서수": len({r.doc_id for r in runs}),
        "금일시도": _count(runs, DONE, today),
        "금일성공": _count(runs, ("성공",), today),
        "금일실패": _count(runs, ("실패",), today),
        "최종처리시각": max((r.at for r in runs), default=None) and
                        max(r.at for r in runs).isoformat(),
        "기준일": today.isoformat(),
    }


def by_bank(runs: list[Run], today: date | None = None) -> list[dict]:
    today = today or date.today()
    banks = sorted({r.bank for r in runs})
    rows = []
    for bank in banks:
        mine = [r for r in runs if r.bank == bank]
        rows.append({
            "은행": bank,
            "총작성건수": len(_docs(mine, ("성공",))),
            "금일작성건수": len(_docs(mine, ("성공",), today)),
            "총시도": _count(mine, DONE),
            "총실패": _count(mine, ("실패",)),
            "총스킵": _count(mine, SKIPPED),
            "총문서수": len({r.doc_id for r in mine}),
            "최종처리시각": max(r.at for r in mine).isoformat(),
        })
    return rows


def daily(runs: list[Run], days: int = 30) -> list[dict]:
    """일자별 × 은행별. 최근 `days` 일."""
    if not runs:
        return []
    cutoff = max(r.at.date() for r in runs) - timedelta(days=days - 1)
    seen: dict[tuple[date, str], list[Run]] = {}
    for run in runs:
        if run.at.date() >= cutoff:
            seen.setdefault((run.at.date(), run.bank), []).append(run)
    rows = []
    for (day, bank), mine in sorted(seen.items()):
        rows.append({
            "처리일자": day.isoformat(), "은행": bank,
            "작성건수": len(_docs(mine, ("성공",))),
            "시도": _count(mine, DONE),
            "성공": _count(mine, ("성공",)),
            "실패": _count(mine, ("실패",)),
            "스킵": _count(mine, SKIPPED),
            "문서수": len({r.doc_id for r in mine}),
        })
    return rows
