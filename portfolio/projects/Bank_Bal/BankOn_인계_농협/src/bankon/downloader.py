"""FTP 다운로드 + zlib 해제.

원격 파일(`/Gam/<path>`)은 경로명이 `.pdf`/`.gam` 이라도 **내용은 표준 zlib
압축본**이다(원천 dxZCompress). RETR 로 받아 zlib 로 해제한다.
"""
from __future__ import annotations

import io
import zlib
from contextlib import contextmanager
from pathlib import Path

import ftplib

from .config import FtpConfig


class DownloadError(Exception):
    """다운로드/해제 실패."""


class ConnectionLost(DownloadError):
    """세션/연결 수준 실패(10053, EOF, 4xx 등) — 새 세션으로 재시도 가치가 있다.

    550 같은 영구 오류(error_perm)는 문서 수준 실패라 여기 포함하지 않는다.
    """


def _open_ftp(cfg: FtpConfig, timeout: int) -> ftplib.FTP:
    ftp = ftplib.FTP()
    try:
        ftp.connect(cfg.host, 21, timeout=timeout)
        ftp.login(cfg.user, cfg.password)
        ftp.set_pasv(cfg.passive)
        ftp.voidcmd("TYPE I")
        return ftp
    except ftplib.all_errors as error:
        raise DownloadError(f"FTP 세션 실패({cfg.host}): {error}") from error


def _close_quietly(ftp: ftplib.FTP) -> None:
    try:
        ftp.quit()
    except Exception:  # noqa: BLE001 - 종료 실패는 무시
        try:
            ftp.close()
        except Exception:  # noqa: BLE001
            pass


@contextmanager
def ftp_session(cfg: FtpConfig, *, timeout: int = 30):
    """설정으로 FTP 세션을 열고 종료 시 닫는다."""
    ftp = _open_ftp(cfg, timeout)
    try:
        yield ftp
    finally:
        _close_quietly(ftp)


class FtpHandle:
    """재접속 가능한 FTP 세션 홀더.

    장시간 배치 중 세션이 죽으면(ConnectionLost) reconnect() 로 새 세션으로
    갈아끼운다. 사용처는 항상 .ftp 속성으로 현재 세션에 접근해야 한다.
    """

    def __init__(self, cfg: FtpConfig, *, timeout: int = 30):
        self._cfg = cfg
        self._timeout = timeout
        self.ftp = _open_ftp(cfg, timeout)

    def reconnect(self) -> None:
        _close_quietly(self.ftp)
        self.ftp = _open_ftp(self._cfg, self._timeout)

    def close(self) -> None:
        _close_quietly(self.ftp)


@contextmanager
def ftp_handle(cfg: FtpConfig, *, timeout: int = 30):
    """재접속 가능한 FtpHandle 을 열고 종료 시 닫는다."""
    handle = FtpHandle(cfg, timeout=timeout)
    try:
        yield handle
    finally:
        handle.close()


def fetch_compressed(ftp: ftplib.FTP, remote_path: str) -> bytes:
    """원격 파일을 메모리로 받는다(압축 상태 그대로)."""
    buffer = io.BytesIO()
    try:
        ftp.retrbinary(f"RETR {remote_path}", buffer.write)
    except ftplib.error_perm as error:
        # 550 등 영구 오류 = 문서 수준 실패(재접속 무익).
        raise DownloadError(f"RETR 실패({remote_path}): {error}") from error
    except ftplib.all_errors as error:
        # OSError(10053)/EOFError/4xx 등 = 연결 수준 실패 → 재접속 재시도 대상.
        raise ConnectionLost(f"RETR 실패({remote_path}): {error}") from error
    return buffer.getvalue()


_ZLIB_MAGICS = (b"\x78\x01", b"\x78\x9c", b"\x78\xda")


def _magic_offsets(blob: bytes, start: int):
    """start 이후의 zlib 매직 후보 오프셋(오름차순)."""
    offsets = []
    for magic in _ZLIB_MAGICS:
        idx = blob.find(magic, start)
        while idx >= 0:
            offsets.append(idx)
            idx = blob.find(magic, idx + 1)
    return sorted(offsets)


def _salvage_appended_stream(blob: bytes) -> bytes | None:
    """손상 스트림 뒤에 이어붙은 완전한 zlib 스트림을 찾아 해제한다.

    실사례(02-2604-3-0450): 원격 파일 = 잘린 1차 업로드 찌꺼기 + 완전한 재업로드
    스트림. 파일 끝에서 정확히 끝나는(eof 도달·잔여 없음) 스트림만 채택한다.
    """
    for off in _magic_offsets(blob, start=1):
        d = zlib.decompressobj()
        try:
            out = d.decompress(blob[off:])
        except zlib.error:
            continue
        if d.eof and not d.unused_data and out:
            return out
    return None


def decompress(blob: bytes) -> bytes:
    """zlib 해제. 이미 비압축(매직 확인)이면 그대로 반환.

    스트림이 손상됐어도 뒤에 완전한 재업로드 스트림이 이어붙어 있으면 그것을 채택한다.
    """
    if blob[:1] == b"\x78":  # zlib 헤더(78 01/9c/da)
        try:
            return zlib.decompress(blob)
        except zlib.error as error:
            salvaged = _salvage_appended_stream(blob)
            if salvaged is not None:
                return salvaged
            raise DownloadError(f"zlib 해제 실패: {error}") from error
    return blob


def download_to(ftp: ftplib.FTP, remote_path: str, dest: str | Path) -> Path:
    """원격 파일을 받아 해제한 뒤 dest 에 저장한다. 저장 경로 반환."""
    data = decompress(fetch_compressed(ftp, remote_path))
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(data)
    return dest_path
