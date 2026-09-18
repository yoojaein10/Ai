# -*- coding: utf-8 -*-
"""보안 유틸리티: 마스킹(S4), 경로/PDF 안전 검증(S6), 시크릿 검출(S15).

이 모듈은 외부 네트워크/DB/Bank24 를 호출하지 않는다. 순수 함수 위주.
PII·시크릿·접속문자열을 절대 원문으로 반환/로깅하지 않는다.
"""
from __future__ import annotations

import os
import re
import unicodedata

# ───────────────────────────── 상수/제한 (S6) ─────────────────────────────
MAX_PDF_BYTES = 50 * 1024 * 1024        # 50MB
MAX_PDF_PAGES = 100
MAX_EXTRACT_CHARS = 5 * 1024 * 1024     # 5MB 추출 텍스트
PDF_MAGIC = b"%PDF-"

# Windows 예약 장치명
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# ───────────────────────────── 마스킹 (S4) ─────────────────────────────
# 접속문자열/시크릿 키워드: DRIVER+SERVER 동시 등장 시 전체 차단
_CONN_BLOCK_RE = re.compile(r"DRIVER\s*=", re.IGNORECASE)
_CONN_SERVER_RE = re.compile(r"SERVER\s*=", re.IGNORECASE)
_SECRET_KV_RE = re.compile(
    r"(?i)\b(PWD|PASSWORD|PASSWD|UID|USER\s*ID|AUTHORIZATION|TOKEN|BEARER)\b"
    r"\s*[:=]\s*([^;,\s]+)"
)


def mask_connection_string(text: str) -> str:
    """접속문자열/시크릿 KV 를 마스킹. DRIVER+SERVER 동시 등장 시 전체 차단."""
    if not text:
        return text or ""
    if _CONN_BLOCK_RE.search(text) and _CONN_SERVER_RE.search(text):
        return "[BLOCKED connection-string]"
    return _SECRET_KV_RE.sub(lambda m: f"{m.group(1)}=***", text)


def mask_name(name: str) -> str:
    """이름 가운데 글자 마스킹. 김나윤 -> 김*윤, 홍길 -> 홍*."""
    s = (name or "").strip()
    if not s:
        return ""
    if len(s) == 1:
        return "*"
    if len(s) == 2:
        return s[0] + "*"
    return s[0] + "*" * (len(s) - 2) + s[-1]


def mask_phone(phone: str) -> str:
    """전화번호 마지막 4자리만 표시. 나머지 숫자는 *."""
    s = phone or ""
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]


_ADDR_DETAIL_RE = re.compile(
    r"((?:산\s*)?\d{1,5})(?:\s*-\s*\d{1,5})?"   # 지번 본번-부번
    r"|(\d{1,4})\s*(?:호|동|층)"                 # 호/동/층
)


def mask_address(addr: str) -> str:
    """주소의 상세 번지·동·호 마스킹. 행정구역/법정동은 유지."""
    s = addr or ""
    if not s:
        return ""
    return _ADDR_DETAIL_RE.sub("**", s)


def mask_request_no(no: str) -> str:
    """의뢰번호 마스킹: 앞 2 + *** + 뒤 2."""
    s = (no or "").strip()
    if len(s) <= 4:
        return "*" * len(s)
    return s[:2] + "*" * (len(s) - 4) + s[-2:]


def mask_traceback(tb_text: str) -> str:
    """traceback 문자열에서 접속문자열/시크릿 KV 마스킹 후 반환."""
    return mask_connection_string(tb_text or "")


# ───────────────────────────── 파일명 정화 (S6) ─────────────────────────────
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_PATH_SEP_RE = re.compile(r"[\\/]+")
_BAD_CHARS_RE = re.compile(r'[<>:"|?*]')


def sanitize_filename(name: str) -> str:
    """파일명 allowlist 정화: 경로구분자/제어문자/예약장치명/후행점·공백 제거.

    실패(빈 결과)면 ValueError.
    """
    s = unicodedata.normalize("NFC", name or "")
    s = _CTRL_RE.sub("", s)
    s = s.replace("..", "")
    s = _PATH_SEP_RE.sub("_", s)
    s = _BAD_CHARS_RE.sub("_", s)
    s = s.rstrip(" .")
    s = s.strip()
    if not s:
        raise ValueError("파일명이 정화 후 비어 있음")
    stem = s.split(".")[0].upper()
    if stem in _RESERVED_NAMES:
        s = "_" + s
    if len(s) > 200:
        raise ValueError("파일명이 너무 김")
    return s


