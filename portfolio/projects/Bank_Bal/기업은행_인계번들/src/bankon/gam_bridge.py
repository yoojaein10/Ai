"""`.gam`(EasyTable) → 구조화 데이터 + HWP 의견서.

gamexport.exe(Delphi)가 .gam 에서 BLOB(Ole%/pf_hwp%)과 구조화 테이블을
출력 폴더에 떨군다:
  - <table>.json      : 구조화 테이블(UTF-8)
  - <table>__<n>__<name> : BLOB 원본. **EasyTable 이 base64 텍스트로 저장**하므로
    base64 디코드해야 실제 바이트(HWP=OLE 복합문서)가 된다.
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import olefile

from .hwp_parser import HwpDocument, HwpParseError, parse_hwp


class GamBridgeError(Exception):
    """gam 처리 실패."""


@dataclass(frozen=True)
class Opinion:
    """추출된 의견서 1건."""

    source_name: str          # 추출 BLOB 파일명(타이틀 포함)
    document: HwpDocument
    payload: bytes = b""      # HWP 원본 바이트(열람용 로컬 저장 소스)
    file_path: str | None = None  # 로컬 저장 경로(pipeline 이 저장 후 스탬프)


@dataclass(frozen=True)
class GamData:
    tables: dict[str, list[dict]]      # gam_info / land_list0 / mullist0 ...
    opinions: tuple[Opinion, ...]

    @property
    def info(self) -> dict:
        """gam_info 의 단일 헤더 행(없으면 빈 dict)."""
        rows = self.tables.get("gam_info") or []
        return rows[0] if rows else {}


def run_gamexport(exe: str, gam_path: str, out_dir: str, *, timeout: int = 300) -> None:
    """gamexport.exe 를 실행해 out_dir 에 추출한다."""
    try:
        result = subprocess.run(
            [exe, gam_path, out_dir],
            capture_output=True,
            text=True,
            # gamexport 콘솔 출력은 CP949. 잘린 선행바이트 등 비정상 바이트가 섞여도
            # 리더 스레드가 UnicodeDecodeError 로 죽지 않게 replace(로그용 출력이라 무손실 불필요).
            encoding="cp949",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise GamBridgeError(f"gamexport 실행 실패: {error}") from error
    if result.returncode != 0:
        raise GamBridgeError(
            f"gamexport 비정상 종료(code={result.returncode}): {result.stdout}{result.stderr}"
        )


def _load_tables(out_dir: Path) -> dict[str, list[dict]]:
    tables: dict[str, list[dict]] = {}
    for json_path in out_dir.glob("*.json"):
        try:
            tables[json_path.stem] = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            raise GamBridgeError(f"테이블 JSON 로드 실패({json_path.name}): {error}") from error
    return tables


def _decode_blob(raw: bytes) -> bytes:
    """BLOB 파일을 실제 바이트로. base64 면 디코드, 아니면 원본."""
    if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return raw  # 이미 OLE 원본
    try:
        return base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError):
        return raw


def _extract_opinions(out_dir: Path) -> list[Opinion]:
    """BLOB 파일 중 HWP5 인 것만 의견서로 파싱."""
    opinions: list[Opinion] = []
    for path in sorted(out_dir.iterdir()):
        if path.suffix.lower() == ".json" or not path.is_file():
            continue
        data = _decode_blob(path.read_bytes())
        if not olefile.isOleFile(io.BytesIO(data)):
            continue  # 이미지 등 비 HWP OLE/기타 - 건너뜀
        try:
            document = parse_hwp(data)
        except HwpParseError:
            continue  # HWP5 가 아닌 OLE(다른 임베드 객체)
        opinions.append(Opinion(source_name=path.name, document=document, payload=data))
    return opinions


def load_extracted(out_dir: str) -> GamData:
    """이미 추출해 둔 폴더를 그대로 읽는다(gamexport 재실행 없음).

    `output/<문서번호>/` 에 남아 있는 추출물로 매핑을 다시 돌릴 때 쓴다 — FTP 다운로드도
    .gam 원본도 필요 없어서 매핑 회귀검사를 초 단위로 돌릴 수 있다.
    """
    out = Path(out_dir)
    if not out.is_dir():
        raise GamBridgeError(f"추출 폴더가 없습니다: {out_dir}")
    return GamData(tables=_load_tables(out), opinions=tuple(_extract_opinions(out)))


def process_gam(exe: str, gam_path: str, out_dir: str) -> GamData:
    """`.gam` 을 추출·파싱해 구조화 데이터와 의견서를 반환한다."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run_gamexport(exe, gam_path, out_dir)
    return GamData(
        tables=_load_tables(out),
        opinions=tuple(_extract_opinions(out)),
    )
