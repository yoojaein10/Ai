"""
1차 정규화: 모든 포맷 → 임시 PDF (텍스트 레이어 보존)
"""
import os
import uuid
import shutil
import tempfile
import subprocess
from pathlib import Path


# win32com은 Windows 전용, import 실패 시 Fallback 경로 사용
try:
    import win32com.client
    import pythoncom
    _WIN32COM = True
except ImportError:
    _WIN32COM = False

import fitz  # PyMuPDF — 이미지→PDF 변환에도 사용 (img2pdf 충돌 대체)
from PIL import Image


SUPPORTED_EXT = {
    ".hwp", ".hwpx",
    ".docx", ".doc",
    ".pdf",
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif",
    ".html", ".htm",
}

# 환경 플래그: 첫 COM 실패 시 이후 호출 스킵
_HWP_COM_AVAILABLE  = None
_WORD_COM_AVAILABLE = None


def to_temp_pdf(src_path: str, tmp_dir: str) -> str:
    """
    src_path 파일을 텍스트가 살아있는 임시 PDF로 변환.
    반환값: 생성된 임시 PDF 경로
    """
    ext = Path(src_path).suffix.lower()

    if ext in (".hwp", ".hwpx"):
        return _hwp_to_pdf(src_path, tmp_dir)

    if ext in (".docx", ".doc"):
        return _word_to_pdf(src_path, tmp_dir)

    if ext == ".pdf":
        return src_path  # 패스스루

    if ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"):
        return _image_to_pdf(src_path, tmp_dir)

    if ext in (".html", ".htm"):
        return _html_to_pdf(src_path, tmp_dir)

    raise ValueError(f"지원하지 않는 형식: {ext}")


# ── HWP 변환 ─────────────────────────────────────────────────────────────────

def _hwp_to_pdf(src: str, tmp_dir: str) -> str:
    global _HWP_COM_AVAILABLE
    out = _tmp_pdf_path(src, tmp_dir)

    if _WIN32COM and _HWP_COM_AVAILABLE is not False:
        try:
            _hwp_via_com(src, out)
            _HWP_COM_AVAILABLE = True
            return out
        except Exception:
            _HWP_COM_AVAILABLE = False

    # Fallback: airun-hwp CLI
    return _hwp_via_airun(src, out)


def _hwp_via_com(src: str, out: str):
    pythoncom.CoInitialize()
    hwp = None
    try:
        hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
        hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        hwp.Open(os.path.abspath(src), "HWP", "forceopen:true")
        hwp.SaveAs(os.path.abspath(out), "PDF", "")
    finally:
        if hwp:
            hwp.Quit()
        pythoncom.CoUninitialize()


def _hwp_via_airun(src: str, out: str) -> str:
    result = subprocess.run(
        ["airun-hwp", src, "--format", "pdf", "--output", out],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"airun-hwp 실패: {result.stderr}")
    return out


# ── DOCX 변환 ────────────────────────────────────────────────────────────────

def _word_to_pdf(src: str, tmp_dir: str) -> str:
    global _WORD_COM_AVAILABLE
    out = _tmp_pdf_path(src, tmp_dir)

    if _WIN32COM and _WORD_COM_AVAILABLE is not False:
        try:
            _word_via_com(src, out)
            _WORD_COM_AVAILABLE = True
            return out
        except Exception:
            _WORD_COM_AVAILABLE = False

    # Fallback: LibreOffice
    return _word_via_libreoffice(src, tmp_dir)


def _word_via_com(src: str, out: str):
    pythoncom.CoInitialize()
    word = None
    doc  = None
    try:
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        doc = word.Documents.Open(os.path.abspath(src))
        # wdFormatPDF = 17
        doc.SaveAs2(os.path.abspath(out), FileFormat=17)
    finally:
        if doc:
            doc.Close(False)
        if word:
            word.Quit()
        pythoncom.CoUninitialize()


def _word_via_libreoffice(src: str, tmp_dir: str) -> str:
    soffice = _find_libreoffice()
    if not soffice:
        raise RuntimeError("LibreOffice를 찾을 수 없습니다. LibreOffice를 설치하거나 MS Word를 설치하세요.")
    result = subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp_dir, src],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"LibreOffice 실패: {result.stderr}")
    base = Path(src).stem + ".pdf"
    return str(Path(tmp_dir) / base)


