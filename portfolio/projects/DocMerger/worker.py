"""
QThread Worker: 변환 + 병합 + 압축을 백그라운드에서 실행, 시그널로 UI 업데이트.
"""
import os
import logging
import shutil
import traceback
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal

from converter import to_temp_pdf, make_tmp_dir, cleanup_tmp_dir
from merger import (rasterize_to_image_pdf, merge_pdfs, compress_pdf,
                    parse_page_ranges, split_pdf_by_ranges,
                    split_pdf_each_page, make_unique_split_path,
                    extract_selected_pages, split_selected_each,
                    save_edited_pdf, set_pdf_password, remove_pdf_password)


class ConvertWorker(QThread):
    # (현재 파일 인덱스, 전체 파일 수, 상태 메시지)
    progress = pyqtSignal(int, int, str)
    # 최종 출력 경로
    finished = pyqtSignal(str)
    # (파일명, 오류 메시지)
    error    = pyqtSignal(str, str)

    def __init__(self, file_items: list[dict], out_path: str,
                 compress_mode: str = "none", quality_level: str = "high"):
        """
        file_items:    [{"path": str, "option": "readable"|"unreadable"}, ...]
        out_path:      최종 PDF 저장 경로
        compress_mode: "none" | "basic" | "strong"
        quality_level: "high" | "medium" | "low" (strong 모드에서만 의미 있음)
        """
        super().__init__()
        self.file_items    = file_items
        self.out_path      = out_path
        self.compress_mode = compress_mode
        self.quality_level = quality_level
        self._tmp_dir      = None
        self._abort        = False

    def abort(self):
        self._abort = True

    def run(self):
        # ── 사전 검증: 입력 파일 중 출력 경로와 동일한 게 있으면 거부 ────────
        try:
            out_resolved = Path(self.out_path).resolve()
            for item in self.file_items:
                try:
                    if Path(item["path"]).resolve() == out_resolved:
                        self.error.emit(
                            Path(item["path"]).name,
                            "입력 파일 중 하나가 출력 경로와 동일합니다. 다른 저장 경로를 선택하세요."
                        )
                        # finished를 보내야 UI가 복구되지 않음 — error만 emit하고 종료
                        return
                except Exception:
                    continue
        except Exception:
            pass

        self._tmp_dir = make_tmp_dir()
        total = len(self.file_items)
        ready_pdfs: list[str] = []

        try:
            # ── Step 2: 1차 정규화 (모든 파일 → 임시 PDF) ──────────────────
            for idx, item in enumerate(self.file_items, 1):
                if self._abort:
                    break

                fname = Path(item["path"]).name
                self.progress.emit(idx, total, f"[{idx}/{total}] 변환 중: {fname}")

                try:
                    tmp_pdf = to_temp_pdf(item["path"], self._tmp_dir)
                    item["tmp_pdf"] = tmp_pdf
                except Exception as e:
                    self.error.emit(fname, str(e))
                    item["tmp_pdf"] = None

            if self._abort:
                return

            # ── Step 3: Unreadable 래스터화 ─────────────────────────────────
            for idx, item in enumerate(self.file_items, 1):
                if self._abort:
                    break
                if item["tmp_pdf"] is None:
                    continue

                fname = Path(item["path"]).name

                if item["option"] == "unreadable":
                    # 이미지 원본 경로는 이미 이미지 PDF이므로 그대로 사용
                    ext = Path(item["path"]).suffix.lower()
                    is_image_source = ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif")

                    if not is_image_source:
                        raster_out = str(Path(self._tmp_dir) / f"{Path(item['path']).stem}_unreadable.pdf")
                        self.progress.emit(idx, total, f"[{idx}/{total}] 이미지 변환 (Unreadable): {fname}")
                        rasterize_to_image_pdf(item["tmp_pdf"], raster_out)
                        item["tmp_pdf"] = raster_out

                ready_pdfs.append(item["tmp_pdf"])

            if self._abort:
                return

            # ── Step 4: 최종 병합 (압축 모드면 임시 경로, 아니면 out_path) ──
            valid_pdfs = [p for p in ready_pdfs if p]
            if not valid_pdfs:
                self.error.emit("병합", "변환된 파일이 없습니다.")
                return

            if self.compress_mode == "none":
                self.progress.emit(total, total, f"병합 중 ({len(valid_pdfs)}개 파일)…")
                merge_pdfs(valid_pdfs, self.out_path)
            else:
                merged_tmp = str(Path(self._tmp_dir) / "merged_before_compress.pdf")
                self.progress.emit(total, total, f"병합 중 ({len(valid_pdfs)}개 파일)…")
                merge_pdfs(valid_pdfs, merged_tmp)

                mode_label = "기본 압축" if self.compress_mode == "basic" else "강한 압축"
                self.progress.emit(total, total, f"{mode_label} 중…")
                compress_pdf(merged_tmp, self.out_path,
                             self.compress_mode, self.quality_level)

                # 임시 병합 파일 삭제
                try:
                    os.remove(merged_tmp)
                except OSError:
                    pass

            self.finished.emit(self.out_path)

        except Exception:
            logging.error(traceback.format_exc())
            # 치명적 오류는 error 시그널로만 알리고 finished는 보내지 않음
            self.error.emit("치명적 오류", traceback.format_exc())

        finally:
            cleanup_tmp_dir(self._tmp_dir)


