import logging
import os
import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QFont, QImage, QPixmap, QTransform
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from worker import (ConvertWorker, CompressWorker, SplitSelectedWorker,
                    PageEditWorker, StandaloneConvertWorker, SecurityWorker)


def ko(value: str) -> str:
    """Keep this file ASCII-safe while showing Korean text in the UI."""
    return value.encode("ascii").decode("unicode_escape")


SUPPORTED_EXT = {
    ".hwp",
    ".hwpx",
    ".docx",
    ".doc",
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tiff",
    ".tif",
    ".html",
    ".htm",
}

LABEL_COLOR = {
    "hwp": ("HWP", "#15803D", "#DCFCE7"),
    "hwpx": ("HWPX", "#15803D", "#DCFCE7"),
    "docx": ("DOCX", "#2563EB", "#DBEAFE"),
    "doc": ("DOC", "#2563EB", "#DBEAFE"),
    "pdf": ("PDF", "#DC2626", "#FEE2E2"),
    "jpg": ("IMG", "#B45309", "#FEF3C7"),
    "jpeg": ("IMG", "#B45309", "#FEF3C7"),
    "png": ("IMG", "#B45309", "#FEF3C7"),
    "bmp": ("IMG", "#B45309", "#FEF3C7"),
    "tiff": ("IMG", "#B45309", "#FEF3C7"),
    "tif": ("IMG", "#B45309", "#FEF3C7"),
    "html": ("HTML", "#0F766E", "#CCFBF1"),
    "htm": ("HTML", "#0F766E", "#CCFBF1"),
}

MENU_ITEMS = [
    ("merge", ko("\\ubcd1\\ud569"), True, "+"),
    ("compress", ko("\\uc555\\ucd95"), True, "-"),
    ("split", ko("\\ubd84\\ud560"), True, "x"),
    ("pages", ko("\\ud398\\uc774\\uc9c0 \\ud3b8\\uc9d1"), True, "p"),
    ("convert", ko("\\ubcc0\\ud658"), True, "c"),
    ("security", ko("\\ubcf4\\uc548"), True, "l"),
    ("ocr", "OCR", False, "o"),
]