# ───────────────────────────── 경로 안전 (S6/S17) ─────────────────────────────
def is_within_root(path: str, root: str) -> bool:
    """resolve 된 path 가 root 내부인지. symlink/junction/reparse 탈출 거부.

    os.path.realpath 로 reparse point 를 해소한 뒤 commonpath 로 검증한다.
    """
    try:
        # Windows UNC + 한글 공유명은 realpath()가 경로를 손상시키는 경우가 있어
        # UNC끼리는 절대경로 정규화로 비교한다.
        if os.name == "nt" and str(path).startswith("\\\\") and str(root).startswith("\\\\"):
            real_path = os.path.normcase(os.path.abspath(path))
            real_root = os.path.normcase(os.path.abspath(root))
        else:
            real_path = os.path.realpath(path)
            real_root = os.path.realpath(root)
    except (OSError, ValueError):
        return False
    try:
        return os.path.normcase(os.path.commonpath([real_path, real_root])) == os.path.normcase(real_root)
    except ValueError:
        # 다른 드라이브 등
        return False


def safe_join_under_root(root: str, filename: str) -> str:
    """root 아래 정화된 파일명으로 안전 경로 생성 후 재검증. 탈출 시 ValueError."""
    safe_name = sanitize_filename(filename)
    candidate = os.path.join(root, safe_name)
    if not is_within_root(candidate, root):
        raise ValueError("경로가 허용 루트를 벗어남")
    return candidate


# ───────────────────────────── PDF 안전 검증 (S6) ─────────────────────────────
class PdfSafetyError(Exception):
    """PDF 안전 검증 실패."""


def validate_pdf_file(path: str, *, allowed_roots: list[str] | None = None) -> None:
    """PDF 파일 안전성 검증. 위반 시 PdfSafetyError.

    - 허용 루트 내부 여부 (allowed_roots 지정 시)
    - 확장자 .pdf
    - %PDF- magic header
    - 크기 <= 50MB
    (페이지 수/텍스트 길이는 추출 단계에서 별도 검증.)
    """
    if not os.path.isfile(path):
        raise PdfSafetyError("파일이 존재하지 않음")

    if allowed_roots:
        if not any(is_within_root(path, r) for r in allowed_roots):
            raise PdfSafetyError("허용된 PDF 루트 밖의 경로")

    if os.path.splitext(path)[1].lower() != ".pdf":
        raise PdfSafetyError("확장자가 .pdf 가 아님")

    size = os.path.getsize(path)
    if size > MAX_PDF_BYTES:
        raise PdfSafetyError(f"PDF 크기 초과: {size} > {MAX_PDF_BYTES}")
    if size == 0:
        raise PdfSafetyError("빈 파일")

    with open(path, "rb") as f:
        head = f.read(len(PDF_MAGIC))
    if head != PDF_MAGIC:
        raise PdfSafetyError("PDF magic header 불일치")


# ───────────────────────────── 시크릿 검출 (S15) ─────────────────────────────
# 변수명/placeholder 와 실제 값을 구분하기 위한 휴리스틱.
_PLACEHOLDER_TOKENS = frozenset({
    "your", "placeholder", "example", "changeme", "xxx", "todo", "none",
    "null", "", "***", "<password>", "<secret>", "dummy", "fake", "test",
    "youR_db_server_host".lower(), "your_db_name", "your_db_server_host",
})

_SECRET_PATTERNS = [
    ("password_kv", re.compile(r"(?i)\b(password|passwd|pwd)\b\s*[:=]\s*([^\s;,#]+)")),
    ("uid_kv", re.compile(r"(?i)\b(uid|user\s*id)\b\s*[:=]\s*([^\s;,#]+)")),
    ("conn_str", re.compile(r"(?i)driver\s*=\s*\{?[^}]*\}?.*server\s*=")),
    ("authorization", re.compile(r"(?i)\b(authorization|bearer|token)\b\s*[:=]\s*([^\s;,#]+)")),
    ("ip_account", re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b.*\b(uid|user|pwd|password)\b", re.IGNORECASE)),
]


def _looks_like_placeholder(value: str) -> bool:
    v = (value or "").strip().strip("\"'").lower()
    if v in _PLACEHOLDER_TOKENS:
        return True
    if v.startswith("your_") or v.startswith("<") or v.startswith("${") or v.startswith("%"):
        return True
    if re.fullmatch(r"[\*x]+", v):
        return True
    return False


def scan_text_for_secrets(text: str) -> list[dict]:
    """텍스트에서 잠재 시크릿을 검출. 값은 반환하지 않고 종류/위치만.

    반환: [{"kind", "line", "is_value": bool}] — is_value=True 면 실제 값 의심.
    """
    findings = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for kind, pat in _SECRET_PATTERNS:
            m = pat.search(line)
            if not m:
                continue
            value = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
            is_value = bool(value) and not _looks_like_placeholder(value)
            if kind in ("conn_str", "ip_account"):
                is_value = True
            findings.append({"kind": kind, "line": lineno, "is_value": is_value})
    return findings