# ── 출력 경로 충돌 방지 헬퍼 ─────────────────────────────────────────────────

def make_unique_output_path(output_dir: str, src_path: str) -> str:
    """sample.pdf → sample_compressed.pdf, 충돌 시 _1, _2 ... 붙임."""
    stem = Path(src_path).stem
    base = Path(output_dir) / f"{stem}_compressed.pdf"
    if not base.exists():
        return str(base)
    i = 1
    while True:
        candidate = Path(output_dir) / f"{stem}_compressed_{i}.pdf"
        if not candidate.exists():
            return str(candidate)
        i += 1


def make_unique_convert_path(output_dir: str, src_path: str) -> str:
    """stem.pdf → 충돌 시 stem_1.pdf, stem_2.pdf ..."""
    stem = Path(src_path).stem
    base = Path(output_dir) / f"{stem}.pdf"
    if not base.exists():
        return str(base)
    i = 1
    while True:
        candidate = Path(output_dir) / f"{stem}_{i}.pdf"
        if not candidate.exists():
            return str(candidate)
        i += 1


# ── PDF 압축 전용 Worker ──────────────────────────────────────────────────────

class CompressWorker(QThread):
    progress = pyqtSignal(int, int, str)   # (현재, 전체, 메시지)
    finished = pyqtSignal(str)             # output_dir
    error    = pyqtSignal(str, str)        # (파일명, 오류 메시지)

    def __init__(self, file_paths: list[str], output_dir: str,
                 compress_mode: str = "basic", quality_level: str = "high"):
        super().__init__()
        self.file_paths    = file_paths
        self.output_dir    = output_dir
        self.compress_mode = compress_mode
        self.quality_level = quality_level
        self._abort        = False

    def abort(self):
        self._abort = True

    def run(self):
        total = len(self.file_paths)
        success_count = 0

        os.makedirs(self.output_dir, exist_ok=True)

        for idx, src_path in enumerate(self.file_paths, 1):
            if self._abort:
                break

            fname = Path(src_path).name
            self.progress.emit(idx, total, f"[{idx}/{total}] {fname}")

            try:
                out_path = make_unique_output_path(self.output_dir, src_path)
                compress_pdf(src_path, out_path, self.compress_mode, self.quality_level)
                success_count += 1
            except Exception:
                logging.error(traceback.format_exc())
                self.error.emit(fname, traceback.format_exc())

        if success_count > 0:
            self.finished.emit(self.output_dir)
        elif not self._abort:
            self.error.emit("압축 실패", f"처리된 파일이 없습니다.")


# ── PDF 분할 Worker ───────────────────────────────────────────────────────────

class SplitWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(str)
    error    = pyqtSignal(str, str)

    def __init__(self, file_paths: list[str], output_dir: str,
                 split_mode: str = "range", range_text: str = ""):
        super().__init__()
        self.file_paths = file_paths
        self.output_dir = output_dir
        self.split_mode = split_mode
        self.range_text = range_text
        self._abort     = False

    def abort(self):
        self._abort = True

    def run(self):
        import fitz as _fitz
        total = len(self.file_paths)
        success_count = 0
        os.makedirs(self.output_dir, exist_ok=True)

        for idx, src_path in enumerate(self.file_paths, 1):
            if self._abort:
                break

            fname = Path(src_path).name
            stem  = Path(src_path).stem
            self.progress.emit(idx, total, f"[{idx}/{total}] {fname}")

            try:
                doc = _fitz.open(src_path)
                page_count = doc.page_count
                doc.close()

                if self.split_mode == "each":
                    split_pdf_each_page(src_path, self.output_dir, stem)
                else:
                    pages = parse_page_ranges(self.range_text, page_count)
                    label = self.range_text.strip().replace(" ", "").replace(",", "_")
                    out_path = make_unique_split_path(
                        self.output_dir, f"{stem}_split_{label}")
                    split_pdf_by_ranges(src_path, out_path, pages)

                success_count += 1

            except Exception as e:
                logging.error(traceback.format_exc())
                self.error.emit(fname, str(e))

        if success_count > 0:
            self.finished.emit(self.output_dir)
        elif not self._abort:
            self.error.emit("분할 실패", "처리된 파일이 없습니다.")


# ── 페이지 편집 Worker ────────────────────────────────────────────────────────

class PageEditWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(str)   # out_path (파일)
    error    = pyqtSignal(str, str)

    def __init__(self, src_pdf: str, output_dir: str,
                 page_ops: list[dict], out_stem: str = ""):
        """
        page_ops: [{"idx": int, "rotation": int}, ...]  (0-based)
        out_stem: 출력 파일 기본 이름 (기본값 = 원본 파일명 stem)
        """
        super().__init__()
        self.src_pdf    = src_pdf
        self.output_dir = output_dir
        self.page_ops   = page_ops
        self.out_stem   = out_stem or Path(src_pdf).stem
        self._abort     = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            self.progress.emit(0, 1, "페이지 편집 저장 중...")
            stem     = self.out_stem + "_edited"
            out_path = make_unique_split_path(self.output_dir, stem)
            save_edited_pdf(self.src_pdf, self.page_ops, out_path)
            self.progress.emit(1, 1, "완료")
            if not self._abort:
                self.finished.emit(out_path)
        except Exception:
            logging.error(traceback.format_exc())
            self.error.emit(Path(self.src_pdf).name, traceback.format_exc())


# ── 선택 페이지 분할 Worker ──────────────────────────────────────────────────

class SplitSelectedWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(str)
    error    = pyqtSignal(str, str)

    def __init__(self, src_pdf: str, output_dir: str,
                 page_indices: list[int], save_mode: str = "single"):
        super().__init__()
        self.src_pdf      = src_pdf
        self.output_dir   = output_dir
        self.page_indices = page_indices  # 0-based
        self.save_mode    = save_mode     # "single" | "each"
        self._abort       = False

    def abort(self):
        self._abort = True

    def run(self):
        stem = Path(self.src_pdf).stem
        try:
            os.makedirs(self.output_dir, exist_ok=True)

            if self.save_mode == "single":
                self.progress.emit(0, 1, "선택 페이지 저장 중...")
                out_pdf = make_unique_split_path(
                    self.output_dir, f"{stem}_selected_pages")
                extract_selected_pages(self.src_pdf, self.page_indices, out_pdf)
                self.progress.emit(1, 1, "완료")

            else:
                total = len(self.page_indices)
                max_pg = max(self.page_indices) + 1 if self.page_indices else 1
                digits = max(3, len(str(max_pg)))
                for idx, p in enumerate(self.page_indices, 1):
                    if self._abort:
                        break
                    self.progress.emit(idx, total, f"[{idx}/{total}] 페이지 {p + 1} 저장 중...")
                    basename = f"{stem}_page_{str(p + 1).zfill(digits)}"
                    out_path = make_unique_split_path(self.output_dir, basename)
                    extract_selected_pages(self.src_pdf, [p], out_path)

            if not self._abort:
                self.finished.emit(self.output_dir)
        except Exception as e:
            logging.error(traceback.format_exc())
            self.error.emit(Path(self.src_pdf).name, str(e))


# ── 단독 변환 Worker ──────────────────────────────────────────────────────────

