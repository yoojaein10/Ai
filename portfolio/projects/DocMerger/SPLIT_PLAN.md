# PDF Split Thumbnail Plan

## Goal

Implement the split menu as a single-PDF, thumbnail-based page selection workflow.
This work is limited to selecting pages and splitting/saving them. Do not add OCR,
security, delete, rotate, or broader page editing features in this step.

## UI

### Split Workspace

- The split menu targets only one PDF at a time.
- Replace the range-input/table-centered split UI with a thumbnail grid.
- Keep the existing application style and do not break merge/compress screens.
- Add a thumbnail page widget, such as `ThumbnailPageWidget`, containing:
  - `page_index`
  - checkbox
  - thumbnail `QLabel`
  - selected-state styling
- Track split thumbnail state on the main window:
  - `self._split_pdf_path`
  - `self._split_page_count`
  - `self._split_page_widgets`

### Right Option Panel

1. Save mode:
   - Save selected pages as one PDF
   - Save selected pages as individual PDFs
2. Quick selection controls:
   - Select all
   - Clear all
   - Select odd pages
   - Select even pages
3. Selection summary:
   - File name
   - Total page count
   - Selected page count
4. Quick selection guide:
   - Mention that all, clear, odd, and even buttons are available.
5. Caution text:
   - Page numbers start at 1.

### Footer

1. Show output folder.
2. Output folder selection button.
3. Progress bar.
4. Run button text:
   - `선택 페이지 분할 실행`

## File Handling

1. Split mode accepts only one PDF target.
2. If another PDF is added while one is already loaded, either ask whether to replace it or automatically replace it with a clear message/behavior.
3. If a non-PDF file is added, show a warning message.
4. Drag and drop must also accept PDF files only.
5. The user selects the output folder.
6. Never overwrite the original PDF.

## Thumbnail Rendering

1. Use PyMuPDF (`fitz`).
2. Render each page at low resolution.
   - Suggested scale: `0.18` to `0.25`
   - Suggested thumbnail width: about `110` to `150px`
3. Convert rendered page data into `QImage`/`QPixmap` and display it in a `QLabel`.
4. A simple first implementation may render thumbnails synchronously.
   - Report that PDFs with 100+ pages may load slowly.
   - Keep the structure clean enough to move rendering into a future `ThumbnailWorker`.
5. When replacing/removing the current PDF, clean up old thumbnail widgets to avoid memory leaks.

## Split Save Logic

1. Use PyMuPDF.
2. Show page numbers as 1-based to the user, but process selected pages internally as 0-based indices.
3. Save selected pages as one PDF:
   - Save selected pages in order into one PDF.
   - Example output name: `sample_selected_pages.pdf`
   - Avoid collisions with suffixes such as `sample_selected_pages_1.pdf`.
4. Save selected pages as individual PDFs:
   - Save each selected page as a separate PDF.
   - Example output names:
     - `sample_page_001.pdf`
     - `sample_page_005.pdf`
   - Avoid collisions with suffixes such as `_1`, `_2`.
5. If no pages are selected, show a warning message.
6. After save completion, ask whether to open the output folder.

## Recommended Implementation

### main.py

- Add/replace the split-only screen using the existing mode or `QStackedWidget` structure.
- Add `ThumbnailPageWidget`.
- Add quick selection methods:
  - `_select_all_split_pages()`
  - `_clear_split_pages()`
  - `_select_odd_split_pages()`
  - `_select_even_split_pages()`
- Keep merge/compress behavior intact.

### merger.py

Add save helpers:

- `extract_selected_pages(src_pdf, page_indices, out_pdf)`
- `split_selected_pages_each(src_pdf, page_indices, output_dir)`

Responsibilities:

- Use PyMuPDF.
- Preserve selected-page order.
- Avoid filename collisions.
- Never overwrite the original PDF.

### worker.py

Add `SplitSelectedWorker`.

Suggested shape:

```python
class SplitSelectedWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str, str)
```

Inputs:

- `src_pdf: str`
- `output_dir: str`
- `page_indices: list[int]`
- `save_mode: "single" | "each"`

Behavior:

- `single`: save selected pages as one PDF.
- `each`: save selected pages as individual PDFs.
- Avoid filename collisions.
- Emit progress.
- Emit `finished(output_dir)` when done.

## Verification

Run:

```powershell
python -m py_compile main.py worker.py merger.py converter.py
python -c "import main; print('main import ok')"
python -c "from PyQt6.QtWidgets import QApplication; from main import MainWindow; app=QApplication([]); w=MainWindow(); print('window init ok', w.windowTitle())"
```

Manual checks:

1. Save selected pages as one PDF.
2. Save selected pages as individual PDFs.
3. Confirm warning when no pages are selected.
4. Confirm non-PDF files are rejected.
5. Confirm drag and drop accepts PDF only.
6. Confirm merge/compress screens still work.

## Result Report Format

Report concisely:

- Modified file list.
- Split menu UI behavior.
- Thumbnail selection behavior.
- Save behavior for `single` and `each`.
- Verification commands and results.
- Remaining limitations.
