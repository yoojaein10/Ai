"""전례 공유폴더(\\\\jun\\JUN)에서 감정서 PDF 경로를 찾는다 — 'PDF등록'용.

실측 구조(2026-08-25, 2026년 담보 2,332폴더 전수):
    \\\\jun\\JUN\\0-2026년 on-line전례\\3-담보\\2501~3000\\01-2608-3-2676\\01-2608-3-2676.pdf
    ├ 연도 폴더: '0-2026년 on-line전례' (2022~2026). 옛날은 '0-2021년 online전례', '1-2020년 online전례',
    │            '2019년 on-line전례', '2015년 on-line전례-0/-1' 등 제각각 → 이름에 'YYYY년'과 '전례'가 있으면 인정.
    ├ 구분 폴더: 감정서번호 세 번째 마디(01-2608-**3**-2676)가 코드. 0-국세청 1-보상 2-경매 3-담보 4-일반거래
    │            5-컨설팅 6-공동주택가격자문 7-자산재평가 8-개별공시지가 9-감정평가서 적정성 검토결과서
    ├ 범위 폴더: 일련번호 500단위 '2501~3000' (4자리 0채움). 잘못 넣은 폴더가 있어(2359가 2501~3000 등) 폴백 탐색.
    ├ 건 폴더: 감정서번호 그대로가 대부분. '01-2601-3-0008(HUG)', '01-2606-3-1757 주금공' 처럼 꼬리가 붙거나
    │          '012604-3-1065-1'(대시 누락+재발행 접미)도 있음 → 접두 일치로 찾는다.
    └ 파일: '{감정서번호}.pdf'. 같은 폴더에 의뢰서.pdf·현장조사서.pdf·공부서류.pdf 등이 같이 있으니 이름을 꼭 맞춘다.
       드물게 '01-2601-3-0084 유청은.pdf' 처럼 이름 뒤에 뭔가 붙음 → 정확 이름 없으면 '{번호}*.pdf' 중 하나뿐일 때만 인정.
연도는 감정서번호 두 번째 마디 앞 두 자리(26 → 2026). 다른 지사(10-, 05-…)는 이 공유에 없다(본사 01- 전용).
"""
from __future__ import annotations

import re
from pathlib import Path

ARCHIVE_ROOT = Path(r"\\jun\JUN")
CATEGORY_NAMES = {
    "0": "0-국세청", "1": "1-보상", "2": "2-경매", "3": "3-담보", "4": "4-일반거래", "5": "5-컨설팅",
    "6": "6-공동주택가격자문", "7": "7-자산재평가", "8": "8-개별공시지가", "9": "9-감정평가서 적정성 검토결과서",
}
_DOC = re.compile(r"^(\d{2})-(\d{2})(\d{2})-(\d)-(\d{4})$")


class ArchiveError(RuntimeError):
    """전례 폴더에서 PDF 를 못 찾았다."""


def parse_doc(doc_id: str) -> tuple[str, int, str, int]:
    """(지사, 연도, 구분코드, 일련번호)."""
    match = _DOC.match(doc_id.strip())
    if not match:
        raise ArchiveError(f"감정서번호 형식이 아닙니다: {doc_id!r}")
    office, yy, _mm, category, seq = match.groups()
    return office, 2000 + int(yy), category, int(seq)


def range_folder(seq: int) -> str:
    low = (seq - 1) // 500 * 500 + 1
    return f"{low:04d}~{low + 499:04d}"


def _is_dir(p: Path) -> bool:
    """NAS 의 '#recycle' 같은 항목은 stat 만 해도 WinError 59 를 낸다 → 예외는 '폴더 아님'."""
    if p.name.startswith("#"):
        return False
    try:
        return p.is_dir()
    except OSError:
        return False


def year_folder(root: Path, year: int) -> Path:
    """'0-2026년 on-line전례' 처럼 연도와 '전례'가 들어간 폴더. 여럿이면 '0-' 접두를 우선."""
    found = [p for p in root.iterdir() if f"{year}년" in p.name and "전례" in p.name and _is_dir(p)]
    if not found:
        raise ArchiveError(f"{year}년 전례 폴더가 없습니다: {root}")
    found.sort(key=lambda p: (not p.name.startswith("0-"), p.name))
    return found[0]


def _doc_dirs(parent: Path, doc_id: str) -> list[Path]:
    """parent 바로 아래에서 이름이 감정서번호로 시작하는(꼬리 허용) 폴더. 대시 누락형도 허용."""
    compact = doc_id.replace("-", "")
    out = []
    for p in parent.iterdir():
        if not _is_dir(p):
            continue
        name = p.name.strip()
        if name.startswith(doc_id) or name.replace("-", "").startswith(compact):
            out.append(p)
    return out