class StandaloneConvertWorker(QThread):
    progress  = pyqtSignal(int, int, str)   # (idx, total, msg)
    file_done = pyqtSignal(str, str)        # (src_path, 상태 텍스트)
    finished  = pyqtSignal(str)             # output_dir
    error     = pyqtSignal(str, str)        # (fname, msg)

    def __init__(self, file_paths: list[str], output_dir: str):
        super().__init__()
        self.file_paths = file_paths
        self.output_dir = output_dir
        self._abort     = False

    def abort(self):
        self._abort = True

    def run(self):
        tmp_dir = make_tmp_dir()
        total   = len(self.file_paths)
        success_count = 0

        try:
            os.makedirs(self.output_dir, exist_ok=True)

            for idx, src_path in enumerate(self.file_paths, 1):
                if self._abort:
                    break

                fname = Path(src_path).name
                self.progress.emit(idx, total, f"[{idx}/{total}] 변환 중: {fname}")

                try:
                    tmp_pdf  = to_temp_pdf(src_path, tmp_dir)
                    out_path = make_unique_convert_path(self.output_dir, src_path)

                    # PDF 패스스루 케이스: 원본과 출력 경로 동일 차단
                    if Path(tmp_pdf).resolve() == Path(out_path).resolve():
                        raise ValueError(
                            "출력 경로가 원본과 동일합니다. 다른 저장 폴더를 선택하세요."
                        )

                    shutil.copy2(tmp_pdf, out_path)
                    success_count += 1
                    self.file_done.emit(src_path, "완료")

                except Exception as e:
                    logging.error(traceback.format_exc())
                    self.error.emit(fname, str(e))
                    self.file_done.emit(src_path, "실패")

            if success_count > 0:
                self.finished.emit(self.output_dir)
            elif not self._abort:
                self.error.emit("변환 실패", "처리된 파일이 없습니다.")

        finally:
            cleanup_tmp_dir(tmp_dir)


# ── PDF 보안 Worker ───────────────────────────────────────────────────────────

def make_unique_security_path(output_dir: str, stem: str, suffix: str) -> str:
    """{stem}{suffix}.pdf → 충돌 시 {stem}{suffix}_1.pdf ..."""
    base = Path(output_dir) / f"{stem}{suffix}.pdf"
    if not base.exists():
        return str(base)
    i = 1
    while True:
        candidate = Path(output_dir) / f"{stem}{suffix}_{i}.pdf"
        if not candidate.exists():
            return str(candidate)
        i += 1


class SecurityWorker(QThread):
    progress  = pyqtSignal(int, int, str)   # (idx, total, msg)
    file_done = pyqtSignal(str, str)        # (src_path, 상태 텍스트)
    finished  = pyqtSignal(str)             # output_dir
    error     = pyqtSignal(str, str)        # (fname, msg)

    def __init__(self, file_paths: list[str], output_dir: str,
                 mode: str, password: str):
        super().__init__()
        self.file_paths = file_paths
        self.output_dir = output_dir
        self.mode       = mode      # "lock" | "unlock"
        self.password   = password
        self._abort     = False

    def abort(self):
        self._abort = True

    def run(self):
        total = len(self.file_paths)
        success_count = 0
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            for idx, src_path in enumerate(self.file_paths, 1):
                if self._abort:
                    break
                fname = Path(src_path).name
                self.progress.emit(idx, total, f"[{idx}/{total}] 처리 중: {fname}")
                try:
                    suffix = "_locked" if self.mode == "lock" else "_unlocked"
                    stem = Path(src_path).stem
                    out_path = make_unique_security_path(self.output_dir, stem, suffix)
                    if self.mode == "lock":
                        set_pdf_password(src_path, out_path, self.password)
                    else:
                        remove_pdf_password(src_path, out_path, self.password)
                    success_count += 1
                    self.file_done.emit(src_path, "완료")
                except Exception as e:
                    logging.error(traceback.format_exc())
                    self.error.emit(fname, str(e))
                    self.file_done.emit(src_path, "실패")
            if success_count > 0:
                self.finished.emit(self.output_dir)
            elif not self._abort:
                self.error.emit("처리 실패", "처리된 파일이 없습니다.")
        except Exception:
            logging.error(traceback.format_exc())
            self.error.emit("치명적 오류", traceback.format_exc())
