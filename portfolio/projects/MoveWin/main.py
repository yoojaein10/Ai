# -*- coding: utf-8 -*-
"""Oct — jellyfish character whose tentacles animate with typing speed."""

import sys
import math
import time
import os
from collections import deque

from PyQt5.QtWidgets import (QApplication, QMainWindow,
                               QSystemTrayIcon, QMenu, QAction)
from PyQt5.QtCore import Qt, QTimer, QRect
from PyQt5.QtGui import QPainter, QColor, QPixmap, QIcon, QImage
from pynput import keyboard


# ── 설정 ──────────────────────────────────────────────────────────────────────
DISPLAY_WIDTH  = 180     # 화면에 표시할 캐릭터 너비 (px)
TENTACLE_SPLIT = 0.52    # 이 비율 아래는 촉수 영역으로 파도 효과 적용
MAX_WAVE_AMP   = 30      # 최대 타자 속도일 때 촉수 좌우 흔들림 (px)
MAX_CPS        = 15.0    # 이 이상은 최대 애니메이션으로 처리
TYPING_WINDOW  = 2.0     # 타자 속도 측정 윈도우 (초)
FPS            = 60


# ── 타자 속도 추적 ────────────────────────────────────────────────────────────
class TypingTracker:
    def __init__(self):
        self._q: deque = deque()

    def press(self):
        now = time.time()
        self._q.append(now)
        cutoff = now - TYPING_WINDOW
        while self._q and self._q[0] < cutoff:
            self._q.popleft()

    @property
    def cps(self) -> float:
        now = time.time()
        recent = [t for t in self._q if t > now - TYPING_WINDOW]
        return len(recent) / TYPING_WINDOW if len(recent) >= 2 else 0.0


