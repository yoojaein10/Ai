# -*- coding: utf-8 -*-
"""파서 공통 기반.

- PDF 텍스트 추출(좌표 재구성). 가능하면 worker process 로 격리(S11).
- 페이지/텍스트 길이 제한 적용(S6). 암호화/손상 PDF 는 건별 예외.
- 은행 판별(헤더 기준). PDF 제목으로 탁상/담보를 판별하지 않는다.
- 공통 파싱 헬퍼 (라인 분리, 날짜 파싱 등).

주의: 강제하지 못한 메모리 제한을 구현했다고 주장하지 않는다. worker 는 페이지/문자
수 상한과 타임아웃, 시크릿 미전달만 보장한다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unicodedata

# base.py 가 worker(__main__)로 직접 실행될 때도 동작하도록 경로 보정.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import security  # noqa: E402


class PdfExtractError(Exception):
    """PDF 추출 실패 (암호화/손상/제한 초과 등). 건별 처리."""


# ───────────────────────────── 추출 ─────────────────────────────
def _reconstruct_lines_from_doc(doc) -> list[str]:
    """fitz Document → 좌표 재구성 라인. 페이지/문자 상한 적용."""
    if doc.page_count > security.MAX_PDF_PAGES:
        raise PdfExtractError(f"페이지 수 초과: {doc.page_count} > {security.MAX_PDF_PAGES}")

    out_lines: list[str] = []
    total_chars = 0
    for page in doc:
        words = page.get_text("words")
        if not words:
            continue
        words.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
        groups: dict[int, list] = {}
        for w in words:
            groups.setdefault(round(w[1] / 3.0), []).append(w)
        for key in sorted(groups):
            ws = sorted(groups[key], key=lambda w: w[0])
            s, prev = "", None
            for w in ws:
                x0, x1, txt = w[0], w[2], w[4]
                cw = (x1 - x0) / max(len(txt), 1)
                if prev is None:
                    s = txt
                else:
                    nsp = max(1, int(round((x0 - prev) / max(cw, 3.0))))
                    s += " " * nsp + txt
                prev = x1
            out_lines.append(s)
            total_chars += len(s)
            if total_chars > security.MAX_EXTRACT_CHARS:
                raise PdfExtractError("추출 텍스트 길이 초과")
    return out_lines


def extract_lines_inproc(path: str) -> list[str]:
    """동일 프로세스에서 추출. 암호화/손상 시 PdfExtractError."""
    try:
        import fitz  # PyMuPDF
    except Exception as e:  # pragma: no cover
        raise PdfExtractError(f"PyMuPDF 미설치: {e}")

    try:
        doc = fitz.open(path)
    except Exception as e:
        raise PdfExtractError(f"PDF 열기 실패(손상 가능): {e}")
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise PdfExtractError("암호화된 PDF")
        return _reconstruct_lines_from_doc(doc)
    finally:
        doc.close()


def extract_lines(path: str, *, allowed_roots: list[str] | None = None,
                  use_worker: bool = True, timeout: float = 30.0) -> list[str]:
    """안전 검증 후 라인 추출. 기본은 worker process 격리.

    worker 실패/타임아웃은 PdfExtractError 로 격리되어 배치 전체를 중단시키지 않는다.
    """
    security.validate_pdf_file(path, allowed_roots=allowed_roots)

    if not use_worker:
        return extract_lines_inproc(path)

    # worker process: 시크릿을 전달하지 않는 최소 환경.
    env = {
        "SystemRoot": os.environ.get("SystemRoot", ""),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": _ROOT,
    }
    try:
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--extract", path],
            capture_output=True, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        raise PdfExtractError("PDF worker 타임아웃")
    if proc.returncode != 0:
        # stderr 는 마스킹 후 짧게만.
        err = security.mask_traceback(proc.stderr.decode("utf-8", "ignore"))[:200]
        raise PdfExtractError(f"PDF worker 실패: {err}")
    try:
        data = json.loads(proc.stdout.decode("utf-8", "ignore"))
    except Exception as e:
        raise PdfExtractError(f"worker 출력 파싱 실패: {e}")
    if data.get("error"):
        raise PdfExtractError(data["error"])
    return list(data.get("lines", []))


# ───────────────────────────── 은행 판별 ─────────────────────────────
# PDF 헤더 은행 판별만 담당. Bank24 출처/탁상 판별과 분리(S 탁상판별).
_BANK_RULES = [
    ("우리은행", ("우리은행",)),
    ("국민은행", ("국민은행", "KB국민")),
    ("새마을금고", ("새마을금고", "MG새마을")),
    ("기업은행", ("중소기업은행", "기업은행", "IBK")),
    ("하나은행", ("KEB하나은행", "하나은행")),
    ("신한은행", ("신한은행",)),
    ("아이엠뱅크", ("iM뱅크", "IM뱅크", "iM은행", "아이엠뱅크")),
    ("농협중앙회", ("농협중앙회",)),
    ("산림조합중앙회", ("산림조합중앙회",)),
    ("농협은행", ("농협은행", "농협",)),
    ("수협은행", ("수협은행", "수산업협동조합", "수협")),
    ("한국투자저축은행", ("한국투자저축은행",)),
]


def detect_bank(lines: list[str]) -> str:
    """헤더(상단 라인)에서 은행명을 판별. 미상이면 ''."""
    head = re.sub(r"\s+", "", "\n".join(lines[:6]))
    for name, needles in _BANK_RULES:
        if any(n.replace(" ", "") in head for n in needles):
            return name
    return ""


# ───────────────────────────── 의뢰기관 제외 판정 ─────────────────────────────
# 저장 제외 대상 의뢰기관(정확 일치만). 부분 포함/유사 명칭은 제외하지 않는다.
EXCLUDED_AGENCY = "주택도시보증공사"

# '의뢰기관' 라벨(추출 과정에서 자간 공백이 낄 수 있어 내부 공백 허용).
_AGENCY_LABEL_RE = re.compile(r"의\s*뢰\s*기\s*관\s*[:：]?")
# 같은 행에 병렬 배치되는 후속 라벨 = 의뢰기관 값 셀의 오른쪽 경계.
_AGENCY_VALUE_END_RE = re.compile(
    r"의\s*뢰\s*번\s*호|자\s*문\s*번\s*호|감\s*정\s*(?:서|평가)?\s*번\s*호|"
    r"접\s*수\s*번\s*호|의\s*뢰\s*일"
)


def _normalize_agency(s: str) -> str:
    """Unicode NFKC 정규화 + 앞뒤 공백 제거 + 연속 공백 축소(§4)."""
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", " ", s).strip()


def collect_agency_values(lines: list[str]) -> list[str]:
    """각 라인의 '의뢰기관' 라벨에 대응하는 값 셀만 추출해 정규화 값으로 반환(§2).

    문서 전체 키워드 검색을 하지 않는다. 라벨 뒤부터 다음 라벨(의뢰번호 등)
    직전까지가 값 셀이다. 라벨이 없는 라인은 건너뛴다.
    """
    values: list[str] = []
    for ln in lines:
        m = _AGENCY_LABEL_RE.search(ln)
        if not m:
            continue
        tail = ln[m.end():]
        end = _AGENCY_VALUE_END_RE.search(tail)
        cell = tail[:end.start()] if end else tail
        values.append(_normalize_agency(cell))
    return values


def requesting_agency_excluded(lines: list[str]) -> bool:
    """의뢰기관 값이 정확히 '주택도시보증공사'일 때만 True(§4-6).

    - 라벨 미발견 또는 값 셀이 비어 있음 → False(제외 아님, 기존 흐름).
    - 서로 다른 비어있지 않은 값이 복수(라벨-값 대응 모호) → False(제외 아님).
    - 비어있지 않은 값이 정확히 하나이고 EXCLUDED_AGENCY 와 일치 → True.
    부분 문자열 포함·유사 명칭·다른 필드 문구만으로는 제외하지 않는다.
    """
    nonempty = [v for v in collect_agency_values(lines) if v]
    distinct = set(nonempty)
    return len(distinct) == 1 and next(iter(distinct)) == EXCLUDED_AGENCY


# ───────────────────────────── 파싱 헬퍼 ─────────────────────────────
def nospace(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip() if s else ""


def split_two(value_part: str, second_label: str) -> tuple[str, str]:
    """value_part 안에 second_label 이 있으면 (앞, 뒤)로 분리."""
    if second_label and second_label in value_part:
        a, b = value_part.split(second_label, 1)
        return clean(a), clean(b)
    return clean(value_part), ""


_SIDO_RE = re.compile(
    r"(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충청|충북|충남|"
    r"전라|전북|전남|경상|경북|경남|제주)"
)
_CONT_RE = re.compile(r"(제?\s*\d+\s*층|제?\s*\d+\s*호)")


def find_addresses(lines: list[str], start: int = 0) -> list[str]:
    """region(lines[start:])에서 시도 토큰으로 시작하는 주소 라인을 찾아 반환.

    라벨 열(물건/정보/주소/세부주소)이 값과 다른 y-그룹으로 분리된 PDF 에 대응한다.
    주소 라인 직후 1~3줄 내에 층/호 연속 정보가 있으면 결합한다.
    """
    region = lines[start:]
    addrs: list[str] = []
    used = set()
    for i, ln in enumerate(region):
        if i in used:
            continue
        m = _SIDO_RE.search(ln)
        if not m or not re.search(r"\d", ln):
            continue
        addr = clean(ln[m.start():])
        for j in range(i + 1, min(i + 4, len(region))):
            cm = _CONT_RE.search(region[j])
            if cm and _SIDO_RE.search(region[j]) is None:
                addr += " " + clean(region[j][cm.start():])
                used.add(j)
                break
        addrs.append(addr)
    return addrs


_DATETIME_RE = re.compile(
    r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})"
    r"(?:\s+(오전|오후)?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?)?"
)
_DATE_COMPACT_RE = re.compile(r"(\d{4})(\d{2})(\d{2})")


def parse_datetime(s: str) -> tuple[str, bool]:
    """의뢰일시 파싱 → (정규화 문자열, date_only).

    - '2026-06-29 오후 3:17:00' → ('2026-06-29 15:17:00', False)
    - '2026-06-29'             → ('2026-06-29', True)
    - '20260629'              → ('2026-06-29', True)
    임의 시간 생성 금지. 시간이 없으면 date_only=True.
    """
    if not s:
        return "", True
    m = _DATETIME_RE.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        date_str = f"{y:04d}-{mo:02d}-{d:02d}"
        if m.group(5) is None:
            return date_str, True
        hh = int(m.group(5))
        mm = int(m.group(6))
        ss = int(m.group(7)) if m.group(7) else 0
        ampm = m.group(4)
        if ampm == "오후" and hh < 12:
            hh += 12
        elif ampm == "오전" and hh == 12:
            hh = 0
        if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
            return date_str, True
        return f"{date_str} {hh:02d}:{mm:02d}:{ss:02d}", False
    m = _DATE_COMPACT_RE.search(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", True
    return clean(s), True


# ───────────────────────────── worker 진입점 ─────────────────────────────
def _worker_main(argv: list[str]) -> int:
    """--extract <path>: 라인만 JSON 으로 stdout 출력. 허용 모델 필드만 반환."""
    if len(argv) >= 3 and argv[1] == "--extract":
        path = argv[2]
        try:
            lines = extract_lines_inproc(path)
            sys.stdout.write(json.dumps({"lines": lines}, ensure_ascii=False))
            return 0
        except Exception as e:
            sys.stdout.write(json.dumps({"error": f"{type(e).__name__}: {e}"},
                                        ensure_ascii=False))
            return 0
    sys.stderr.write("usage: base.py --extract <path>\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(_worker_main(sys.argv))
