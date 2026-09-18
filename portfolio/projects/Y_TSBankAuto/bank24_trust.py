# -*- coding: utf-8 -*-
"""Bank24 바이너리 신뢰 검증 (지시 §22–§33).

real 자동화는 "신뢰된 Bank24 바이너리"에서만 허용한다. 신뢰 기준:
- 실행 경로는 INI/환경변수/PATH 에서 받지 않는다. 코드 내 단일 승인 절대경로만 사용한다.
- 실행/조작 전에 경로 정규화, reparse 여부, 소유권, 사용자 쓰기 가능 여부를 검사한다.
- Authenticode 유효 서명 + 승인 게시자, 또는 사전 승인된 SHA-256 을 검증한다.
- PID 의 실제 이미지 경로를 승인 절대경로와 정확히 비교한다.
- 승인 게시자/해시를 임의로 생성·등록하지 않는다. 기준이 없으면 real 을 차단하고
  사용자에게 등록을 요청한다(fail-closed).

이 모듈은 자격증명을 다루지 않으며, 자식 프로세스의 명령행/환경변수로 어떤 값도
전달하지 않는다. shell=True 및 문자열 조립 명령을 사용하지 않는다.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

import settings_integrity as _si

# ─────────────────────────── 승인 기준(빈 값 = fail-closed) ───────────────────────────
# 단일 승인 절대경로. 비어 있으면 real 차단(PATH_NOT_CONFIGURED).
# INI/환경변수/PATH 에서 받지 않는다. 등록은 사용자 승인 절차로만 한다(§26/§27).
APPROVED_BANK24_EXE: str = ""

# Authenticode 서명자 subject CN allowlist. 비어 있으면 게시자 검증 불가(fail-closed).
APPROVED_PUBLISHERS: frozenset = frozenset()

# 사전 승인된 SHA-256(소문자 hex) allowlist. 비어 있으면 해시 검증 불가(fail-closed).
APPROVED_SHA256: frozenset = frozenset()

# 승인된 Bank24 창 클래스. 비어 있으면 창 신뢰 불가(fail-closed).
APPROVED_WINDOW_CLASSES: frozenset = frozenset()

_HASH_CHUNK = 1024 * 1024


# ─────────────────────────── 고정 오류 코드 ───────────────────────────
class TrustError(Exception):
    """신뢰 검증 실패. 고정 코드만 담는다(원문/경로/PII 미포함)."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


# codes:
# PATH_NOT_CONFIGURED PATH_NOT_ABSOLUTE PATH_NOT_FOUND PATH_REPARSE
# PATH_OWNER_UNTRUSTED PATH_USER_WRITABLE PATH_MISMATCH PATH_UNVERIFIABLE
# NO_TRUST_BASELINE HASH_MISMATCH SIG_UNAVAILABLE SIG_INVALID SIG_PUBLISHER_UNTRUSTED
# PID_IMAGE_UNAVAILABLE PID_IMAGE_MISMATCH WINDOW_UNTRUSTED


@dataclass
class TrustResult:
    method: str          # "sha256" | "authenticode"
    exe_norm: str        # 정규화된 승인 절대경로
    install_dir: str     # 실행 작업 디렉터리(승인 EXE 폴더)


# ─────────────────────────── 경로 정규화/승인 ───────────────────────────
def _normcase(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def approved_exe_norm(path: str | None = None) -> str:
    """승인 절대경로를 정규화해 반환. 미설정/상대경로면 TrustError."""
    raw = APPROVED_BANK24_EXE if path is None else path
    if not raw:
        raise TrustError("PATH_NOT_CONFIGURED")
    if not os.path.isabs(raw):
        raise TrustError("PATH_NOT_ABSOLUTE")
    return _normcase(raw)


# ─────────────────────────── 바이너리 파일 검증 (§24) ───────────────────────────
EXE_BASENAME = "bank24.exe"   # 대소문자 무시 비교(§19)


def signature_state(path: str) -> str:
    """Authenticode 서명 상태: "none"|"valid"|"invalid"|"unknown".

    WinVerifyTrust 로 판정한다. 서명이 없으면 "none"(허용), 있으나 무효면 "invalid"(차단, §23).
    확인 불가(비-Windows/미설치)면 "unknown"(허용 — 다른 신뢰검사로 보완).
    """
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return "unknown"
    try:
        WTD_UI_NONE, WTD_REVOKE_NONE, WTD_CHOICE_FILE = 2, 0, 1
        WTD_STATEACTION_VERIFY, WTD_STATEACTION_CLOSE = 1, 2
        TRUST_E_NOSIGNATURE = ctypes.c_long(0x800B0100).value
        TRUST_E_SUBJECT_FORM_UNKNOWN = ctypes.c_long(0x800B0003).value
        TRUST_E_PROVIDER_UNKNOWN = ctypes.c_long(0x800B0001).value

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        class WFI(ctypes.Structure):
            _fields_ = [("cbStruct", wintypes.DWORD), ("pcwszFilePath", wintypes.LPCWSTR),
                        ("hFile", wintypes.HANDLE), ("pgKnownSubject", ctypes.c_void_p)]

        class WTD(ctypes.Structure):
            _fields_ = [("cbStruct", wintypes.DWORD), ("pPolicyCallbackData", ctypes.c_void_p),
                        ("pSIPClientData", ctypes.c_void_p), ("dwUIChoice", wintypes.DWORD),
                        ("fdwRevocationChecks", wintypes.DWORD), ("dwUnionChoice", wintypes.DWORD),
                        ("pFile", ctypes.POINTER(WFI)), ("dwStateAction", wintypes.DWORD),
                        ("hWVTStateData", wintypes.HANDLE), ("pwszURLReference", wintypes.LPCWSTR),
                        ("dwProvFlags", wintypes.DWORD), ("dwUIContext", wintypes.DWORD),
                        ("pSignatureSettings", ctypes.c_void_p)]

        action = GUID(0xaac56b, 0xcd44, 0x11d0,
                      (ctypes.c_ubyte * 8)(0x8c, 0xc2, 0x00, 0xc0, 0x4f, 0xc2, 0x95, 0xee))
        fi = WFI(ctypes.sizeof(WFI), path, None, None)
        wd = WTD()
        wd.cbStruct = ctypes.sizeof(WTD)
        wd.dwUIChoice = WTD_UI_NONE
        wd.fdwRevocationChecks = WTD_REVOKE_NONE
        wd.dwUnionChoice = WTD_CHOICE_FILE
        wd.pFile = ctypes.pointer(fi)
        wd.dwStateAction = WTD_STATEACTION_VERIFY
        wintrust = ctypes.WinDLL("wintrust.dll")
        rc = ctypes.c_long(wintrust.WinVerifyTrust(None, ctypes.byref(action),
                                                   ctypes.byref(wd))).value
        wd.dwStateAction = WTD_STATEACTION_CLOSE
        wintrust.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(wd))
        if rc == 0:
            return "valid"
        if rc in (TRUST_E_NOSIGNATURE, TRUST_E_SUBJECT_FORM_UNKNOWN, TRUST_E_PROVIDER_UNKNOWN):
            return "none"
        return "invalid"
    except Exception:
        return "unknown"


def exe_fingerprint(exe_norm: str) -> tuple:
    """실행 파일 지문(SHA-256, 크기). 검사-실행 사이 교체 감지용(§29/§30)."""
    return (sha256_of(exe_norm), os.path.getsize(exe_norm))


def verify_exe_unchanged(exe_norm: str, fp: tuple) -> None:
    """지문이 바뀌었으면(파일 교체) 차단한다(§30)."""
    if exe_fingerprint(exe_norm) != fp:
        raise TrustError("EXE_REPLACED")


