# -*- coding: utf-8 -*-
"""settings.ini 트러스트 앵커 무결성 검사 (지시 §8, §3-a).

real(실제 자동화/DB) 기능은 설정 파일이 안전할 때만 허용한다. 안전하지 않으면
real 을 차단(fail-closed)하되, fake 흐름은 안전한 기본값으로 계속 사용할 수 있다.

검사 항목:
- 파일과 상위 폴더가 reparse point(symlink/junction) 인지
- 로컬 경로인지(UNC/네트워크 드라이브 금지)
- 소유자가 현재 사용자 또는 관리자/SYSTEM 인지
- 광역 사용자(Everyone/Authenticated Users/Users)에게 쓰기 ACE 가 있는지

OS 권한 정보를 확인할 수 없으면(pywin32 부재/예외) verifiable=False 로 두고 real 을 차단한다.

경로 결정: 모든 실행 방식에서 고정 경로 C:\\Bank24Extractor\\settings.ini 를 사용한다
(Y_BankAuto 와 동일). _internal 과 _MEIPASS 에서 실제 설정을 찾지 않는다.

자동 생성(ensure_settings_file): 파일이 없을 때만, 시크릿·서버주소·PII 가 없는
기본본을 UTF-8 로 원자적 생성한다. 기존 파일은 절대 덮어쓰거나 병합하지 않으며,
경로에 reparse point(symlink/junction) 나 UNC/네트워크가 있으면 생성하지 않고
안전하게 실패한다(fail-closed). 생성 후에도 무결성 검사·real 승인 절차는 그대로 적용된다.
"""
from __future__ import annotations

import os
import stat as _stat
import sys
import tempfile
from dataclasses import dataclass, field

SETTINGS_NAME = "settings.ini"
# 고정 애플리케이션 디렉터리/설정 경로 (모든 실행 방식 공통)
DEFAULT_APP_DIR = r"C:\Bank24Extractor"
DEFAULT_SETTINGS_PATH = os.path.join(DEFAULT_APP_DIR, SETTINGS_NAME)

# 자동 생성 시 로그인 값과 DB 시크릿은 빈 값으로 두어 real 실행이 fail-closed를 유지한다.
# (DB 자격증명은 keyring/전용 환경변수로만 제공, allowlist 는 비어 있어 real 차단.)
_DEFAULT_INI = '; Y_TSBankAuto 설정 (자동 생성본 · 시크릿 없음)\n; Bank24 ID/PW는 [login]에서 읽습니다. 파일 ACL을 제한하고 외부에 공유하지 마십시오.\n; DB 시크릿은 Windows 자격증명 관리자(keyring) 또는 전용 환경변수로만 제공합니다.\n; 값이 빈 상태에서는 실제 자동화/DB(real)가 fail-closed 로 차단됩니다.\n\n[login]\nsave_credentials = false\nbank24_id =\nREDACTED_CONFIGURE_LOCALLY =\n\n; [bank24] 섹션은 요구하지 않습니다(§12). Bank24 실행 경로/메인 창 클래스는 코드 상수입니다.\n\n[options]\nsource_tab = 탁상\n\n[database]\nserver =\nport = 1433\ndatabase =\ndriver = ODBC Driver 18 for SQL Server\nencrypt = yes\ntrust_server_certificate = true\n\n[allowlist]\n; 대상 서버/DB 를 명시적으로 추가하기 전까지 real 은 차단됩니다.\nservers =\ndatabases =\n\n[paths]\npdf_root =\nlog_dir =\noutput_dir =\nretention_days = 90\n\n[safety]\nrollback_test = true\nautocommit = false\nallow_commit = false\n'


# ───────────────────────────── 경로 결정 ─────────────────────────────
def resolve_settings_path() -> str:
    return DEFAULT_SETTINGS_PATH


# ───────────────────────────── 사실 수집(OS 의존) ─────────────────────────────
def _is_reparse(path: str) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    attr = getattr(st, "st_file_attributes", 0)
    flag = getattr(_stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attr & flag)


def _is_local_path(path: str) -> bool:
    """UNC(\\\\server\\share) 또는 네트워크 드라이브면 False."""
    ap = os.path.abspath(path)
    if ap.startswith("\\\\"):
        return False   # UNC
    drive = os.path.splitdrive(ap)[0]
    try:
        import win32file
        # 4 == DRIVE_REMOTE
        if drive and win32file.GetDriveType(drive + "\\") == 4:
            return False
    except Exception:
        pass   # win32file 없으면 UNC 검사만으로 판단
    return True


# 쓰기로 간주하는 접근 마스크 비트
_WRITE_BITS = 0
try:
    import ntsecuritycon as _ncon  # type: ignore
    _WRITE_BITS = (
        _ncon.FILE_WRITE_DATA | _ncon.FILE_APPEND_DATA | _ncon.FILE_WRITE_EA
        | _ncon.FILE_WRITE_ATTRIBUTES | _ncon.WRITE_DAC | _ncon.WRITE_OWNER
        | _ncon.GENERIC_WRITE | _ncon.GENERIC_ALL
    )
except Exception:
    _WRITE_BITS = 0x40000000 | 0x10000000 | 0x0002 | 0x0004 | 0x00040000 | 0x00080000


@dataclass
class IntegrityFacts:
    path: str
    exists: bool = False
    verifiable: bool = False        # OS 권한/소유자 확인 성공 여부
    is_reparse: bool = False
    parent_reparse: bool = False
    is_local: bool = True
    owner_ok: bool = False
    world_writable: bool = False
    error: str = ""


def _broad_sids():
    import win32security
    sids = []
    for wk in (win32security.WinWorldSid,              # Everyone
               win32security.WinAuthenticatedUserSid,  # Authenticated Users
               win32security.WinBuiltinUsersSid):      # Users
        try:
            sids.append(win32security.CreateWellKnownSid(wk))
        except Exception:
            pass
    return sids


def _sid_equal(a, b) -> bool:
    """SID 동등 비교. pywin32 버전에 따라 win32security.EqualSid 가 없을 수 있어
    PySID == 및 ConvertSidToStringSid 폴백을 사용한다. 비교 불가 시 False."""
    import win32security
    fn = getattr(win32security, "EqualSid", None)
    if fn is not None:
        try:
            return bool(fn(a, b))
        except Exception:
            pass
    try:
        if a == b:
            return True
    except Exception:
        pass
    try:
        return (win32security.ConvertSidToStringSid(a)
                == win32security.ConvertSidToStringSid(b))
    except Exception:
        return False


def _current_user_sid():
    import win32api
    import win32security
    name = win32api.GetUserName()
    sid, _, _ = win32security.LookupAccountName("", name)
    return sid


def _owner_is_trusted(owner_sid) -> bool:
    import win32security
    try:
        if _sid_equal(owner_sid, _current_user_sid()):
            return True
    except Exception:
        pass
    for wk in (win32security.WinLocalSystemSid,
               win32security.WinBuiltinAdministratorsSid):
        try:
            if _sid_equal(owner_sid, win32security.CreateWellKnownSid(wk)):
                return True
        except Exception:
            pass
    return False


class _AclError(Exception):
    """ACL 판정 불가(미지 ACE 형식/파싱 오류). real 차단으로 처리한다."""


# ACE 상속 전용 플래그: 대상 객체 자신에는 적용되지 않음
_INHERIT_ONLY_ACE = 0x08


def _ace_components(ace) -> tuple:
    """pywin32 GetAce 결과에서 (ace_type, ace_flags, mask, sid)를 안전 추출.

    일반 ACE 는 ((type,flags), mask, sid) 3-튜플, object ACE 는 추가 필드(Flags,
    ObjectType, InheritedObjectType)가 끼어 길이가 다르다. 두 형식 모두에서
    (type,flags)는 첫 요소, mask 는 두 번째, SID 는 항상 마지막 요소다.
    """
    header = ace[0]
    if not isinstance(header, (tuple, list)) or len(header) < 2:
        raise _AclError("ace_header")
    try:
        ace_type = int(header[0])
        ace_flags = int(header[1])
        mask = int(ace[1])
        sid = ace[-1]
    except (TypeError, ValueError, IndexError):
        raise _AclError("ace_parse")
    return ace_type, ace_flags, mask, sid


def _classify_world_writable(aces, is_broad, write_bits) -> bool:
    """순수 판정 로직(OS 독립, 테스트 가능).

    aces: [(ace_type, ace_flags, mask, sid_key)] — DACL 순서 그대로.
    is_broad(sid_key) -> bool: 광역 SID(Everyone/Users/Authenticated Users) 여부.
    정규 DACL 은 DENY 가 ALLOW 보다 앞선다. 광역 SID 에 대해 먼저 나온 DENY 쓰기비트는
    이후 ALLOW 에서 제외한다. 미지 ACE 형식은 _AclError 로 fail-closed.
    """
    # win32security 상수(테스트에서 win32security 부재 시 기본값 사용)
    try:
        import win32security as _ws
        A_ALLOW = getattr(_ws, "ACCESS_ALLOWED_ACE_TYPE", 0)
        A_DENY = getattr(_ws, "ACCESS_DENIED_ACE_TYPE", 1)
        A_ALLOW_OBJ = getattr(_ws, "ACCESS_ALLOWED_OBJECT_ACE_TYPE", 5)
        A_DENY_OBJ = getattr(_ws, "ACCESS_DENIED_OBJECT_ACE_TYPE", 6)
        AUDIT = {getattr(_ws, "SYSTEM_AUDIT_ACE_TYPE", 2),
                 getattr(_ws, "SYSTEM_ALARM_ACE_TYPE", 3),
                 getattr(_ws, "SYSTEM_AUDIT_OBJECT_ACE_TYPE", 7),
                 getattr(_ws, "SYSTEM_ALARM_OBJECT_ACE_TYPE", 8)}
    except Exception:
        A_ALLOW, A_DENY, A_ALLOW_OBJ, A_DENY_OBJ = 0, 1, 5, 6
        AUDIT = {2, 3, 7, 8}

    denied_write = 0   # 광역 SID 에 이미 거부된 쓰기 비트 누적
    for ace_type, ace_flags, mask, sid_key in aces:
        if ace_flags & _INHERIT_ONLY_ACE:
            continue                      # 객체 자신에 미적용
        if ace_type in AUDIT:
            continue                      # 감사/알람은 권한 부여 아님
        is_allow = ace_type in (A_ALLOW, A_ALLOW_OBJ)
        is_deny = ace_type in (A_DENY, A_DENY_OBJ)
        if not (is_allow or is_deny):
            raise _AclError("unknown_ace")   # 미지 ACE → fail-closed
        write_here = mask & write_bits
        if not write_here or not is_broad(sid_key):
            continue
        if is_deny:
            denied_write |= write_here
        else:  # allow: 앞선 deny 로 가려지지 않은 쓰기비트가 남으면 광역 쓰기 가능
            if write_here & ~denied_write:
                return True
    return False


def _dacl_world_writable(sd) -> bool:
    import win32security
    dacl = sd.GetSecurityDescriptorDacl()
    if dacl is None:
        return True    # NULL DACL = 모두 허용 → 위험

    broad = _broad_sids()

    def _is_broad(sid) -> bool:
        for b in broad:
            if _sid_equal(sid, b):
                return True
        return False

    aces = []
    for i in range(dacl.GetAceCount()):
        try:
            ace = dacl.GetAce(i)
        except Exception:
            raise _AclError("ace_get")
        aces.append(_ace_components(ace))
    return _classify_world_writable(aces, _is_broad, _WRITE_BITS)


def gather_facts(path: str) -> IntegrityFacts:
    f = IntegrityFacts(path=path)
    f.exists = os.path.isfile(path)
    parent = os.path.dirname(os.path.abspath(path))
    f.is_reparse = _is_reparse(path) if f.exists else False
    f.parent_reparse = _is_reparse(parent)
    f.is_local = _is_local_path(path)
    if not f.exists:
        return f
    try:
        import win32security
        needed = (win32security.OWNER_SECURITY_INFORMATION |
                  win32security.DACL_SECURITY_INFORMATION)
        sd = win32security.GetFileSecurity(path, needed)
        owner = sd.GetSecurityDescriptorOwner()
        f.owner_ok = _owner_is_trusted(owner)
        f.world_writable = _dacl_world_writable(sd)
        f.verifiable = True
    except Exception as e:
        f.verifiable = False
        f.error = type(e).__name__
    return f


# ───────────────────────────── 평가(순수 함수) ─────────────────────────────
@dataclass
class IntegrityResult:
    real_allowed: bool
    reasons: list = field(default_factory=list)

    @property
    def fake_allowed(self) -> bool:
        return True   # fake 는 항상 안전 기본값으로 사용 가능


def evaluate(facts: IntegrityFacts) -> IntegrityResult:
    """사실 → real 허용 여부. 하나라도 위험하면 real 차단(fail-closed)."""
    reasons: list[str] = []
    if not facts.exists:
        reasons.append("설정 파일 없음(real 차단, fake 기본값 사용)")
        return IntegrityResult(False, reasons)
    if not facts.is_local:
        reasons.append("공용/네트워크(UNC) 경로")
    if facts.is_reparse:
        reasons.append("설정 파일이 reparse point")
    if facts.parent_reparse:
        reasons.append("상위 폴더가 reparse point")
    if not facts.verifiable:
        reasons.append("소유자/ACL 확인 불가(fail-closed)")
    else:
        if not facts.owner_ok:
            reasons.append("설정 파일 소유자가 신뢰되지 않음")
        if facts.world_writable:
            reasons.append("광역 사용자에게 쓰기 권한 있음")
    return IntegrityResult(not reasons, reasons)


# ───────────────────────────── 자동 생성 (fail-closed) ─────────────────────────────
class _UnsafePath(Exception):
    """비정상/비신뢰 경로. 생성하지 않고 안전하게 실패한다."""


def _path_has_reparse(path: str) -> bool:
    """대상 및 존재하는 모든 상위 경로 중 reparse point(symlink/junction) 가 있으면 True."""
    cur = os.path.abspath(path)
    seen: set[str] = set()
    while cur and cur not in seen:
        seen.add(cur)
        if os.path.exists(cur) and _is_reparse(cur):
            return True
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return False


def _ensure_parent_dir_safe(parent: str) -> None:
    """상위 디렉터리를 안전하게 확보. 비로컬/reparse 경로는 거부(fail-closed)."""
    if not _is_local_path(parent):
        raise _UnsafePath("nonlocal")
    if _path_has_reparse(parent):
        raise _UnsafePath("reparse")
    if not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)   # 동시 생성은 exist_ok 로 안전
    # 생성 직후에도 reparse 로 바뀌었는지 재확인(TOCTOU 완화)
    if _is_reparse(parent):
        raise _UnsafePath("reparse")


def ensure_settings_file(path: str | None = None) -> tuple[bool, str]:
    """settings.ini 가 없으면 시크릿 없는 기본본을 원자적으로 생성한다.

    반환: (created, reason).
    - 이미 존재하면 (False, "exists") — 절대 덮어쓰거나 병합하지 않는다.
    - 경로가 비정상(reparse/UNC)이면 (False, "unsafe:...") — 생성하지 않고 안전 실패.
    - 동시 실행으로 다른 프로세스가 먼저 만들면 (False, "race").
    이 함수는 예외를 던지지 않는다. 실패 시 파일이 없어 무결성 게이트가 real 을 차단한다.
    """
    p = os.path.abspath(path or resolve_settings_path())
    # 1) 이미 있으면(심볼릭 링크 포함) 손대지 않는다.
    if os.path.lexists(p):
        return False, "exists"
    parent = os.path.dirname(p)
    # 2) 상위 경로 안전성 확보(비로컬/reparse 거부).
    try:
        _ensure_parent_dir_safe(parent)
    except _UnsafePath as e:
        return False, f"unsafe:{e}"
    except OSError as e:
        return False, f"unsafe:{type(e).__name__}"
    # 3) 임시 파일에 기록 후 원자적으로 게시(덮어쓰기 없음 · 동시성 안전).
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=".settings.", suffix=".tmp", dir=parent)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(_DEFAULT_INI)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        # os.link: 대상이 있으면 FileExistsError(덮어쓰지 않음), 성공 시 원자적.
        try:
            os.link(tmp, p)
        except FileExistsError:
            return False, "race"
        except OSError:
            # 하드링크 미지원 FS: rename 폴백. Windows rename 은 대상 존재 시 실패.
            if os.path.lexists(p):
                return False, "race"
            os.rename(tmp, p)
            tmp = None   # rename 으로 이동됨
        return True, "created"
    except FileExistsError:
        return False, "race"
    except OSError as e:
        return False, f"unsafe:{type(e).__name__}"
    finally:
        if tmp and os.path.lexists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def check_settings(path: str | None = None) -> tuple[IntegrityResult, str]:
    """settings 경로 결정 + 무결성 평가. (결과, 경로) 반환."""
    p = path or resolve_settings_path()
    return evaluate(gather_facts(p)), p
