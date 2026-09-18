# -*- coding: utf-8 -*-
"""선택형 자동 인쇄 (비필수 후처리).

이 모듈은 '이번 실행에서 앱이 직접 저장·검증한 PDF'만을 대상으로, 사용자가 GUI에서
선택한 Windows 프린터로 문서당 1부를 출력한다. 인쇄는 non-blocking 후처리이며,
어떤 실패도 예외로 전파되지 않고 상위 작업 루프/DB 트랜잭션에 영향을 주지 않는다.

보안·안전 설계 요약:
- PDF를 셸/외부 뷰어/ShellExecute/os.system 등으로 열지 않는다. PyMuPDF로 각 페이지를
  고정 DPI 래스터로 렌더링(능동 콘텐츠 미실행)한 뒤 Windows GDI(win32ui)로만 출력한다.
- 프린터명·파일 경로를 명령 문자열에 보간하지 않는다(외부 프로세스 자체를 쓰지 않음).
- 대상 PDF는 허용 출력 디렉터리 하위의 일반 파일로 제한하고, 심볼릭/재분석 지점·경로
  탈출·저장 후 교체가 의심되면 인쇄만 건너뛴다.
- 로그/예외에 개인정보(담당자명·전화번호·주소·문서번호·프린터명·경로·PDF 버퍼·traceback)를
  남기지 않는다. 실패 사유는 비식별 코드로만 관리한다.

Windows GDI/win32print 경계는 Backend로 분리해 테스트에서 mock 처리한다(실제 스풀러에
작업을 제출하지 않고 검증 가능).
"""
from __future__ import annotations

import os
import stat

# ── 상수 (근거는 모듈 하단 최종 보고/주석 참조) ───────────────────────────────
# 렌더링 해상도: 300 DPI. 의뢰서 텍스트 가독성에 충분하며, 페이지당 메모리/시간이
# 예측 가능한 범위(A4 300DPI ≈ 8.7M px)로 고정된다.
RENDER_DPI = 300

# 파일 크기 상한: 30MB. 실제 은행 의뢰서 PDF는 수십 KB~수 MB 수준이므로, 비정상적으로
# 큰 파일로 인한 메모리·인쇄 폭주를 막는 보수적 상한이다.
MAX_PDF_BYTES = 30 * 1024 * 1024

# 페이지 수 상한: 20페이지. 의뢰서는 통상 1~3페이지이므로, 대량 페이지 렌더링 폭주를
# 방지하는 여유 상한이다.
MAX_PDF_PAGES = 20

# 실행당 인쇄 작업 상한 기본값 100건. 설정에서 낮출 수 있으나(HARD 상한으로 clamp)
# 일반 GUI에서는 노출하지 않아 실수로 무제한이 될 수 없다.
DEFAULT_MAX_JOBS_PER_RUN = 100
HARD_MAX_JOBS_PER_RUN = 500  # 조작된 설정값도 이 값을 넘길 수 없다(무제한 방지).

# 문서당 인쇄 매수는 1부로 고정한다.
COPIES = 1

PDF_SIGNATURE = b"%PDF-"

# ── 상태(문서별, PDF/파싱/DB 상태와 분리) ────────────────────────────────────
PRINT_OK = "인쇄 성공"
PRINT_SKIP = "인쇄 건너뜀"
PRINT_FAIL = "인쇄 실패"
PRINT_UNCERTAIN = "결과 확인 필요"

# 비식별 사유 코드 (원문 PII 없음)
CODE_AUTOPRINT_OFF = "AUTOPRINT_OFF"
CODE_NO_PRINTER = "NO_PRINTER_SELECTED"
CODE_PRINTER_NOT_FOUND = "PRINTER_NOT_FOUND"
CODE_PRINTER_AMBIGUOUS = "PRINTER_AMBIGUOUS"
CODE_PRINTER_NOT_READY = "PRINTER_NOT_READY"
CODE_PRINTER_QUERY_FAIL = "PRINTER_QUERY_FAIL"
CODE_PATH_OUTSIDE = "PATH_OUTSIDE_ALLOWED"
CODE_PATH_SYMLINK = "PATH_SYMLINK_OR_REPARSE"
CODE_NOT_REGULAR = "NOT_REGULAR_FILE"
CODE_FILE_MISSING = "FILE_MISSING"
CODE_BAD_EXT = "BAD_EXTENSION"
CODE_BAD_SIGNATURE = "BAD_PDF_SIGNATURE"
CODE_TOO_LARGE = "TOO_LARGE"
CODE_TOO_MANY_PAGES = "TOO_MANY_PAGES"
CODE_EMPTY_PDF = "EMPTY_PDF"
CODE_RUN_LIMIT = "RUN_LIMIT_EXCEEDED"
CODE_ALREADY_PRINTED = "ALREADY_PRINTED"
CODE_RENDER_ERROR = "RENDER_ERROR"
CODE_SUBMIT_UNCERTAIN = "SUBMIT_RESULT_UNCERTAIN"
CODE_INTERNAL = "INTERNAL_ERROR"
CODE_OK = "OK"