# ── 이미지 로딩 ───────────────────────────────────────────────────────────────
def resource(rel: str) -> str:
    """소스 실행 / PyInstaller 번들 모두 동작하는 경로 반환."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def load_character(img_path: str) -> QPixmap:
    """
    PNG 로드 → 체크무늬 배경 제거 → 캐릭터 영역 크롭 → 스케일.
    Pillow + numpy 사용. 없으면 PyQt5 폴백.
    """
    try:
        import numpy as np
        from PIL import Image

        img = Image.open(img_path).convert('RGBA')
        arr = np.array(img, dtype=np.uint8)
        h, w = arr.shape[:2]

        # 코너 alpha 확인: 불투명하면 배경이 구워진 것
        corner_alpha = int(min(
            arr[0, 0, 3], arr[0, w - 1, 3],
            arr[h - 1, 0, 3], arr[h - 1, w - 1, 3]
        ))
        if corner_alpha > 200:
            _flood_remove_bg(arr, h, w)

        # 비투명 픽셀 바운딩 박스
        alpha_ch = arr[:, :, 3]
        rows = np.any(alpha_ch > 15, axis=1)
        cols = np.any(alpha_ch > 15, axis=0)
        if rows.any() and cols.any():
            r0, r1 = int(np.where(rows)[0][0]),  int(np.where(rows)[0][-1])
            c0, c1 = int(np.where(cols)[0][0]),  int(np.where(cols)[0][-1])
            pad = 4
            arr = arr[max(0, r0 - pad):min(h, r1 + pad + 1),
                      max(0, c0 - pad):min(w, c1 + pad + 1)]

        rh, rw = arr.shape[:2]
        qimg = QImage(arr.tobytes(), rw, rh, rw * 4, QImage.Format_RGBA8888)
        pix  = QPixmap.fromImage(qimg)

    except ImportError:
        pix = _load_pyqt5_fallback(img_path)

    return pix.scaledToWidth(DISPLAY_WIDTH, Qt.SmoothTransformation)


def _flood_remove_bg(arr, h: int, w: int) -> None:
    """
    이미지 가장자리에서 BFS 플러드필로 회색/흰색 체크무늬 배경 제거.
    근-회색(r≈g≈b)이고 밝은 픽셀을 투명으로 바꿈.
    """
    import numpy as np
    visited = np.zeros((h, w), dtype=bool)
    q: deque = deque()

    for x in range(w):
        for y in (0, h - 1):
            if not visited[y, x]:
                visited[y, x] = True
                q.append((y, x))
    for y in range(1, h - 1):
        for x in (0, w - 1):
            if not visited[y, x]:
                visited[y, x] = True
                q.append((y, x))

    while q:
        y, x = q.popleft()
        r, g, b = int(arr[y, x, 0]), int(arr[y, x, 1]), int(arr[y, x, 2])
        # 조건: 근-회색(채도 낮음) + 충분히 밝음 → 배경
        if abs(r - g) < 32 and abs(g - b) < 32 and r > 128:
            arr[y, x, 3] = 0
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx]:
                    visited[ny, nx] = True
                    q.append((ny, nx))


def _load_pyqt5_fallback(img_path: str) -> QPixmap:
    """Pillow 없을 때 PyQt5만으로 배경 제거 + 크롭."""
    raw = QPixmap(img_path)
    img = raw.toImage().convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()

    def alpha_at(x, y):
        return QColor(img.pixel(x, y)).alpha()

    corner_alpha = min(alpha_at(0, 0), alpha_at(w - 1, 0),
                       alpha_at(0, h - 1), alpha_at(w - 1, h - 1))
    if corner_alpha > 200:
        transparent = QColor(0, 0, 0, 0)
        visited: set = set()
        q: deque = deque()
        seeds = ([(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)] +
                 [(0, y) for y in range(1, h - 1)] + [(w - 1, y) for y in range(1, h - 1)])
        for s in seeds:
            visited.add(s)
            q.append(s)
        while q:
            x, y = q.popleft()
            c = QColor(img.pixel(x, y))
            r, g, b = c.red(), c.green(), c.blue()
            if abs(r - g) < 32 and abs(g - b) < 32 and r > 128:
                img.setPixelColor(x, y, transparent)
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                        visited.add((nx, ny))
                        q.append((nx, ny))

    min_x, max_x, min_y, max_y = w, 0, h, 0
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if QColor(img.pixel(x, y)).alpha() > 15:
                if x < min_x: min_x = x
                if x > max_x: max_x = x
                if y < min_y: min_y = y
                if y > max_y: max_y = y

    pix = QPixmap.fromImage(img)
    if min_x < max_x:
        pad = 4
        pix = pix.copy(QRect(max(0, min_x - pad), max(0, min_y - pad),
                              min(w, max_x - min_x + 1 + pad * 2),
                              min(h, max_y - min_y + 1 + pad * 2)))
    return pix


# ── 메인 윈도우 ───────────────────────────────────────────────────────────────
class OctWindow(QMainWindow):
    def __init__(self, img_path: str):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 캐릭터 이미지 로드 (전체, 잘리지 않음)
        self.pix    = load_character(img_path)
        self.char_w = self.pix.width()
        self.char_h = self.pix.height()

        # 촉수 파도 여백: 2차 하모닉 포함한 실제 최대 진폭(×1.3) + 여유
        self.pad_x = int(MAX_WAVE_AMP * 1.35) + 8
        win_w = self.char_w + self.pad_x * 2
        win_h = self.char_h + 20   # 위아래 bob 여유

        self.resize(win_w, win_h)

        # 초기 위치: 화면 우측 하단
        scr = QApplication.primaryScreen().availableGeometry()
        self.move(scr.right() - win_w - 20, scr.bottom() - win_h - 10)

        # 상태
        self.t          = 0.0
        self.smooth_cps = 0.0
        self._drag_pos  = None

        # 키보드 리스너 (전역)
        self.tracker   = TypingTracker()
        self._listener = keyboard.Listener(on_press=lambda _: self.tracker.press())
        self._listener.daemon = True
        self._listener.start()

        # 60fps 타이머
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._tick)
        self._tmr.start(1000 // FPS)

        # 시스템 트레이
        icon = QIcon(self.pix.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip("Oct - 우클릭으로 종료")
        menu = QMenu()
        act  = QAction("종료 (Exit)", self)
        act.triggered.connect(QApplication.instance().quit)
        menu.addAction(act)
        tray.setContextMenu(menu)
        tray.show()
        self._tray = tray  # 참조 유지

        self.show()

    # ── 타이머 콜백 ───────────────────────────────────────────────────────────
    def _tick(self):
        cps   = self.tracker.cps
        # 빠른 증가, 느린 감소 (타자 멈춰도 서서히 느려짐)
        alpha = 0.18 if cps > self.smooth_cps else 0.04
        self.smooth_cps += (cps - self.smooth_cps) * alpha

        speed = 0.5 + min(self.smooth_cps / MAX_CPS, 1.0) * 5.5
        self.t += speed / FPS
        self.update()

    # ── 그리기 ────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        ratio = min(self.smooth_cps / MAX_CPS, 1.0)

        # 전체 캐릭터 위아래 bob
        bob = int(math.sin(self.t * 1.5) * (2 + self.smooth_cps * 0.5))

        split  = int(self.char_h * TENTACLE_SPLIT)   # 몸통/촉수 경계 (픽셀)
        tent_h = self.char_h - split                  # 촉수 영역 높이

        # ① 몸통 (위쪽): 파도 없이 그대로
        p.drawPixmap(
            QRect(self.pad_x, bob, self.char_w, split),
            self.pix,
            QRect(0, 0, self.char_w, split)
        )

        # ② 촉수 (아래쪽): 2px 수평 스트립씩 좌우로 사인파 이동
        amp  = 1.5 + ratio * MAX_WAVE_AMP   # 흔들림 폭: 느림=작음, 빠름=큼
        freq = 3.0 + ratio * 3.0            # 파장 반복 횟수

        STRIP = 2
        for row in range(0, tent_h, STRIP):
            f = row / tent_h   # 0 = 몸통 경계, 1 = 촉수 끝

            # 진폭은 촉수 끝으로 갈수록 커짐 (f^0.8 으로 빠르게 증가)
            wave_amp = amp * (f ** 0.8)

            # 기본 파도 + 부드러운 2차 하모닉 (더 자연스러운 촉수 느낌)
            wave = (math.sin(self.t * 4.5 + f * freq * math.pi * 2) * wave_amp
                    + math.sin(self.t * 7.2 + f * math.pi * 5.1) * wave_amp * 0.28)
            wave = int(wave)

            src_y   = split + row
            sh      = min(STRIP, self.char_h - src_y)
            if sh <= 0:
                break

            p.drawPixmap(
                QRect(self.pad_x + wave, bob + split + row, self.char_w, sh),
                self.pix,
                QRect(0, src_y, self.char_w, sh)
            )

        p.end()

    # ── 드래그 이동 ───────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.LeftButton and self._drag_pos is not None:
            self.move(e.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None


# ── 진입점 ────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    OctWindow(resource('char.png'))
    sys.exit(app.exec_())
