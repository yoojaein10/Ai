# -*- coding: utf-8 -*-
"""PDF 안전 다운로드·저장 (지시 §5).

- 파일명은 UUID+타임스탬프. 고객명/주소/의뢰번호/Content-Disposition 미사용.
- 확장자 .pdf 코드 고정. 구성된 PDF 루트 내부에만 저장.
- 루트 자체와 모든 상위 구성요소의 symlink/junction/reparse 검사(문자열 포함검사만으론 판단 안 함).
- 임시파일 exclusive-create, 기존 파일 미덮어씀. flush/fsync/close 후 크기·PDF magic 검사.
- 성공 시에만 같은 볼륨 원자적 rename. 실패·중지·timeout 시 현재 작업이 만든 부분 파일만 정리.
- 기존 PDF 자동삭제 금지. 전체 경로·파일명 로그 금지(호출부 책임).
"""
from __future__ import annotations

import os
import uuid

import security

_PDF_EXT = ".pdf"


class PdfDownloadError(Exception):
    """PDF 다운로드/저장 안전 검증 실패."""


def generate_filename(timestamp: str) -> str:
    """UUID+타임스탬프 기반 결정적 안전 파일명. PII 미포함."""
    ts = "".join(c for c in (timestamp or "") if c.isalnum())
    return f"{uuid.uuid4().hex}_{ts}{_PDF_EXT}"


def _has_reparse_point(path: str) -> bool:
    """경로가 symlink/junction/reparse point 인지. Windows 속성 비트로 검사."""
    if os.path.islink(path):
        return True
    if os.name == "nt":
        try:
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs == -1:
                return False
            FILE_ATTRIBUTE_REPARSE_POINT = 0x400
            return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
        except Exception:
            return False
    return False


def assert_safe_root(pdf_root: str) -> str:
    """PDF 루트와 모든 상위 구성요소가 reparse 없는 실제 디렉터리인지 검증.

    실패 시 PdfDownloadError. 반환: realpath.
    """
    if not pdf_root:
        raise PdfDownloadError("PDF 루트 미구성")
    real = os.path.realpath(pdf_root)
    if not os.path.isdir(real):
        raise PdfDownloadError("PDF 루트가 디렉터리가 아님")
    # 루트부터 드라이브까지 모든 구성요소의 reparse 검사
    cur = real
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        if _has_reparse_point(cur):
            raise PdfDownloadError("경로에 symlink/junction/reparse 포함")
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return real


def save_pdf_bytes(data: bytes, pdf_root: str, *, timestamp: str,
                   stop_check=None) -> str:
    """검증된 PDF 바이트를 안전하게 저장하고 최종 경로 반환.

    exclusive-create 임시파일 → flush/fsync → 크기·magic 검사 → 원자적 rename.
    실패/중지 시 이 함수가 만든 부분 파일만 정리한다. 기존 파일은 건드리지 않는다.
    """
    real_root = assert_safe_root(pdf_root)
    if stop_check is not None and stop_check():
        raise PdfDownloadError("중지 요청됨")

    if not data or data[:len(security.PDF_MAGIC)] != security.PDF_MAGIC:
        raise PdfDownloadError("PDF magic 불일치")
    if len(data) > security.MAX_PDF_BYTES:
        raise PdfDownloadError("PDF 크기 초과")
    if len(data) == 0:
        raise PdfDownloadError("빈 파일")

    final_name = generate_filename(timestamp)
    tmp_name = final_name + ".part"
    final_path = os.path.join(real_root, final_name)
    tmp_path = os.path.join(real_root, tmp_name)

    # 최종 경로가 루트 내부인지 재검증(문자열 포함검사만 의존하지 않음)
    if not security.is_within_root(final_path, real_root):
        raise PdfDownloadError("최종 경로가 루트를 벗어남")

    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd = None
    created = False
    try:
        fd = os.open(tmp_path, flags, 0o600)   # exclusive-create, 기존 파일 있으면 실패
        created = True
        with os.fdopen(fd, "wb") as f:
            fd = None
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # close 후 크기·magic 재검사
        size = os.path.getsize(tmp_path)
        if size != len(data):
            raise PdfDownloadError("기록 크기 불일치")
        with open(tmp_path, "rb") as rf:
            head = rf.read(len(security.PDF_MAGIC))
        if head != security.PDF_MAGIC:
            raise PdfDownloadError("저장 후 magic 불일치")
        if os.path.exists(final_path):
            raise PdfDownloadError("최종 파일이 이미 존재(덮어쓰기 금지)")
        # 같은 볼륨 원자적 rename (대상 존재 시 Windows 에서 실패 → 덮어쓰기 없음)
        os.rename(tmp_path, final_path)
        created = False
        return final_path
    except Exception:
        # 이 함수가 만든 부분 파일만 정리
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        if created:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
        raise
