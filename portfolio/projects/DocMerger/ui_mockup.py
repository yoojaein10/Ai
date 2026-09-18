import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QRadioButton,
    QButtonGroup, QProgressBar, QFileDialog, QFrame, QSizePolicy,
    QAbstractItemView, QStatusBar
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QColor, QIcon, QDragEnterEvent, QDropEvent


FILE_TYPE_COLOR = {
    "hwp":  "#D4EDDA",
    "hwpx": "#D4EDDA",
    "docx": "#CCE5FF",
    "doc":  "#CCE5FF",
    "pdf":  "#FFF3CD",
    "jpg":  "#F8D7DA",
    "jpeg": "#F8D7DA",
    "png":  "#F8D7DA",
    "tiff": "#F8D7DA",
    "bmp":  "#F8D7DA",
}

LABEL_COLOR = {
    "hwp":  ("HWP",  "#155724", "#D4EDDA"),
    "hwpx": ("HWPX", "#155724", "#D4EDDA"),
    "docx": ("DOCX", "#004085", "#CCE5FF"),
    "doc":  ("DOC",  "#004085", "#CCE5FF"),
    "pdf":  ("PDF",  "#856404", "#FFF3CD"),
    "jpg":  ("IMG",  "#721C24", "#F8D7DA"),
    "jpeg": ("IMG",  "#721C24", "#F8D7DA"),
    "png":  ("IMG",  "#721C24", "#F8D7DA"),
    "tiff": ("IMG",  "#721C24", "#F8D7DA"),
    "bmp":  ("IMG",  "#721C24", "#F8D7DA"),
}


class FileItemWidget(QWidget):
    def __init__(self, filename: str, parent=None):
        super().__init__(parent)
        self.filename = filename
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(10)

        # 순서 핸들 (드래그 힌트)
        handle = QLabel("⠿")
        handle.setFixedWidth(16)
        handle.setStyleSheet("color: #aaa; font-size: 16px;")
        layout.addWidget(handle)

        # 파일 타입 뱃지
        tag_text, tag_fg, tag_bg = LABEL_COLOR.get(ext, ("FILE", "#333", "#eee"))
        badge = QLabel(tag_text)
        badge.setFixedWidth(42)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background:{tag_bg}; color:{tag_fg}; border-radius:4px;"
            f"font-size:10px; font-weight:bold; padding:2px 4px;"
        )
        layout.addWidget(badge)

        # 파일명
        name_label = QLabel(filename)
        name_label.setFont(QFont("Malgun Gothic", 9))
        name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        name_label.setToolTip(filename)
        layout.addWidget(name_label)

        # Readable / Unreadable 라디오
        self.btn_readable   = QRadioButton("Readable")
        self.btn_unreadable = QRadioButton("Unreadable")
        self.btn_readable.setChecked(True)
        self.btn_readable.setFont(QFont("Malgun Gothic", 9))
        self.btn_unreadable.setFont(QFont("Malgun Gothic", 9))

        self.option_group = QButtonGroup(self)
        self.option_group.addButton(self.btn_readable)
        self.option_group.addButton(self.btn_unreadable)

        layout.addWidget(self.btn_readable)
        layout.addWidget(self.btn_unreadable)

        # 삭제 버튼
        del_btn = QPushButton("✕")
        del_btn.setFixedSize(24, 24)
        del_btn.setStyleSheet(
            "QPushButton{background:#fff;border:1px solid #ddd;border-radius:4px;color:#999;}"
            "QPushButton:hover{background:#fee;color:#c00;}"
        )
        del_btn.clicked.connect(self._remove_self)
        layout.addWidget(del_btn)

    def _remove_self(self):
        list_widget = self.parent().parent()
        for i in range(list_widget.count()):
            if list_widget.itemWidget(list_widget.item(i)) is self:
                list_widget.takeItem(i)
                break

    def get_option(self) -> str:
        return "readable" if self.btn_readable.isChecked() else "unreadable"


