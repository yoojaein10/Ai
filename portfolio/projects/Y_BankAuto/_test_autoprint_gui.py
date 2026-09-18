# -*- coding: utf-8 -*-
"""자동 인쇄 GUI 동작 테스트 (offscreen Qt, 실제 프린터 미사용).

프린터 목록 조회는 print_manager.list_installed_printers를 mock으로 대체하며 실제
스풀러/GDI에 작업을 제출하지 않는다. 설정 경로는 tmp로 격리해 실제 settings.ini를
건드리지 않는다.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6.QtWidgets")
from PyQt6.QtWidgets import QApplication

import gui_prototype as gp
import print_manager as pm


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


def _patch_paths(monkeypatch, tmp_path):
    app_dir = tmp_path / "app"
    monkeypatch.setattr(gp, "APP_DIR", app_dir)
    monkeypatch.setattr(gp, "OUTPUT_DIR", app_dir / "output")
    monkeypatch.setattr(gp, "LOG_DIR", app_dir / "logs")
    monkeypatch.setattr(gp, "SETTINGS_INI", app_dir / "settings.ini")
    monkeypatch.setattr(gp, "CRASH_LOG", app_dir / "logs" / "crash.log")
    monkeypatch.setattr(gp, "PDF_DIR", tmp_path / "pdf")


def _drain(app, win, timeout_ms=3000):
    w = getattr(win, "_printer_worker", None)
    if w is not None:
        w.wait(timeout_ms)
    for _ in range(20):
        app.processEvents()


def make_window(app, monkeypatch, tmp_path, printers, ini_text=None):
    _patch_paths(monkeypatch, tmp_path)
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    if ini_text is not None:
        (tmp_path / "app" / "settings.ini").write_text(ini_text, encoding="utf-8")
    monkeypatch.setattr(pm, "list_installed_printers",
                        lambda *a, **k: list(printers))
    win = gp.MainWindow()
    _drain(app, win)
    return win


def test_default_autoprint_on(app, monkeypatch, tmp_path):
    win = make_window(app, monkeypatch, tmp_path, printers=["P1"])
    try:
        assert win.chk_autoprint.isChecked() is True   # 기본 ON
    finally:
        win.close()


def test_installed_printers_populate_combo(app, monkeypatch, tmp_path):
    win = make_window(app, monkeypatch, tmp_path, printers=["Printer X", "Printer Y"])
    try:
        texts = [win.cmb_printer.itemText(i) for i in range(win.cmb_printer.count())]
        assert texts == ["Printer X", "Printer Y"]
    finally:
        win.close()


def test_checkbox_enables_disables_widgets(app, monkeypatch, tmp_path):
    win = make_window(app, monkeypatch, tmp_path, printers=["P1"])
    try:
        win.chk_autoprint.setChecked(True)
        app.processEvents()
        assert win.cmb_printer.isEnabled() and win.btn_printer_refresh.isEnabled()
        win.chk_autoprint.setChecked(False)
        app.processEvents()
        assert not win.cmb_printer.isEnabled()
        assert not win.btn_printer_refresh.isEnabled()
    finally:
        win.close()


def test_off_snapshot_skips_print(app, monkeypatch, tmp_path):
    win = make_window(app, monkeypatch, tmp_path, printers=["P1"])
    try:
        win.chk_autoprint.setChecked(False)
        app.processEvents()
        snap = win._print_snapshot(str(tmp_path / "pdf"))
        assert snap["enabled"] is False
        assert snap["printer"] == ""
    finally:
        win.close()


def test_snapshot_uses_selected_printer(app, monkeypatch, tmp_path):
    win = make_window(app, monkeypatch, tmp_path, printers=["P1", "P2"])
    try:
        win.chk_autoprint.setChecked(True)
        idx = win.cmb_printer.findText("P2")
        win.cmb_printer.setCurrentIndex(idx)
        app.processEvents()
        snap = win._print_snapshot(str(tmp_path / "pdf"))
        assert snap["enabled"] is True
        assert snap["printer"] == "P2"
        assert snap["max_jobs_per_run"] == 100
    finally:
        win.close()


def test_settings_save_and_restore(app, monkeypatch, tmp_path):
    win = make_window(app, monkeypatch, tmp_path, printers=["P1", "P2"])
    try:
        idx = win.cmb_printer.findText("P2")
        win.cmb_printer.setCurrentIndex(idx)
        win.cmb_printer.activated.emit(idx)    # 사용자 선택(activated) → 저장
        app.processEvents()
    finally:
        win.close()
    # 동일 tmp 설정으로 재구성 → 저장된 P2 복원
    win2 = make_window(app, monkeypatch, tmp_path, printers=["P1", "P2"])
    try:
        assert win2._selected_printer_name() == "P2"
    finally:
        win2.close()


def test_missing_saved_printer_not_adopted(app, monkeypatch, tmp_path):
    ini = "[print]\nenabled = true\nprinter = GonePrinter\nmax_jobs_per_run = 100\n"
    win = make_window(app, monkeypatch, tmp_path, printers=["P1", "P2"], ini_text=ini)
    try:
        # 저장 프린터가 목록에 없으면 다른/기본 프린터를 임의 선택하지 않는다.
        assert win.cmb_printer.currentIndex() == -1
        assert win._selected_printer_name() == ""
    finally:
        win.close()


def test_corrupted_enabled_is_fail_closed(app, monkeypatch, tmp_path):
    # 손상된 boolean → 안전 기본(OFF).
    ini = "[print]\nenabled = maybe\nprinter =\nmax_jobs_per_run = 100\n"
    win = make_window(app, monkeypatch, tmp_path, printers=["P1"], ini_text=ini)
    try:
        assert win.chk_autoprint.isChecked() is False
    finally:
        win.close()


def test_tampered_max_jobs_clamped(app, monkeypatch, tmp_path):
    ini = "[print]\nenabled = true\nprinter =\nmax_jobs_per_run = 999999\n"
    win = make_window(app, monkeypatch, tmp_path, printers=["P1"], ini_text=ini)
    try:
        assert win._print_max_jobs() == pm.HARD_MAX_JOBS_PER_RUN  # 무제한 방지
    finally:
        win.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
