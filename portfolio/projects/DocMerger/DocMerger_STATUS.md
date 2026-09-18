# DocMerger Status

Last updated: 2026-05-11

## Current Release

- Project path: `D:\AI\Claude\DocMerger`
- Stable packaged release: `dist\DocMerger_V7.zip`
- Latest packaged release: `dist\DocMerger_V7.zip`
- ZIP contents: `DocMerger.exe`
- Preserved packages:
  - `dist\DocMerger_V3.zip`
  - `dist\DocMerger_V4.zip`
  - `dist\DocMerger_V5.zip`
  - `dist\DocMerger_V6.zip`
- V7 build command used: `pyinstaller DocMerger.spec --clean`
- V7 EXE path: `dist\DocMerger.exe`
- EXE size: about 86.5 MB
- V7 ZIP size: about 85.9 MB
- V7 ZIP extraction verification passed at `test_output\v7_verify_codex\`

## Verified Core Features

- Merge: passed
  - PDF + PDF + PNG merge produced the expected page count.
  - DOCX + PDF + PNG merge passed, including DOCX to PDF through win32com.
- Compress: passed
  - `none` and `basic` modes passed.
  - `strong/high` falls back to copying the original when the compressed output would be larger.
  - `strong/medium` and `strong/low` reduce file size normally.
- Split: passed
  - Thumbnail-based selected-page split works.
  - Save selected pages as one PDF works.
  - Save selected pages as individual PDFs works.
  - Output filename collision avoidance works.
  - `SplitSelectedWorker` QThread path passed.
- Page edit: passed
  - Page Edit menu is enabled.
  - Single-PDF thumbnail workflow works.
  - Select all / clear selection works.
  - Selected page delete works, including all-pages-delete prevention.
  - Selected page 90-degree rotation works and persists in saved PDF.
  - Selected page left/right movement works.
  - Edited result saves as a new PDF with `_edited` suffix and collision avoidance.
  - Original overwrite is blocked in both worker and merger layers.
- Standalone convert: passed
  - Convert menu is enabled.
  - Multiple supported inputs can be added, checked, removed, and drag-dropped.
  - Each selected input converts to a separate PDF in the selected output folder.
  - PDF passthrough, PNG/image conversion, and DOCX conversion were tested.
  - Output filename collision avoidance works with `_1`, `_2`, etc.
  - Original overwrite is avoided.
  - Per-file status updates work.
- Security: passed (V7)
  - Security menu enabled (index 5).
  - PDF-only file table (reuses `CompressPdfTable`).
  - Lock mode: AES-256 password encryption via PyMuPDF, output suffix `_locked`.
  - Unlock mode: password authentication then encryption removal, output suffix `_unlocked`.
  - Already-encrypted PDF in lock mode raises ValueError.
  - Non-encrypted PDF in unlock mode raises ValueError.
  - Wrong password raises ValueError.
  - Same-path guard prevents overwriting original.
  - Filename collision avoidance: `_locked_1.pdf`, `_locked_2.pdf`, etc.
  - Confirm field visible only in lock mode (hidden in unlock mode).
  - `SecurityWorker` QThread path verified: both files locked, `file_done` signal fired.
  - `test_pages_ui.py` 49/49 regression passed after security changes.

## Fixes And Features Applied

- `main.py`
  - Removed unused `SplitWorker` import.
  - Added `try/finally` around split PDF loading/rendering document handle.
  - Synced footer output label on mode changes.
  - Updated split run button text to include run/execute wording.
  - Enabled the Page Edit menu.
  - Added `EditPageWidget` and a pages workspace/option panel.
  - Added page delete, rotate, move left/right, and save edited result flows.
- `merger.py`
  - Added size fallback in `compress_pdf_strong`.
  - Added `save_edited_pdf()` for page edit output.
- `worker.py`
  - Added `PageEditWorker`.
  - Added `StandaloneConvertWorker` and `make_unique_convert_path()`.
- `main.py`
  - Enabled the Convert menu.
  - Added `ConvertFileTable`.
  - Added convert workspace/option panel and convert run flow.
- `merger.py`
  - Added `set_pdf_password()` (AES-256 encryption).
  - Added `remove_pdf_password()` (authenticated decryption).
- `worker.py`
  - Added `make_unique_security_path()`.
  - Added `SecurityWorker` (lock/unlock mode, per-file `file_done` signal).
- `main.py`
  - Enabled Security menu (MENU_ITEMS `enabled=True`).
  - Added `_security_out_dir` and `_security_worker` state variables.
  - Added `_build_security_workspace()` and `_build_security_option_panel()`.
  - Added stack index 5 for both workspace and option stacks.
  - Updated `_set_mode`, `_select_output`, `_update_selection_summary`, `_run`, `_set_running`.
  - Added `_add_security_files`, `_on_security_mode_changed`, `_run_security`.
  - Added `_on_security_finished`, `_on_security_error`, `_on_security_file_done`.

## Verification Completed

- `python -m py_compile main.py worker.py merger.py converter.py`
- `python -B -c "import main; print('main import ok')"`
- Offscreen `MainWindow()` initialization: 6 workspace stacks, 6 option stacks.
- All security widgets present: `security_table`, `rb_sec_lock`, `rb_sec_unlock`, `le_sec_password`, `le_sec_confirm`, `lbl_total_sec`, `lbl_target_sec`.
- Security unit tests: 6/6 passed (set, remove, wrong pw, already-locked, same-path, non-encrypted).
- SecurityWorker integration test: 2 PDFs locked, `file_done` signal correct, output files encrypted.
- `test_pages_ui.py` passed 49/49 checks.
- PyInstaller V7 build passed.
- EXE launch checked (PID confirmed, WorkingSet normal).
- V7 ZIP contents and extraction verified at `test_output\v7_verify_codex\`.
- All V3/V4/V5/V6 ZIPs preserved.

## Known Deferred Items

- `SplitWorker` class and old range-based split helper functions are still preserved.
  - Related helpers include `parse_page_ranges`, `split_pdf_by_ranges`, and `split_pdf_each_page`.
  - Deletion was intentionally deferred.
- Full manual testing on an actual target office PC is still recommended.
- The current EXE is not code signed; this is acceptable for internal distribution.

## Next Development Candidates

Recommended order:

1. Security menu
   - Completed in V7.
2. OCR menu
   - Searchable PDF creation.
   - Requires OCR engine and Korean/English data decisions.
   - Deployment size concern: Tesseract + kor data (~50MB+).
   - Recommend separate design session before implementation.

## Suggested Next Prompt

```text
OCR 메뉴 설계를 시작하자.

Goal:
- OCR 메뉴를 활성화해서 이미지 기반 PDF를 텍스트 검색 가능한 PDF로 만든다.
- 파일을 수정하기 전에 분석/계획 리포트만 제출해줘.

분석 대상:
1. 현재 프로젝트에서 사용 가능한 OCR 라이브러리 후보 (Tesseract, PaddleOCR, EasyOCR 등)
2. 한국어 + 영어 동시 지원 여부
3. PyInstaller 단독 EXE 패키징 가능 여부 및 예상 용량 증가
4. 처리 흐름: 입력 PDF → 페이지별 이미지 → OCR → 텍스트 레이어 삽입 → 출력 PDF
5. PyMuPDF에서 텍스트 오버레이 삽입 가능 여부

리포트 형식:
- 라이브러리 후보별 장단점 표
- 권장 선택 및 이유
- 구현 범위 제안 (1차)
- 예상 배포 용량
```
