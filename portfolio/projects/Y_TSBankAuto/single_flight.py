# -*- coding: utf-8 -*-
"""프로세스 단위 single-flight 락 (지시 §7).

목적: 자동화 세션의 중복 기동을 차단한다. 같은 사용자 세션에서 하나만 실행된다.

설계 원칙:
- 이름은 무작위가 아니라 현재 사용자 SID + 고정 앱 ID 에서 결정적으로 파생한다.
- Windows 네임드 뮤텍스는 Local\\ (세션 로컬) 네임스페이스만 사용한다. Global\\ 금지.
- 뮤텍스에는 현재 사용자 + SYSTEM 만 접근 가능한 명시적 DACL 을 적용한다.
- 기존 뮤텍스가 있으면 다른 세션 실행 중으로 보고 신규 실행을 차단한다.
- 파일락 fallback 은 사용자 전용 로컬 경로, exclusive-create, reparse 차단을 적용한다.
- 정상·실패·중지·timeout 모든 경로에서 락을 해제한다(context manager).

pywin32 가 없거나 뮤텍스 생성에 실패하면 파일락으로 안전하게 degrade 한다.
"""
from __future__ import annotations

import hashlib
import os
import stat as _stat

APP_ID = "Y_TSBankAuto.single_flight.v1"   # 고정 앱 ID (버전 포함)


class SingleFlightError(Exception):
    """single-flight 획득 실패(다른 세션 실행 중 또는 안전 검사 실패)."""


# ───────────────────────────── 결정적 이름 파생 ─────────────────────────────
def current_user_sid() -> str:
    """현재 사용자 SID 문자열(best-effort). 실패 시 사용자명 기반 대체 토큰."""
    try:
        import win32api
        import win32security
        # 프로세스 토큰의 사용자 SID
        import win32con
        import win32process
        th = win32security.OpenProcessToken(
            win32process.GetCurrentProcess(), win32con.TOKEN_QUERY)
        sid, _ = win32security.GetTokenInformation(th, win32security.TokenUser)
        return win32security.ConvertSidToStringSid(sid)
    except Exception:
        # fallback: 사용자명 + 도메인(비밀 아님). SID 파생 불가 환경(테스트 등).
        who = (os.environ.get("USERDOMAIN", "") + "\\" +
               os.environ.get("USERNAME", "unknown"))
        return "NOSID:" + who


def mutex_name(sid: str, app_id: str = APP_ID) -> str:
    """SID + 앱 ID 로 결정적 Local 세션 뮤텍스 이름 생성. 절대 Global 사용 안 함."""
    digest = hashlib.sha256(f"{sid}|{app_id}".encode("utf-8")).hexdigest()[:32]
    return f"Local\\Y_TSBankAuto_SF_{digest}"


def lock_dir() -> str:
    """파일락 fallback 용 사용자 전용 로컬 디렉터리."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or os.getcwd()
    return os.path.join(base, "Y_TSBankAuto", "locks")


def lock_file_path(sid: str, app_id: str = APP_ID) -> str:
    digest = hashlib.sha256(f"{sid}|{app_id}".encode("utf-8")).hexdigest()[:32]
    return os.path.join(lock_dir(), f"sf_{digest}.lock")


# ───────────────────────────── 안전 헬퍼 ─────────────────────────────
def _is_reparse(path: str) -> bool:
    """경로가 reparse point(symlink/junction) 인지."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    attr = getattr(st, "st_file_attributes", 0)
    reparse_flag = getattr(_stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attr & reparse_flag)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        pass
    # psutil 없으면 보수적으로 살아있다고 본다(무리한 회수 방지).
    return True


# ───────────────────────────── 뮤텍스 백엔드 ─────────────────────────────
def _build_user_only_security_attributes():
    """현재 사용자 + SYSTEM 만 접근 가능한 DACL 을 가진 SECURITY_ATTRIBUTES.

    실패 시 None (상속 기본 보안). pywin32 필요.
    """
    import ntsecuritycon as ncon
    import win32security

    # 현재 사용자 SID
    import win32api
    user_name = win32api.GetUserName()
    user_sid, _, _ = win32security.LookupAccountName("", user_name)
    system_sid = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid)

    dacl = win32security.ACL()
    full = ncon.MUTEX_ALL_ACCESS | ncon.SYNCHRONIZE | ncon.STANDARD_RIGHTS_ALL
    dacl.AddAccessAllowedAce(win32security.ACL_REVISION, full, user_sid)
    dacl.AddAccessAllowedAce(win32security.ACL_REVISION, full, system_sid)

    sd = win32security.SECURITY_DESCRIPTOR()
    sd.SetSecurityDescriptorDacl(1, dacl, 0)   # 명시적 DACL, 상속 프로텍트

    sa = win32security.SECURITY_ATTRIBUTES()
    sa.SECURITY_DESCRIPTOR = sd
    sa.bInheritHandle = False
    return sa


class _MutexBackend:
    def __init__(self, name: str):
        self.name = name
        self._handle = None

    def acquire(self) -> bool:
        import win32event
        import winerror
        try:
            sa = _build_user_only_security_attributes()
        except Exception:
            sa = None
        handle = win32event.CreateMutex(sa, True, self.name)  # bInitialOwner=True
        last = 0
        try:
            import win32api
            last = win32api.GetLastError()
        except Exception:
            pass
        if handle == 0 or handle is None:
            raise SingleFlightError("뮤텍스 생성 실패")
        if last == winerror.ERROR_ALREADY_EXISTS:
            # 다른 세션이 이미 보유 → 신규 실행 차단.
            try:
                import win32api
                win32api.CloseHandle(handle)
            except Exception:
                pass
            return False
        self._handle = handle
        return True

    def release(self):
        h, self._handle = self._handle, None
        if h is None:
            return
        try:
            import win32event
            win32event.ReleaseMutex(h)
        except Exception:
            pass
        try:
            import win32api
            win32api.CloseHandle(h)
        except Exception:
            pass


# ───────────────────────────── 파일락 백엔드 ─────────────────────────────
class _FileLockBackend:
    def __init__(self, path: str):
        self.path = path
        self._fd = None

    def _check_dir_safe(self, d: str):
        if _is_reparse(d):
            raise SingleFlightError("락 디렉터리가 reparse point")

    def acquire(self) -> bool:
        d = os.path.dirname(self.path)
        os.makedirs(d, exist_ok=True)
        self._check_dir_safe(d)
        if _is_reparse(self.path):
            raise SingleFlightError("락 파일이 reparse point")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(self.path, flags, 0o600)
        except FileExistsError:
            # 기존 락: 소유 PID 확인. 죽은 프로세스면 1회 회수 시도.
            if self._reclaim_if_stale():
                try:
                    fd = os.open(self.path, flags, 0o600)
                except OSError:
                    return False
            else:
                return False
        except OSError as e:
            raise SingleFlightError(f"락 파일 생성 실패: {type(e).__name__}")
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
        except OSError:
            pass
        self._fd = fd
        return True

    def _reclaim_if_stale(self) -> bool:
        try:
            with open(self.path, "r", encoding="ascii", errors="ignore") as f:
                pid = int((f.read() or "0").strip() or "0")
        except (OSError, ValueError):
            return False
        if pid == os.getpid():
            return False
        if _pid_alive(pid):
            return False
        try:
            os.remove(self.path)
            return True
        except OSError:
            return False

    def release(self):
        fd, self._fd = self._fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.remove(self.path)
            except OSError:
                pass


# ───────────────────────────── SingleFlight ─────────────────────────────
class SingleFlight:
    """single-flight 락. context manager 로 사용하면 모든 종료 경로에서 해제된다.

    backend: "auto"(뮤텍스→파일락), "mutex", "file". 테스트는 명시 백엔드 사용.
    """

    def __init__(self, *, backend: str = "auto", sid: str | None = None,
                 app_id: str = APP_ID):
        self.sid = sid or current_user_sid()
        self.app_id = app_id
        self.backend_kind = backend
        self._backend = None
        self.acquired = False

    def _make_backend(self):
        if self.backend_kind == "file":
            return _FileLockBackend(lock_file_path(self.sid, self.app_id))
        if self.backend_kind == "mutex":
            return _MutexBackend(mutex_name(self.sid, self.app_id))
        # auto: 뮤텍스 시도, 실패 시 파일락
        try:
            import win32event  # noqa: F401
            return _MutexBackend(mutex_name(self.sid, self.app_id))
        except Exception:
            return _FileLockBackend(lock_file_path(self.sid, self.app_id))

    def acquire(self) -> bool:
        if self.acquired:
            return True
        self._backend = self._make_backend()
        try:
            ok = self._backend.acquire()
        except SingleFlightError:
            # auto 모드에서 뮤텍스 안전검사 실패 시 파일락으로 degrade.
            if self.backend_kind == "auto" and isinstance(self._backend, _MutexBackend):
                self._backend = _FileLockBackend(lock_file_path(self.sid, self.app_id))
                ok = self._backend.acquire()
            else:
                raise
        self.acquired = bool(ok)
        return self.acquired

    def release(self):
        if self._backend is not None:
            self._backend.release()
            self._backend = None
        self.acquired = False

    def __enter__(self) -> "SingleFlight":
        if not self.acquire():
            raise SingleFlightError("다른 세션이 이미 실행 중(single-flight)")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False