def verify_exe_file(exe_path: str, *, signer_cn_provider=None) -> str:
    """Bank24 실행 경로 최소 검증 — Y_BankAuto 수준(§11–§13/§49).

    절대경로 여부와 존재 여부만 확인한다. 정규화 절대경로 반환, 위반 시 TrustError.
    ACL/소유자/광역쓰기/reparse/Authenticode/게시자/SHA-256/상위폴더 ACL 검사는
    Bank24 연결 경로에서 제거했다(과도 게이트 제거). 이 함수는 그 어떤 것도 검사하지 않는다.
    """
    exe = approved_exe_norm(exe_path)              # 빈값(PATH_NOT_CONFIGURED)/비절대(PATH_NOT_ABSOLUTE)
    if not os.path.isfile(exe):
        raise TrustError("PATH_NOT_FOUND")         # 실행 파일 존재 확인(§13)
    return exe


def verify_binary_file(path: str | None = None) -> str:
    """승인 EXE 파일의 존재·reparse·소유권·사용자 쓰기 가능 여부 검사.

    반환: 정규화된 승인 절대경로. 위반 시 TrustError(고정코드).
    """
    exe = approved_exe_norm(path)
    if not os.path.isfile(exe):
        raise TrustError("PATH_NOT_FOUND")
    if _si._is_reparse(exe) or _si._path_has_reparse(exe):
        raise TrustError("PATH_REPARSE")
    try:
        import win32security
        needed = (win32security.OWNER_SECURITY_INFORMATION |
                  win32security.DACL_SECURITY_INFORMATION)
        sd = win32security.GetFileSecurity(exe, needed)
        owner = sd.GetSecurityDescriptorOwner()
        if not _si._owner_is_trusted(owner):
            raise TrustError("PATH_OWNER_UNTRUSTED")
        if _si._dacl_world_writable(sd):
            raise TrustError("PATH_USER_WRITABLE")
    except TrustError:
        raise
    except Exception:
        # 소유자/ACL 확인 불가 → fail-closed
        raise TrustError("PATH_UNVERIFIABLE")
    return exe