# 감정서 PDF 가 아닌 같은 폴더의 관련 서류 — 느슨한 매칭에서 제외(2684: '01-2608-3-2684 현장조사.pdf' 를 감정서로 집던 사고, 2026-08-31)
RELATED_WORDS = ("현장조사", "수수료", "청구서", "공부", "의뢰서")


def _pdf_in(folder: Path, doc_id: str) -> Path | None:
    exact = folder / f"{doc_id}.pdf"
    if exact.is_file():
        return exact
    cands = [p for p in folder.glob("*.pdf") if p.is_file() and not any(w in p.name for w in RELATED_WORDS)]
    loose = [p for p in cands if p.name.startswith(doc_id)]
    if len(loose) == 1:
        return loose[0]
    # 파일명 오타('01-26208-3-2684.pdf', 2684 실물) — 번호 뒷자리를 담은 감정서 PDF 가 1개뿐이면 그것
    seq = doc_id.rsplit("-", 1)[-1]
    typo = [p for p in cands if seq in p.name and p.name.startswith(doc_id[:3])]
    return typo[0] if len(typo) == 1 else None


def find_pdf(doc_id: str, *, root: Path = ARCHIVE_ROOT) -> Path:
    """감정서 PDF 절대경로. 규칙 위치 → 같은 구분의 다른 범위 폴더 순으로 찾는다."""
    _office, year, category, seq = parse_doc(doc_id)
    year_dir = year_folder(root, year)
    cat_dir = year_dir / CATEGORY_NAMES[category]
    if not cat_dir.is_dir():
        raise ArchiveError(f"구분 폴더가 없습니다: {cat_dir}")
    expected = cat_dir / range_folder(seq)
    ranges = [expected] if expected.is_dir() else []
    ranges += [p for p in sorted(cat_dir.iterdir()) if p != expected and "~" in p.name and _is_dir(p)]
    tried = []
    for rng in ranges:
        for folder in _doc_dirs(rng, doc_id):
            pdf = _pdf_in(folder, doc_id)
            if pdf is not None:
                return pdf
            tried.append(folder)
    raise ArchiveError(
        f"{doc_id}.pdf 를 못 찾았습니다. 기대 위치 {expected}"
        + (f" / 폴더는 있으나 PDF 없음: {[str(t) for t in tried]}" if tried else ""))


def find_folder(doc_id: str, *, root: Path = ARCHIVE_ROOT) -> Path:
    """감정서 번호의 전례 폴더 — 감정서 PDF 가 **아직 없어도** 찾는다(감정서 PDF 가 든 폴더 우선, 없으면 첫 번호 폴더).

    관련 서류(현장조사서·수수료·공부)는 감정서보다 먼저 올라오는 일이 흔하다(2776 실측 2026-09-07: 현장조사서.pdf 는
    있는데 감정서 PDF 가 없어 현장조사서까지 '건너뜀'이 됐다). 종전엔 find_pdf(...).parent 라 감정서에 묶여 있었다."""
    try:
        return find_pdf(doc_id, root=root).parent
    except ArchiveError as error:
        _office, year, category, seq = parse_doc(doc_id)
        cat_dir = year_folder(root, year) / CATEGORY_NAMES[category]
        if cat_dir.is_dir():
            expected = cat_dir / range_folder(seq)
            ranges = [expected] if expected.is_dir() else []
            ranges += [p for p in sorted(cat_dir.iterdir()) if p != expected and "~" in p.name and _is_dir(p)]
            for rng in ranges:
                for folder in _doc_dirs(rng, doc_id):
                    return folder
        raise ArchiveError(f"{doc_id} 전례 폴더가 없습니다") from error


SURVEY_PDF_SUFFIX = " 현장조사.pdf"
# 국민 작성폼 PDF등록 창의 탭별 첨부 파일(감정서 PDF 와 같은 폴더, 2703 실물 2026-08-28):
#   '(관련)수수료 등' ← '<번호> 수수료.pdf', '관련서류' ← '<번호> 공부.pdf'
RELATED_PDF_KINDS = ("현장조사", "수수료", "공부")
# 종류별로 인정하는 파일명 단어(앞이 우선). 담당자마다 관례가 다름(2711 실물 2026-08-31: 번호 없는 '공부.pdf'·'청구서.pdf'·
# '현장조사서.pdf' 만 있어 exe 가 '수수료 PDF 못 찾음'으로 실패) → '청구서' 도 수수료로 인정(사용자 확정 2026-08-31).
RELATED_PDF_WORDS = {"수수료": ("수수료", "청구서"), "공부": ("공부",), "현장조사": ("현장조사",)}


