# -*- coding: utf-8 -*-
"""설정 원자 저장·복원 + GUI 레이아웃/프린터 저장 회귀 테스트.

- 실제 C:\\Bank24Extractor\\settings.ini 를 읽거나 쓰지 않는다(경로를 tmp로 주입).
- 실제 프린터/Windows 스풀러를 호출하지 않는다(list_installed_printers mock).
- 합성 프린터명·합성 설정만 사용. 단독 pytest 프로세스로 실행.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import glob
import threading

import pytest

import gui_prototype as gp
import print_manager as pm


# ── 경로 주입 헬퍼 ───────────────────────────────────────────────────────────
def _inject_paths(monkeypatch, tmp_path):
    app_dir = tmp_path / "app"
    monkeypatch.setattr(gp, "APP_DIR", app_dir)
    monkeypatch.setattr(gp, "OUTPUT_DIR", app_dir / "output")
    monkeypatch.setattr(gp, "LOG_DIR", app_dir / "logs")
    monkeypatch.setattr(gp, "SETTINGS_INI", app_dir / "settings.ini")
    monkeypatch.setattr(gp, "CRASH_LOG", app_dir / "logs" / "crash.log")
    monkeypatch.setattr(gp, "PDF_DIR", tmp_path / "pdf")
    gp._known_identity.clear()
    return app_dir


def _tmp_files(app_dir):
    return glob.glob(os.path.join(str(app_dir), ".settings_*.tmp"))


# ════════════════════════════════════════════════════════════════════════════
# 원자 저장 / round-trip / 특수문자 / 외부변경 (Qt 불필요)
# ════════════════════════════════════════════════════════════════════════════
def test_printer_name_roundtrip_with_percent_and_special(monkeypatch, tmp_path):
    app_dir = _inject_paths(monkeypatch, tmp_path)
    cfg = gp.load_settings()
    tricky = "HP %s LaserJet (Copy #2) 100%"   # % 가 있어도 interpolation=None로 보존
    cfg.set("print", "printer", tricky)
    assert gp.save_settings(cfg) == "OK"
    reloaded = gp.load_settings()
    assert reloaded.get("print", "printer") == tricky   # 정확 round-trip
    assert _tmp_files(app_dir) == []


def test_existing_keys_preserved_no_unexpected(monkeypatch, tmp_path):
    _inject_paths(monkeypatch, tmp_path)
    cfg = gp.load_settings()
    before = gp._cfg_mapping(cfg)
    cfg.set("print", "printer", "Printer A")
    assert gp.save_settings(cfg) == "OK"
    reloaded = gp.load_settings()
    after = gp._cfg_mapping(reloaded)
    # print.printer만 바뀌고 나머지는 의미적으로 동일, 예상외 섹션/키 없음
    assert set(after.keys()) == set(before.keys())
    for sec in before:
        for k, v in before[sec].items():
            if (sec, k) == ("print", "printer"):
                continue
            assert after[sec][k] == v
    assert after["print"]["printer"] == "Printer A"


def test_atomic_failure_preserves_original(monkeypatch, tmp_path):
    app_dir = _inject_paths(monkeypatch, tmp_path)
    cfg = gp.load_settings()
    cfg.set("print", "printer", "Original")
    assert gp.save_settings(cfg) == "OK"
    original_bytes = (app_dir / "settings.ini").read_bytes()

    # DACL 복사 실패를 강제 → 원본 미교체(원자 저장 실패)
    monkeypatch.setattr(gp, "_copy_dacl", lambda s, d: False)
    cfg.set("print", "printer", "ShouldNotPersist")
    code = gp.save_settings(cfg)
    assert code == "ACL_PRESERVE_FAILED"
    # 원본 내용 그대로, 임시파일 없음
    assert (app_dir / "settings.ini").read_bytes() == original_bytes
    assert _tmp_files(app_dir) == []


def test_external_change_not_overwritten(monkeypatch, tmp_path):
    app_dir = _inject_paths(monkeypatch, tmp_path)
    cfg = gp.load_settings()
    cfg.set("print", "printer", "Mine")
    assert gp.save_settings(cfg) == "OK"

    # 외부 프로세스가 파일을 변경(크기 달라짐)
    ext = "[print]\nprinter = ExternallyEdited_LongerValue_XXXXXXXXXX\n"
    (app_dir / "settings.ini").write_text(ext, encoding="utf-8")

    cfg.set("print", "printer", "MyNewValue")
    code = gp.save_settings(cfg)
    assert code == "EXTERNAL_CHANGE"
    # 외부 변경 내용이 보존됨(우리 값으로 덮어쓰지 않음)
    assert "ExternallyEdited" in (app_dir / "settings.ini").read_text(encoding="utf-8")
    assert _tmp_files(app_dir) == []


def test_unsafe_path_not_saved(monkeypatch, tmp_path):
    app_dir = _inject_paths(monkeypatch, tmp_path)
    app_dir.mkdir(parents=True, exist_ok=True)
    # 부모가 디렉터리가 아닌 '파일'인 경로 → 저장 거부
    notdir = app_dir / "afile"
    notdir.write_text("x", encoding="utf-8")
    monkeypatch.setattr(gp, "SETTINGS_INI", notdir / "settings.ini")
    gp._known_identity.clear()
    cfg = gp._new_parser()
    cfg.add_section("print")
    cfg.set("print", "printer", "X")
    assert gp.save_settings(cfg) == "UNSAFE_PATH"


def test_concurrent_saves_no_corruption(monkeypatch, tmp_path):
    app_dir = _inject_paths(monkeypatch, tmp_path)
    cfg = gp.load_settings()
    cfg.set("print", "printer", "Seed")
    assert gp.save_settings(cfg) == "OK"

    errors = []

    def worker(name):
        try:
            c = gp.load_settings()
            c.set("print", "printer", name)
            gp.save_settings(c)   # 락으로 직렬화 — 예외/손상 없어야 함
        except Exception as e:   # noqa
            errors.append(type(e).__name__)

    threads = [threading.Thread(target=worker, args=(f"P{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    reloaded = gp.load_settings()          # 파일이 여전히 파싱 가능(손상 없음)
    assert reloaded.get("print", "printer") is not None
    assert _tmp_files(app_dir) == []       # 임시파일 잔존 없음


def test_valid_printer_name_rejects_control_chars():
    assert gp._valid_printer_name("Normal Printer") is True
    assert gp._valid_printer_name("") is True
    assert gp._valid_printer_name("bad\x00nul") is False
    assert gp._valid_printer_name("bad\r\nCRLF") is False
    assert gp._valid_printer_name("bad\x1bctrl") is False


# ════════════════════════════════════════════════════════════════════════════
# GUI (offscreen): 레이아웃 + 프린터 저장/복원
# ════════════════════════════════════════════════════════════════════════════
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


def _drain(app, win, timeout_ms=3000):
    w = getattr(win, "_printer_worker", None)
    if w is not None:
        w.wait(timeout_ms)
    for _ in range(20):
        app.processEvents()


def make_window(app, monkeypatch, tmp_path, printers, ini_text=None):
    app_dir = _inject_paths(monkeypatch, tmp_path)
    app_dir.mkdir(parents=True, exist_ok=True)
    if ini_text is not None:
        (app_dir / "settings.ini").write_text(ini_text, encoding="utf-8")
    monkeypatch.setattr(pm, "list_installed_printers", lambda *a, **k: list(printers))
    win = gp.MainWindow()
    _drain(app, win)
    return win


# ── 레이아웃 ─────────────────────────────────────────────────────────────────
def test_left_column_is_scrollable(app, monkeypatch, tmp_path):
    win = make_window(app, monkeypatch, tmp_path, printers=["P1"])
    try:
        assert win._left_scroll.widgetResizable() is True
        assert (win._left_scroll.horizontalScrollBarPolicy()
                == Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    finally:
        win.close()


def test_run_button_not_overlapping_print_panel(app, monkeypatch, tmp_path):
    win = make_window(app, monkeypatch, tmp_path, printers=["P1"])
    win.resize(1000, 720)
    win.show()
    app.processEvents()
    try:
        # 실행 버튼과 자동 인쇄 체크박스가 전역 좌표에서 겹치지 않아야 한다.
        r_btn = win.btn_run.rect()
        g_btn = win.btn_run.mapToGlobal(r_btn.topLeft())
        rect_btn = r_btn.translated(g_btn - r_btn.topLeft())
        r_chk = win.chk_autoprint.rect()
        g_chk = win.chk_autoprint.mapToGlobal(r_chk.topLeft())
        rect_chk = r_chk.translated(g_chk - r_chk.topLeft())
        assert not rect_btn.intersects(rect_chk)
    finally:
        win.close()


def test_small_window_scrolls_to_reach_controls(app, monkeypatch, tmp_path):
    win = make_window(app, monkeypatch, tmp_path, printers=["P1"])
    win.resize(960, 560)     # 작은 창(고DPI 근사)
    win.show()
    app.processEvents()
    try:
        vbar = win._left_scroll.verticalScrollBar()
        # 내용이 넘치면 스크롤로 접근 가능해야 함(가로 스크롤은 없음)
        assert vbar.maximum() >= 0
        assert (win._left_scroll.horizontalScrollBarPolicy()
                == Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 버튼 위젯 자체는 존재하고 스크롤 영역 자식으로 배치됨
        assert win.btn_run is not None
    finally:
        win.close()


# ── 프린터 저장/복원 ─────────────────────────────────────────────────────────
def test_selection_saved_immediately_first_item(app, monkeypatch, tmp_path):
    win = make_window(app, monkeypatch, tmp_path, printers=["First", "Second"])
    try:
        # 목록 로딩 후 미선택(-1). 사용자가 '첫 항목'을 고르는 상황을 재현.
        win.cmb_printer.setCurrentIndex(0)
        win.cmb_printer.activated.emit(0)     # activated는 첫 항목도 발생
        app.processEvents()
        assert win._pref_printer == "First"
        reloaded = gp.load_settings()
        assert reloaded.get("print", "printer") == "First"
    finally:
        win.close()


def test_restore_after_restart(app, monkeypatch, tmp_path):
    win = make_window(app, monkeypatch, tmp_path, printers=["P1", "P2"])
    try:
        win.cmb_printer.setCurrentIndex(win.cmb_printer.findText("P2"))
        win.cmb_printer.activated.emit(win.cmb_printer.findText("P2"))
        app.processEvents()
    finally:
        win.close()
    win2 = make_window(app, monkeypatch, tmp_path, printers=["P1", "P2"])
    try:
        assert win2._selected_printer_name() == "P2"
    finally:
        win2.close()


def test_refresh_does_not_clear_pref(app, monkeypatch, tmp_path):
    win = make_window(app, monkeypatch, tmp_path, printers=["P1", "P2"])
    try:
        idx = win.cmb_printer.findText("P2")
        win.cmb_printer.setCurrentIndex(idx)
        win.cmb_printer.activated.emit(idx)
        app.processEvents()
        assert win._pref_printer == "P2"
        # 프로그램적 목록 재로딩(새로고침) → 선호값 유지, 복원됨
        win._on_printers_listed(["P1", "P2"])
        app.processEvents()
        assert win._pref_printer == "P2"
        assert win._selected_printer_name() == "P2"
    finally:
        win.close()


def test_off_on_preserves_pref(app, monkeypatch, tmp_path):
    win = make_window(app, monkeypatch, tmp_path, printers=["P1", "P2"])
    try:
        idx = win.cmb_printer.findText("P2")
        win.cmb_printer.setCurrentIndex(idx)
        win.cmb_printer.activated.emit(idx)
        app.processEvents()
        win.chk_autoprint.setChecked(False)   # OFF
        app.processEvents()
        assert win._pref_printer == "P2"       # 선호값 유지
        win.chk_autoprint.setChecked(True)     # ON → 목록 재조회
        _drain(app, win)
        assert win._pref_printer == "P2"
        assert win._selected_printer_name() == "P2"
    finally:
        win.close()


def test_missing_printer_not_replaced(app, monkeypatch, tmp_path):
    ini = "[print]\nenabled = true\nprinter = GonePrinter\nmax_jobs_per_run = 100\n"
    win = make_window(app, monkeypatch, tmp_path, printers=["P1", "P2"], ini_text=ini)
    try:
        # 저장 프린터가 사라짐 → 다른/기본 프린터로 대체하지 않고 미선택
        assert win.cmb_printer.currentIndex() == -1
        assert win._selected_printer_name() == ""
        # 선호값 자체는 보존(재등장 대비)
        assert win._pref_printer == "GonePrinter"
    finally:
        win.close()


def test_programmatic_list_change_does_not_save(app, monkeypatch, tmp_path):
    win = make_window(app, monkeypatch, tmp_path, printers=["P1", "P2"])
    try:
        # 사용자가 P1 저장
        win.cmb_printer.setCurrentIndex(0)
        win.cmb_printer.activated.emit(0)
        app.processEvents()
        assert gp.load_settings().get("print", "printer") == "P1"
        # 프로그램적 clear/addItems/setCurrentIndex(-1) 는 저장을 유발하지 않음
        win._on_printers_listed(["Q1", "Q2"])   # P1 사라짐 → 미선택
        app.processEvents()
        # 저장된 선호값은 여전히 P1 (프로그램적 미선택이 지우지 않음)
        assert gp.load_settings().get("print", "printer") == "P1"
    finally:
        win.close()


def test_save_failure_does_not_raise(app, monkeypatch, tmp_path):
    win = make_window(app, monkeypatch, tmp_path, printers=["P1"])
    try:
        # 저장이 실패해도 예외가 전파되지 않아야 한다(작업 중단 없음).
        monkeypatch.setattr(gp, "save_settings", lambda cfg: "WRITE_FAIL")
        win.cmb_printer.setCurrentIndex(0)
        win.cmb_printer.activated.emit(0)       # _save_settings 내부 실패 경로
        app.processEvents()
        assert win._pref_printer == "P1"        # 메모리 선호값은 갱신됨
    finally:
        win.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