# ─────────────────────────── 신뢰 기준 검증 (§25) ───────────────────────────
def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def _authenticode_signer_cn(path: str) -> str:
    """Authenticode 유효 서명 검증(WinVerifyTrust) 후 서명자 subject CN 반환.

    서명 무효/미서명/확인 불가 시 TrustError. 이 경로는 승인 게시자 allowlist 가
    설정된 경우에만 사용된다(기본은 미설정 → 사용 안 함).
    """
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        raise TrustError("SIG_UNAVAILABLE")

    # WinVerifyTrust 로 서명 유효성만 확인 (체인/취소 포함)
    try:
        WTD_UI_NONE = 2
        WTD_REVOKE_NONE = 0
        WTD_CHOICE_FILE = 1
        WTD_STATEACTION_VERIFY = 1
        WTD_STATEACTION_CLOSE = 2

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        class WINTRUST_FILE_INFO(ctypes.Structure):
            _fields_ = [("cbStruct", wintypes.DWORD),
                        ("pcwszFilePath", wintypes.LPCWSTR),
                        ("hFile", wintypes.HANDLE),
                        ("pgKnownSubject", ctypes.c_void_p)]

        class WINTRUST_DATA(ctypes.Structure):
            _fields_ = [("cbStruct", wintypes.DWORD),
                        ("pPolicyCallbackData", ctypes.c_void_p),
                        ("pSIPClientData", ctypes.c_void_p),
                        ("dwUIChoice", wintypes.DWORD),
                        ("fdwRevocationChecks", wintypes.DWORD),
                        ("dwUnionChoice", wintypes.DWORD),
                        ("pFile", ctypes.POINTER(WINTRUST_FILE_INFO)),
                        ("dwStateAction", wintypes.DWORD),
                        ("hWVTStateData", wintypes.HANDLE),
                        ("pwszURLReference", wintypes.LPCWSTR),
                        ("dwProvFlags", wintypes.DWORD),
                        ("dwUIContext", wintypes.DWORD),
                        ("pSignatureSettings", ctypes.c_void_p)]

        # WINTRUST_ACTION_GENERIC_VERIFY_V2
        action = GUID(0xaac56b, 0xcd44, 0x11d0,
                      (ctypes.c_ubyte * 8)(0x8c, 0xc2, 0x00, 0xc0, 0x4f, 0xc2, 0x95, 0xee))
        fi = WINTRUST_FILE_INFO(ctypes.sizeof(WINTRUST_FILE_INFO), path, None, None)
        wd = WINTRUST_DATA()
        wd.cbStruct = ctypes.sizeof(WINTRUST_DATA)
        wd.dwUIChoice = WTD_UI_NONE
        wd.fdwRevocationChecks = WTD_REVOKE_NONE
        wd.dwUnionChoice = WTD_CHOICE_FILE
        wd.pFile = ctypes.pointer(fi)
        wd.dwStateAction = WTD_STATEACTION_VERIFY
        wintrust = ctypes.WinDLL("wintrust.dll")
        rc = wintrust.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(wd))
        wd.dwStateAction = WTD_STATEACTION_CLOSE
        wintrust.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(wd))
        if rc != 0:
            raise TrustError("SIG_INVALID")
    except TrustError:
        raise
    except Exception:
        raise TrustError("SIG_UNAVAILABLE")

    # 서명자 subject CN 추출
    try:
        import win32api
        import win32con
        import win32crypt
        CERT_QUERY_OBJECT_FILE = 1
        CERT_QUERY_CONTENT_FLAG_ALL = 0x3ffe
        CERT_QUERY_FORMAT_FLAG_ALL = 0x0e
        res = win32crypt.CryptQueryObject(
            CERT_QUERY_OBJECT_FILE, path, CERT_QUERY_CONTENT_FLAG_ALL,
            CERT_QUERY_FORMAT_FLAG_ALL, 0)
        store = res["Store"] if isinstance(res, dict) else res[-1]
        cn = ""
        for cert in store.CertEnumCertificatesInStore():
            try:
                cn = cert.GetNameString(
                    win32con.CERT_NAME_SIMPLE_DISPLAY_TYPE, 0, None) or cn
            except Exception:
                continue
            if cn:
                break
        if not cn:
            raise TrustError("SIG_UNAVAILABLE")
        return cn
    except TrustError:
        raise
    except Exception:
        raise TrustError("SIG_UNAVAILABLE")


def verify_trust_baseline(path: str, *, computed_hash: str | None = None,
                          signer_cn_provider=None) -> str:
    """신뢰 기준(SHA-256 우선, 없으면 Authenticode 게시자) 검증. 기준 미설정 시 차단.

    반환: method("sha256"|"authenticode"). 위반 시 TrustError.
    provider 인자는 테스트에서 합성 값을 주입하기 위한 것이다.
    """
    if APPROVED_SHA256:
        h = (computed_hash or sha256_of(path)).lower()
        if h in APPROVED_SHA256:
            return "sha256"
        raise TrustError("HASH_MISMATCH")
    if APPROVED_PUBLISHERS:
        cn = (signer_cn_provider(path) if signer_cn_provider
              else _authenticode_signer_cn(path))
        if cn in APPROVED_PUBLISHERS:
            return "authenticode"
        raise TrustError("SIG_PUBLISHER_UNTRUSTED")
    raise TrustError("NO_TRUST_BASELINE")


# ─────────────────────────── 정적 신뢰 종합 (실행 전) ───────────────────────────
def verify_static_trust(path: str | None = None, *, computed_hash: str | None = None,
                        signer_cn_provider=None) -> TrustResult:
    """실행/부착 전에 파일·신뢰 기준을 모두 검사한다. 통과 시 TrustResult."""
    exe = verify_binary_file(path)
    method = verify_trust_baseline(exe, computed_hash=computed_hash,
                                   signer_cn_provider=signer_cn_provider)
    return TrustResult(method=method, exe_norm=exe, install_dir=os.path.dirname(exe))


