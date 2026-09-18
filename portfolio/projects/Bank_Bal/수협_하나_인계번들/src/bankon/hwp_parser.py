"""HWP5 (한글) 의견서 본문 추출.

감정평가 의견서는 HWP5 형식(OLE 복합문서)이며, BodyText/Section* 스트림에
본문이 담긴다. pyhwp 등 외부 의존성 없이 표준 라이브러리 olefile + zlib 만으로
서술형 본문 텍스트를 추출한다.

설계 메모:
- HWP5 FileHeader: 32B 시그니처 "HWP Document File" + 4B 버전 + 4B 플래그.
  플래그 bit0 = 압축(BodyText 가 raw-deflate), bit1 = 암호화.
- 레코드 헤더(4B LE): tag=bits0-9, level=bits10-19, size=bits20-31.
  size==0xFFF 이면 다음 4B 가 실제 크기.
- HWPTAG_PARA_TEXT(0x43) 데이터는 UTF-16LE 텍스트 + 제어문자.
- **표**는 CTRL_HEADER(0x47, ctrl_id ' lbt'=tbl LE) → TABLE(0x4D, offset4 에
  rows/cols) → 셀마다 LIST_HEADER(0x48, offset8 부터 col/row/colspan/rowspan
  UINT16 — 실물 헥스 덤프로 확인) → 셀 문단들(레벨 깊음) 순의 자식 레코드.
  이를 HTML `<table>` 문자열 하나로 재구성해 문단으로 내보낸다(LLM 표 표현용).
  자기보다 얕은 레벨 레코드가 오면 표가 끝난 것. 중첩 표는 스택으로 처리.
"""
from __future__ import annotations

import html
import io
import struct
import zlib
from dataclasses import dataclass, field

import olefile

HWP5_SIGNATURE = "HWP Document File"
HWPTAG_PARA_TEXT = 0x43
HWPTAG_CTRL_HEADER = 0x47
HWPTAG_LIST_HEADER = 0x48
HWPTAG_TABLE = 0x4D
_CTRL_ID_TABLE = b" lbt"  # 'tbl ' 의 리틀엔디언 표기

# 본문 제어문자 분류 (HWP5 스펙)
#  - CHAR  : 1 wchar 차지
#  - INLINE_EXT : 8 wchar(16바이트) 차지
_CHAR_CONTROLS = frozenset((0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31))
_INLINE_EXT_CONTROLS = frozenset(
    (1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23)
)
_LINE_BREAKS = frozenset((10, 13))


class HwpParseError(Exception):
    """HWP 파싱 실패."""


@dataclass(frozen=True)
class HwpDocument:
    """추출된 HWP 문서. 불변."""

    version: str
    compressed: bool
    paragraphs: tuple[str, ...]

    @property
    def text(self) -> str:
        """빈 문단을 제외한 전체 본문."""
        return "\n".join(p for p in self.paragraphs if p.strip())


def _read_file_header(ole: olefile.OleFileIO) -> tuple[str, bool, bool]:
    """(version, compressed, encrypted) 반환."""
    raw = ole.openstream("FileHeader").read()
    if len(raw) < 40:
        raise HwpParseError("FileHeader 스트림이 너무 짧습니다.")
    signature = raw[:32].split(b"\x00", 1)[0].decode("latin1")
    if signature != HWP5_SIGNATURE:
        raise HwpParseError(f"HWP5 시그니처 불일치: {signature!r}")
    version_dword = struct.unpack("<I", raw[32:36])[0]
    flags = struct.unpack("<I", raw[36:40])[0]
    version = ".".join(
        str(b) for b in (
            version_dword >> 24,
            (version_dword >> 16) & 0xFF,
            (version_dword >> 8) & 0xFF,
            version_dword & 0xFF,
        )
    )
    return version, bool(flags & 1), bool(flags & 2)


def _iter_records(data: bytes):
    """(tag, level, payload) 레코드 스트림을 순회."""
    offset, size = 0, len(data)
    while offset + 4 <= size:
        header = struct.unpack("<I", data[offset:offset + 4])[0]
        offset += 4
        tag = header & 0x3FF
        level = (header >> 10) & 0x3FF
        length = (header >> 20) & 0xFFF
        if length == 0xFFF:
            if offset + 4 > size:
                break
            length = struct.unpack("<I", data[offset:offset + 4])[0]
            offset += 4
        yield tag, level, data[offset:offset + length]
        offset += length


def _decode_para_text(record: bytes) -> str:
    """PARA_TEXT 레코드에서 일반 문자만 추출(제어문자는 길이만큼 건너뜀)."""
    chars: list[str] = []
    pos, size = 0, len(record)
    while pos + 2 <= size:
        code = struct.unpack("<H", record[pos:pos + 2])[0]
        if code in _INLINE_EXT_CONTROLS:
            pos += 16
            continue
        if code in _CHAR_CONTROLS:
            if code in _LINE_BREAKS:
                chars.append("\n")
            pos += 2
            continue
        chars.append(chr(code))
        pos += 2
    return "".join(chars)


@dataclass
class _Cell:
    col: int
    row: int
    colspan: int
    rowspan: int
    texts: list[str] = field(default_factory=list)


