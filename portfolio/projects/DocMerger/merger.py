"""
2차 처리: Unreadable 래스터화 + 최종 PDF 병합 + PDF 압축 + PDF 분할
"""
import io
import re
import shutil
import fitz  # PyMuPDF
from pathlib import Path
from PIL import Image


DPI = 200  # Unreadable 래스터화 해상도 (150~300 권장)
_MATRIX = fitz.Matrix(DPI / 72, DPI / 72)

# 강한 압축 프리셋: (DPI, JPEG quality)
_STRONG_PRESETS = {
    "high":   (150, 85),
    "medium": (120, 72),
    "low":    (96,  55),
}


def rasterize_to_image_pdf(src_pdf: str, out_pdf: str):
    """
    텍스트 레이어가 있는 PDF → 전 페이지를 이미지로 굽고 새 PDF에 임베딩.
    결과물은 복사/검색이 불가능한 순수 이미지 PDF.
    """
    src = fitz.open(src_pdf)
    out = fitz.open()

    for page in src:
        pix = page.get_pixmap(matrix=_MATRIX, alpha=False)
        # 픽셀 이미지를 새 PDF 페이지에 직접 삽입 (Tesseract 불필요)
        img_page = out.new_page(width=pix.width, height=pix.height)
        img_page.insert_image(img_page.rect, stream=pix.tobytes("png"))

    out.save(out_pdf, garbage=4, deflate=True)
    src.close()
    out.close()


def merge_pdfs(pdf_paths: list[str], out_path: str):
    """
    pdf_paths 순서대로 병합 → out_path 단일 PDF 저장.
    """
    merged = fitz.open()

    for path in pdf_paths:
        doc = fitz.open(path)
        merged.insert_pdf(doc)
        doc.close()

    merged.save(out_path, garbage=4, deflate=True)
    merged.close()


# ── PDF 압축 ─────────────────────────────────────────────────────────────────

def compress_pdf_basic(src_pdf: str, out_pdf: str):
    """
    기본 압축: garbage collection + deflate + clean.
    텍스트 레이어를 그대로 유지한다.
    """
    doc = fitz.open(src_pdf)
    try:
        doc.save(out_pdf, garbage=4, deflate=True, clean=True)
    finally:
        doc.close()


def compress_pdf_strong(src_pdf: str, out_pdf: str, quality_level: str = "high"):
    """
    강한 압축: 각 페이지를 이미지(JPEG)로 렌더링 후 새 PDF로 재구성.
    주의 — 텍스트 레이어가 사라져 검색/복사가 불가능해진다.

    quality_level: "high" | "medium" | "low"
    """
    if quality_level not in _STRONG_PRESETS:
        quality_level = "high"
    dpi, jpeg_q = _STRONG_PRESETS[quality_level]
    matrix = fitz.Matrix(dpi / 72, dpi / 72)

    src = fitz.open(src_pdf)
    out = fitz.open()
    try:
        for page in src:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            # PyMuPDF Pixmap → PIL → JPEG 바이트로 압축
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=jpeg_q, optimize=True)
            jpeg_bytes = buf.getvalue()
            img.close()

            new_page = out.new_page(width=pix.width, height=pix.height)
            new_page.insert_image(new_page.rect, stream=jpeg_bytes)

        out.save(out_pdf, garbage=4, deflate=True, clean=True)
    finally:
        src.close()
        out.close()

    # 압축 결과가 원본보다 클 경우 원본을 출력 경로로 복사
    if (Path(out_pdf).resolve() != Path(src_pdf).resolve()
            and Path(out_pdf).stat().st_size > Path(src_pdf).stat().st_size):
        shutil.copy2(src_pdf, out_pdf)