class DropListWidget(QListWidget):
    """드래그앤드롭 + 순서 변경 지원 리스트"""

    SUPPORTED = {".hwp", ".hwpx", ".docx", ".doc", ".pdf",
                 ".jpg", ".jpeg", ".png", ".tiff", ".bmp"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSpacing(2)
        self.setStyleSheet(
            "QListWidget{background:#fafafa;border:2px dashed #ccc;border-radius:8px;}"
            "QListWidget::item:selected{background:#e8f0fe;}"
            "QListWidget::item:hover{background:#f0f4ff;}"
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
                ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
                if ext in self.SUPPORTED:
                    self.add_file(path.replace("\\", "/").split("/")[-1])
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def add_file(self, filename: str):
        item = QListWidgetItem(self)
        widget = FileItemWidget(filename)
        item.setSizeHint(QSize(0, 42))
        self.addItem(item)
        self.setItemWidget(item, widget)

    def get_file_options(self) -> list[dict]:
        result = []
        for i in range(self.count()):
            w = self.itemWidget(self.item(i))
            if w:
                result.append({"file": w.filename, "option": w.get_option()})
        return result


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DocMerger  —  PDF 통합 변환기")
        self.setMinimumSize(780, 580)
        self.resize(860, 640)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 12)
        root.setSpacing(12)

        # ── 헤더 ──────────────────────────────────────────
        header = QLabel("📄  DocMerger")
        header.setFont(QFont("Malgun Gothic", 15, QFont.Weight.Bold))
        header.setStyleSheet("color:#2c3e50;")
        root.addWidget(header)

        sub = QLabel("HWP · DOCX · 이미지 · PDF를 순서대로 올려 하나의 PDF로 합칩니다.")
        sub.setFont(QFont("Malgun Gothic", 9))
        sub.setStyleSheet("color:#666;")
        root.addWidget(sub)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color:#ddd;")
        root.addWidget(divider)

        # ── 파일 리스트 ──────────────────────────────────
        list_label = QHBoxLayout()
        list_label.addWidget(QLabel("파일 목록  (드래그로 순서 변경)"))
        list_label.addStretch()

        badge_desc = QHBoxLayout()
        for text, fg, bg in [("HWP","#155724","#D4EDDA"),("DOCX","#004085","#CCE5FF"),
                              ("PDF","#856404","#FFF3CD"),("IMG","#721C24","#F8D7DA")]:
            b = QLabel(text)
            b.setFixedWidth(36)
            b.setAlignment(Qt.AlignmentFlag.AlignCenter)
            b.setStyleSheet(f"background:{bg};color:{fg};border-radius:3px;"
                            f"font-size:9px;font-weight:bold;padding:1px 3px;")
            badge_desc.addWidget(b)
        list_label.addLayout(badge_desc)
        root.addLayout(list_label)

        self.list_widget = DropListWidget()
        self.list_widget.setMinimumHeight(280)
        root.addWidget(self.list_widget)

        # ── 드롭 안내 오버레이 느낌 ──────────────────────
        drop_hint = QLabel("여기에 파일을 드래그하거나 아래 '파일 추가' 버튼을 사용하세요")
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_hint.setFont(QFont("Malgun Gothic", 9))
        drop_hint.setStyleSheet("color:#bbb;")
        root.addWidget(drop_hint)

        # ── 버튼 행 ──────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        add_btn = QPushButton("＋  파일 추가")
        add_btn.setFixedHeight(34)
        add_btn.setStyleSheet(self._btn_style("#ecf0f1", "#2c3e50"))
        add_btn.clicked.connect(self._add_files)
        btn_row.addWidget(add_btn)

        clear_btn = QPushButton("🗑  전체 삭제")
        clear_btn.setFixedHeight(34)
        clear_btn.setStyleSheet(self._btn_style("#ecf0f1", "#c0392b"))
        clear_btn.clicked.connect(self.list_widget.clear)
        btn_row.addWidget(clear_btn)

        btn_row.addStretch()

        self.out_label = QLabel("저장 경로: 미지정")
        self.out_label.setFont(QFont("Malgun Gothic", 9))
        self.out_label.setStyleSheet("color:#555;")
        btn_row.addWidget(self.out_label)

        out_btn = QPushButton("📁  저장 위치")
        out_btn.setFixedHeight(34)
        out_btn.setStyleSheet(self._btn_style("#ecf0f1", "#2980b9"))
        out_btn.clicked.connect(self._select_output)
        btn_row.addWidget(out_btn)

        root.addLayout(btn_row)

        # ── 진행 상태 ─────────────────────────────────────
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFixedHeight(18)
        self.progress.setTextVisible(True)
        self.progress.setFormat("대기 중")
        self.progress.setStyleSheet(
            "QProgressBar{border:1px solid #ddd;border-radius:4px;background:#f5f5f5;text-align:center;font-size:9px;}"
            "QProgressBar::chunk{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #3498db,stop:1 #2ecc71);border-radius:3px;}"
        )
        root.addWidget(self.progress)

        # ── 실행 버튼 ─────────────────────────────────────
        self.run_btn = QPushButton("▶  PDF 변환 및 병합 실행")
        self.run_btn.setFixedHeight(44)
        self.run_btn.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        self.run_btn.setStyleSheet(self._btn_style("#2ecc71", "white", hover="#27ae60"))
        self.run_btn.clicked.connect(self._run_mock)
        root.addWidget(self.run_btn)

        # ── 상태바 ────────────────────────────────────────
        self.status = QStatusBar()
        self.status.showMessage("준비")
        self.setStatusBar(self.status)

        # 목각 샘플 데이터
        for f in ["공문_2026.hwp", "계약서_최종.docx", "첨부이미지.jpg", "기존문서.pdf"]:
            self.list_widget.add_file(f)

        self.out_path = ""

    # ── 슬롯 ────────────────────────────────────────────────

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "파일 선택", "",
            "지원 파일 (*.hwp *.hwpx *.docx *.doc *.pdf *.jpg *.jpeg *.png *.tiff *.bmp)"
        )
        for p in paths:
            self.list_widget.add_file(p.replace("\\", "/").split("/")[-1])

    def _select_output(self):
        path, _ = QFileDialog.getSaveFileName(self, "저장 위치 선택", "merged_output.pdf", "PDF (*.pdf)")
        if path:
            self.out_path = path
            short = path.replace("\\", "/").split("/")[-1]
            self.out_label.setText(f"저장 경로: {short}")

    def _run_mock(self):
        """목각: 실제 변환 없이 UI 흐름만 시뮬레이션"""
        items = self.list_widget.get_file_options()
        if not items:
            self.status.showMessage("파일을 먼저 추가하세요.")
            return

        self.run_btn.setEnabled(False)
        self.run_btn.setText("처리 중…")
        self.progress.setFormat("변환 중…")

        # 목각: 즉시 완료 표시 (실제 구현 시 QThread Worker로 교체)
        total = len(items)
        for i, item in enumerate(items, 1):
            pct = int(i / total * 100)
            self.progress.setValue(pct)
            self.progress.setFormat(f"[{i}/{total}] {item['file']} ({item['option']}) — {pct}%")
            QApplication.processEvents()

        self.progress.setValue(100)
        self.progress.setFormat("완료 ✓")
        self.run_btn.setEnabled(True)
        self.run_btn.setText("▶  PDF 변환 및 병합 실행")
        self.status.showMessage(f"완료 — {total}개 파일 처리됨 → merged_output.pdf")

    @staticmethod
    def _btn_style(bg: str, color: str, hover: str = "") -> str:
        h = hover or bg
        return (
            f"QPushButton{{background:{bg};color:{color};border:1px solid #ddd;"
            f"border-radius:6px;padding:0 14px;font-family:'Malgun Gothic';font-size:10px;}}"
            f"QPushButton:hover{{background:{h};}}"
            f"QPushButton:disabled{{background:#eee;color:#aaa;}}"
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