def find_related_pdf(doc_id: str, kind: str, *, root: Path = ARCHIVE_ROOT) -> Path:
    """감정서 PDF 와 같은 폴더의 관련 서류 PDF(kind: 현장조사·수수료·공부). 찾는 순서 —
    ① '<번호> <단어>.pdf' ② 번호로 시작하고 단어를 담은 PDF 가 정확히 1개 ③ 번호 없는 '<단어>*.pdf'(예 '공부.pdf'·'청구서.pdf')가
    정확히 1개. 단어는 RELATED_PDF_WORDS 순서(수수료 → 청구서). 어느 단계든 후보가 2개 이상이면 고르지 않고 ArchiveError(fail-closed).
    없으면 ArchiveError — 감정서 PDF 로 대신 올리지 않는다(2703 현장조사서에 잘못 올린 전례)."""
    folder = find_folder(doc_id, root=root)         # 감정서 PDF 가 없어도 폴더만 있으면 찾는다(2026-09-07)
    words = RELATED_PDF_WORDS.get(kind, (kind,))
    ambiguous: list[Path] = []
    for word in words:
        exact = folder / f"{doc_id} {word}.pdf"
        if exact.is_file():
            return exact
        loose = sorted(p for p in folder.glob(f"{doc_id}*{word}*.pdf") if p.is_file())
        if len(loose) == 1:
            return loose[0]
        ambiguous += loose
    if not ambiguous:
        for word in words:
            bare = sorted(p for p in folder.glob(f"*{word}*.pdf") if p.is_file() and not p.name.startswith(doc_id))
            if len(bare) == 1:
                return bare[0]
            ambiguous += bare
    expected = folder / f"{doc_id} {words[0]}.pdf"
    raise ArchiveError(f"{kind} PDF 를 못 찾았습니다: {expected}"
                       + (f" (후보 {len(ambiguous)}개: {[p.name for p in ambiguous]})" if ambiguous else ""))


def find_survey_pdf(doc_id: str, *, root: Path = ARCHIVE_ROOT) -> Path:
    """현장조사서용 PDF — '<번호> 현장조사.pdf'(국민 전례 관례, 2026-08-27 사용자 지시).
    기업 전례는 번호 없는 '현장조사서.pdf'도 쓴다(2704·2682, 정찰 2026-08-28) → 번호형이 없을 때만 폴더 안 '*현장조사*.pdf' 가
    **정확히 1개**면 그것. 감정서 PDF 로 대신하지 않는다."""
    try:
        return find_related_pdf(doc_id, "현장조사", root=root)
    except ArchiveError as error:
        folder = find_folder(doc_id, root=root)
        loose = sorted(p for p in folder.glob("*현장조사*.pdf") if p.is_file())
        if len(loose) == 1:
            return loose[0]
        raise ArchiveError(f"{error} / 번호 없는 현장조사 PDF 후보 {len(loose)}개") from error

# ── 러너용: 종류별 PDF 확정(없으면 건너뜀) ─────────────────────────
PDF_FINDERS = {
    "감정서": lambda doc_id, root: find_pdf(doc_id, root=root),
    "현장조사": lambda doc_id, root: find_survey_pdf(doc_id, root=root),
    "수수료": lambda doc_id, root: find_related_pdf(doc_id, "수수료", root=root),
    "공부": lambda doc_id, root: find_related_pdf(doc_id, "공부", root=root),
}
MIN_PDF_BYTES = 1000


def locate_pdf(doc_id: str, kind: str, explicit: str | Path | None = None, *,
               root: Path = ARCHIVE_ROOT) -> tuple[Path | None, str | None]:
    """러너가 화면을 건드리기 전에 PDF 를 확정한다 → (경로, 건너뜀 사유).
    · 자동 탐색에서 **못 찾으면 (None, 사유)** — 러너는 그 PDF 등록만 건너뛰고 입력·저장은 진행해 '완료'로 남긴다
      (사용자 결정 2026-09-03: 로그에 'PDF 건너뜀' 표시, 사람이 확인해 수동 등록).
    · 자동 탐색으로 찾았는데 MIN_PDF_BYTES 미만(깨진 파일)이면 **그 PDF 등록만 건너뛴다** — (None, 사유)
      (사용자 결정 2026-09-07: 종전엔 ArchiveError 로 건 전체를 실패시켰음. 비고 'PDF 건너뜀' 으로 사람이 확인).
    · explicit(--pdf/--survey-pdf 로 지정한 파일)은 사람이 손으로 돌릴 때만 쓰므로 여전히 fail-closed —
      지정 파일이 없거나 깨졌으면 ArchiveError(큐 워커는 이 옵션을 쓰지 않는다)."""
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise ArchiveError(f"{kind} PDF 지정 파일이 없습니다: {path}")
    else:
        try:
            path = PDF_FINDERS[kind](doc_id, root)
        except ArchiveError as error:
            return None, str(error)
    size = path.stat().st_size
    if size < MIN_PDF_BYTES:
        if explicit:
            raise ArchiveError(f"{kind} PDF 가 비정상적으로 작습니다: {path} ({size}B)")
        return None, f"{kind} PDF 가 비정상적으로 작습니다(깨진 파일): {path} ({size}B)"
    return path, None