def _find_libreoffice() -> str | None:
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


# ── 이미지 변환 ──────────────────────────────────────────────────────────────

def _image_to_pdf(src: str, tmp_dir: str) -> str:
    """이미지 → 이미지 PDF (PyMuPDF 사용, 텍스트 레이어 없음)"""
    out = _tmp_pdf_path(src, tmp_dir)

    # RGBA / P 모드는 JPEG 저장 불가 → RGB 변환 후 임시 파일 경유
    img = Image.open(src)
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
        tmp_jpg = os.path.join(tmp_dir, Path(src).stem + "_conv.jpg")
        img.save(tmp_jpg, "JPEG", quality=95)
        src = tmp_jpg

    doc = fitz.open()
    with open(src, "rb") as f:
        img_bytes = f.read()
    ext = Path(src).suffix.lstrip(".").lower()
    rect = fitz.Rect(0, 0, 595, 842)  # A4 기본 크기 (pt)

    # 실제 이미지 크기 비율로 rect 조정
    pil = Image.open(src)
    w, h = pil.size
    scale = min(595 / w, 842 / h)
    rect = fitz.Rect(0, 0, w * scale, h * scale)

    page = doc.new_page(width=rect.width, height=rect.height)
    page.insert_image(rect, stream=img_bytes)
    doc.save(out)
    doc.close()
    return out


# ── HTML 변환 ────────────────────────────────────────────────────────────────

def _html_to_pdf(src: str, tmp_dir: str) -> str:
    """
    HTML/HTM → PDF. 우선순위:
      1) wkhtmltopdf — 콘텐츠 높이 계산 후 --page-height 지정 → 단일 긴 페이지
      2) WeasyPrint fallback
    """
    out = _tmp_pdf_path(src, tmp_dir)

    # ── 1) wkhtmltopdf ───────────────────────────────────────────────────
    wk = _find_wkhtmltopdf()
    if wk:
        try:
            preprocessed = _preprocess_html(src, tmp_dir)
            zoom = _calc_zoom(preprocessed)
            page_height_mm = _calc_page_height_mm(src, zoom)
            # A4 폭(210mm)을 고정하고 높이만 크게 설정 → 단일 긴 페이지
            # --page-width와 --page-height를 동시에 줘야 wkhtmltopdf가 커스텀 크기를 인식
            result = subprocess.run(
                [wk,
                 "--quiet",
                 "--enable-local-file-access",
                 "--disable-smart-shrinking",
                 "--zoom",          str(zoom),
                 "--page-width",    "210mm",
                 "--page-height",   f"{page_height_mm:.0f}mm",
                 "--margin-top",    "0",
                 "--margin-bottom", "0",
                 "--margin-left",   "0",
                 "--margin-right",  "0",
                 preprocessed, os.path.abspath(out)],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0 and os.path.exists(out):
                # 하단 여백 제거 후 반환
                trimmed = _tmp_pdf_path(src, tmp_dir)
                _trim_bottom_whitespace(out, trimmed)
                return trimmed
        except Exception:
            pass

    # ── 2) WeasyPrint fallback ────────────────────────────────────────────
    try:
        from weasyprint import HTML
        HTML(filename=os.path.abspath(src)).write_pdf(out)
        if os.path.exists(out):
            return out
    except ImportError:
        pass
    except Exception as e:
        raise RuntimeError(f"WeasyPrint HTML 변환 실패: {e}")

    raise RuntimeError(
        "HTML/HTM 변환에는 다음 중 하나가 필요합니다:\n"
        "1. wkhtmltopdf (https://wkhtmltopdf.org)\n"
        "2. pip install weasyprint"
    )


def _calc_zoom(src: str) -> float:
    """HTML 콘텐츠 폭 기반으로 A4 페이지를 꽉 채우는 zoom 계산."""
    import re
    try:
        with open(src, encoding="utf-8", errors="replace") as f:
            html = f.read()
        # 단어 경계로 width= 속성만 매칭 (marginwidth 등 제외)
        m = re.search(r'<(?:table|div)[^>]+(?<![a-z])width=["\']?(\d+)', html, re.IGNORECASE)
        if m:
            px = int(m.group(1))
            if 400 <= px <= 1600:
                # A4 @ 96dpi = 793.7px, 양쪽 여백 0 → zoom = 793/content_px
                zoom = round(793.0 / px, 2)
                return min(max(zoom, 0.5), 3.0)
    except Exception:
        pass
    return 1.0


def _calc_page_height_mm(src: str, zoom: float) -> float:
    """HTML 루트 컨테이너 height 속성으로 단일 페이지 높이(mm) 계산."""
    import re
    try:
        with open(src, encoding="utf-8", errors="replace") as f:
            html = f.read()
        m = re.search(r'<(?:table|div)[^>]+(?<![a-z])height=["\']?(\d+)', html, re.IGNORECASE)
        if m:
            px = int(m.group(1))
            if px > 100:
                height_mm = px * zoom / 96.0 * 25.4
                return round(height_mm + 30, 0)   # 30mm 여유
    except Exception:
        pass
    return 5000.0  # fallback: 5m (충분히 큰 값)


def _trim_bottom_whitespace(src_pdf: str, out: str):
    """단일 페이지 PDF 하단 빈 공간 제거 (저해상도 스캔 방식)."""
    try:
        doc = fitz.open(src_pdf)
        page = doc[0]
        W, H = page.rect.width, page.rect.height

        # 5dpi로 렌더 → 빠른 스캔
        scale = 5 / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY)
        samples = pix.samples  # bytes, grayscale

        # 하단에서 위로 스캔: 첫 번째 비흰색 행 찾기
        last_content_row = 0
        pw = pix.width
        for row in range(pix.height - 1, -1, -1):
            line = samples[row * pw:(row + 1) * pw]
            if any(b < 250 for b in line):
                last_content_row = row
                break

        doc.close()

        if last_content_row <= 0:
            import shutil as _sh
            _sh.copy(src_pdf, out)
            return

        # pt 환경으로 변환 (+10pt 여유)
        new_h = min((last_content_row + 1) / scale + 10, H)

        src = fitz.open(src_pdf)
        dst = fitz.open()
        big = dst.new_page(width=W, height=new_h)
        big.show_pdf_page(fitz.Rect(0, 0, W, new_h), src, 0,
                          clip=fitz.Rect(0, 0, W, new_h))
        dst.save(out)
        dst.close()
        src.close()
    except Exception:
        import shutil as _sh
        _sh.copy(src_pdf, out)