@dataclass
class _Table:
    level: int                 # CTRL_HEADER 레코드의 level
    ready: bool = False        # TABLE 레코드 수신 후 True(캡션/셀 LIST_HEADER 구분)
    caption: list[str] = field(default_factory=list)
    cells: list[_Cell] = field(default_factory=list)


def _parse_cell(payload: bytes) -> _Cell | None:
    if len(payload) < 16:
        return None
    col, row, colspan, rowspan = struct.unpack_from("<HHHH", payload, 8)
    if colspan < 1 or rowspan < 1:
        return None
    return _Cell(col=col, row=row, colspan=colspan, rowspan=rowspan)


def _render_table(table: _Table) -> str:
    """셀들을 (row, col) 순으로 HTML <table> 문자열로 조립. 내용 없으면 ''."""
    has_text = any(t.strip() for c in table.cells for t in c.texts)
    if not has_text and not any(t.strip() for t in table.caption):
        return ""  # 셀 전부 빈 장식용(스페이서) 표는 스킵
    rows: dict[int, list[_Cell]] = {}
    for cell in table.cells:
        rows.setdefault(cell.row, []).append(cell)
    parts = ["<table>"]
    caption = "\n".join(t.strip() for t in table.caption if t.strip())
    if caption:
        parts.append(f"<caption>{caption}</caption>")
    for row in sorted(rows):
        parts.append("<tr>")
        for cell in sorted(rows[row], key=lambda c: c.col):
            attrs = ""
            if cell.colspan > 1:
                attrs += f' colspan="{cell.colspan}"'
            if cell.rowspan > 1:
                attrs += f' rowspan="{cell.rowspan}"'
            content = "\n".join(t.strip() for t in cell.texts if t.strip())
            parts.append(f"<td{attrs}>{content}</td>")
        parts.append("</tr>")
    parts.append("</table>")
    return "".join(parts)


def _section_paragraphs(section_data: bytes) -> list[str]:
    """PARA_TEXT 를 문단으로 추출하되, 표는 HTML 문자열 하나로 재구성한다."""
    paragraphs: list[str] = []
    stack: list[_Table] = []

    def close_tables(level: int) -> None:
        """level 이하로 돌아오면(형제/상위 레코드) 열린 표를 닫아 내보낸다."""
        while stack and level <= stack[-1].level:
            rendered = _render_table(stack.pop())
            if not rendered:
                continue
            if stack:  # 중첩 표 → 바깥 표의 현재 셀 내용으로
                sink = stack[-1].cells[-1].texts if stack[-1].cells else stack[-1].caption
                sink.append(rendered)
            else:
                paragraphs.append(rendered)

    for tag, level, payload in _iter_records(section_data):
        close_tables(level)
        if tag == HWPTAG_CTRL_HEADER:
            if payload[:4] == _CTRL_ID_TABLE:
                stack.append(_Table(level=level))
        elif tag == HWPTAG_TABLE:
            if stack and level == stack[-1].level + 1:
                stack[-1].ready = True
        elif tag == HWPTAG_LIST_HEADER:
            if stack and level == stack[-1].level + 1 and stack[-1].ready:
                cell = _parse_cell(payload)
                if cell is not None:
                    stack[-1].cells.append(cell)
        elif tag == HWPTAG_PARA_TEXT:
            text = _decode_para_text(payload)
            if stack:
                table = stack[-1]
                sink = table.cells[-1].texts if table.cells else table.caption
                sink.append(html.escape(text, quote=False))
            else:
                paragraphs.append(text)
    close_tables(-1)
    return paragraphs


def parse_hwp(source: str | bytes) -> HwpDocument:
    """HWP5 파일 경로 또는 바이트열에서 본문을 추출한다.

    Args:
        source: .hwp 파일 경로(str) 또는 파일 내용(bytes).

    Raises:
        HwpParseError: HWP5 가 아니거나 암호화되어 있거나 파싱에 실패한 경우.
    """
    payload: bytes | str
    if isinstance(source, bytes):
        payload = io.BytesIO(source)
    else:
        payload = source

    try:
        ole = olefile.OleFileIO(payload)
    except Exception as error:  # noqa: BLE001 - olefile 은 다양한 예외를 던진다
        raise HwpParseError(f"OLE 복합문서 열기 실패: {error}") from error

    try:
        version, compressed, encrypted = _read_file_header(ole)
        if encrypted:
            raise HwpParseError("암호화된 HWP 는 지원하지 않습니다.")

        sections = sorted(
            entry for entry in ole.listdir() if entry and entry[0] == "BodyText"
        )
        if not sections:
            raise HwpParseError("BodyText 섹션이 없습니다.")

        paragraphs: list[str] = []
        for section in sections:
            raw = ole.openstream(section).read()
            try:
                data = zlib.decompress(raw, -15) if compressed else raw
            except zlib.error as error:
                raise HwpParseError(
                    f"섹션 압축 해제 실패({'/'.join(section)}): {error}"
                ) from error
            paragraphs.extend(_section_paragraphs(data))
    finally:
        ole.close()

    return HwpDocument(
        version=version,
        compressed=compressed,
        paragraphs=tuple(paragraphs),
    )