def compress_pdf(src_pdf: str, out_pdf: str, mode: str = "none",
                 quality_level: str = "high"):
    """
    PDF 압축 디스패처.
    mode: "none" | "basic" | "strong"
    """
    if mode == "none":
        # 동일 경로면 복사 생략
        if Path(src_pdf).resolve() == Path(out_pdf).resolve():
            return
        shutil.copy2(src_pdf, out_pdf)
        return

    if mode == "basic":
        compress_pdf_basic(src_pdf, out_pdf)
        return

    if mode == "strong":
        compress_pdf_strong(src_pdf, out_pdf, quality_level)
        return

    raise ValueError(f"알 수 없는 압축 모드: {mode}")


# ── PDF 분할 ─────────────────────────────────────────────────────────────────

def parse_page_ranges(range_text: str, page_count: int) -> list[int]:
    """
    사용자 입력(1-based) → 0-based 인덱스 리스트 (중복 제거, 입력 순 유지).
    range_text 예: "1-3,5,8-10"
    """
    text = range_text.strip()
    if not text:
        raise ValueError("페이지 범위를 입력하세요.")
    if re.search(r'[^0-9,\-\s]', text):
        raise ValueError(f"숫자, 콤마, 하이픈만 입력할 수 있습니다: '{text}'")

    seen: set[int] = set()
    pages: list[int] = []

    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            halves = part.split("-", 1)
            try:
                s, e = int(halves[0].strip()), int(halves[1].strip())
            except ValueError:
                raise ValueError(f"잘못된 범위 형식: '{part}'")
            if s < 1 or e < 1:
                raise ValueError(f"페이지 번호는 1 이상이어야 합니다: '{part}'")
            if s > e:
                raise ValueError(f"시작 페이지가 끝 페이지보다 큽니다: '{part}'")
            if e > page_count:
                raise ValueError(
                    f"페이지 {e}는 전체 페이지 수({page_count})를 초과합니다.")
            for p in range(s, e + 1):
                if p not in seen:
                    seen.add(p)
                    pages.append(p - 1)
        else:
            try:
                p = int(part)
            except ValueError:
                raise ValueError(f"숫자를 확인하세요: '{part}'")
            if p < 1:
                raise ValueError(f"페이지 번호는 1 이상이어야 합니다: '{part}'")
            if p > page_count:
                raise ValueError(
                    f"페이지 {p}는 전체 페이지 수({page_count})를 초과합니다.")
            if p not in seen:
                seen.add(p)
                pages.append(p - 1)

    if not pages:
        raise ValueError("유효한 페이지가 없습니다.")
    return pages


def split_pdf_by_ranges(src_pdf: str, out_pdf: str, pages: list[int]):
    """0-based 페이지 인덱스 리스트 → 해당 페이지만 새 PDF로 저장."""
    src = fitz.open(src_pdf)
    out = fitz.open()
    try:
        for p in pages:
            out.insert_pdf(src, from_page=p, to_page=p)
        out.save(out_pdf, garbage=4, deflate=True)
    finally:
        src.close()
        out.close()


def split_pdf_each_page(src_pdf: str, output_dir: str, stem: str) -> list[str]:
    """각 페이지를 output_dir에 개별 PDF로 저장. 저장된 경로 리스트 반환."""
    src = fitz.open(src_pdf)
    out_paths: list[str] = []
    try:
        total = src.page_count
        digits = max(3, len(str(total)))
        for i in range(total):
            basename = f"{stem}_page_{str(i + 1).zfill(digits)}"
            out_path = make_unique_split_path(output_dir, basename)
            one = fitz.open()
            one.insert_pdf(src, from_page=i, to_page=i)
            one.save(out_path, garbage=4, deflate=True)
            one.close()
            out_paths.append(out_path)
    finally:
        src.close()
    return out_paths


def make_unique_split_path(output_dir: str, basename: str) -> str:
    """output_dir/basename.pdf, 충돌 시 basename_1.pdf ..."""
    base = Path(output_dir) / f"{basename}.pdf"
    if not base.exists():
        return str(base)
    i = 1
    while True:
        cand = Path(output_dir) / f"{basename}_{i}.pdf"
        if not cand.exists():
            return str(cand)
        i += 1