# ─────────────────────────── PID 이미지 경로 검증 (§28) ───────────────────────────
def pid_image_path(pid: int) -> str:
    """PID 의 실제 이미지 경로. 확인 불가 시 TrustError(PID_IMAGE_UNAVAILABLE)."""
    if not isinstance(pid, int) or pid <= 0:
        raise TrustError("PID_IMAGE_UNAVAILABLE")
    # 1) win32: QueryFullProcessImageName (신뢰 가능한 실제 경로)
    try:
        import win32api
        import win32con
        import win32process
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = win32api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            img = win32process.GetModuleFileNameEx(h, 0)
        except Exception:
            img = win32process.QueryFullProcessImageName(h, 0)
        finally:
            win32api.CloseHandle(h)
        if img:
            return img
    except Exception:
        pass
    # 2) psutil 폴백
    try:
        import psutil
        return psutil.Process(pid).exe()
    except Exception:
        raise TrustError("PID_IMAGE_UNAVAILABLE")


def verify_pid_image(pid: int, exe_norm: str) -> None:
    """PID 실제 이미지 경로가 승인 절대경로와 정확히 일치하는지. 불일치 시 TrustError."""
    img = pid_image_path(pid)
    if _normcase(img) != _normcase(exe_norm):
        raise TrustError("PID_IMAGE_MISMATCH")


# ─────────────────────────── 창 신뢰 검증 (§29/§30) ───────────────────────────
def verify_window(win, exe_norm: str, allowed_classes) -> None:
    """창(pid/hwnd/이미지경로/클래스) 신뢰 검증. 제목만으로 신뢰하지 않는다(§21/§30).

    win: bank24_automation.WindowInfo. allowed_classes: INI [bank24] window_classes.
    위반 시 TrustError(WINDOW_UNTRUSTED).
    """
    try:
        classes = tuple(allowed_classes or ())
        if int(getattr(win, "pid", 0)) <= 0 or int(getattr(win, "hwnd", 0)) <= 0:
            raise TrustError("WINDOW_UNTRUSTED")
        if _normcase(getattr(win, "exe_path", "") or "") != _normcase(exe_norm):
            raise TrustError("WINDOW_UNTRUSTED")
        if not classes:
            raise TrustError("WINDOW_UNTRUSTED")   # 허용 클래스 미설정 → fail-closed
        if getattr(win, "window_class", "") not in classes:
            raise TrustError("WINDOW_UNTRUSTED")
    except TrustError:
        raise
    except Exception:
        raise TrustError("WINDOW_UNTRUSTED")
    # PID 실제 이미지도 재확인(§20)
    verify_pid_image(int(win.pid), exe_norm)


# ─────────────────────────── 안전 실행 (§23/§31/§32/§33) ───────────────────────────
def build_launch_spec(exe_norm: str) -> dict:
    """안전 실행 사양. shell=False, argv 리스트, cwd=설치폴더, 자격증명/민감 env 미포함.

    exe_norm: 검증된 정규화 절대경로. 반환 dict 는 subprocess.Popen 인자만 담는다.
    실제 실행은 호출측(adapter)이 하며, 이 함수는 순수하게 사양만 만든다(테스트 가능).
    """
    install_dir = os.path.dirname(exe_norm)
    # 자식에게 자격증명/민감 env 를 전달하지 않는다. 최소 안전 env 만 구성.
    safe_env = {}
    for k in ("SystemRoot", "windir", "TEMP", "TMP", "NUMBER_OF_PROCESSORS",
              "PROCESSOR_ARCHITECTURE"):
        v = os.environ.get(k)
        if v:
            safe_env[k] = v
    creationflags = 0
    try:
        import subprocess
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    except Exception:
        creationflags = 0
    return {
        "argv": [exe_norm],           # 문자열 조립 없음(§18)
        "cwd": install_dir,           # 신뢰된 설치 폴더로 고정(§24, CWD DLL 하이재킹 완화)
        "shell": False,
        "env": safe_env,              # 자격증명 없음(§30)
        "close_fds": True,
        "creationflags": creationflags,
    }