class PrintResult:
    """문서별 인쇄 결과. job_id는 실행별 비식별 순번(개인정보 없음)."""
    __slots__ = ("status", "code", "job_id")

    def __init__(self, status, code, job_id=None):
        self.status = status
        self.code = code
        self.job_id = job_id

    def __repr__(self):  # 디버깅용 — PII 없음(상태/코드/순번만)
        return f"PrintResult(status={self.status!r}, code={self.code!r}, job_id={self.job_id!r})"

    def __eq__(self, other):
        return (isinstance(other, PrintResult)
                and self.status == other.status
                and self.code == other.code
                and self.job_id == other.job_id)


def clamp_max_jobs(value) -> int:
    """실행당 인쇄 상한을 안전 범위로 강제. 손상값은 기본값으로 처리."""
    try:
        v = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_MAX_JOBS_PER_RUN
    if v < 0:
        return DEFAULT_MAX_JOBS_PER_RUN
    if v > HARD_MAX_JOBS_PER_RUN:
        return HARD_MAX_JOBS_PER_RUN
    return v


def parse_bool_strict(value):
    """명시적 boolean 형식만 허용. 그 외에는 None(=불명확)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off"):
        return False
    return None


# ── 페이지 배치 계산 (순수 함수, 단위 테스트 대상) ────────────────────────────
def compute_placement(page_w_pt, page_h_pt,
                      printable_w_px, printable_h_px,
                      dpi_x, dpi_y):
    """페이지 실제 크기·방향을 존중하며 인쇄 가능 영역 안에 비율 유지로 맞춘 사각형.

    반환: (x, y, w, h) 정수 device pixel. 자르기·왜곡 없이 중앙 정렬한다.
    page_*_pt: PDF 포인트(1/72 inch). dpi_*: 프린터 device 논리 DPI.
    """
    if page_w_pt <= 0 or page_h_pt <= 0:
        raise ValueError("invalid page size")
    if printable_w_px <= 0 or printable_h_px <= 0 or dpi_x <= 0 or dpi_y <= 0:
        raise ValueError("invalid device metrics")
    # 실제 크기를 device pixel로 환산 (inch = pt/72)
    full_w = (page_w_pt / 72.0) * dpi_x
    full_h = (page_h_pt / 72.0) * dpi_y
    # 비율 유지 fit (가로/세로 중 더 제한적인 배율). 왜곡·자르기 없음.
    scale = min(printable_w_px / full_w, printable_h_px / full_h)
    target_w = full_w * scale
    target_h = full_h * scale
    x = (printable_w_px - target_w) / 2.0
    y = (printable_h_px - target_h) / 2.0
    return (int(round(x)), int(round(y)),
            max(1, int(round(target_w))), max(1, int(round(target_h))))


# ── 경로/파일 검증 (허용 디렉터리·심볼릭·시그니처·크기·페이지) ────────────────
class _Skip(Exception):
    """인쇄만 건너뛰는 내부 신호(비식별 코드 포함)."""
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


def validate_target_path(pdf_path, allowed_dir):
    """대상이 허용 출력 디렉터리 하위의 '실제 일반 파일'인지 검증.

    통과 시 정규화된 realpath 문자열 반환. 위반 시 _Skip(code) 발생.
    - realpath 정규화 후 허용 디렉터리 하위인지 확인(경로 탈출 차단).
    - 심볼릭 링크/재분석 지점(경로 치환)·비일반 파일 차단.
    """
    if not pdf_path or not allowed_dir:
        raise _Skip(CODE_PATH_OUTSIDE)

    real = os.path.realpath(pdf_path)
    base = os.path.realpath(allowed_dir)

    # 심볼릭/정션 등으로 경로가 치환되면 realpath와 단순 abspath가 달라진다 → 차단.
    if _norm(real) != _norm(pdf_path):
        raise _Skip(CODE_PATH_SYMLINK)

    real_n = _norm(real)
    base_n = _norm(base)
    # 허용 디렉터리 하위인지 (경계 문자 포함 비교로 접두 오탐 방지)
    if real_n != base_n and not real_n.startswith(base_n + os.sep):
        raise _Skip(CODE_PATH_OUTSIDE)

    try:
        lst = os.lstat(real)
    except OSError:
        raise _Skip(CODE_FILE_MISSING)
    # 심볼릭 링크 자체이면 차단
    if stat.S_ISLNK(lst.st_mode):
        raise _Skip(CODE_PATH_SYMLINK)
    # Windows 재분석 지점(정션/심볼릭) 차단
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if getattr(lst, "st_file_attributes", 0) & reparse:
        raise _Skip(CODE_PATH_SYMLINK)
    if not stat.S_ISREG(lst.st_mode):
        raise _Skip(CODE_NOT_REGULAR)
    if os.path.splitext(real)[1].lower() != ".pdf":
        raise _Skip(CODE_BAD_EXT)
    return real


def read_validated_pdf_bytes(real_path):
    """검증된 경로를 한 번 열어 크기·시그니처를 확인하고 바이트를 반환.

    같은 열린 핸들에서 fstat·read를 수행해 검증-렌더 사이 파일 교체(TOCTOU) 위험을
    최소화한다(검증된 바이트를 이후 렌더링에 그대로 사용).
    """
    try:
        f = open(real_path, "rb")
    except OSError:
        raise _Skip(CODE_FILE_MISSING)
    try:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise _Skip(CODE_NOT_REGULAR)
        if st.st_size <= 0:
            raise _Skip(CODE_EMPTY_PDF)
        if st.st_size > MAX_PDF_BYTES:
            raise _Skip(CODE_TOO_LARGE)
        data = f.read(st.st_size + 1)  # 크기 검증 후 초과 없음 확인용 +1
    finally:
        f.close()
    if len(data) > MAX_PDF_BYTES:
        raise _Skip(CODE_TOO_LARGE)
    if not data.startswith(PDF_SIGNATURE):
        raise _Skip(CODE_BAD_SIGNATURE)
    return data


# ── PyMuPDF 렌더링 (능동 콘텐츠 미실행) ──────────────────────────────────────
class RenderedPage:
    """렌더링된 한 페이지: 실제 크기(pt)와 device 독립 raster(PIL Image)."""
    __slots__ = ("width_pt", "height_pt", "image")

    def __init__(self, width_pt, height_pt, image):
        self.width_pt = width_pt
        self.height_pt = height_pt
        self.image = image


def render_pdf_pages(pdf_bytes, dpi=RENDER_DPI, max_pages=MAX_PDF_PAGES):
    """검증된 PDF 바이트를 페이지별 raster 이미지로 렌더링.

    PyMuPDF의 stream 모드로 열고 각 페이지를 pixmap으로만 렌더한다. OpenAction/
    JavaScript/첨부/링크/양식/외부 리소스를 실행하지 않는다(픽스맵 렌더는 능동 콘텐츠를
    구동하지 않음). 반환 이미지는 사용 후 호출측에서 참조 해제한다.
    """
    import fitz  # 프로젝트가 이미 사용하는 PyMuPDF
    from PIL import Image

    pages = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        n = doc.page_count
        if n <= 0:
            raise _Skip(CODE_EMPTY_PDF)
        if n > max_pages:
            raise _Skip(CODE_TOO_MANY_PAGES)
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        for i in range(n):
            page = doc.load_page(i)
            rect = page.rect  # 실제 크기(pt) — 방향 포함
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            try:
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            finally:
                pix = None  # 픽셀 버퍼 참조 즉시 해제
            pages.append(RenderedPage(rect.width, rect.height, img))
    finally:
        doc.close()
    return pages


# ── Windows GDI / win32print 백엔드 (테스트에서 mock) ─────────────────────────
class _RealBackend:
    """실제 Windows 프린터 조회/상태/GDI 출력. 최소 권한(조회·인쇄)만 사용한다."""

    def enum_printer_names(self):
        import win32print
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        infos = win32print.EnumPrinters(flags, None, 4)  # level 4: 이름 빠른 조회
        names = []
        for info in infos:
            name = info.get("pPrinterName") if isinstance(info, dict) else None
            if name:
                names.append(name)
        return names

    def printer_ready_code(self, name):
        """프린터 준비 상태 코드 반환: None이면 준비됨, 아니면 비식별 사유 코드.

        열기/조회에 최소 권한만 사용하고 설정·권한을 변경하지 않는다.
        """
        import win32print
        NOT_READY = (
            win32print.PRINTER_STATUS_PAUSED
            | win32print.PRINTER_STATUS_ERROR
            | win32print.PRINTER_STATUS_OFFLINE
            | getattr(win32print, "PRINTER_STATUS_NOT_AVAILABLE", 0x00001000)
            | getattr(win32print, "PRINTER_STATUS_USER_INTERVENTION", 0x00040000)
            | getattr(win32print, "PRINTER_STATUS_DOOR_OPEN", 0x00400000)
            | getattr(win32print, "PRINTER_STATUS_PAPER_JAM", 0x00000008)
        )
        WORK_OFFLINE = getattr(win32print, "PRINTER_ATTRIBUTE_WORK_OFFLINE", 0x00000400)
        try:
            h = win32print.OpenPrinter(name)  # 기본(조회) 접근권한
        except Exception:
            return CODE_PRINTER_NOT_FOUND
        try:
            info = win32print.GetPrinter(h, 2)
        except Exception:
            return CODE_PRINTER_QUERY_FAIL
        finally:
            try:
                win32print.ClosePrinter(h)
            except Exception:
                pass
        status = info.get("Status", 0) if isinstance(info, dict) else 0
        attrs = info.get("Attributes", 0) if isinstance(info, dict) else 0
        if status & NOT_READY:
            return CODE_PRINTER_NOT_READY
        if attrs & WORK_OFFLINE:
            return CODE_PRINTER_NOT_READY
        return None

    def submit_print_job(self, printer_name, rendered_pages, job_name):
        """렌더된 페이지들을 GDI로 프린터에 출력. 실패 시 예외 발생.

        프린터 기존 설정(컬러/흑백 등)을 존중하며 devmode를 변경하지 않는다(앱이
        프린터 기본 설정을 영구 변경하지 않음).
        """
        import win32ui
        import win32con
        from PIL import ImageWin

        HORZRES, VERTRES = 8, 10
        LOGPIXELSX, LOGPIXELSY = 88, 90

        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer_name)  # 프린터 기본 devmode 사용(변경 없음)
        try:
            printable_w = hdc.GetDeviceCaps(HORZRES)
            printable_h = hdc.GetDeviceCaps(VERTRES)
            dpi_x = hdc.GetDeviceCaps(LOGPIXELSX)
            dpi_y = hdc.GetDeviceCaps(LOGPIXELSY)
            hdc.StartDoc(job_name)  # job_name은 비식별 순번 기반(개인정보 없음)
            try:
                for rp in rendered_pages:
                    x, y, w, h = compute_placement(
                        rp.width_pt, rp.height_pt,
                        printable_w, printable_h, dpi_x, dpi_y,
                    )
                    hdc.StartPage()
                    dib = ImageWin.Dib(rp.image)
                    dib.draw(hdc.GetHandleOutput(), (x, y, x + w, y + h))
                    hdc.EndPage()
                    dib = None
                hdc.EndDoc()
            except Exception:
                try:
                    hdc.AbortDoc()
                except Exception:
                    pass
                raise
        finally:
            try:
                hdc.DeleteDC()
            except Exception:
                pass


def list_installed_printers(backend=None):
    """설치된 Windows 프린터 이름을 정렬·중복제거해 반환. 조회 실패는 빈 목록."""
    backend = backend or _RealBackend()
    try:
        names = backend.enum_printer_names()
    except Exception:
        return []  # 프린터 목록 조회 실패를 전체 작업 실패로 처리하지 않는다.
    seen = {}
    for n in names:
        if isinstance(n, str) and n.strip():
            seen.setdefault(n, True)
    return sorted(seen.keys())


# ── 인쇄 매니저 (실행별, 불변 스냅샷 기반) ────────────────────────────────────
class PrintManager:
    """실행 1회 동안의 인쇄 오케스트레이션.

    생성 시점의 (자동 인쇄 여부, 선택 프린터, 허용 디렉터리, 실행당 상한)을 불변
    스냅샷으로 보관한다. 문서별 print_document()는 절대 예외를 전파하지 않는다.
    """

    def __init__(self, *, enabled, printer_name, allowed_dir,
                 max_jobs_per_run=DEFAULT_MAX_JOBS_PER_RUN,
                 backend=None, renderer=None):
        self.enabled = bool(enabled)
        self.printer_name = printer_name or ""
        self.allowed_dir = allowed_dir or ""
        self.max_jobs = clamp_max_jobs(max_jobs_per_run)
        self._backend = backend or _RealBackend()
        self._renderer = renderer or render_pdf_pages
        self._attempted = set()   # 정규화 realpath 집합(내부 전용, 로그 금지)
        self._submitted = 0       # 제출 시도 건수(실행당 상한 계산용)
        self._seq = 0             # 비식별 순번
        self.counts = {"성공": 0, "건너뜀": 0, "실패": 0, "확인필요": 0}

    # 상태 → 카운터
    _TALLY = {PRINT_OK: "성공", PRINT_SKIP: "건너뜀",
              PRINT_FAIL: "실패", PRINT_UNCERTAIN: "확인필요"}

    def _tally(self, status):
        key = self._TALLY.get(status)
        if key:
            self.counts[key] += 1

    def _next_job_id(self):
        self._seq += 1
        return "P%04d" % self._seq

    def print_document(self, pdf_path) -> PrintResult:
        """한 문서를 인쇄(또는 건너뜀). 예외를 절대 밖으로 전파하지 않는다."""
        try:
            res = self._decide_and_print(pdf_path)
        except _Skip as sk:
            res = PrintResult(PRINT_SKIP, sk.code, None)
        except Exception:
            # traceback/지역변수/버퍼를 남기지 않는다(비식별 코드만).
            res = PrintResult(PRINT_FAIL, CODE_INTERNAL, None)
        self._tally(res.status)
        return res

    def _decide_and_print(self, pdf_path) -> PrintResult:
        # 1) 자동 인쇄 OFF → 조회·검증·렌더·인쇄 모두 건너뜀
        if not self.enabled:
            return PrintResult(PRINT_SKIP, CODE_AUTOPRINT_OFF, None)
        # 2) 프린터 미선택 → 인쇄만 건너뜀
        if not self.printer_name:
            return PrintResult(PRINT_SKIP, CODE_NO_PRINTER, None)

        # 3) 경로/파일 검증 (허용 디렉터리·심볼릭·확장자)
        real = validate_target_path(pdf_path, self.allowed_dir)

        # 4) 실행별 1회 인쇄 보장(저장 재시도와 무관하게 중복 인쇄 방지)
        if real in self._attempted:
            return PrintResult(PRINT_SKIP, CODE_ALREADY_PRINTED, None)

        # 5) 인쇄 직전 파일 재검증 + 검증된 바이트 확보(교체 위험 최소화)
        pdf_bytes = read_validated_pdf_bytes(real)

        # 6) 실행당 상한 초과분은 건너뜀(DB·다음 문서 처리에는 영향 없음)
        if self._submitted >= self.max_jobs:
            return PrintResult(PRINT_SKIP, CODE_RUN_LIMIT, None)

        # 7) 인쇄 직전 프린터 목록 재조회 + 정확히 하나 일치 + 준비 상태 확인
        try:
            names = self._backend.enum_printer_names()
        except Exception:
            return PrintResult(PRINT_SKIP, CODE_PRINTER_QUERY_FAIL, None)
        matches = _count_exact_matches(names, self.printer_name)
        if matches == 0:
            return PrintResult(PRINT_SKIP, CODE_PRINTER_NOT_FOUND, None)
        if matches > 1:
            return PrintResult(PRINT_SKIP, CODE_PRINTER_AMBIGUOUS, None)
        ready_code = self._backend.printer_ready_code(self.printer_name)
        if ready_code is not None:
            return PrintResult(PRINT_SKIP, ready_code, None)

        # 8) 렌더링(능동 콘텐츠 미실행). 렌더 실패는 인쇄만 실패 처리.
        pages = None
        try:
            pages = self._renderer(pdf_bytes)
        except _Skip:
            raise
        except Exception:
            return PrintResult(PRINT_FAIL, CODE_RENDER_ERROR, None)

        # 9) 제출 시도 순간 '제출 시도됨'으로 기록(중복·상한 반영). 문서당 1부 고정.
        self._attempted.add(real)
        self._submitted += 1
        job_id = self._next_job_id()
        job_name = "Bank24 Document %s" % job_id  # 비식별 문서명
        try:
            for _ in range(COPIES):  # COPIES == 1 고정
                self._backend.submit_print_job(self.printer_name, pages, job_name)
        except Exception:
            # 제출 후 성공 여부 불확실 → 자동 재인쇄하지 않음
            return PrintResult(PRINT_UNCERTAIN, CODE_SUBMIT_UNCERTAIN, job_id)
        finally:
            pages = None  # 렌더 이미지 참조 해제(로그/덤프 금지)

        return PrintResult(PRINT_OK, CODE_OK, job_id)


def _count_exact_matches(names, selected):
    """열거 목록에서 선택 프린터명과 '정확히 일치'하는 원소 개수.

    부분 문자열·대소문자 추측·유사 이름 매칭을 사용하지 않는다. 중복 열거(2개 이상)는
    모호 상태로 보고 호출측에서 인쇄를 건너뛴다(fallback 없음).
    """
    if not selected:
        return 0
    return sum(1 for n in names if isinstance(n, str) and n == selected)
