# -*- coding: utf-8 -*-
"""탁상 저장 성공 건의 의뢰서 PDF 를 DESK 공유폴더에 복사하고 APW_IW_DESKFILE 에 등록한다.

흐름(행별, 탁상 SP commit 이후·BankOnline 호출과 독립):
  1. NewMasterID(=DESKFILE.Docid) 형식 검증. 불일치면 건너뜀.
  2. 대상 파일 ``\\\\server\\data1\\DESK\\{MasterID}-1.pdf`` 가 이미 있으면 건너뜀(접미사 없음).
  3. 원본 PDF 를 exclusive-create 로 복사(덮어쓰기 없음).
  4. APW_IW_DESKFILE 기존 행 조회 → 없으면 SP_IW_I_DESKFILE(Kind=1),
     있고 file1name 비어 있으면 SP_IW_U_DESKFILE(Kind=1), file1name 이 이미 있으면 건너뜀.
  5. SP 실패 시 복사한 파일을 삭제하고 안전코드만 반환(탁상 저장은 되돌리지 않음).

보안:
- 공유 루트는 코드 상수(DESK_ROOT). 파일명은 MasterID 정규식 통과값에서만 생성 → 경로 탈출 없음.
- SQL 은 고정 문자열 + ``?`` 바인딩만. 로그에는 안전코드·행 번호만(경로/PII 원문 없음).
- fileupman 은 Reg_Charge→이름 고정 매핑(899=양혜지, 1729=김유진). 미매핑이면 두 이름을 번갈아 사용.
"""
from __future__ import annotations

import datetime as _dt
import itertools
import os
import re
import shutil

import config
import tabletop_save

DESK_ROOT = r"\\server\data1\DESK"
FILE_SUFFIX = "-1.pdf"
KIND = 1
MASTERID_RE = re.compile(r"^\d{2}-\d{8}-\d{3}$")

UPMAN_BY_REG_CHARGE = {899: "양혜지", 1729: "김유진"}
_UPMAN_CYCLE = itertools.cycle(["양혜지", "김유진"])

SQL_SELECT_ROW = (
    "SELECT file1name FROM dbo.APW_IW_DESKFILE WHERE Docid = ?"
)
SQL_INSERT = (
    "EXEC dbo.SP_IW_I_DESKFILE @Docid=?, @filename=?, @fileupdate=?, "
    "@fileupman=?, @Kind=?"
)
SQL_UPDATE = (
    "EXEC dbo.SP_IW_U_DESKFILE @Docid=?, @filename=?, @fileupdate=?, "
    "@fileupman=?, @Kind=?"
)


class DeskFileError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _log(logger, message: str) -> None:
    if callable(logger):
        try:
            logger(f"[DESK] {message}")
        except Exception:
            pass


def master_id(output: dict) -> str:
    """저장 결과의 NewMasterID 를 검증해 반환. 형식 불일치면 빈 문자열."""
    value = str((output or {}).get("NewMasterID") or "").strip()
    return value if MASTERID_RE.fullmatch(value) else ""


def upman_for(output: dict) -> str:
    """Reg_Charge 매핑 우선, 없으면 두 이름을 번갈아 사용."""
    raw = (output or {}).get("RegCharge")
    try:
        code = int(raw) if raw is not None and str(raw).strip() != "" else None
    except (TypeError, ValueError):
        code = None
    if code in UPMAN_BY_REG_CHARGE:
        return UPMAN_BY_REG_CHARGE[code]
    return next(_UPMAN_CYCLE)


def dest_path(docid: str, root: str = DESK_ROOT) -> str:
    """루트 하위 고정 파일명. docid 는 master_id() 통과값이어야 한다."""
    if not MASTERID_RE.fullmatch(docid or ""):
        raise DeskFileError("DOCID_INVALID")
    root_abs = os.path.abspath(root)
    path = os.path.abspath(os.path.join(root_abs, docid + FILE_SUFFIX))
    if os.path.commonpath([root_abs, path]) != root_abs:
        raise DeskFileError("DESK_PATH_INVALID")
    return path


def _copy_exclusive(src: str, dst: str) -> None:
    """덮어쓰기 없이 복사. 이미 있으면 DESK_FILE_EXISTS."""
    if not os.path.isfile(src):
        raise DeskFileError("PDF_NOT_FOUND")
    try:
        fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
    except FileExistsError:
        raise DeskFileError("DESK_FILE_EXISTS")
    except OSError:
        raise DeskFileError("DESK_ROOT_UNAVAILABLE")
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as inp:
            shutil.copyfileobj(inp, out)
    except Exception:
        _safe_remove(dst)
        raise DeskFileError("DESK_COPY_FAILED")


def _safe_remove(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _decide_sql(cur, docid: str) -> str | None:
    """기존 행 유무로 INSERT/UPDATE/건너뜀(None) 결정."""
    cur.execute(SQL_SELECT_ROW, (docid,))
    rows = cur.fetchall() or []
    if not rows:
        return SQL_INSERT
    if any(str(r[0] or "").strip() for r in rows):
        return None
    return SQL_UPDATE


def register(output: dict, pdf_path: str, app: config.AppConfig, *,
             connector=None, logger=None, root: str = DESK_ROOT,
             now=None) -> tuple[str, str]:
    """Return (status, code). status: 'Y' 등록, 'S' 건너뜀, 'N' 실패."""
    docid = master_id(output)
    if not docid:
        _log(logger, "건너뜀 DOCID_INVALID")
        return ("S", "DOCID_INVALID")
    try:
        dst = dest_path(docid, root)
    except DeskFileError as exc:
        _log(logger, f"건너뜀 {exc.code}")
        return ("S", exc.code)
    if os.path.exists(dst):
        _log(logger, "건너뜀 DESK_FILE_EXISTS")
        return ("S", "DESK_FILE_EXISTS")

    try:
        _copy_exclusive(pdf_path, dst)
    except DeskFileError as exc:
        _log(logger, f"실패 {exc.code}")
        return ("S" if exc.code == "DESK_FILE_EXISTS" else "N", exc.code)

    stamp = now or _dt.datetime.now().replace(microsecond=0)
    upman = upman_for(output)
    conn = None
    try:
        conn = tabletop_save._connect(app, connector)
        tabletop_save._verify_target_and_metadata(conn, app)
        cur = conn.cursor()
        sql = _decide_sql(cur, docid)
        if sql is None:
            conn.rollback()
            _safe_remove(dst)
            _log(logger, "건너뜀 DESK_ROW_HAS_FILE1")
            return ("S", "DESK_ROW_HAS_FILE1")
        cur.execute(sql, (docid, dst, stamp, upman, KIND))
        try:
            while cur.nextset():
                pass
        except Exception:
            pass
        conn.commit()
        _log(logger, "등록 성공 " + ("INSERT" if sql is SQL_INSERT else "UPDATE"))
        return ("Y", "")
    except tabletop_save.SaveError as exc:
        _rollback(conn)
        _safe_remove(dst)
        _log(logger, f"실패 {exc.code}")
        return ("N", exc.code)
    except Exception as exc:
        _rollback(conn)
        _safe_remove(dst)
        code = type(exc).__name__
        tabletop_save._dbdiag_write("deskfile", exc)
        _log(logger, f"실패 {code}")
        return ("N", code)
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _rollback(conn) -> None:
    try:
        if conn is not None:
            conn.rollback()
    except Exception:
        pass