class CompressPdfTable(QTableWidget):
    """압축 모드 전용 파일 테이블 — PDF 파일만 허용."""
    COL_CHECK  = 0
    COL_TYPE   = 1
    COL_NAME   = 2
    COL_SIZE   = 3
    COL_STATUS = 4
    COL_DELETE = 5

    def __init__(self, on_changed=None, parent=None):
        super().__init__(0, 6, parent)
        self._on_changed = on_changed
        self._paths: list[str] = []

        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(False)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(46)

        self.setHorizontalHeaderLabels([
            "", ko("\\ud615\\uc2dd"), ko("\\ud30c\\uc77c\\uba85"),
            ko("\\ud06c\\uae30"), ko("\\uc0c1\\ud0dc"), "",
        ])
        header = self.horizontalHeader()
        header.setSectionResizeMode(self.COL_CHECK,  QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_TYPE,   QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_NAME,   QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_SIZE,   QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_DELETE, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(self.COL_CHECK,  42)
        self.setColumnWidth(self.COL_TYPE,   72)
        self.setColumnWidth(self.COL_SIZE,   100)
        self.setColumnWidth(self.COL_STATUS, 130)
        self.setColumnWidth(self.COL_DELETE, 48)

        self.setStyleSheet(
            "QTableWidget{background:#FFFFFF;border:1px solid #E5EAF0;border-radius:10px;"
            "selection-background-color:#FFF7ED;selection-color:#0F172A;}"
            "QHeaderView::section{background:#F8FAFC;color:#64748B;border:none;"
            "border-bottom:1px solid #E5EAF0;padding:8px 6px;font-weight:bold;}"
            "QTableWidget::item{border-bottom:1px solid #F1F5F9;padding:4px;color:#334155;}"
        )

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            skipped = []
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if Path(path).suffix.lower() == ".pdf":
                    self.add_file(path)
                else:
                    skipped.append(Path(path).name)
            if skipped:
                QMessageBox.warning(
                    self, ko("\\uc9c0\\uc6d0 \\uc548 \\ud568"),
                    ko("PDF \\ud30c\\uc77c\\ub9cc \\ucd94\\uac00 \\uac00\\ub2a5\\ud569\\ub2c8\\ub2e4.") +
                    "\n" + ", ".join(skipped),
                )
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def add_file(self, path: str):
        if Path(path).suffix.lower() != ".pdf":
            QMessageBox.warning(
                self, ko("\\uc9c0\\uc6d0 \\uc548 \\ud568"),
                ko("PDF \\ud30c\\uc77c\\ub9cc \\ucd94\\uac00 \\uac00\\ub2a5\\ud569\\ub2c8\\ub2e4."),
            )
            return
        if path in self._paths:
            return

        row = self.rowCount()
        self.insertRow(row)
        self._paths.insert(row, path)

        check = QCheckBox()
        check.setChecked(True)
        check.stateChanged.connect(self._notify_changed)
        self.setCellWidget(row, self.COL_CHECK, self._center_widget(check))

        badge = QLabel("PDF")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedWidth(54)
        badge.setStyleSheet(
            "background:#FEE2E2;color:#DC2626;border-radius:7px;"
            "padding:4px 6px;font-size:10px;font-weight:bold;"
        )
        self.setCellWidget(row, self.COL_TYPE, self._center_widget(badge))

        name_item = QTableWidgetItem(Path(path).name)
        name_item.setToolTip(path)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setItem(row, self.COL_NAME, name_item)

        size_item = QTableWidgetItem(self._fmt_size(path))
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setItem(row, self.COL_SIZE, size_item)

        status_item = QTableWidgetItem(ko("\\ub300\\uae30"))
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setItem(row, self.COL_STATUS, status_item)

        del_btn = QPushButton(ko("\\uc0ad\\uc81c"))
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setFixedHeight(26)
        del_btn.setStyleSheet(
            "QPushButton{background:#FFFFFF;color:#94A3B8;border:1px solid #E2E8F0;"
            "border-radius:7px;font-size:8pt;}"
            "QPushButton:hover{background:#FEF2F2;color:#DC2626;border-color:#FCA5A5;}"
        )
        del_btn.clicked.connect(lambda _=False, p=path: self.remove_path(p))
        self.setCellWidget(row, self.COL_DELETE, self._center_widget(del_btn))

        self._notify_changed()

    def remove_path(self, path: str):
        if path not in self._paths:
            return
        row = self._paths.index(path)
        self._paths.pop(row)
        self.removeRow(row)
        self._notify_changed()

    def delete_selected_rows(self):
        rows = sorted(
            [r for r in range(self.rowCount())
             if (cb := self._cb_at(r)) and cb.isChecked()],
            reverse=True,
        )
        for row in rows:
            if 0 <= row < len(self._paths):
                self._paths.pop(row)
                self.removeRow(row)
        self._notify_changed()

    def set_all_checked(self, checked: bool):
        for row in range(self.rowCount()):
            cb = self._cb_at(row)
            if cb:
                cb.setChecked(checked)
        self._notify_changed()

    def get_checked_paths(self) -> list[str]:
        return [p for i, p in enumerate(self._paths)
                if (cb := self._cb_at(i)) and cb.isChecked()]

    def total_count(self)   -> int: return len(self._paths)
    def checked_count(self) -> int:
        return sum(1 for r in range(self.rowCount())
                   if (cb := self._cb_at(r)) and cb.isChecked())

    def set_status(self, path: str, text: str):
        if path in self._paths:
            item = self.item(self._paths.index(path), self.COL_STATUS)
            if item:
                item.setText(text)

    def clear(self):
        self._paths.clear()
        self.setRowCount(0)
        self._notify_changed()

    def _cb_at(self, row: int) -> QCheckBox | None:
        wrap = self.cellWidget(row, self.COL_CHECK)
        return wrap.findChild(QCheckBox) if wrap else None

    @staticmethod
    def _center_widget(w: QWidget) -> QWidget:
        wrap = QWidget()
        lay  = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(); lay.addWidget(w); lay.addStretch()
        return wrap

    @staticmethod
    def _fmt_size(path: str) -> str:
        try:
            s = Path(path).stat().st_size
        except OSError:
            return "-"
        if s >= 1 << 20: return f"{s/(1<<20):.2f} MB"
        if s >= 1 << 10: return f"{s/(1<<10):.1f} KB"
        return f"{s} B"

    def _notify_changed(self):
        if self._on_changed:
            self._on_changed()


class ConvertFileTable(QTableWidget):
    """변환 모드 전용 파일 테이블 — 모든 지원 포맷 허용."""
    COL_CHECK  = 0
    COL_TYPE   = 1
    COL_NAME   = 2
    COL_SIZE   = 3
    COL_STATUS = 4
    COL_DELETE = 5

    def __init__(self, on_changed=None, parent=None):
        super().__init__(0, 6, parent)
        self._on_changed = on_changed
        self._paths: list[str] = []

        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(False)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(46)

        self.setHorizontalHeaderLabels([
            "", ko("\\ud615\\uc2dd"), ko("\\ud30c\\uc77c\\uba85"),
            ko("\\ud06c\\uae30"), ko("\\uc0c1\\ud0dc"), "",
        ])
        header = self.horizontalHeader()
        header.setSectionResizeMode(self.COL_CHECK,  QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_TYPE,   QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_NAME,   QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_SIZE,   QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_DELETE, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(self.COL_CHECK,  42)
        self.setColumnWidth(self.COL_TYPE,   72)
        self.setColumnWidth(self.COL_SIZE,   100)
        self.setColumnWidth(self.COL_STATUS, 130)
        self.setColumnWidth(self.COL_DELETE, 48)

        self.setStyleSheet(
            "QTableWidget{background:#FFFFFF;border:1px solid #E5EAF0;border-radius:10px;"
            "selection-background-color:#EFF6FF;selection-color:#0F172A;}"
            "QHeaderView::section{background:#F8FAFC;color:#64748B;border:none;"
            "border-bottom:1px solid #E5EAF0;padding:8px 6px;font-weight:bold;}"
            "QTableWidget::item{border-bottom:1px solid #F1F5F9;padding:4px;color:#334155;}"
        )

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            skipped = []
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if Path(path).suffix.lower() in SUPPORTED_EXT:
                    self.add_file(path)
                else:
                    skipped.append(Path(path).name)
            if skipped:
                QMessageBox.warning(
                    self, ko("\\uc9c0\\uc6d0 \\uc548 \\ud568"),
                    ko("\\uc9c0\\uc6d0\\ud558\\uc9c0 \\uc54a\\ub294 \\ud30c\\uc77c \\ud615\\uc2dd\\uc785\\ub2c8\\ub2e4:") +
                    "\n" + ", ".join(skipped),
                )
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def add_file(self, path: str):
        if Path(path).suffix.lower() not in SUPPORTED_EXT:
            QMessageBox.warning(
                self, ko("\\uc9c0\\uc6d0 \\uc548 \\ud568"),
                ko("\\uc9c0\\uc6d0\\ud558\\uc9c0 \\uc54a\\ub294 \\ud30c\\uc77c \\ud615\\uc2dd\\uc785\\ub2c8\\ub2e4."),
            )
            return
        if path in self._paths:
            return

        row = self.rowCount()
        self.insertRow(row)
        self._paths.insert(row, path)

        check = QCheckBox()
        check.setChecked(True)
        check.stateChanged.connect(self._notify_changed)
        self.setCellWidget(row, self.COL_CHECK, self._center_widget(check))

        ext  = Path(path).suffix.lstrip(".").lower()
        text, fg, bg = LABEL_COLOR.get(ext, ("FILE", "#334155", "#E2E8F0"))
        badge = QLabel(text)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedWidth(54)
        badge.setStyleSheet(
            f"background:{bg};color:{fg};border-radius:7px;"
            "padding:4px 6px;font-size:10px;font-weight:bold;"
        )
        self.setCellWidget(row, self.COL_TYPE, self._center_widget(badge))

        name_item = QTableWidgetItem(Path(path).name)
        name_item.setToolTip(path)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setItem(row, self.COL_NAME, name_item)

        size_item = QTableWidgetItem(self._fmt_size(path))
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setItem(row, self.COL_SIZE, size_item)

        status_item = QTableWidgetItem(ko("\\ub300\\uae30"))
        status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setItem(row, self.COL_STATUS, status_item)

        del_btn = QPushButton(ko("\\uc0ad\\uc81c"))
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setFixedHeight(26)
        del_btn.setStyleSheet(
            "QPushButton{background:#FFFFFF;color:#94A3B8;border:1px solid #E2E8F0;"
            "border-radius:7px;font-size:8pt;}"
            "QPushButton:hover{background:#FEF2F2;color:#DC2626;border-color:#FCA5A5;}"
        )
        del_btn.clicked.connect(lambda _=False, p=path: self.remove_path(p))
        self.setCellWidget(row, self.COL_DELETE, self._center_widget(del_btn))

        self._notify_changed()

    def remove_path(self, path: str):
        if path not in self._paths:
            return
        row = self._paths.index(path)
        self._paths.pop(row)
        self.removeRow(row)
        self._notify_changed()

    def delete_selected_rows(self):
        rows = sorted(
            [r for r in range(self.rowCount())
             if (cb := self._cb_at(r)) and cb.isChecked()],
            reverse=True,
        )
        for row in rows:
            if 0 <= row < len(self._paths):
                self._paths.pop(row)
                self.removeRow(row)
        self._notify_changed()

    def set_all_checked(self, checked: bool):
        for row in range(self.rowCount()):
            cb = self._cb_at(row)
            if cb:
                cb.setChecked(checked)
        self._notify_changed()

    def get_checked_paths(self) -> list[str]:
        return [p for i, p in enumerate(self._paths)
                if (cb := self._cb_at(i)) and cb.isChecked()]

    def total_count(self) -> int:
        return len(self._paths)

    def checked_count(self) -> int:
        return sum(1 for r in range(self.rowCount())
                   if (cb := self._cb_at(r)) and cb.isChecked())

    def update_status(self, path: str, text: str):
        if path in self._paths:
            item = self.item(self._paths.index(path), self.COL_STATUS)
            if item:
                item.setText(text)

    def clear(self):
        self._paths.clear()
        self.setRowCount(0)
        self._notify_changed()

    def _cb_at(self, row: int) -> QCheckBox | None:
        wrap = self.cellWidget(row, self.COL_CHECK)
        return wrap.findChild(QCheckBox) if wrap else None

    @staticmethod
    def _center_widget(w: QWidget) -> QWidget:
        wrap = QWidget()
        lay  = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(); lay.addWidget(w); lay.addStretch()
        return wrap

    @staticmethod
    def _fmt_size(path: str) -> str:
        try:
            s = Path(path).stat().st_size
        except OSError:
            return "-"
        if s >= 1 << 20: return f"{s/(1<<20):.2f} MB"
        if s >= 1 << 10: return f"{s/(1<<10):.1f} KB"
        return f"{s} B"

    def _notify_changed(self):
        if self._on_changed:
            self._on_changed()


_THUMB_COLS = 4   # 썸네일 그리드 열 수
_THUMB_SCALE = 0.22  # PyMuPDF 렌더 스케일


class ThumbnailPageWidget(QFrame):
    """단일 PDF 페이지 썸네일 카드 — 클릭 또는 체크박스로 선택."""
    selection_changed = pyqtSignal()
    THUMB_W = 120  # 표시 폭(px)

    def __init__(self, page_index: int, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._page_index = page_index
        self._selected   = False
        self.setObjectName("thumbCard")
        self.setFixedWidth(140)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        scaled = pixmap.scaledToWidth(self.THUMB_W,
                                      Qt.TransformationMode.SmoothTransformation)
        self._thumb_label = QLabel()
        self._thumb_label.setFixedSize(scaled.width(), scaled.height())
        self._thumb_label.setPixmap(scaled)
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._thumb_label, 0, Qt.AlignmentFlag.AlignCenter)

        bot = QHBoxLayout()
        bot.setContentsMargins(0, 0, 0, 0)
        self._check = QCheckBox()
        self._check.stateChanged.connect(self._on_check_state)
        bot.addWidget(self._check)
        page_lbl = QLabel(str(page_index + 1))
        page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page_lbl.setObjectName("pageNum")
        bot.addWidget(page_lbl, 1)
        layout.addLayout(bot)

        self._update_style()

    def mousePressEvent(self, event):
        self.set_selected(not self._selected)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool):
        if self._selected == selected:
            return
        self._selected = selected
        self._check.blockSignals(True)
        self._check.setChecked(selected)
        self._check.blockSignals(False)
        self._update_style()
        self.selection_changed.emit()

    def is_selected(self) -> bool:
        return self._selected

    def page_index(self) -> int:
        return self._page_index

    def _on_check_state(self, state: int):
        sel = (state == 2)
        if self._selected == sel:
            return
        self._selected = sel
        self._update_style()
        self.selection_changed.emit()

    def _update_style(self):
        if self._selected:
            self.setStyleSheet(
                "#thumbCard{background:#DCFCE7;border:2px solid #16A34A;border-radius:10px;}"
                "#thumbCard QLabel{background:transparent;color:#15803D;}"
                "#thumbCard QCheckBox{background:transparent;}"
            )
        else:
            self.setStyleSheet(
                "#thumbCard{background:#FFFFFF;border:1px solid #E5EAF0;border-radius:10px;}"
                "#thumbCard QLabel{background:transparent;color:#64748B;}"
                "#thumbCard QCheckBox{background:transparent;}"
            )


class EditPageWidget(ThumbnailPageWidget):
    """페이지 편집 모드 전용 썸네일 — 회전 상태 추가."""

    def __init__(self, page_index: int, pixmap: QPixmap, parent=None):
        self._orig_pixmap = pixmap
        self._rotation    = 0
        super().__init__(page_index, pixmap, parent)

        self._rot_label = QLabel("")
        self._rot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rot_label.setObjectName("rotLabel")
        self.layout().addWidget(self._rot_label)

    def rotation(self) -> int:
        return self._rotation

    def rotate_90(self):
        self._rotation = (self._rotation + 90) % 360
        transform = QTransform().rotate(self._rotation)
        rotated   = self._orig_pixmap.transformed(
            transform, Qt.TransformationMode.SmoothTransformation
        )
        scaled = rotated.scaledToWidth(
            self.THUMB_W, Qt.TransformationMode.SmoothTransformation
        )
        self._thumb_label.setPixmap(scaled)
        self._thumb_label.setFixedSize(scaled.width(), scaled.height())
        self._rot_label.setText(f"↻ {self._rotation}°" if self._rotation else "")


class _PagesDropTarget(QWidget):
    """페이지 편집 화면 컨테이너 — PDF 파일 드롭 지원."""
    pdf_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setStyleSheet("background:#F6F8FB;")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(
            url.toLocalFile().lower().endswith(".pdf")
            for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path.lower().endswith(".pdf"):
                    self.pdf_dropped.emit(path)
                    event.acceptProposedAction()
                    return
        event.ignore()


class _SplitDropTarget(QWidget):
    """분할 화면 컨테이너 — 파일 드롭 지원."""
    pdf_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setStyleSheet("background:#F6F8FB;")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(
            url.toLocalFile().lower().endswith(".pdf")
            for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path.lower().endswith(".pdf"):
                    self.pdf_dropped.emit(path)
                    event.acceptProposedAction()
                    return
        event.ignore()


class DropFileTable(QTableWidget):
    COL_CHECK = 0
    COL_TYPE = 1
    COL_NAME = 2
    COL_PAGES = 3
    COL_OPTION = 4
    COL_SIZE = 5
    COL_DELETE = 6

    def __init__(self, on_changed=None, parent=None):
        super().__init__(0, 7, parent)
        self._on_changed = on_changed
        self._paths: list[str] = []

        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(False)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(46)

        self.setHorizontalHeaderLabels(
            [
                "",
                ko("\\ud615\\uc2dd"),
                ko("\\ud30c\\uc77c\\uba85"),
                ko("\\ud398\\uc774\\uc9c0"),
                ko("\\ud30c\\uc77c \\uc635\\uc158"),
                ko("\\ud06c\\uae30"),
                "",
            ]
        )
        header = self.horizontalHeader()
        header.setSectionResizeMode(self.COL_CHECK, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_TYPE, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_PAGES, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_OPTION, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_SIZE, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_DELETE, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(self.COL_CHECK, 42)
        self.setColumnWidth(self.COL_TYPE, 72)
        self.setColumnWidth(self.COL_PAGES, 72)
        self.setColumnWidth(self.COL_OPTION, 168)
        self.setColumnWidth(self.COL_SIZE, 90)
        self.setColumnWidth(self.COL_DELETE, 48)

        self.setStyleSheet(
            "QTableWidget{background:#FFFFFF;border:1px solid #E5EAF0;border-radius:10px;"
            "selection-background-color:#ECFDF5;selection-color:#0F172A;}"
            "QHeaderView::section{background:#F8FAFC;color:#64748B;border:none;"
            "border-bottom:1px solid #E5EAF0;padding:8px 6px;font-weight:bold;}"
            "QTableWidget::item{border-bottom:1px solid #F1F5F9;padding:4px;color:#334155;}"
        )

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if Path(path).suffix.lower() in SUPPORTED_EXT:
                    self.add_file(path)
            event.acceptProposedAction()
            self._notify_changed()
        else:
            super().dropEvent(event)

    def add_file(self, path: str):
        if path in self._paths:
            return

        row = self.rowCount()
        self.insertRow(row)
        self._paths.insert(row, path)

        check = QCheckBox()
        check.setChecked(True)
        check.stateChanged.connect(self._notify_changed)
        self.setCellWidget(row, self.COL_CHECK, self._center_widget(check))

        ext = Path(path).suffix.lstrip(".").lower()
        text, fg, bg = LABEL_COLOR.get(ext, ("FILE", "#334155", "#E2E8F0"))
        badge = QLabel(text)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedWidth(54)
        badge.setStyleSheet(
            f"background:{bg};color:{fg};border-radius:7px;padding:4px 6px;font-size:10px;"
            "font-weight:bold;"
        )
        self.setCellWidget(row, self.COL_TYPE, self._center_widget(badge))

        name_item = QTableWidgetItem(Path(path).name)
        name_item.setToolTip(path)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setItem(row, self.COL_NAME, name_item)

        page_item = QTableWidgetItem("-")
        page_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        page_item.setFlags(page_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setItem(row, self.COL_PAGES, page_item)

        option_widget = self._option_widget(ext)
        self.setCellWidget(row, self.COL_OPTION, option_widget)

        size_item = QTableWidgetItem(self._format_size(path))
        size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setItem(row, self.COL_SIZE, size_item)

        delete_btn = QPushButton(ko("\\uc0ad\\uc81c"))
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.setFixedHeight(26)
        delete_btn.setStyleSheet(
            "QPushButton{background:#FFFFFF;color:#94A3B8;border:1px solid #E2E8F0;"
            "border-radius:7px;font-size:8pt;} QPushButton:hover{background:#FEF2F2;"
            "color:#DC2626;border-color:#FCA5A5;}"
        )
        delete_btn.clicked.connect(lambda _checked=False, p=path: self.remove_path(p))
        self.setCellWidget(row, self.COL_DELETE, self._center_widget(delete_btn))

        self._notify_changed()

    def remove_path(self, path: str):
        if path not in self._paths:
            return
        row = self._paths.index(path)
        self._paths.pop(row)
        self.removeRow(row)
        self._notify_changed()

    def delete_selected_rows(self):
        rows = sorted(
            [row for row in range(self.rowCount())
             if (cb := self._checkbox_at(row)) and cb.isChecked()],
            reverse=True
        )
        for row in rows:
            if 0 <= row < len(self._paths):
                self._paths.pop(row)
                self.removeRow(row)
        self._notify_changed()

    def set_all_checked(self, checked: bool):
        for row in range(self.rowCount()):
            checkbox = self._checkbox_at(row)
            if checkbox:
                checkbox.setChecked(checked)
        self._notify_changed()

    def get_file_items(self, checked_only: bool = False) -> list[dict]:
        items = []
        for row, path in enumerate(self._paths):
            checkbox = self._checkbox_at(row)
            if checked_only and checkbox and not checkbox.isChecked():
                continue
            items.append({"path": path, "option": self._option_at(row)})
        return items

    def total_count(self) -> int:
        return len(self._paths)

    def checked_count(self) -> int:
        count = 0
        for row in range(self.rowCount()):
            checkbox = self._checkbox_at(row)
            if checkbox and checkbox.isChecked():
                count += 1
        return count

    def clear(self):
        self._paths.clear()
        self.setRowCount(0)
        self._notify_changed()

    def _checkbox_at(self, row: int) -> QCheckBox | None:
        return self._find_child_widget(row, self.COL_CHECK, QCheckBox)

    def _option_at(self, row: int) -> str:
        group = self.cellWidget(row, self.COL_OPTION)
        if group and group.property("option") == "unreadable":
            return "unreadable"
        return "readable"

    def _option_widget(self, ext: str) -> QWidget:
        wrap = QWidget()
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        readable = QRadioButton("Readable")
        unreadable = QRadioButton("Unreadable")
        readable.setChecked(True)
        buttons = QButtonGroup(wrap)
        buttons.addButton(readable)
        buttons.addButton(unreadable)

        def sync_option():
            wrap.setProperty("option", "readable" if readable.isChecked() else "unreadable")

        readable.toggled.connect(sync_option)
        unreadable.toggled.connect(sync_option)
        sync_option()

        if ext in ("jpg", "jpeg", "png", "bmp", "tiff", "tif"):
            readable.setEnabled(False)
            unreadable.setEnabled(False)
        if ext in ("html", "htm"):
            readable.setEnabled(False)
            unreadable.setEnabled(False)

        for rb in (readable, unreadable):
            rb.setFont(QFont("Malgun Gothic", 8))
            rb.setStyleSheet("QRadioButton{color:#475569;background:transparent;}")
            layout.addWidget(rb)
        return wrap

    @staticmethod
    def _center_widget(widget: QWidget) -> QWidget:
        wrap = QWidget()
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        layout.addWidget(widget)
        layout.addStretch()
        return wrap

    def _find_child_widget(self, row: int, col: int, cls):
        wrap = self.cellWidget(row, col)
        if not wrap:
            return None
        return wrap.findChild(cls)

    @staticmethod
    def _format_size(path: str) -> str:
        try:
            size = Path(path).stat().st_size
        except OSError:
            return "-"
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.2f} MB"
        if size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} B"

    def _notify_changed(self):
        if self._on_changed:
            self._on_changed()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DocMerger Studio")
        self.setMinimumSize(1120, 720)
        self.resize(1220, 780)
        self._worker: ConvertWorker | None = None
        self._out_path = ""
        self._mode = "merge"
        self._compress_out_dir = ""
        self._compress_worker: CompressWorker | None = None
        self._split_out_dir = ""
        self._split_pdf_path: str = ""
        self._split_page_count: int = 0
        self._split_page_widgets: list[ThumbnailPageWidget] = []
        self._split_worker: SplitSelectedWorker | None = None
        self._pages_pdf_path: str = ""
        self._pages_page_count: int = 0
        self._pages_page_widgets: list[EditPageWidget] = []
        self._pages_out_dir: str = ""
        self._pages_worker: PageEditWorker | None = None
        self._convert_out_dir: str = ""
        self._convert_worker: StandaloneConvertWorker | None = None
        self._security_out_dir: str = ""
        self._security_worker: SecurityWorker | None = None
        self._sidebar_buttons: dict[str, QPushButton] = {}
        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        root.setStyleSheet("background:#F6F8FB;")
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self._build_sidebar())

        self._workspace_stack = QStackedWidget()
        self._workspace_stack.addWidget(self._build_merge_workspace())    # 0
        self._workspace_stack.addWidget(self._build_compress_workspace()) # 1
        self._workspace_stack.addWidget(self._build_split_workspace())    # 2
        self._workspace_stack.addWidget(self._build_pages_workspace())    # 3
        self._workspace_stack.addWidget(self._build_convert_workspace())  # 4
        self._workspace_stack.addWidget(self._build_security_workspace()) # 5
        body_layout.addWidget(self._workspace_stack, 1)

        self._option_stack = QStackedWidget()
        self._option_stack.addWidget(self._build_merge_option_panel())    # 0
        self._option_stack.addWidget(self._build_compress_option_panel()) # 1
        self._option_stack.addWidget(self._build_split_option_panel())    # 2
        self._option_stack.addWidget(self._build_pages_option_panel())    # 3
        self._option_stack.addWidget(self._build_convert_option_panel())  # 4
        self._option_stack.addWidget(self._build_security_option_panel()) # 5
        body_layout.addWidget(self._option_stack)

        layout.addWidget(body, 1)
        layout.addWidget(self._build_footer())

        self.status = QStatusBar()
        self.status.showMessage(ko("\\uc900\\ube44"))
        self.status.setStyleSheet("QStatusBar{background:#FFFFFF;color:#64748B;}")
        self.setStatusBar(self.status)
        self._set_mode("merge")

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setFixedWidth(184)
        sidebar.setStyleSheet("background:#FFFFFF;border-right:1px solid #E5EAF0;")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        brand = QHBoxLayout()
        logo = QLabel("D")
        logo.setFixedSize(34, 34)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFont(QFont("Malgun Gothic", 12, QFont.Weight.Bold))
        logo.setStyleSheet("background:#22C55E;color:#FFFFFF;border-radius:9px;")
        brand.addWidget(logo)

        title_box = QWidget()
        title_layout = QVBoxLayout(title_box)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        title = QLabel("DocMerger Studio")
        title.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        title.setStyleSheet("color:#0F172A;background:transparent;")
        title_layout.addWidget(title)
        subtitle = QLabel(ko("PDF \\ubcd1\\ud569 \\u00b7 \\ubcc0\\ud658"))
        subtitle.setFont(QFont("Malgun Gothic", 8))
        subtitle.setStyleSheet("color:#94A3B8;background:transparent;")
        title_layout.addWidget(subtitle)
        brand.addWidget(title_box, 1)
        layout.addLayout(brand)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color:#EEF2F7;")
        layout.addWidget(divider)

        for key, label, enabled, icon in MENU_ITEMS:
            btn = QPushButton(f"{icon}   {label}")
            btn.setFixedHeight(38)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(QFont("Malgun Gothic", 9, QFont.Weight.Bold))
            btn.clicked.connect(lambda _checked=False, k=key, e=enabled: self._on_menu_clicked(k, e))
            layout.addWidget(btn)
            self._sidebar_buttons[key] = btn

        layout.addStretch()

        history = QPushButton("i   " + ko("\\ucd5c\\uadfc \\ud30c\\uc77c"))
        history.setFixedHeight(34)
        history.setStyleSheet(self._side_btn_style(False))
        layout.addWidget(history)

        favorite = QPushButton("*   " + ko("\\uc990\\uaca8\\ucc3e\\uae30"))
        favorite.setFixedHeight(34)
        favorite.setStyleSheet(self._side_btn_style(False))
        layout.addWidget(favorite)
        return sidebar

    def _build_merge_workspace(self) -> QWidget:
        workspace = QWidget()
        workspace.setStyleSheet("background:#F6F8FB;")
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(22, 16, 18, 14)
        layout.setSpacing(12)

        toolbar = QHBoxLayout()
        add_btn = QPushButton("+  " + ko("\\ud30c\\uc77c \\ucd94\\uac00"))
        add_btn.setFixedHeight(34)
        add_btn.setStyleSheet(self._button_style("#F0FDF4", "#15803D", "#DCFCE7"))
        add_btn.clicked.connect(self._add_files)
        toolbar.addWidget(add_btn)

        selected_delete = QPushButton(ko("\\uc120\\ud0dd \\uc0ad\\uc81c"))
        selected_delete.setFixedHeight(34)
        selected_delete.setStyleSheet(self._button_style("#FFFFFF", "#475569", "#F1F5F9"))
        selected_delete.clicked.connect(self._delete_selected)
        toolbar.addWidget(selected_delete)

        clear_btn = QPushButton(ko("\\uc804\\uccb4 \\uc0ad\\uc81c"))
        clear_btn.setFixedHeight(34)
        clear_btn.setStyleSheet(self._button_style("#FFFFFF", "#DC2626", "#FEF2F2"))
        clear_btn.clicked.connect(self.file_table_clear_safe)
        toolbar.addWidget(clear_btn)

        toolbar.addStretch()

        up_btn = QPushButton(ko("\\uc704\\ub85c"))
        up_btn.setEnabled(False)
        up_btn.setFixedHeight(34)
        up_btn.setStyleSheet(self._button_style("#FFFFFF", "#94A3B8", "#FFFFFF"))
        toolbar.addWidget(up_btn)

        down_btn = QPushButton(ko("\\uc544\\ub798\\ub85c"))
        down_btn.setEnabled(False)
        down_btn.setFixedHeight(34)
        down_btn.setStyleSheet(self._button_style("#FFFFFF", "#94A3B8", "#FFFFFF"))
        toolbar.addWidget(down_btn)

        layout.addLayout(toolbar)

        dropzone = QFrame()
        dropzone.setFixedHeight(92)
        dropzone.setStyleSheet(
            "QFrame{background:#FFFFFF;border:2px dashed #CBD5E1;border-radius:12px;}"
        )
        drop_layout = QHBoxLayout(dropzone)
        drop_layout.setContentsMargins(24, 14, 24, 14)
        drop_layout.setSpacing(14)

        file_icon = QLabel("PDF")
        file_icon.setFixedSize(48, 48)
        file_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        file_icon.setStyleSheet(
            "background:#F0FDF4;color:#16A34A;border:1px solid #BBF7D0;border-radius:12px;"
            "font-weight:bold;"
        )
        drop_layout.addWidget(file_icon)

        drop_text = QWidget()
        drop_text_layout = QVBoxLayout(drop_text)
        drop_text_layout.setContentsMargins(0, 0, 0, 0)
        drop_text_layout.setSpacing(2)
        main_hint = QLabel(ko("\\ud30c\\uc77c\\uc744 \\uc5ec\\uae30\\uc5d0 \\ub4dc\\ub798\\uadf8\\ud558\\uac70\\ub098 \\ucd94\\uac00\\ud558\\uc138\\uc694"))
        main_hint.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        main_hint.setStyleSheet("color:#334155;background:transparent;")
        drop_text_layout.addWidget(main_hint)
        sub_hint = QLabel(ko("HWP, DOCX, PDF, IMG, HTML\\uc744 PDF\\ub85c \\ubcc0\\ud658 \\ud6c4 \\ubcd1\\ud569\\ud569\\ub2c8\\ub2e4."))
        sub_hint.setFont(QFont("Malgun Gothic", 8))
        sub_hint.setStyleSheet("color:#94A3B8;background:transparent;")
        drop_text_layout.addWidget(sub_hint)
        drop_layout.addWidget(drop_text)
        drop_layout.addStretch()
        layout.addWidget(dropzone)

        self.file_table = DropFileTable(on_changed=self._update_selection_summary)
        self.file_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.file_table, 1)

        return workspace

    def _build_compress_workspace(self) -> QWidget:
        workspace = QWidget()
        workspace.setStyleSheet("background:#F6F8FB;")
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(22, 16, 18, 14)
        layout.setSpacing(12)

        toolbar = QHBoxLayout()
        add_btn = QPushButton("+  " + ko("\\ud30c\\uc77c \\ucd94\\uac00"))
        add_btn.setFixedHeight(34)
        add_btn.setStyleSheet(self._button_style("#F0FDF4", "#15803D", "#DCFCE7"))
        add_btn.clicked.connect(self._add_compress_files)
        toolbar.addWidget(add_btn)

        del_btn = QPushButton(ko("\\uc120\\ud0dd \\uc0ad\\uc81c"))
        del_btn.setFixedHeight(34)
        del_btn.setStyleSheet(self._button_style("#FFFFFF", "#475569", "#F1F5F9"))
        del_btn.clicked.connect(lambda: self.compress_table.delete_selected_rows())
        toolbar.addWidget(del_btn)

        clear_btn = QPushButton(ko("\\uc804\\uccb4 \\uc0ad\\uc81c"))
        clear_btn.setFixedHeight(34)
        clear_btn.setStyleSheet(self._button_style("#FFFFFF", "#DC2626", "#FEF2F2"))
        clear_btn.clicked.connect(lambda: self.compress_table.clear())
        toolbar.addWidget(clear_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        dropzone = QFrame()
        dropzone.setFixedHeight(92)
        dropzone.setStyleSheet(
            "QFrame{background:#FFFFFF;border:2px dashed #CBD5E1;border-radius:12px;}"
        )
        drop_layout = QHBoxLayout(dropzone)
        drop_layout.setContentsMargins(24, 14, 24, 14)
        drop_layout.setSpacing(14)

        file_icon = QLabel("PDF")
        file_icon.setFixedSize(48, 48)
        file_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        file_icon.setStyleSheet(
            "background:#FEF2F2;color:#DC2626;border:1px solid #FECACA;border-radius:12px;"
            "font-weight:bold;"
        )
        drop_layout.addWidget(file_icon)

        drop_text = QWidget()
        dt_layout = QVBoxLayout(drop_text)
        dt_layout.setContentsMargins(0, 0, 0, 0)
        dt_layout.setSpacing(2)
        main_hint = QLabel(ko("PDF \\ud30c\\uc77c\\uc744 \\ub4dc\\ub798\\uadf8\\ud558\\uac70\\ub098 \\ucd94\\uac00\\ud558\\uc138\\uc694"))
        main_hint.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        main_hint.setStyleSheet("color:#334155;background:transparent;")
        dt_layout.addWidget(main_hint)
        sub_hint = QLabel(ko("PDF\\ub9cc \\uc9c0\\uc6d0\\ud569\\ub2c8\\ub2e4. \\uc555\\ucd95 \\ud6c4 \\uac1c\\ubcc4 \\ud30c\\uc77c\\ub85c \\uc800\\uc7a5\\ub429\\ub2c8\\ub2e4."))
        sub_hint.setFont(QFont("Malgun Gothic", 8))
        sub_hint.setStyleSheet("color:#94A3B8;background:transparent;")
        dt_layout.addWidget(sub_hint)
        drop_layout.addWidget(drop_text)
        drop_layout.addStretch()
        layout.addWidget(dropzone)

        self.compress_table = CompressPdfTable(on_changed=self._update_selection_summary)
        self.compress_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.compress_table, 1)

        return workspace

    def _build_split_workspace(self) -> QWidget:
        workspace = _SplitDropTarget()
        workspace.pdf_dropped.connect(self._load_split_pdf)
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(22, 16, 18, 14)
        layout.setSpacing(12)

        # ── 툴바 ─────────────────────────────────────────────────────────────
        toolbar = QHBoxLayout()

        add_btn = QPushButton("+  " + ko("\\ud30c\\uc77c \\ucd94\\uac00"))
        add_btn.setFixedHeight(34)
        add_btn.setStyleSheet(self._button_style("#F0FDF4", "#15803D", "#DCFCE7"))
        add_btn.clicked.connect(self._add_split_files)
        toolbar.addWidget(add_btn)

        remove_btn = QPushButton(ko("\\ud30c\\uc77c \\uc81c\\uac70"))
        remove_btn.setFixedHeight(34)
        remove_btn.setStyleSheet(self._button_style("#FFFFFF", "#DC2626", "#FEF2F2"))
        remove_btn.clicked.connect(self._clear_split_view)
        toolbar.addWidget(remove_btn)

        toolbar.addSpacing(8)

        all_btn = QPushButton(ko("\\uc804\\uccb4 \\uc120\\ud0dd"))
        all_btn.setFixedHeight(34)
        all_btn.setStyleSheet(self._button_style("#FFFFFF", "#2563EB", "#EFF6FF"))
        all_btn.clicked.connect(self._select_all_split_pages)
        toolbar.addWidget(all_btn)

        none_btn = QPushButton(ko("\\uc804\\uccb4 \\ud574\\uc81c"))
        none_btn.setFixedHeight(34)
        none_btn.setStyleSheet(self._button_style("#FFFFFF", "#475569", "#F1F5F9"))
        none_btn.clicked.connect(self._clear_split_pages)
        toolbar.addWidget(none_btn)

        odd_btn = QPushButton(ko("\\ud648\\uc218"))
        odd_btn.setFixedHeight(34)
        odd_btn.setStyleSheet(self._button_style("#FFFFFF", "#7C3AED", "#F5F3FF"))
        odd_btn.clicked.connect(self._select_odd_split_pages)
        toolbar.addWidget(odd_btn)

        even_btn = QPushButton(ko("\\uc9dd\\uc218"))
        even_btn.setFixedHeight(34)
        even_btn.setStyleSheet(self._button_style("#FFFFFF", "#0891B2", "#ECFEFF"))
        even_btn.clicked.connect(self._select_even_split_pages)
        toolbar.addWidget(even_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # ── 뷰 스택: [0] 드롭존 | [1] 썸네일 그리드 ─────────────────────────
        self._split_view_stack = QStackedWidget()

        # -- index 0: 드롭존 --
        dropzone = QFrame()
        dropzone.setStyleSheet(
            "QFrame{background:#FFFFFF;border:2px dashed #CBD5E1;border-radius:12px;}"
        )
        dz_layout = QHBoxLayout(dropzone)
        dz_layout.setContentsMargins(24, 30, 24, 30)
        dz_layout.setSpacing(14)
        file_icon = QLabel("PDF")
        file_icon.setFixedSize(56, 56)
        file_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        file_icon.setStyleSheet(
            "background:#EFF6FF;color:#2563EB;border:1px solid #BFDBFE;"
            "border-radius:14px;font-weight:bold;font-size:11pt;"
        )
        dz_layout.addWidget(file_icon)
        dz_text = QWidget()
        dz_tl = QVBoxLayout(dz_text)
        dz_tl.setContentsMargins(0, 0, 0, 0)
        dz_tl.setSpacing(4)
        main_hint = QLabel(
            ko("\\ubd84\\ud560\\ud560 PDF \\ud30c\\uc77c\\uc744 \\ub4dc\\ub798\\uadf8\\ud558\\uac70\\ub098 \\ucd94\\uac00\\ud558\\uc138\\uc694")
        )
        main_hint.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        main_hint.setStyleSheet("color:#334155;background:transparent;")
        dz_tl.addWidget(main_hint)
        sub_hint = QLabel(
            ko("PDF 1\\uac1c\\ub9cc \\uc9c0\\uc6d0\\ud569\\ub2c8\\ub2e4. \\uc120\\ud0dd\\ud55c \\ud398\\uc774\\uc9c0\\ub97c PDF\\ub85c \\uc800\\uc7a5\\ud569\\ub2c8\\ub2e4.")
        )
        sub_hint.setFont(QFont("Malgun Gothic", 8))
        sub_hint.setStyleSheet("color:#94A3B8;background:transparent;")
        dz_tl.addWidget(sub_hint)
        dz_layout.addWidget(dz_text)
        dz_layout.addStretch()
        self._split_view_stack.addWidget(dropzone)   # index 0

        # -- index 1: 썸네일 스크롤 영역 --
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            "QScrollArea{border:none;background:#F6F8FB;}"
            "QScrollBar:vertical{width:8px;background:#F1F5F9;border-radius:4px;}"
            "QScrollBar::handle:vertical{background:#CBD5E1;border-radius:4px;min-height:20px;}"
        )
        grid_container = QWidget()
        grid_container.setStyleSheet("background:#F6F8FB;")
        self._split_grid = QGridLayout(grid_container)
        self._split_grid.setContentsMargins(4, 8, 4, 8)
        self._split_grid.setSpacing(10)
        self._split_grid.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(grid_container)
        self._split_view_stack.addWidget(scroll)     # index 1

        layout.addWidget(self._split_view_stack, 1)
        return workspace

    def _build_merge_option_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(292)
        panel.setStyleSheet("background:#FFFFFF;border-left:1px solid #E5EAF0;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(12)

        title = QLabel(ko("\\uc791\\uc5c5 \\uc635\\uc158"))
        title.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        title.setStyleSheet("color:#0F172A;background:transparent;")
        layout.addWidget(title)

        compression = self._card(ko("\\uc555\\ucd95 \\uc635\\uc158"))
        c_layout = compression.layout()
        self.rb_compress_none = QRadioButton(ko("\\uc555\\ucd95 \\uc548 \\ud568"))
        self.rb_compress_basic = QRadioButton(ko("\\uae30\\ubcf8 \\uc555\\ucd95"))
        self.rb_compress_strong = QRadioButton(ko("\\uac15\\ud55c \\uc555\\ucd95"))
        self.rb_compress_basic.setChecked(True)
        self._compress_group = QButtonGroup(self)
        for rb in (self.rb_compress_none, self.rb_compress_basic, self.rb_compress_strong):
            self._compress_group.addButton(rb)
            rb.setStyleSheet("QRadioButton{color:#334155;background:transparent;padding:3px;}")
            rb.toggled.connect(self._sync_quality_enabled)
            c_layout.addWidget(rb)

        quality_label = QLabel(ko("\\ud488\\uc9c8"))
        quality_label.setStyleSheet("color:#64748B;background:transparent;font-weight:bold;margin-top:8px;")
        c_layout.addWidget(quality_label)

        self.combo_quality = QComboBox()
        self.combo_quality.addItem(ko("\\ub192\\uc74c"), "high")
        self.combo_quality.addItem(ko("\\ubcf4\\ud1b5"), "medium")
        self.combo_quality.addItem(ko("\\ub0ae\\uc74c"), "low")
        self.combo_quality.setStyleSheet(
            "QComboBox{background:#FFFFFF;border:1px solid #DDE5EF;border-radius:8px;"
            "padding:6px 8px;color:#334155;}"
        )
        c_layout.addWidget(self.combo_quality)
        layout.addWidget(compression)

        summary = self._card(ko("\\uc120\\ud0dd \\uc694\\uc57d"))
        s_layout = summary.layout()
        self.lbl_total = QLabel(ko("\\uc804\\uccb4 \\ud30c\\uc77c: 0"))
        self.lbl_target = QLabel(ko("\\uc791\\uc5c5 \\ub300\\uc0c1: 0"))
        for label in (self.lbl_total, self.lbl_target):
            label.setStyleSheet("color:#334155;background:transparent;padding:3px;")
            s_layout.addWidget(label)
        layout.addWidget(summary)

        output = self._card(ko("\\ucd9c\\ub825 \\ud615\\uc2dd"))
        o_layout = output.layout()
        format_box = QComboBox()
        format_box.addItem("PDF (*.pdf)")
        format_box.setStyleSheet(
            "QComboBox{background:#FFFFFF;border:1px solid #DDE5EF;border-radius:8px;"
            "padding:6px 8px;color:#334155;}"
        )
        o_layout.addWidget(format_box)
        layout.addWidget(output)

        advanced = self._card(ko("\\uace0\\uae09 \\uc635\\uc158"))
        a_layout = advanced.layout()
        advanced_label = QLabel(ko("\\uac15\\ud55c \\uc555\\ucd95\\uc740 \\ud14d\\uc2a4\\ud2b8 \\uc120\\ud0dd/\\uac80\\uc0c9\\uc774 \\uc0ac\\ub77c\\uc9c8 \\uc218 \\uc788\\uc2b5\\ub2c8\\ub2e4."))
        advanced_label.setWordWrap(True)
        advanced_label.setStyleSheet("color:#64748B;background:transparent;line-height:140%;")
        a_layout.addWidget(advanced_label)
        layout.addWidget(advanced)

        layout.addStretch()
        self._sync_quality_enabled()
        return panel

    def _build_compress_option_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(292)
        panel.setStyleSheet("background:#FFFFFF;border-left:1px solid #E5EAF0;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(12)

        title = QLabel(ko("\\uc555\\ucd95 \\uc635\\uc158"))
        title.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        title.setStyleSheet("color:#0F172A;background:transparent;")
        layout.addWidget(title)

        mode_card = self._card(ko("\\uc555\\ucd95 \\ubc29\\uc2dd"))
        c_layout = mode_card.layout()
        self.rb_compress_basic_c = QRadioButton(ko("\\uae30\\ubcf8 \\uc555\\ucd95"))
        self.rb_compress_strong_c = QRadioButton(ko("\\uac15\\ud55c \\uc555\\ucd95"))
        self.rb_compress_basic_c.setChecked(True)
        self._compress_group_c = QButtonGroup(self)
        for rb in (self.rb_compress_basic_c, self.rb_compress_strong_c):
            self._compress_group_c.addButton(rb)
            rb.setStyleSheet("QRadioButton{color:#334155;background:transparent;padding:3px;}")
            rb.toggled.connect(self._sync_quality_enabled_c)
            c_layout.addWidget(rb)

        quality_label = QLabel(ko("\\ud488\\uc9c8 (\\uac15\\ud55c \\uc555\\ucd95 \\uc804\\uc6a9)"))
        quality_label.setStyleSheet("color:#64748B;background:transparent;font-weight:bold;margin-top:8px;")
        c_layout.addWidget(quality_label)

        self.combo_quality_c = QComboBox()
        self.combo_quality_c.addItem(ko("\\ub192\\uc74c"), "high")
        self.combo_quality_c.addItem(ko("\\ubcf4\\ud1b5"), "medium")
        self.combo_quality_c.addItem(ko("\\ub0ae\\uc74c"), "low")
        self.combo_quality_c.setStyleSheet(
            "QComboBox{background:#FFFFFF;border:1px solid #DDE5EF;border-radius:8px;"
            "padding:6px 8px;color:#334155;}"
        )
        c_layout.addWidget(self.combo_quality_c)
        layout.addWidget(mode_card)

        summary = self._card(ko("\\uc120\\ud0dd \\uc694\\uc57d"))
        s_layout = summary.layout()
        self.lbl_total_c = QLabel(ko("\\uc804\\uccb4 \\ud30c\\uc77c: 0"))
        self.lbl_target_c = QLabel(ko("\\uc791\\uc5c5 \\ub300\\uc0c1: 0"))
        for label in (self.lbl_total_c, self.lbl_target_c):
            label.setStyleSheet("color:#334155;background:transparent;padding:3px;")
            s_layout.addWidget(label)
        layout.addWidget(summary)

        note_card = self._card(ko("\\uc548\\ub0b4"))
        n_layout = note_card.layout()
        note_lbl = QLabel(
            ko("\\uac15\\ud55c \\uc555\\ucd95\\uc740 \\ud14d\\uc2a4\\ud2b8 \\uc120\\ud0dd/\\uac80\\uc0c9\\uc774 \\uc0ac\\ub77c\\uc9c8 \\uc218 \\uc788\\uc2b5\\ub2c8\\ub2e4.")
            + "\n"
            + ko("\\uc555\\ucd95\\ub41c \\ud30c\\uc77c\\uc740 \\uc120\\ud0dd \\ud3f4\\ub354\\uc5d0 \\uc800\\uc7a5\\ub429\\ub2c8\\ub2e4.")
        )
        note_lbl.setWordWrap(True)
        note_lbl.setStyleSheet("color:#64748B;background:transparent;line-height:140%;")
        n_layout.addWidget(note_lbl)
        layout.addWidget(note_card)

        layout.addStretch()
        self._sync_quality_enabled_c()
        return panel

    def _build_split_option_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(292)
        panel.setStyleSheet("background:#FFFFFF;border-left:1px solid #E5EAF0;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(12)

        title = QLabel(ko("\\ubd84\\ud560 \\uc635\\uc158"))
        title.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        title.setStyleSheet("color:#0F172A;background:transparent;")
        layout.addWidget(title)

        mode_card = self._card(ko("\\uc800\\uc7a5 \\ubc29\\uc2dd"))
        m_layout = mode_card.layout()
        self.rb_split_single = QRadioButton(
            ko("\\uc120\\ud0dd \\ud398\\uc774\\uc9c0\\ub97c \\ud558\\ub098\\uc758 PDF\\ub85c \\uc800\\uc7a5")
        )
        self.rb_split_each_s = QRadioButton(
            ko("\\uc120\\ud0dd \\ud398\\uc774\\uc9c0\\ub97c \\uac01\\uac01 PDF\\ub85c \\uc800\\uc7a5")
        )
        self.rb_split_single.setChecked(True)
        self._split_save_group = QButtonGroup(self)
        for rb in (self.rb_split_single, self.rb_split_each_s):
            self._split_save_group.addButton(rb)
            rb.setFont(QFont("Malgun Gothic", 8))
            rb.setStyleSheet("QRadioButton{color:#334155;background:transparent;padding:3px;}")
            m_layout.addWidget(rb)
        layout.addWidget(mode_card)

        summary_card = self._card(ko("\\uc120\\ud0dd \\uc694\\uc57d"))
        s_layout = summary_card.layout()
        self.lbl_split_filename = QLabel(ko("(\\ud30c\\uc77c \\uc5c6\\uc74c)"))
        self.lbl_split_total    = QLabel(ko("\\uc804\\uccb4 \\ud398\\uc774\\uc9c0: 0"))
        self.lbl_split_selected = QLabel(ko("\\uc120\\ud0dd \\ud398\\uc774\\uc9c0: 0"))
        for lbl in (self.lbl_split_filename, self.lbl_split_total, self.lbl_split_selected):
            lbl.setStyleSheet("color:#334155;background:transparent;padding:3px;font-size:8pt;")
            lbl.setWordWrap(True)
            s_layout.addWidget(lbl)
        layout.addWidget(summary_card)

        tip_card = self._card(ko("\\ube60\\ub978 \\uc120\\ud0dd"))
        t_layout = tip_card.layout()
        tip_lbl = QLabel(
            ko("\\ud234\\ubc14 \\uc804\\uccb4\\uc120\\ud0dd / \\ud574\\uc81c / \\ud648\\uc218 / \\uc9dd\\uc218 \\ubc84\\ud2bc\\uc73c\\ub85c \\ube60\\ub974\\uac8c \\uc120\\ud0dd\\ud560 \\uc218 \\uc788\\uc2b5\\ub2c8\\ub2e4.")
        )
        tip_lbl.setWordWrap(True)
        tip_lbl.setStyleSheet("color:#64748B;background:transparent;font-size:8pt;")
        t_layout.addWidget(tip_lbl)
        layout.addWidget(tip_card)

        note_card = self._card(ko("\\uc548\\ub0b4"))
        n_layout = note_card.layout()
        note_lbl = QLabel(ko("\\ud398\\uc774\\uc9c0 \\ubc88\\ud638\\ub294 1\\ubd80\\ud130 \\uc2dc\\uc791\\ud569\\ub2c8\\ub2e4."))
        note_lbl.setWordWrap(True)
        note_lbl.setStyleSheet("color:#64748B;background:transparent;font-size:8pt;")
        n_layout.addWidget(note_lbl)
        layout.addWidget(note_card)

        layout.addStretch()
        return panel

    def _build_pages_workspace(self) -> QWidget:
        workspace = _PagesDropTarget()
        workspace.pdf_dropped.connect(self._load_pages_pdf)
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(22, 16, 18, 14)
        layout.setSpacing(12)

        toolbar = QHBoxLayout()

        add_btn = QPushButton("+  " + ko("\\ud30c\\uc77c \\ucd94\\uac00"))
        add_btn.setFixedHeight(34)
        add_btn.setStyleSheet(self._button_style("#F0FDF4", "#15803D", "#DCFCE7"))
        add_btn.clicked.connect(self._add_pages_file)
        toolbar.addWidget(add_btn)

        remove_btn = QPushButton(ko("\\ud30c\\uc77c \\uc81c\\uac70"))
        remove_btn.setFixedHeight(34)
        remove_btn.setStyleSheet(self._button_style("#FFFFFF", "#DC2626", "#FEF2F2"))
        remove_btn.clicked.connect(self._clear_pages_view)
        toolbar.addWidget(remove_btn)

        toolbar.addSpacing(8)

        all_btn = QPushButton(ko("\\uc804\\uccb4 \\uc120\\ud0dd"))
        all_btn.setFixedHeight(34)
        all_btn.setStyleSheet(self._button_style("#FFFFFF", "#2563EB", "#EFF6FF"))
        all_btn.clicked.connect(self._select_all_pages)
        toolbar.addWidget(all_btn)

        none_btn = QPushButton(ko("\\uc804\\uccb4 \\ud574\\uc81c"))
        none_btn.setFixedHeight(34)
        none_btn.setStyleSheet(self._button_style("#FFFFFF", "#475569", "#F1F5F9"))
        none_btn.clicked.connect(self._clear_pages_selection)
        toolbar.addWidget(none_btn)

        toolbar.addSpacing(8)

        del_btn = QPushButton(ko("\\uc120\\ud0dd \\uc0ad\\uc81c"))
        del_btn.setFixedHeight(34)
        del_btn.setStyleSheet(self._button_style("#FFFFFF", "#DC2626", "#FEF2F2"))
        del_btn.clicked.connect(self._delete_selected_pages)
        toolbar.addWidget(del_btn)

        rot_btn = QPushButton("↻  90°")
        rot_btn.setFixedHeight(34)
        rot_btn.setStyleSheet(self._button_style("#FFFFFF", "#7C3AED", "#F5F3FF"))
        rot_btn.clicked.connect(self._rotate_selected_pages)
        toolbar.addWidget(rot_btn)

        left_btn = QPushButton("←  " + ko("\\uc774\\ub3d9"))
        left_btn.setFixedHeight(34)
        left_btn.setStyleSheet(self._button_style("#FFFFFF", "#0891B2", "#ECFEFF"))
        left_btn.clicked.connect(lambda: self._move_pages(-1))
        toolbar.addWidget(left_btn)

        right_btn = QPushButton("→  " + ko("\\uc774\\ub3d9"))
        right_btn.setFixedHeight(34)
        right_btn.setStyleSheet(self._button_style("#FFFFFF", "#0891B2", "#ECFEFF"))
        right_btn.clicked.connect(lambda: self._move_pages(1))
        toolbar.addWidget(right_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._pages_view_stack = QStackedWidget()

        dropzone = QFrame()
        dropzone.setStyleSheet(
            "QFrame{background:#FFFFFF;border:2px dashed #CBD5E1;border-radius:12px;}"
        )
        dz_layout = QHBoxLayout(dropzone)
        dz_layout.setContentsMargins(24, 30, 24, 30)
        dz_layout.setSpacing(14)
        file_icon = QLabel("PDF")
        file_icon.setFixedSize(56, 56)
        file_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        file_icon.setStyleSheet(
            "background:#F5F3FF;color:#7C3AED;border:1px solid #DDD6FE;"
            "border-radius:14px;font-weight:bold;font-size:11pt;"
        )
        dz_layout.addWidget(file_icon)
        dz_text = QWidget()
        dz_tl = QVBoxLayout(dz_text)
        dz_tl.setContentsMargins(0, 0, 0, 0)
        dz_tl.setSpacing(4)
        main_hint = QLabel(
            ko("\\ud3b8\\uc9d1\\ud560 PDF \\ud30c\\uc77c\\uc744 \\ub4dc\\ub798\\uadf8\\ud558\\uac70\\ub098 \\ucd94\\uac00\\ud558\\uc138\\uc694")
        )
        main_hint.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        main_hint.setStyleSheet("color:#334155;background:transparent;")
        dz_tl.addWidget(main_hint)
        sub_hint = QLabel(
            ko("PDF 1\\uac1c\\ub9cc \\uc9c0\\uc6d0\\ud569\\ub2c8\\ub2e4. \\uc0ad\\uc81c\\u00b7\\ud68c\\uc804\\u00b7\\uc21c\\uc11c \\ubcc0\\uacbd \\ud6c4 \\uc0c8 PDF\\ub85c \\uc800\\uc7a5\\ud569\\ub2c8\\ub2e4.")
        )
        sub_hint.setFont(QFont("Malgun Gothic", 8))
        sub_hint.setStyleSheet("color:#94A3B8;background:transparent;")
        dz_tl.addWidget(sub_hint)
        dz_layout.addWidget(dz_text)
        dz_layout.addStretch()
        self._pages_view_stack.addWidget(dropzone)   # index 0

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            "QScrollArea{border:none;background:#F6F8FB;}"
            "QScrollBar:vertical{width:8px;background:#F1F5F9;border-radius:4px;}"
            "QScrollBar::handle:vertical{background:#CBD5E1;border-radius:4px;min-height:20px;}"
        )
        grid_container = QWidget()
        grid_container.setStyleSheet("background:#F6F8FB;")
        self._pages_grid = QGridLayout(grid_container)
        self._pages_grid.setContentsMargins(4, 8, 4, 8)
        self._pages_grid.setSpacing(10)
        self._pages_grid.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(grid_container)
        self._pages_view_stack.addWidget(scroll)     # index 1

        layout.addWidget(self._pages_view_stack, 1)
        return workspace

    def _build_pages_option_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(292)
        panel.setStyleSheet("background:#FFFFFF;border-left:1px solid #E5EAF0;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(12)

        title = QLabel(ko("\\ud398\\uc774\\uc9c0 \\ud3b8\\uc9d1 \\uc635\\uc158"))
        title.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        title.setStyleSheet("color:#0F172A;background:transparent;")
        layout.addWidget(title)

        summary_card = self._card(ko("\\uc120\\ud0dd \\uc694\\uc57d"))
        s_layout = summary_card.layout()
        self.lbl_pages_filename = QLabel(ko("(\\ud30c\\uc77c \\uc5c6\\uc74c)"))
        self.lbl_pages_total    = QLabel(ko("\\uc6d0\\ubcf8 \\ud398\\uc774\\uc9c0: 0"))
        self.lbl_pages_current  = QLabel(ko("\\ud604\\uc7ac \\ud398\\uc774\\uc9c0: 0"))
        self.lbl_pages_selected = QLabel(ko("\\uc120\\ud0dd \\ud398\\uc774\\uc9c0: 0"))
        for lbl in (self.lbl_pages_filename, self.lbl_pages_total,
                    self.lbl_pages_current, self.lbl_pages_selected):
            lbl.setStyleSheet("color:#334155;background:transparent;padding:3px;font-size:8pt;")
            lbl.setWordWrap(True)
            s_layout.addWidget(lbl)
        layout.addWidget(summary_card)

        tip_card = self._card(ko("\\uc870\\uc791 \\uc548\\ub0b4"))
        t_layout = tip_card.layout()
        tip_lbl = QLabel(
            ko("\\ud398\\uc774\\uc9c0\\ub97c \\uc120\\ud0dd\\ud55c \\ud6c4 \\ub3c4\\uad6c\\ubaa8\\uc74c\\uc5d0\\uc11c")
            + "\n"
            + ko("\\uc0ad\\uc81c / 90\\u00b0 \\ud68c\\uc804 / \\uc21c\\uc11c \\ubcc0\\uacbd\\uc744 \\ud560 \\uc218 \\uc788\\uc2b5\\ub2c8\\ub2e4.")
        )
        tip_lbl.setWordWrap(True)
        tip_lbl.setStyleSheet("color:#64748B;background:transparent;font-size:8pt;")
        t_layout.addWidget(tip_lbl)
        layout.addWidget(tip_card)

        note_card = self._card(ko("\\uc548\\ub0b4"))
        n_layout = note_card.layout()
        note_lbl = QLabel(
            ko("\\uc6d0\\ubcf8 PDF\\ub294 \\ub36e\\uc5b4\\uc4f0\\uc9c0 \\uc54a\\uc2b5\\ub2c8\\ub2e4.")
            + "\n"
            + ko("\\uacb0\\uacfc\\ubb3c\\uc740 \\uc120\\ud0dd \\ud3f4\\ub354\\uc5d0 _edited \\ud30c\\uc77c\\ub85c \\uc800\\uc7a5\\ub429\\ub2c8\\ub2e4.")
        )
        note_lbl.setWordWrap(True)
        note_lbl.setStyleSheet("color:#64748B;background:transparent;font-size:8pt;")
        n_layout.addWidget(note_lbl)
        layout.addWidget(note_card)

        layout.addStretch()
        return panel

    def _build_convert_workspace(self) -> QWidget:
        workspace = QWidget()
        workspace.setStyleSheet("background:#F6F8FB;")
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(22, 16, 18, 14)
        layout.setSpacing(12)

        toolbar = QHBoxLayout()
        add_btn = QPushButton("+  " + ko("\\ud30c\\uc77c \\ucd94\\uac00"))
        add_btn.setFixedHeight(34)
        add_btn.setStyleSheet(self._button_style("#F0FDF4", "#15803D", "#DCFCE7"))
        add_btn.clicked.connect(self._add_convert_files)
        toolbar.addWidget(add_btn)

        del_btn = QPushButton(ko("\\uc120\\ud0dd \\uc0ad\\uc81c"))
        del_btn.setFixedHeight(34)
        del_btn.setStyleSheet(self._button_style("#FFFFFF", "#475569", "#F1F5F9"))
        del_btn.clicked.connect(lambda: self.convert_table.delete_selected_rows())
        toolbar.addWidget(del_btn)

        clear_btn = QPushButton(ko("\\uc804\\uccb4 \\uc0ad\\uc81c"))
        clear_btn.setFixedHeight(34)
        clear_btn.setStyleSheet(self._button_style("#FFFFFF", "#DC2626", "#FEF2F2"))
        clear_btn.clicked.connect(lambda: self.convert_table.clear())
        toolbar.addWidget(clear_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        dropzone = QFrame()
        dropzone.setFixedHeight(92)
        dropzone.setStyleSheet(
            "QFrame{background:#FFFFFF;border:2px dashed #CBD5E1;border-radius:12px;}"
        )
        drop_layout = QHBoxLayout(dropzone)
        drop_layout.setContentsMargins(24, 14, 24, 14)
        drop_layout.setSpacing(14)

        file_icon = QLabel(ko("\\ubcc0\\ud658"))
        file_icon.setFixedSize(48, 48)
        file_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        file_icon.setStyleSheet(
            "background:#EFF6FF;color:#2563EB;border:1px solid #BFDBFE;"
            "border-radius:12px;font-weight:bold;font-size:8pt;"
        )
        drop_layout.addWidget(file_icon)

        drop_text = QWidget()
        dt_layout = QVBoxLayout(drop_text)
        dt_layout.setContentsMargins(0, 0, 0, 0)
        dt_layout.setSpacing(2)
        main_hint = QLabel(
            ko("\\ud30c\\uc77c\\uc744 \\ub4dc\\ub798\\uadf8\\ud558\\uac70\\ub098 \\ucd94\\uac00\\ud558\\uc138\\uc694")
        )
        main_hint.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        main_hint.setStyleSheet("color:#334155;background:transparent;")
        dt_layout.addWidget(main_hint)
        sub_hint = QLabel(
            ko("HWP, DOCX, PDF, IMG, HTML \\ud30c\\uc77c\\uc744 \\uac1c\\ubcc4 PDF\\ub85c \\ubcc0\\ud658\\ud569\\ub2c8\\ub2e4.")
        )
        sub_hint.setFont(QFont("Malgun Gothic", 8))
        sub_hint.setStyleSheet("color:#94A3B8;background:transparent;")
        dt_layout.addWidget(sub_hint)
        drop_layout.addWidget(drop_text)
        drop_layout.addStretch()
        layout.addWidget(dropzone)

        self.convert_table = ConvertFileTable(on_changed=self._update_selection_summary)
        self.convert_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.convert_table, 1)

        return workspace

    def _build_convert_option_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(292)
        panel.setStyleSheet("background:#FFFFFF;border-left:1px solid #E5EAF0;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(12)

        title = QLabel(ko("\\ub2e8\\ub3c5 \\ubcc0\\ud658 \\uc635\\uc158"))
        title.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        title.setStyleSheet("color:#0F172A;background:transparent;")
        layout.addWidget(title)

        summary_card = self._card(ko("\\ud30c\\uc77c \\uc694\\uc57d"))
        s_layout = summary_card.layout()
        self.lbl_total_cv  = QLabel(ko("\\uc804\\uccb4 \\ud30c\\uc77c: 0"))
        self.lbl_target_cv = QLabel(ko("\\uc791\\uc5c5 \\ub300\\uc0c1: 0"))
        for lbl in (self.lbl_total_cv, self.lbl_target_cv):
            lbl.setStyleSheet(
                "color:#334155;background:transparent;padding:3px;font-size:8pt;")
            s_layout.addWidget(lbl)
        layout.addWidget(summary_card)

        note_card = self._card(ko("\\uc548\\ub0b4"))
        n_layout = note_card.layout()
        note_lbl = QLabel(
            ko("\\uc6d0\\ubcf8 \\ud30c\\uc77c\\uc740 \\ub36e\\uc5b4\\uc4f0\\uc9c0 \\uc54a\\uc2b5\\ub2c8\\ub2e4.")
            + "\n"
            + ko("\\uac01 \\ud30c\\uc77c\\uc740 \\uc120\\ud0dd \\ud3f4\\ub354\\uc5d0")
            + "\n"
            + ko("\\uac1c\\ubcc4 PDF\\ub85c \\uc800\\uc7a5\\ub429\\ub2c8\\ub2e4.")
        )
        note_lbl.setWordWrap(True)
        note_lbl.setStyleSheet("color:#64748B;background:transparent;font-size:8pt;")
        n_layout.addWidget(note_lbl)
        layout.addWidget(note_card)

        layout.addStretch()
        return panel

    def _build_security_workspace(self) -> QWidget:
        workspace = QWidget()
        workspace.setStyleSheet("background:#F6F8FB;")
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(22, 16, 18, 14)
        layout.setSpacing(12)

        toolbar = QHBoxLayout()
        add_btn = QPushButton("+  " + ko("\\ud30c\\uc77c \\ucd94\\uac00"))
        add_btn.setFixedHeight(34)
        add_btn.setStyleSheet(self._button_style("#F0FDF4", "#15803D", "#DCFCE7"))
        add_btn.clicked.connect(self._add_security_files)
        toolbar.addWidget(add_btn)

        del_btn = QPushButton(ko("\\uc120\\ud0dd \\uc0ad\\uc81c"))
        del_btn.setFixedHeight(34)
        del_btn.setStyleSheet(self._button_style("#FFFFFF", "#475569", "#F1F5F9"))
        del_btn.clicked.connect(lambda: self.security_table.delete_selected_rows())
        toolbar.addWidget(del_btn)

        clear_btn = QPushButton(ko("\\uc804\\uccb4 \\uc0ad\\uc81c"))
        clear_btn.setFixedHeight(34)
        clear_btn.setStyleSheet(self._button_style("#FFFFFF", "#DC2626", "#FEF2F2"))
        clear_btn.clicked.connect(lambda: self.security_table.clear())
        toolbar.addWidget(clear_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        dropzone = QFrame()
        dropzone.setFixedHeight(92)
        dropzone.setStyleSheet(
            "QFrame{background:#FFFFFF;border:2px dashed #CBD5E1;border-radius:12px;}"
        )
        drop_layout = QHBoxLayout(dropzone)
        drop_layout.setContentsMargins(24, 14, 24, 14)
        drop_layout.setSpacing(14)

        file_icon = QLabel(ko("\\ubcf4\\uc548"))
        file_icon.setFixedSize(48, 48)
        file_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        file_icon.setStyleSheet(
            "background:#FDF4FF;color:#9333EA;border:1px solid #E9D5FF;"
            "border-radius:12px;font-weight:bold;font-size:8pt;"
        )
        drop_layout.addWidget(file_icon)

        drop_text = QWidget()
        dt_layout = QVBoxLayout(drop_text)
        dt_layout.setContentsMargins(0, 0, 0, 0)
        dt_layout.setSpacing(2)
        main_hint = QLabel(
            ko("PDF \\ud30c\\uc77c\\uc744 \\ub4dc\\ub798\\uadf8\\ud558\\uac70\\ub098 \\ucd94\\uac00\\ud558\\uc138\\uc694")
        )
        main_hint.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        main_hint.setStyleSheet("color:#334155;background:transparent;")
        dt_layout.addWidget(main_hint)
        sub_hint = QLabel(
            ko("PDF\\ub9cc \\uc9c0\\uc6d0\\ud569\\ub2c8\\ub2e4. \\uc554\\ud638 \\uc124\\uc815 \\ub610\\ub294 \\ud574\\uc81c \\ud6c4 \\uc800\\uc7a5\\ud569\\ub2c8\\ub2e4.")
        )
        sub_hint.setFont(QFont("Malgun Gothic", 8))
        sub_hint.setStyleSheet("color:#94A3B8;background:transparent;")
        dt_layout.addWidget(sub_hint)
        drop_layout.addWidget(drop_text)
        drop_layout.addStretch()
        layout.addWidget(dropzone)

        self.security_table = CompressPdfTable(on_changed=self._update_selection_summary)
        self.security_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.security_table, 1)

        return workspace

    def _build_security_option_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(292)
        panel.setStyleSheet("background:#FFFFFF;border-left:1px solid #E5EAF0;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(12)

        title = QLabel(ko("\\ubcf4\\uc548 \\uc635\\uc158"))
        title.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        title.setStyleSheet("color:#0F172A;background:transparent;")
        layout.addWidget(title)

        # 작업 선택
        mode_card = self._card(ko("\\uc791\\uc5c5 \\uc120\\ud0dd"))
        m_layout = mode_card.layout()
        self.rb_sec_lock   = QRadioButton(ko("\\uc554\\ud638 \\uc124\\uc815  (\\uc7a0\\uae08)"))
        self.rb_sec_unlock = QRadioButton(ko("\\uc554\\ud638 \\ud574\\uc81c  (\\uc7a0\\uae08 \\ud574\\uc81c)"))
        self.rb_sec_lock.setChecked(True)
        for rb in (self.rb_sec_lock, self.rb_sec_unlock):
            rb.setStyleSheet("color:#334155;background:transparent;font-size:9pt;")
            m_layout.addWidget(rb)
            rb.toggled.connect(self._on_security_mode_changed)
        layout.addWidget(mode_card)

        # 암호 입력
        pw_card = self._card(ko("\\uc554\\ud638 \\uc785\\ub825"))
        pw_layout = pw_card.layout()

        lbl_pw = QLabel(ko("\\uc554\\ud638"))
        lbl_pw.setStyleSheet("color:#475569;background:transparent;font-size:8pt;")
        pw_layout.addWidget(lbl_pw)
        self.le_sec_password = QLineEdit()
        self.le_sec_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.le_sec_password.setPlaceholderText(ko("\\uc554\\ud638 \\uc785\\ub825"))
        self.le_sec_password.setFixedHeight(30)
        self.le_sec_password.setStyleSheet(
            "QLineEdit{border:1px solid #E2E8F0;border-radius:6px;"
            "padding:4px 8px;background:#FAFAFA;color:#0F172A;font-size:9pt;}"
            "QLineEdit:focus{border-color:#9333EA;background:#FFFFFF;}"
        )
        pw_layout.addWidget(self.le_sec_password)

        self.lbl_sec_confirm = QLabel(ko("\\uc554\\ud638 \\ud655\\uc778"))
        self.lbl_sec_confirm.setStyleSheet("color:#475569;background:transparent;font-size:8pt;")
        pw_layout.addWidget(self.lbl_sec_confirm)
        self.le_sec_confirm = QLineEdit()
        self.le_sec_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.le_sec_confirm.setPlaceholderText(ko("\\uc554\\ud638 \\ub2e4\\uc2dc \\uc785\\ub825"))
        self.le_sec_confirm.setFixedHeight(30)
        self.le_sec_confirm.setStyleSheet(
            "QLineEdit{border:1px solid #E2E8F0;border-radius:6px;"
            "padding:4px 8px;background:#FAFAFA;color:#0F172A;font-size:9pt;}"
            "QLineEdit:focus{border-color:#9333EA;background:#FFFFFF;}"
        )
        pw_layout.addWidget(self.le_sec_confirm)
        layout.addWidget(pw_card)

        # 파일 요약
        summary_card = self._card(ko("\\ud30c\\uc77c \\uc694\\uc57d"))
        s_layout = summary_card.layout()
        self.lbl_total_sec  = QLabel(ko("\\uc804\\uccb4 \\ud30c\\uc77c: 0"))
        self.lbl_target_sec = QLabel(ko("\\uc791\\uc5c5 \\ub300\\uc0c1: 0"))
        for lbl in (self.lbl_total_sec, self.lbl_target_sec):
            lbl.setStyleSheet(
                "color:#334155;background:transparent;padding:3px;font-size:8pt;")
            s_layout.addWidget(lbl)
        layout.addWidget(summary_card)

        # 안내
        note_card = self._card(ko("\\uc548\\ub0b4"))
        n_layout = note_card.layout()
        note_lbl = QLabel(
            ko("\\uc6d0\\ubcf8 \\ud30c\\uc77c\\uc740 \\ub36e\\uc5b4\\uc4f0\\uc9c0 \\uc54a\\uc2b5\\ub2c8\\ub2e4.")
            + "\n"
            + ko("\\uc554\\ud638 \\uc124\\uc815: _locked.pdf")
            + "\n"
            + ko("\\uc554\\ud638 \\ud574\\uc81c: _unlocked.pdf")
        )
        note_lbl.setWordWrap(True)
        note_lbl.setStyleSheet("color:#64748B;background:transparent;font-size:8pt;")
        n_layout.addWidget(note_lbl)
        layout.addWidget(note_card)

        layout.addStretch()
        return panel

    def _add_security_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            ko("PDF \\ud30c\\uc77c \\uc120\\ud0dd"),
            "",
            "PDF (*.pdf)",
        )
        for path in paths:
            self.security_table.add_file(path)
        self._update_selection_summary()

    def _on_security_mode_changed(self):
        lock_mode = self.rb_sec_lock.isChecked()
        self.lbl_sec_confirm.setVisible(lock_mode)
        self.le_sec_confirm.setVisible(lock_mode)

    def _run_security(self):
        paths = self.security_table.get_checked_paths()
        if not paths:
            QMessageBox.warning(
                self, ko("\\uc54c\\ub9bc"),
                ko("\\uc791\\uc5c5\\ud560 \\ud30c\\uc77c\\uc744 \\ud558\\ub098 \\uc774\\uc0c1 \\uccb4\\ud06c\\ud558\\uc138\\uc694."),
            )
            return

        pw = self.le_sec_password.text().strip()
        if not pw:
            QMessageBox.warning(
                self, ko("\\uc54c\\ub9bc"),
                ko("\\uc554\\ud638\\ub97c \\uc785\\ub825\\ud558\\uc138\\uc694."),
            )
            return

        mode = "lock" if self.rb_sec_lock.isChecked() else "unlock"
        if mode == "lock":
            if pw != self.le_sec_confirm.text():
                QMessageBox.warning(
                    self, ko("\\uc54c\\ub9bc"),
                    ko("\\uc554\\ud638\\uac00 \\uc77c\\uce58\\ud558\\uc9c0 \\uc54a\\uc2b5\\ub2c8\\ub2e4. \\ub2e4\\uc2dc \\ud655\\uc778\\ud558\\uc138\\uc694."),
                )
                return

        if not self._security_out_dir:
            d = QFileDialog.getExistingDirectory(
                self, ko("\\uc800\\uc7a5 \\ud3f4\\ub354 \\uc120\\ud0dd"), ""
            )
            if not d:
                return
            self._security_out_dir = d
            self.out_label.setText(d)

        self._set_running(True)
        self.progress.setValue(0)
        self.progress.setFormat(ko("\\uc2dc\\uc791 \\uc911..."))

        self._security_worker = SecurityWorker(paths, self._security_out_dir, mode, pw)
        self._security_worker.progress.connect(self._on_progress)
        self._security_worker.file_done.connect(self._on_security_file_done)
        self._security_worker.finished.connect(self._on_security_finished)
        self._security_worker.error.connect(self._on_security_error)
        self._security_worker.start()

    def _on_security_finished(self, out_dir: str):
        self.progress.setValue(100)
        self.progress.setFormat(ko("\\uc644\\ub8cc"))
        self._set_running(False)
        self.status.showMessage(ko("\\ubcf4\\uc548 \\ucc98\\ub9ac \\uc644\\ub8cc: ") + out_dir)
        self.le_sec_password.clear()
        self.le_sec_confirm.clear()
        reply = QMessageBox.question(
            self,
            ko("\\uc644\\ub8cc"),
            ko("\\ubcf4\\uc548 \\ucc98\\ub9ac\\uc774 \\uc644\\ub8cc\\ub418\\uc5c8\\uc2b5\\ub2c8\\ub2e4.\\n\\n")
            + out_dir
            + ko("\\n\\n\\ud3f4\\ub354\\ub97c \\uc5f4\\uc5b4\\ubcfc\\uae4c\\uc694?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            os.startfile(out_dir)
        self._security_out_dir = ""
        self.out_label.setText(ko("\\ubbf8\\uc9c0\\uc815"))
        self.progress.setValue(0)
        self.progress.setFormat(ko("\\ub300\\uae30 \\uc911"))

    def _on_security_error(self, filename: str, msg: str):
        self.status.showMessage(ko("\\uc624\\ub958: ") + f"{filename} - {msg}")
        QMessageBox.warning(
            self,
            ko("\\ubcf4\\uc548 \\uc624\\ub958"),
            ko("\\ud30c\\uc77c: ") + f"{filename}\n\n{msg}",
        )
        if self._security_worker is None or not self._security_worker.isRunning():
            self._set_running(False)
            self.progress.setFormat(ko("\\ub300\\uae30 \\uc911"))

    def _on_security_file_done(self, src_path: str, status_text: str):
        if hasattr(self, "security_table"):
            self.security_table.set_status(src_path, status_text)

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setFixedHeight(78)
        footer.setStyleSheet("background:#FFFFFF;border-top:1px solid #E5EAF0;")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(22, 12, 22, 12)
        layout.setSpacing(14)

        status_dot = QLabel("✓")
        status_dot.setFixedSize(22, 22)
        status_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_dot.setStyleSheet("background:#DCFCE7;color:#16A34A;border-radius:11px;font-weight:bold;")
        layout.addWidget(status_dot)

        state = QLabel(ko("\\uc900\\ube44"))
        state.setStyleSheet("color:#334155;background:transparent;font-weight:bold;")
        layout.addWidget(state)

        path_box = QWidget()
        path_layout = QVBoxLayout(path_box)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(2)
        path_title = QLabel(ko("\\uc800\\uc7a5 \\uc704\\uce58"))
        path_title.setStyleSheet("color:#94A3B8;background:transparent;font-size:8pt;")
        path_layout.addWidget(path_title)
        self.out_label = QLabel(ko("\\ubbf8\\uc9c0\\uc815"))
        self.out_label.setStyleSheet("color:#334155;background:transparent;")
        path_layout.addWidget(self.out_label)
        layout.addWidget(path_box, 1)

        out_btn = QPushButton(ko("\\ucc3e\\uc544\\ubcf4\\uae30"))
        out_btn.setFixedHeight(34)
        out_btn.setStyleSheet(self._button_style("#FFFFFF", "#475569", "#F1F5F9"))
        out_btn.clicked.connect(self._select_output)
        layout.addWidget(out_btn)

        self.progress = QProgressBar()
        self.progress.setFixedHeight(20)
        self.progress.setValue(0)
        self.progress.setFormat(ko("\\ub300\\uae30 \\uc911"))
        self.progress.setStyleSheet(
            "QProgressBar{background:#F8FAFC;border:1px solid #DDE5EF;border-radius:8px;"
            "text-align:center;color:#64748B;font-size:8pt;}"
            "QProgressBar::chunk{background:#22C55E;border-radius:7px;}"
        )
        layout.addWidget(self.progress, 1)

        self.run_btn = QPushButton("▶  " + ko("\\uc791\\uc5c5 \\uc2e4\\ud589"))
        self.run_btn.setFixedHeight(46)
        self.run_btn.setMinimumWidth(168)
        self.run_btn.setFont(QFont("Malgun Gothic", 10, QFont.Weight.Bold))
        self.run_btn.setStyleSheet(self._button_style("#22C55E", "#FFFFFF", "#16A34A"))
        self.run_btn.clicked.connect(self._run)
        layout.addWidget(self.run_btn)
        return footer

    def _card(self, title: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet("QFrame{background:#FFFFFF;border:1px solid #E5EAF0;border-radius:12px;}")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(6)
        label = QLabel(title)
        label.setStyleSheet("color:#0F172A;background:transparent;font-weight:bold;")
        layout.addWidget(label)
        return card

    def _on_menu_clicked(self, key: str, enabled: bool):
        if not enabled:
            label = next((item_label for item_key, item_label, _enabled, _icon in MENU_ITEMS if item_key == key), "")
            QMessageBox.information(
                self,
                ko("\\uc900\\ube44 \\uc911"),
                f"{label} " + ko("\\uc804\\uc6a9 \\ud654\\uba74\\uc740 \\ub2e4\\uc74c \\ub2e8\\uacc4\\uc5d0\\uc11c \\uad6c\\ud604\\ud569\\ub2c8\\ub2e4."),
            )
            return
        self._set_mode(key)

    def _set_mode(self, key: str):
        self._mode = key
        self._set_active_menu(key)
        idx_map = {"merge": 0, "compress": 1, "split": 2, "pages": 3, "convert": 4, "security": 5}
        idx = idx_map.get(key, 0)
        self._workspace_stack.setCurrentIndex(idx)
        self._option_stack.setCurrentIndex(idx)
        if key == "compress":
            self.run_btn.setText("▶  " + ko("\\uc555\\ucd95 \\uc2e4\\ud589"))
            self.out_label.setText(self._compress_out_dir or ko("\\ubbf8\\uc9c0\\uc815"))
        elif key == "split":
            self.run_btn.setText("▶  " + ko("\\uc120\\ud0dd \\ud398\\uc774\\uc9c0 \\ubd84\\ud560 \\uc2e4\\ud589"))
            self.out_label.setText(self._split_out_dir or ko("\\ubbf8\\uc9c0\\uc815"))
        elif key == "pages":
            self.run_btn.setText("▶  " + ko("\\ud3b8\\uc9d1 \\uacb0\\uacfc \\uc800\\uc7a5"))
            self.out_label.setText(self._pages_out_dir or ko("\\ubbf8\\uc9c0\\uc815"))
        elif key == "convert":
            self.run_btn.setText("▶  " + ko("\\ubcc0\\ud658 \\uc2e4\\ud589"))
            self.out_label.setText(self._convert_out_dir or ko("\\ubbf8\\uc9c0\\uc815"))
        elif key == "security":
            self.run_btn.setText("▶  " + ko("\\ubcf4\\uc548 \\uc2e4\\ud589"))
            self.out_label.setText(self._security_out_dir or ko("\\ubbf8\\uc9c0\\uc815"))
        else:
            self.run_btn.setText("▶  " + ko("\\uc791\\uc5c5 \\uc2e4\\ud589"))
            self.out_label.setText(self._out_path or ko("\\ubbf8\\uc9c0\\uc815"))
        self._update_selection_summary()

    def _set_active_menu(self, key: str):
        for menu_key, button in self._sidebar_buttons.items():
            button.setStyleSheet(self._side_btn_style(active=(menu_key == key)))

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            ko("\\ud30c\\uc77c \\uc120\\ud0dd"),
            "",
            ko("\\uc9c0\\uc6d0 \\ud30c\\uc77c")
            + " (*.hwp *.hwpx *.docx *.doc *.pdf *.jpg *.jpeg *.png *.bmp *.tiff *.tif *.html *.htm)",
        )
        for path in paths:
            self.file_table.add_file(path)
        self._update_selection_summary()

    def _add_compress_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            ko("PDF \\ud30c\\uc77c \\uc120\\ud0dd"),
            "",
            "PDF (*.pdf)",
        )
        for path in paths:
            self.compress_table.add_file(path)
        self._update_selection_summary()

    def _add_split_files(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            ko("PDF \\ud30c\\uc77c \\uc120\\ud0dd"),
            "",
            "PDF (*.pdf)",
        )
        if path:
            self._load_split_pdf(path)

    def _select_output(self):
        if self._mode in ("compress", "split", "pages", "convert", "security"):
            d = QFileDialog.getExistingDirectory(
                self, ko("\\uc800\\uc7a5 \\ud3f4\\ub354 \\uc120\\ud0dd"), ""
            )
            if d:
                if self._mode == "compress":
                    self._compress_out_dir = d
                elif self._mode == "split":
                    self._split_out_dir = d
                elif self._mode == "pages":
                    self._pages_out_dir = d
                elif self._mode == "security":
                    self._security_out_dir = d
                else:
                    self._convert_out_dir = d
                self.out_label.setText(d)
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, ko("\\uc800\\uc7a5 \\uc704\\uce58 \\uc120\\ud0dd"), "merged_output.pdf", "PDF (*.pdf)"
            )
            if path:
                self._out_path = path
                self.out_label.setText(path)

    def _delete_selected(self):
        self.file_table.delete_selected_rows()

    def file_table_clear_safe(self):
        self.file_table.clear()

    def _update_selection_summary(self):
        if self._mode == "compress":
            if hasattr(self, "lbl_total_c") and hasattr(self, "compress_table"):
                self.lbl_total_c.setText(ko("\\uc804\\uccb4 \\ud30c\\uc77c: ") + str(self.compress_table.total_count()))
                self.lbl_target_c.setText(ko("\\uc791\\uc5c5 \\ub300\\uc0c1: ") + str(self.compress_table.checked_count()))
        elif self._mode == "split":
            if hasattr(self, "lbl_split_filename"):
                if self._split_pdf_path:
                    self.lbl_split_filename.setText(Path(self._split_pdf_path).name)
                    self.lbl_split_total.setText(
                        ko("\\uc804\\uccb4 \\ud398\\uc774\\uc9c0: ") + str(self._split_page_count))
                    sel = sum(1 for w in self._split_page_widgets if w.is_selected())
                    self.lbl_split_selected.setText(
                        ko("\\uc120\\ud0dd \\ud398\\uc774\\uc9c0: ") + str(sel))
                else:
                    self.lbl_split_filename.setText(ko("(\\ud30c\\uc77c \\uc5c6\\uc74c)"))
                    self.lbl_split_total.setText(ko("\\uc804\\uccb4 \\ud398\\uc774\\uc9c0: 0"))
                    self.lbl_split_selected.setText(ko("\\uc120\\ud0dd \\ud398\\uc774\\uc9c0: 0"))
        elif self._mode == "pages":
            if hasattr(self, "lbl_pages_filename"):
                if self._pages_pdf_path:
                    self.lbl_pages_filename.setText(Path(self._pages_pdf_path).name)
                    self.lbl_pages_total.setText(
                        ko("\\uc6d0\\ubcf8 \\ud398\\uc774\\uc9c0: ") + str(self._pages_page_count))
                    self.lbl_pages_current.setText(
                        ko("\\ud604\\uc7ac \\ud398\\uc774\\uc9c0: ") + str(len(self._pages_page_widgets)))
                    sel = sum(1 for w in self._pages_page_widgets if w.is_selected())
                    self.lbl_pages_selected.setText(
                        ko("\\uc120\\ud0dd \\ud398\\uc774\\uc9c0: ") + str(sel))
                else:
                    self.lbl_pages_filename.setText(ko("(\\ud30c\\uc77c \\uc5c6\\uc74c)"))
                    self.lbl_pages_total.setText(ko("\\uc6d0\\ubcf8 \\ud398\\uc774\\uc9c0: 0"))
                    self.lbl_pages_current.setText(ko("\\ud604\\uc7ac \\ud398\\uc774\\uc9c0: 0"))
                    self.lbl_pages_selected.setText(ko("\\uc120\\ud0dd \\ud398\\uc774\\uc9c0: 0"))
        elif self._mode == "convert":
            if hasattr(self, "lbl_total_cv") and hasattr(self, "convert_table"):
                self.lbl_total_cv.setText(
                    ko("\\uc804\\uccb4 \\ud30c\\uc77c: ") + str(self.convert_table.total_count()))
                self.lbl_target_cv.setText(
                    ko("\\uc791\\uc5c5 \\ub300\\uc0c1: ") + str(self.convert_table.checked_count()))
        elif self._mode == "security":
            if hasattr(self, "lbl_total_sec") and hasattr(self, "security_table"):
                self.lbl_total_sec.setText(
                    ko("\\uc804\\uccb4 \\ud30c\\uc77c: ") + str(self.security_table.total_count()))
                self.lbl_target_sec.setText(
                    ko("\\uc791\\uc5c5 \\ub300\\uc0c1: ") + str(self.security_table.checked_count()))
        else:
            if not hasattr(self, "lbl_total"):
                return
            self.lbl_total.setText(ko("\\uc804\\uccb4 \\ud30c\\uc77c: ") + str(self.file_table.total_count()))
            self.lbl_target.setText(ko("\\uc791\\uc5c5 \\ub300\\uc0c1: ") + str(self.file_table.checked_count()))

    def _run(self):
        if self._mode == "compress":
            self._run_compress()
        elif self._mode == "split":
            self._run_split()
        elif self._mode == "pages":
            self._run_pages()
        elif self._mode == "convert":
            self._run_convert()
        elif self._mode == "security":
            self._run_security()
        else:
            self._run_merge()

    def _run_merge(self):
        items = self.file_table.get_file_items(checked_only=True)
        if not items:
            QMessageBox.warning(self, ko("\\uc54c\\ub9bc"), ko("\\uc791\\uc5c5\\ud560 \\ud30c\\uc77c\\uc744 \\ud558\\ub098 \\uc774\\uc0c1 \\uccb4\\ud06c\\ud558\\uc138\\uc694."))
            return
        if not self._out_path:
            path, _ = QFileDialog.getSaveFileName(
                self, ko("\\uc800\\uc7a5 \\uc704\\uce58 \\uc120\\ud0dd"), "merged_output.pdf", "PDF (*.pdf)"
            )
            if not path:
                return
            self._out_path = path
            self.out_label.setText(path)

        self._set_running(True)
        self.progress.setValue(0)
        self.progress.setFormat(ko("\\uc2dc\\uc791 \\uc911..."))

        self._worker = ConvertWorker(
            items,
            self._out_path,
            compress_mode=self._current_compress_mode(),
            quality_level=self.combo_quality.currentData() or "high",
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _run_compress(self):
        paths = self.compress_table.get_checked_paths()
        if not paths:
            QMessageBox.warning(self, ko("\\uc54c\\ub9bc"), ko("\\uc555\\ucd95\\ud560 PDF \\ud30c\\uc77c\\uc744 \\ud558\\ub098 \\uc774\\uc0c1 \\uccb4\\ud06c\\ud558\\uc138\\uc694."))
            return
        if not self._compress_out_dir:
            d = QFileDialog.getExistingDirectory(
                self, ko("\\uc800\\uc7a5 \\ud3f4\\ub354 \\uc120\\ud0dd"), ""
            )
            if not d:
                return
            self._compress_out_dir = d
            self.out_label.setText(d)

        mode = "strong" if self.rb_compress_strong_c.isChecked() else "basic"
        quality = self.combo_quality_c.currentData() or "high"

        self._set_running(True)
        self.progress.setValue(0)
        self.progress.setFormat(ko("\\uc2dc\\uc791 \\uc911..."))

        self._compress_worker = CompressWorker(
            paths, self._compress_out_dir, mode, quality
        )
        self._compress_worker.progress.connect(self._on_progress)
        self._compress_worker.finished.connect(self._on_compress_finished)
        self._compress_worker.error.connect(self._on_compress_error)
        self._compress_worker.start()

    def _current_compress_mode(self) -> str:
        if self.rb_compress_none.isChecked():
            return "none"
        if self.rb_compress_strong.isChecked():
            return "strong"
        return "basic"

    def _sync_quality_enabled(self):
        self.combo_quality.setEnabled(self.rb_compress_strong.isChecked())

    def _sync_quality_enabled_c(self):
        self.combo_quality_c.setEnabled(self.rb_compress_strong_c.isChecked())

    def _load_split_pdf(self, path: str):
        """PDF를 로드하고 썸네일 그리드를 생성한다."""
        import fitz as _fitz
        self._clear_split_view()
        self._split_pdf_path = path

        doc = _fitz.open(path)
        try:
            self._split_page_count = doc.page_count
            mat = _fitz.Matrix(_THUMB_SCALE, _THUMB_SCALE)

            row = col = 0
            for i in range(doc.page_count):
                page = doc[i]
                pix = page.get_pixmap(matrix=mat, alpha=False)
                samples = bytes(pix.samples)
                img = QImage(samples, pix.width, pix.height, pix.stride,
                             QImage.Format.Format_RGB888)
                pixmap = QPixmap.fromImage(img)

                thumb = ThumbnailPageWidget(i, pixmap)
                thumb.selection_changed.connect(self._update_selection_summary)
                self._split_page_widgets.append(thumb)
                self._split_grid.addWidget(thumb, row, col)

                col += 1
                if col >= _THUMB_COLS:
                    col = 0
                    row += 1
        finally:
            doc.close()

        self._split_view_stack.setCurrentIndex(1)
        self.status.showMessage(
            Path(path).name + f" — {self._split_page_count}" + ko("\\ud398\\uc774\\uc9c0")
        )
        self._update_selection_summary()

    def _clear_split_view(self):
        """썸네일 그리드 초기화 및 드롭존으로 복귀."""
        self._split_pdf_path = ""
        self._split_page_count = 0
        for w in self._split_page_widgets:
            self._split_grid.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._split_page_widgets.clear()
        self._split_out_dir = ""
        self.out_label.setText(ko("\\ubbf8\\uc9c0\\uc815"))
        if hasattr(self, "_split_view_stack"):
            self._split_view_stack.setCurrentIndex(0)
        self._update_selection_summary()

    def _get_selected_split_pages(self) -> list[int]:
        return [w.page_index() for w in self._split_page_widgets if w.is_selected()]

    def _select_all_split_pages(self):
        for w in self._split_page_widgets:
            w.set_selected(True)
        self._update_selection_summary()

    def _clear_split_pages(self):
        for w in self._split_page_widgets:
            w.set_selected(False)
        self._update_selection_summary()

    def _select_odd_split_pages(self):
        for w in self._split_page_widgets:
            w.set_selected((w.page_index() + 1) % 2 == 1)
        self._update_selection_summary()

    def _select_even_split_pages(self):
        for w in self._split_page_widgets:
            w.set_selected((w.page_index() + 1) % 2 == 0)
        self._update_selection_summary()

    # ── 페이지 편집 전용 메서드 ───────────────────────────────────────────────

    def _add_pages_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, ko("PDF \\ud30c\\uc77c \\uc120\\ud0dd"), "", "PDF (*.pdf)"
        )
        if path:
            self._load_pages_pdf(path)

    def _load_pages_pdf(self, path: str):
        import fitz as _fitz
        self._clear_pages_view()
        self._pages_pdf_path = path

        doc = _fitz.open(path)
        try:
            self._pages_page_count = doc.page_count
            mat = _fitz.Matrix(_THUMB_SCALE, _THUMB_SCALE)
            row = col = 0
            for i in range(doc.page_count):
                page = doc[i]
                pix = page.get_pixmap(matrix=mat, alpha=False)
                samples = bytes(pix.samples)
                img = QImage(samples, pix.width, pix.height, pix.stride,
                             QImage.Format.Format_RGB888)
                pixmap = QPixmap.fromImage(img)

                thumb = EditPageWidget(i, pixmap)
                thumb.selection_changed.connect(self._update_selection_summary)
                self._pages_page_widgets.append(thumb)
                self._pages_grid.addWidget(thumb, row, col)

                col += 1
                if col >= _THUMB_COLS:
                    col = 0
                    row += 1
        finally:
            doc.close()

        self._pages_view_stack.setCurrentIndex(1)
        self.status.showMessage(
            Path(path).name + f" — {self._pages_page_count}" + ko("\\ud398\\uc774\\uc9c0")
        )
        self._update_selection_summary()

    def _clear_pages_view(self):
        self._pages_pdf_path = ""
        self._pages_page_count = 0
        for w in self._pages_page_widgets:
            self._pages_grid.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._pages_page_widgets.clear()
        self._pages_out_dir = ""
        if hasattr(self, "_pages_view_stack"):
            self._pages_view_stack.setCurrentIndex(0)
        if self._mode == "pages":
            self.out_label.setText(ko("\\ubbf8\\uc9c0\\uc815"))
        self._update_selection_summary()

    def _select_all_pages(self):
        for w in self._pages_page_widgets:
            w.set_selected(True)
        self._update_selection_summary()

    def _clear_pages_selection(self):
        for w in self._pages_page_widgets:
            w.set_selected(False)
        self._update_selection_summary()

    def _delete_selected_pages(self):
        selected  = [w for w in self._pages_page_widgets if w.is_selected()]
        if not selected:
            QMessageBox.warning(
                self, ko("\\uc54c\\ub9bc"),
                ko("\\uc0ad\\uc81c\\ud560 \\ud398\\uc774\\uc9c0\\ub97c \\uc120\\ud0dd\\ud558\\uc138\\uc694."),
            )
            return
        remaining = [w for w in self._pages_page_widgets if not w.is_selected()]
        if not remaining:
            QMessageBox.warning(
                self, ko("\\uc54c\\ub9bc"),
                ko("\\ubaa8\\ub4e0 \\ud398\\uc774\\uc9c0\\ub97c \\uc0ad\\uc81c\\ud560 \\uc218 \\uc5c6\\uc2b5\\ub2c8\\ub2e4.\\n\\uc5ec\\ub4e0 \\ud398\\uc774\\uc9c0\\uac00 1\\uc7a5 \\uc774\\uc0c1 \\ud544\\uc694\\ud569\\ub2c8\\ub2e4."),
            )
            return
        for w in selected:
            self._pages_grid.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self._pages_page_widgets = remaining
        self._rebuild_pages_grid()
        self._update_selection_summary()

    def _rotate_selected_pages(self):
        selected = [w for w in self._pages_page_widgets if w.is_selected()]
        if not selected:
            QMessageBox.warning(
                self, ko("\\uc54c\\ub9bc"),
                ko("\\ud68c\\uc804\\ud560 \\ud398\\uc774\\uc9c0\\ub97c \\uc120\\ud0dd\\ud558\\uc138\\uc694."),
            )
            return
        for w in selected:
            w.rotate_90()

    def _move_pages(self, direction: int):
        """선택 페이지를 왼쪽(-1) 또는 오른쪽(+1)으로 한 칸 이동."""
        widgets = self._pages_page_widgets
        n = len(widgets)
        if n == 0:
            return
        if direction == -1:
            for i in range(1, n):
                if widgets[i].is_selected() and not widgets[i - 1].is_selected():
                    widgets[i - 1], widgets[i] = widgets[i], widgets[i - 1]
        else:
            for i in range(n - 2, -1, -1):
                if widgets[i].is_selected() and not widgets[i + 1].is_selected():
                    widgets[i], widgets[i + 1] = widgets[i + 1], widgets[i]
        self._rebuild_pages_grid()

    def _rebuild_pages_grid(self):
        for w in self._pages_page_widgets:
            self._pages_grid.removeWidget(w)
        for i, w in enumerate(self._pages_page_widgets):
            row, col = divmod(i, _THUMB_COLS)
            self._pages_grid.addWidget(w, row, col)

    def _get_pages_page_ops(self) -> list[dict]:
        return [{"idx": w.page_index(), "rotation": w.rotation()}
                for w in self._pages_page_widgets]

    def _run_pages(self):
        if not self._pages_pdf_path:
            QMessageBox.warning(
                self, ko("\\uc54c\\ub9bc"),
                ko("\\ud3b8\\uc9d1\\ud560 PDF\\ub97c \\uba3c\\uc800 \\ucd94\\uac00\\ud558\\uc138\\uc694."),
            )
            return
        page_ops = self._get_pages_page_ops()
        if not page_ops:
            QMessageBox.warning(
                self, ko("\\uc54c\\ub9bc"),
                ko("\\uc800\\uc7a5\\ud560 \\ud398\\uc774\\uc9c0\\uac00 \\uc5c6\\uc2b5\\ub2c8\\ub2e4."),
            )
            return
        if not self._pages_out_dir:
            d = QFileDialog.getExistingDirectory(
                self, ko("\\uc800\\uc7a5 \\ud3f4\\ub354 \\uc120\\ud0dd"), ""
            )
            if not d:
                return
            self._pages_out_dir = d
            self.out_label.setText(d)

        self._set_running(True)
        self.progress.setValue(0)
        self.progress.setFormat(ko("\\uc2dc\\uc791 \\uc911..."))

        self._pages_worker = PageEditWorker(
            self._pages_pdf_path, self._pages_out_dir, page_ops
        )
        self._pages_worker.progress.connect(self._on_progress)
        self._pages_worker.finished.connect(self._on_pages_finished)
        self._pages_worker.error.connect(self._on_pages_error)
        self._pages_worker.start()

    def _on_pages_finished(self, out_path: str):
        self.progress.setValue(100)
        self.progress.setFormat(ko("\\uc644\\ub8cc"))
        self._set_running(False)
        self.status.showMessage(ko("\\ud3b8\\uc9d1 \\uc644\\ub8cc: ") + out_path)
        reply = QMessageBox.question(
            self,
            ko("\\uc644\\ub8cc"),
            ko("\\ud398\\uc774\\uc9c0 \\ud3b8\\uc9d1\\uc774 \\uc644\\ub8cc\\ub418\\uc5c8\\uc2b5\\ub2c8\\ub2e4.\\n\\n")
            + out_path
            + ko("\\n\\n\\ud30c\\uc77c\\uc744 \\uc5f4\\uc5b4\\ubcfc\\uae4c\\uc694?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            os.startfile(out_path)
        self._pages_out_dir = ""
        self.out_label.setText(ko("\\ubbf8\\uc9c0\\uc815"))
        self.progress.setValue(0)
        self.progress.setFormat(ko("\\ub300\\uae30 \\uc911"))

    def _on_pages_error(self, filename: str, msg: str):
        self.status.showMessage(ko("\\uc624\\ub958: ") + f"{filename} - {msg}")
        QMessageBox.warning(
            self,
            ko("\\ud3b8\\uc9d1 \\uc624\\ub958"),
            ko("\\ud30c\\uc77c: ") + f"{filename}\n\n{msg}",
        )
        if self._pages_worker is None or not self._pages_worker.isRunning():
            self._set_running(False)
            self.progress.setFormat(ko("\\ub300\\uae30 \\uc911"))

    def _on_progress(self, current: int, total: int, msg: str):
        pct = int(current / total * 100) if total else 0
        self.progress.setValue(pct)
        self.progress.setFormat(f"{msg}  ({pct}%)")
        self.status.showMessage(msg)

    def _on_finished(self, out_path: str):
        self.progress.setValue(100)
        self.progress.setFormat(ko("\\uc644\\ub8cc"))
        self._set_running(False)
        self.status.showMessage(ko("\\uc644\\ub8cc: ") + out_path)
        reply = QMessageBox.question(
            self,
            ko("\\uc644\\ub8cc"),
            ko("PDF \\uc0dd\\uc131\\uc774 \\uc644\\ub8cc\\ub418\\uc5c8\\uc2b5\\ub2c8\\ub2e4.\\n\\n")
            + out_path
            + ko("\\n\\n\\ud30c\\uc77c\\uc744 \\uc5f4\\uc5b4\\ubcfc\\uae4c\\uc694?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            os.startfile(out_path)
        self._out_path = ""
        self.out_label.setText(ko("\\ubbf8\\uc9c0\\uc815"))
        self.progress.setValue(0)
        self.progress.setFormat(ko("\\ub300\\uae30 \\uc911"))

    def _on_error(self, filename: str, msg: str):
        self.status.showMessage(ko("\\uc624\\ub958: ") + f"{filename} - {msg}")
        QMessageBox.warning(
            self,
            ko("\\ubcc0\\ud658 \\uc624\\ub958"),
            ko("\\ud30c\\uc77c: ") + f"{filename}\n\n{msg}",
        )
        if self._worker is None or not self._worker.isRunning():
            self._set_running(False)
            self.progress.setFormat(ko("\\ub300\\uae30 \\uc911"))

    def _on_compress_finished(self, out_dir: str):
        self.progress.setValue(100)
        self.progress.setFormat(ko("\\uc644\\ub8cc"))
        self._set_running(False)
        self.status.showMessage(ko("\\uc555\\ucd95 \\uc644\\ub8cc: ") + out_dir)
        reply = QMessageBox.question(
            self,
            ko("\\uc644\\ub8cc"),
            ko("\\uc555\\ucd95\\uc774 \\uc644\\ub8cc\\ub418\\uc5c8\\uc2b5\\ub2c8\\ub2e4.\\n\\n")
            + out_dir
            + ko("\\n\\n\\ud3f4\\ub354\\ub97c \\uc5f4\\uc5b4\\ubcfc\\uae4c\\uc694?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            os.startfile(out_dir)
        self._compress_out_dir = ""
        self.out_label.setText(ko("\\ubbf8\\uc9c0\\uc815"))
        self.progress.setValue(0)
        self.progress.setFormat(ko("\\ub300\\uae30 \\uc911"))

    def _on_compress_error(self, filename: str, msg: str):
        self.status.showMessage(ko("\\uc624\\ub958: ") + f"{filename} - {msg}")
        QMessageBox.warning(
            self,
            ko("\\uc555\\ucd95 \\uc624\\ub958"),
            ko("\\ud30c\\uc77c: ") + f"{filename}\n\n{msg}",
        )
        if self._compress_worker is None or not self._compress_worker.isRunning():
            self._set_running(False)
            self.progress.setFormat(ko("\\ub300\\uae30 \\uc911"))

    def _run_split(self):
        if not self._split_pdf_path:
            QMessageBox.warning(self, ko("\\uc54c\\ub9bc"),
                                ko("\\ubd84\\ud560\\ud560 PDF\\ub97c \\uba3c\\uc800 \\ucd94\\uac00\\ud558\\uc138\\uc694."))
            return

        page_indices = self._get_selected_split_pages()
        if not page_indices:
            QMessageBox.warning(self, ko("\\uc54c\\ub9bc"),
                                ko("\\ubd84\\ud560\\ud560 \\ud398\\uc774\\uc9c0\\ub97c \\ud558\\ub098 \\uc774\\uc0c1 \\uc120\\ud0dd\\ud558\\uc138\\uc694."))
            return

        save_mode = "each" if self.rb_split_each_s.isChecked() else "single"

        if not self._split_out_dir:
            d = QFileDialog.getExistingDirectory(
                self, ko("\\uc800\\uc7a5 \\ud3f4\\ub354 \\uc120\\ud0dd"), ""
            )
            if not d:
                return
            self._split_out_dir = d
            self.out_label.setText(d)

        self._set_running(True)
        self.progress.setValue(0)
        self.progress.setFormat(ko("\\uc2dc\\uc791 \\uc911..."))

        self._split_worker = SplitSelectedWorker(
            self._split_pdf_path, self._split_out_dir, page_indices, save_mode
        )
        self._split_worker.progress.connect(self._on_progress)
        self._split_worker.finished.connect(self._on_split_finished)
        self._split_worker.error.connect(self._on_split_error)
        self._split_worker.start()

    def _on_split_finished(self, out_dir: str):
        self.progress.setValue(100)
        self.progress.setFormat(ko("\\uc644\\ub8cc"))
        self._set_running(False)
        self.status.showMessage(ko("\\ubd84\\ud560 \\uc644\\ub8cc: ") + out_dir)
        reply = QMessageBox.question(
            self,
            ko("\\uc644\\ub8cc"),
            ko("\\ubd84\\ud560\\uc774 \\uc644\\ub8cc\\ub418\\uc5c8\\uc2b5\\ub2c8\\ub2e4.\\n\\n")
            + out_dir
            + ko("\\n\\n\\ud3f4\\ub354\\ub97c \\uc5f4\\uc5b4\\ubcfc\\uae4c\\uc694?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            os.startfile(out_dir)
        self._split_out_dir = ""
        self.out_label.setText(ko("\\ubbf8\\uc9c0\\uc815"))
        self.progress.setValue(0)
        self.progress.setFormat(ko("\\ub300\\uae30 \\uc911"))

    def _on_split_error(self, filename: str, msg: str):
        self.status.showMessage(ko("\\uc624\\ub958: ") + f"{filename} - {msg}")
        QMessageBox.warning(
            self,
            ko("\\ubd84\\ud560 \\uc624\\ub958"),
            ko("\\ud30c\\uc77c: ") + f"{filename}\n\n{msg}",
        )
        if self._split_worker is None or not self._split_worker.isRunning():
            self._set_running(False)
            self.progress.setFormat(ko("\\ub300\\uae30 \\uc911"))

    def _add_convert_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            ko("\\ud30c\\uc77c \\uc120\\ud0dd"),
            "",
            ko("\\uc9c0\\uc6d0 \\ud30c\\uc77c")
            + " (*.hwp *.hwpx *.docx *.doc *.pdf *.jpg *.jpeg"
              " *.png *.bmp *.tiff *.tif *.html *.htm)",
        )
        for path in paths:
            self.convert_table.add_file(path)
        self._update_selection_summary()

    def _run_convert(self):
        paths = self.convert_table.get_checked_paths()
        if not paths:
            QMessageBox.warning(
                self, ko("\\uc54c\\ub9bc"),
                ko("\\ubcc0\\ud658\\ud560 \\ud30c\\uc77c\\uc744 \\ud558\\ub098 \\uc774\\uc0c1 \\uccb4\\ud06c\\ud558\\uc138\\uc694."),
            )
            return
        if not self._convert_out_dir:
            d = QFileDialog.getExistingDirectory(
                self, ko("\\uc800\\uc7a5 \\ud3f4\\ub354 \\uc120\\ud0dd"), ""
            )
            if not d:
                return
            self._convert_out_dir = d
            self.out_label.setText(d)

        self._set_running(True)
        self.progress.setValue(0)
        self.progress.setFormat(ko("\\uc2dc\\uc791 \\uc911..."))

        self._convert_worker = StandaloneConvertWorker(paths, self._convert_out_dir)
        self._convert_worker.progress.connect(self._on_progress)
        self._convert_worker.file_done.connect(self._on_convert_file_done)
        self._convert_worker.finished.connect(self._on_convert_finished)
        self._convert_worker.error.connect(self._on_convert_error)
        self._convert_worker.start()

    def _on_convert_finished(self, out_dir: str):
        self.progress.setValue(100)
        self.progress.setFormat(ko("\\uc644\\ub8cc"))
        self._set_running(False)
        self.status.showMessage(ko("\\ubcc0\\ud658 \\uc644\\ub8cc: ") + out_dir)
        reply = QMessageBox.question(
            self,
            ko("\\uc644\\ub8cc"),
            ko("\\ubcc0\\ud658\\uc774 \\uc644\\ub8cc\\ub418\\uc5c8\\uc2b5\\ub2c8\\ub2e4.\\n\\n")
            + out_dir
            + ko("\\n\\n\\ud3f4\\ub354\\ub97c \\uc5f4\\uc5b4\\ubcfc\\uae4c\\uc694?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            os.startfile(out_dir)
        self._convert_out_dir = ""
        self.out_label.setText(ko("\\ubbf8\\uc9c0\\uc815"))
        self.progress.setValue(0)
        self.progress.setFormat(ko("\\ub300\\uae30 \\uc911"))

    def _on_convert_error(self, filename: str, msg: str):
        self.status.showMessage(ko("\\uc624\\ub958: ") + f"{filename} - {msg}")
        QMessageBox.warning(
            self,
            ko("\\ubcc0\\ud658 \\uc624\\ub958"),
            ko("\\ud30c\\uc77c: ") + f"{filename}\n\n{msg}",
        )
        if self._convert_worker is None or not self._convert_worker.isRunning():
            self._set_running(False)
            self.progress.setFormat(ko("\\ub300\\uae30 \\uc911"))

    def _on_convert_file_done(self, src_path: str, status_text: str):
        if hasattr(self, "convert_table"):
            self.convert_table.update_status(src_path, status_text)

    def _set_running(self, running: bool):
        self.run_btn.setEnabled(not running)
        if running:
            self.run_btn.setText(ko("\\ucc98\\ub9ac \\uc911..."))
        elif self._mode == "compress":
            self.run_btn.setText("▶  " + ko("\\uc555\\ucd95 \\uc2e4\\ud589"))
        elif self._mode == "split":
            self.run_btn.setText("▶  " + ko("\\uc120\\ud0dd \\ud398\\uc774\\uc9c0 \\ubd84\\ud560 \\uc2e4\\ud589"))
        elif self._mode == "pages":
            self.run_btn.setText("▶  " + ko("\\ud3b8\\uc9d1 \\uacb0\\uacfc \\uc800\\uc7a5"))
        elif self._mode == "convert":
            self.run_btn.setText("▶  " + ko("\\ubcc0\\ud658 \\uc2e4\\ud589"))
        elif self._mode == "security":
            self.run_btn.setText("▶  " + ko("\\ubcf4\\uc548 \\uc2e4\\ud589"))
        else:
            self.run_btn.setText("▶  " + ko("\\uc791\\uc5c5 \\uc2e4\\ud589"))

    @staticmethod
    def _side_btn_style(active: bool) -> str:
        if active:
            return (
                "QPushButton{background:#E9FBEF;color:#16A34A;border:none;border-radius:10px;"
                "text-align:left;padding-left:12px;font-family:'Malgun Gothic';font-size:9pt;font-weight:bold;}"
                "QPushButton:hover{background:#DCFCE7;}"
            )
        return (
            "QPushButton{background:transparent;color:#334155;border:none;border-radius:10px;"
            "text-align:left;padding-left:12px;font-family:'Malgun Gothic';font-size:9pt;}"
            "QPushButton:hover{background:#F1F5F9;}"
        )

    @staticmethod
    def _button_style(bg: str, fg: str, hover: str) -> str:
        return (
            f"QPushButton{{background:{bg};color:{fg};border:1px solid #DDE5EF;border-radius:9px;"
            "padding:0 12px;font-family:'Malgun Gothic';font-size:9pt;}}"
            f"QPushButton:hover{{background:{hover};}}"
            "QPushButton:disabled{background:#F8FAFC;color:#CBD5E1;}"
        )


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()   # PyInstaller EXE 멀티프로세싱 지원

    log_path = Path(__file__).parent / "error.log"
    logging.basicConfig(
        filename=str(log_path),
        level=logging.ERROR,
        format="%(asctime)s %(levelname)s\n%(message)s\n",
        encoding="utf-8",
    )

    try:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception:
        logging.error(traceback.format_exc())
        raise