def _preprocess_html(src: str, tmp_dir: str) -> str:
    """테이블 고정 height 속성 제거 → wkhtmltopdf 페이지 나눔 공백 방지"""
    import re
    with open(src, encoding="utf-8", errors="replace") as f:
        html = f.read()
    # table/tr/td/th 의 height 속성 제거
    html = re.sub(r'(<(?:table|tr|td|th)[^>]*)\s+height=["\']\d+["\']', r'\1', html, flags=re.IGNORECASE)
    # style 내 height 고정값도 auto로 교체 (table 요소 한정)
    html = re.sub(r'(<(?:table|tr|td|th)[^>]*style=["\'][^"\']*)\bheight\s*:\s*\d+px', r'\1height:auto', html, flags=re.IGNORECASE)
    out = os.path.join(tmp_dir, Path(src).stem + "_pre.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out


def _find_wkhtmltopdf() -> str | None:
    import sys
    candidates = []
    # PyInstaller EXE 내장 경로 (sys._MEIPASS)
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, "wkhtmltopdf.exe"))
    candidates += [
        r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe",
        r"C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return shutil.which("wkhtmltopdf")


# ── 유틸 ─────────────────────────────────────────────────────────────────────

def _tmp_pdf_path(src: str, tmp_dir: str) -> str:
    return str(Path(tmp_dir) / (Path(src).stem + "_" + uuid.uuid4().hex[:8] + "_tmp.pdf"))


def make_tmp_dir() -> str:
    return tempfile.mkdtemp(prefix="docmerger_")


def cleanup_tmp_dir(tmp_dir: str):
    import shutil
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass
