import sys
import os
import json
import ctypes
from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                             QWidget, QSystemTrayIcon, QMenu, QPushButton, QLabel,
                             QSlider)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile
from PyQt6.QtCore import QUrl, QSize, Qt, pyqtSignal, QObject, QPoint
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtGui import QIcon, QAction

# 전역 설정
APP_ID = "ScheduleApp_SingleInstance_Server"
# 실행 환경(로컬 개발 vs EXE 배포)에 따른 주소 자동 전환
if getattr(sys, 'frozen', False):
    BASE_URL = 'http://192.0.2.10:3000/'  # 실서버 배포 주소 (EXE 실행 시)
else:
    BASE_URL = "http://localhost:3001/"   # 로컬 개발용 주소 (테스트 시)

# 사번 저장 파일 경로 (백엔드 /current-empno API와 동일 경로)
EMPNO_FILE = r"C:\ProgramData\ScheduleApp\current_empno.txt"


def save_empno(empno_str) -> None:
    """유효한 숫자 사번이면 EMPNO_FILE에 저장"""
    try:
        val = int(str(empno_str).strip())
        os.makedirs(os.path.dirname(EMPNO_FILE), exist_ok=True)
        with open(EMPNO_FILE, "w", encoding="utf-8") as f:
            f.write(str(val))
    except (ValueError, TypeError, OSError):
        pass

class Communicate(QObject):
    received_empno = pyqtSignal(str)

class TitleBar(QWidget):
    """커스텀 드래그 가능 타이틀 바"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setObjectName("titleBar")
        self._drag_pos = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 4, 0)
        layout.setSpacing(0)

        # 타이틀 텍스트
        self.title_label = QLabel("일정")
        self.title_label.setObjectName("titleLabel")
        layout.addWidget(self.title_label)
        layout.addStretch()

        # 투명도 슬라이더
        self.opacity_label = QLabel("◐")
        self.opacity_label.setObjectName("opacityLabel")
        self.opacity_label.setFixedWidth(16)
        layout.addWidget(self.opacity_label)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setObjectName("opacitySlider")
        self.opacity_slider.setRange(30, 100)  # 30%~100%
        self.opacity_slider.setValue(100)
        self.opacity_slider.setFixedWidth(80)
        self.opacity_slider.setToolTip("투명도 조절")
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        layout.addWidget(self.opacity_slider)

        layout.addSpacing(8)

        # 최소화 버튼
        self.btn_minimize = QPushButton("─")
        self.btn_minimize.setObjectName("btnMinimize")
        self.btn_minimize.setFixedSize(40, 36)
        self.btn_minimize.clicked.connect(lambda: self.window().showMinimized())
        layout.addWidget(self.btn_minimize)

        # 닫기 버튼
        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("btnClose")
        self.btn_close.setFixedSize(40, 36)
        self.btn_close.clicked.connect(lambda: self.window().close())
        layout.addWidget(self.btn_close)

        self.setStyleSheet("""
            #titleBar {
                background-color: #ffffff;
                border-bottom: 1px solid #e5e7eb;
            }
            #titleLabel {
                color: #374151;
                font-size: 13px;
                font-weight: 500;
            }
            #btnMinimize, #btnClose {
                border: none;
                background: transparent;
                font-size: 13px;
                color: #6b7280;
                border-radius: 0px;
            }
            #btnMinimize:hover {
                background-color: #e5e7eb;
                color: #111827;
            }
            #btnClose:hover {
                background-color: #ef4444;
                color: #ffffff;
            }
            #opacityLabel {
                color: #9ca3af;
                font-size: 14px;
            }
            #opacitySlider {
                height: 20px;
            }
            #opacitySlider::groove:horizontal {
                border: none;
                height: 4px;
                background: #e5e7eb;
                border-radius: 2px;
            }
            #opacitySlider::handle:horizontal {
                background: #6b7280;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            #opacitySlider::handle:horizontal:hover {
                background: #374151;
            }
        """)

    def _on_opacity_changed(self, value):
        self.window().setWindowOpacity(value / 100.0)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        win = self.window()
        if win.isMaximized():
            win.showNormal()
        else:
            win.showMaximized()


class MainWindow(QMainWindow):
    def __init__(self, initial_empno=None):
        super().__init__()
        self.setWindowTitle("ScheduleApp - 캘린더")
        self.resize(1400, 960)

        # 프레임리스 윈도우
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        # 중앙 위젯 + 수직 레이아웃
        central = QWidget()
        central.setObjectName("centralWidget")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 커스텀 타이틀 바
        self.title_bar = TitleBar(self)
        layout.addWidget(self.title_bar)

        # 웹 브라우저 (persistent storage로 localStorage 유지)
        storage_dir = os.path.join(os.path.expanduser("~"), ".scheduleapp")
        profile = QWebEngineProfile("ScheduleApp", self)
        profile.setPersistentStoragePath(os.path.join(storage_dir, "storage"))
        profile.setCachePath(os.path.join(storage_dir, "cache"))
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        from PyQt6.QtWebEngineCore import QWebEnginePage
        page = QWebEnginePage(profile, self)
        self.browser = QWebEngineView()
        self.browser.setPage(page)
        layout.addWidget(self.browser)

        self.setCentralWidget(central)

        # 전체 스타일
        self.setStyleSheet("""
            #centralWidget {
                background-color: #ffffff;
                border: 1px solid #d1d5db;
            }
        """)

        # 트레이 아이콘 설정
        self.create_tray_icon()

        # 최초 URL 로드
        self.load_url(initial_empno)

    def load_url(self, empno=None):
        url = BASE_URL + "calendar"
        if empno:
            url += f"?empno={empno}"
        self.browser.setUrl(QUrl(url))

    def _icon_path(self, filename):
        if getattr(sys, 'frozen', False):
            return os.path.join(sys._MEIPASS, "assets", filename)
        return os.path.join(os.path.dirname(__file__), "assets", filename)

    def create_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        icon = QIcon(self._icon_path("Cal.ico"))
        self.tray_icon.setIcon(icon)
        self.setWindowIcon(icon)
        
        tray_menu = QMenu()
        show_action = QAction("Open", self)
        show_action.triggered.connect(self.show_and_raise)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        self.tray_icon.show()

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_and_raise()

    def show_and_raise(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self.browser.reload()

    def closeEvent(self, event):
        # 창을 닫아도 종료하지 않고 트레이로 숨김
        if self.tray_icon.isVisible():
            self.hide()
            event.ignore()

class ScheduleApp:
    ERROR_ALREADY_EXISTS = 183

    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        # Windows Mutex로 중복 실행 차단 (시스템 수준)
        self._mutex = ctypes.windll.kernel32.CreateMutexW(None, True, APP_ID)
        if ctypes.windll.kernel32.GetLastError() == self.ERROR_ALREADY_EXISTS:
            self.send_to_existing_instance()
            sys.exit(0)

        # 커뮤니케이터 (인스턴스 간 통신용)
        self.comm = Communicate()
        self.comm.received_empno.connect(self.handle_new_empno)

        # 이전 비정상 종료로 남은 서버 정리 후 listen
        QLocalServer.removeServer(APP_ID)
        self.server = QLocalServer()
        self.server.listen(APP_ID)
        self.server.newConnection.connect(self.handle_new_connection)

        # 첫 번째 인스턴스: 메인 윈도우 생성
        initial_empno = sys.argv[1] if len(sys.argv) > 1 else None
        if initial_empno:
            save_empno(initial_empno)
        self.window = MainWindow(initial_empno)
        self.window.show()

    def send_to_existing_instance(self):
        socket = QLocalSocket()
        socket.connectToServer(APP_ID)
        if socket.waitForConnected(500):
            new_empno = sys.argv[1] if len(sys.argv) > 1 else ""
            socket.write(new_empno.encode('utf-8'))
            socket.waitForBytesWritten(500)
            socket.disconnectFromServer()

    def handle_new_connection(self):
        socket = self.server.nextPendingConnection()
        if socket.waitForReadyRead(500):
            new_empno = socket.readAll().data().decode('utf-8')
            self.comm.received_empno.emit(new_empno)
            socket.disconnectFromServer()

    def handle_new_empno(self, empno):
        # 기존 창을 활성화하고 새 ID 로드
        self.window.show_and_raise()
        if empno:
            save_empno(empno)
            self.window.load_url(empno)

    def run(self):
        return self.app.exec()

if __name__ == "__main__":
    app = ScheduleApp()
    sys.exit(app.run())