def extract_selected_pages(src_pdf: str, page_indices: list[int], out_pdf: str):
    """0-based 인덱스 리스트 → 선택 페이지를 하나의 PDF로 저장."""
    src = fitz.open(src_pdf)
    out = fitz.open()
    try:
        for p in page_indices:
            out.insert_pdf(src, from_page=p, to_page=p)
        out.save(out_pdf, garbage=4, deflate=True)
    finally:
        src.close()
        out.close()


def split_selected_each(src_pdf: str, page_indices: list[int],
                        output_dir: str, stem: str) -> list[str]:
    """선택 페이지 각각을 개별 PDF로 저장. 저장된 경로 리스트 반환."""
    total_pdf_pages = max(page_indices) + 1 if page_indices else 1
    digits = max(3, len(str(total_pdf_pages)))
    src = fitz.open(src_pdf)
    out_paths: list[str] = []
    try:
        for p in page_indices:
            basename = f"{stem}_page_{str(p + 1).zfill(digits)}"
            out_path = make_unique_split_path(output_dir, basename)
            one = fitz.open()
            one.insert_pdf(src, from_page=p, to_page=p)
            one.save(out_path, garbage=4, deflate=True)
            one.close()
            out_paths.append(out_path)
    finally:
        src.close()
    return out_paths


# ── PDF 보안 ──────────────────────────────────────────────────────────────────

def set_pdf_password(src_pdf: str, out_pdf: str, user_pw: str, owner_pw: str = ""):
    """AES-256 열기 암호 설정. 이미 암호 있으면 ValueError."""
    if Path(out_pdf).resolve() == Path(src_pdf).resolve():
        raise ValueError(
            "출력 경로가 원본과 동일합니다."
        )
    doc = fitz.open(src_pdf)
    try:
        if doc.needs_pass:
            raise ValueError(
                "이미 암호가 설정된 PDF입니다. 먼저 암호를 해제하세요."
            )
        all_perms = (
            fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY | fitz.PDF_PERM_MODIFY
            | fitz.PDF_PERM_ANNOTATE | fitz.PDF_PERM_FORM
            | fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_ASSEMBLE
            | fitz.PDF_PERM_PRINT_HQ
        )
        doc.save(
            out_pdf,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw=user_pw,
            owner_pw=owner_pw or user_pw,
            permissions=all_perms,
        )
    finally:
        doc.close()


def remove_pdf_password(src_pdf: str, out_pdf: str, password: str):
    """암호 인증 후 해제. 암호 없는 파일·잘못된 암호는 ValueError."""
    if Path(out_pdf).resolve() == Path(src_pdf).resolve():
        raise ValueError(
            "출력 경로가 원본과 동일합니다."
        )
    doc = fitz.open(src_pdf)
    try:
        if not doc.needs_pass:
            raise ValueError("이 파일에는 암호가 없습니다.")
        if doc.authenticate(password) == 0:
            raise ValueError("암호가 올바르지 않습니다.")
        doc.save(out_pdf, encryption=fitz.PDF_ENCRYPT_NONE)
    finally:
        doc.close()


def save_edited_pdf(src_pdf: str, page_ops: list[dict], out_pdf: str):
    """
    page_ops 순서대로 페이지를 새 PDF에 저장한다.
    page_ops: [{"idx": int, "rotation": int}, ...]  (0-based, rotation degrees)
    원본 경로와 동일한 출력 경로는 거부한다.
    """
    if Path(out_pdf).resolve() == Path(src_pdf).resolve():
        raise ValueError(
            "출력 경로가 원본과 동일합니다. 다른 저장 경로를 선택하세요."
        )
    src = fitz.open(src_pdf)
    out = fitz.open()
    try:
        for op in page_ops:
            out.insert_pdf(src, from_page=op["idx"], to_page=op["idx"])
            if op["rotation"] != 0:
                original_rot = out[-1].rotation
                new_rot = (original_rot + op["rotation"]) % 360
                out[-1].set_rotation(new_rot)
        out.save(out_pdf, garbage=4, deflate=True)
    finally:
        src.close()
        out.close()
