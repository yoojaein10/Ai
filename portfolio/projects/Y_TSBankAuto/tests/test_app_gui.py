# -*- coding: utf-8 -*-
"""운영형 PyQt6 GUI 테스트 (지시 §3~5, §7, §16).

- 순수 함수(mask_request_row/badge_palette/row_status_style)는 Qt 없이 검증.
- 위젯/워커는 offscreen QApplication 으로 생성·검증(디스플레이 불필요).
- Qt 불가 환경은 skip.
"""
import os
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # 오프스크린 강제

import app_gui
import bank24_adapter
import bank24_credentials as bc
import security

try:
    from PyQt6.QtWidgets import QApplication, QWidget
    _QT_OK = True
except Exception:
    _QT_OK = False

_APP = None


def setUpModule():
    global _APP
    if _QT_OK:
        _APP = QApplication.instance() or QApplication([])


# ── bank24_login_flow 용 fake env 제공자(실 Bank24 미실행) ──
def _normal_login_env():
    """로그인창 발견→직접입력 성공→메인창 등장(done)까지 가는 합성 env."""
    from tests.test_bank24_login_flow import (
        FakeEnv, FakeStop, FakeCred, FakeWinAPI, _login_dialog, _main_window)
    dlg = _login_dialog(hwnd=100)
    main = _main_window(hwnd=500, title="BANK24")
    # windows() 호출 순서: 기존메인스캔[dlg]→snapshot[dlg]→poll[dlg]→wait_main[main]
    return FakeEnv(window_batches=[[dlg], [dlg], [dlg], [main]],
                   stop=FakeStop(), credential=FakeCred(),
                   winapi=FakeWinAPI(succeed_on_first=True))


def _submit_fail_login_env():
    """로그인창/신규창 없음 → 로그인 전송 실패(submit_failed) env."""
    from tests.test_bank24_login_flow import FakeEnv, FakeStop, FakeCred, FakeClock
    return FakeEnv(window_batches=[[]], stop=FakeStop(), credential=FakeCred(),
                   clock=FakeClock(step=40))   # 30초 폴링 즉시 소진


class TestPureHelpers(unittest.TestCase):
    def test_grid_agency_exclusion_is_exact(self):
        self.assertTrue(app_gui.is_excluded_grid_agency("  주택도시보증공사  "))
        self.assertTrue(app_gui.is_excluded_grid_agency(" HUG "))
        self.assertFalse(app_gui.is_excluded_grid_agency("주택도시보증공사 서울지사"))

    def test_excluded_grid_tokens_uses_exact_agency(self):
        rows = [
            bank24_adapter.RequestSummary("HUG", "주택도시보증공사"),
            bank24_adapter.RequestSummary("KB", "국민은행"),
            bank24_adapter.RequestSummary("HUG-BRANCH", "주택도시보증공사 서울지사"),
        ]
        self.assertEqual(app_gui.excluded_grid_tokens(rows), {"HUG"})

    def test_excluded_grid_tokens_uses_real_unicode_agency_not_token(self):
        rows = [
            bank24_adapter.RequestSummary(
                "202607020000250",
                "\uc8fc\ud0dd\ub3c4\uc2dc\ubcf4\uc99d\uacf5\uc0ac"),
            bank24_adapter.RequestSummary(
                "HUG-BRANCH",
                "\uc8fc\ud0dd\ub3c4\uc2dc\ubcf4\uc99d\uacf5\uc0ac \uc11c\uc6b8\uc9c0\uc0ac"),
        ]
        self.assertEqual(app_gui.excluded_grid_tokens(rows), {"202607020000250"})

    def test_badge_palette(self):
        self.assertEqual(app_gui.badge_palette("run")[2], "실행 중")
        self.assertEqual(app_gui.badge_palette("nope")[2], "대기")  # default wait

    def test_row_status_style(self):
        fg, bg = app_gui.row_status_style("실패")
        self.assertTrue(fg.startswith("#") and bg.startswith("#"))

    def test_mask_request_row(self):
        req = bank24_adapter.RequestSummary(
            request_token="TOK-1", bank_label="우리은행", branch_label="강남",
            masked_request_no='REDACTED_CONFIGURE_LOCALLY7890')
        row = app_gui.mask_request_row(req)
        self.assertEqual(row["token"], "TOK-1")
        self.assertEqual(row["status"], "처리 대기")
        self.assertNotEqual(row["req_no"], 'REDACTED_CONFIGURE_LOCALLY7890')
        self.assertIn("*", row["req_no"])


class TestWorkerSignals(unittest.TestCase):
    """QThread 워커의 run()을 직접 호출해 signal 페이로드(마스킹)를 검증."""

    def _collect(self, worker):
        got = {"requests": None, "status": [], "done": [], "log": []}
        worker.sig_requests.connect(lambda rows: got.update(requests=rows))
        worker.sig_status.connect(lambda s: got["status"].append(s))
        worker.sig_done.connect(lambda m: got["done"].append(m))
        worker.sig_log.connect(lambda l: got["log"].append(l))
        return got

    def test_grid_hug_is_excluded_before_pdf_download(self):
        import tempfile
        import config

        class Adapter:
            calls = []
            def download_pdf(self, token, root, timestamp):
                self.calls.append(token)
                return os.path.join(root, f"{token}.pdf")

        adapter = Adapter()
        rows, logs = [], []
        with tempfile.TemporaryDirectory() as root:
            worker = app_gui.Worker(
                "process", tokens=["HUG"], pdf_root=root, allowed_roots=[root])
            worker.sig_row.connect(lambda t, s: rows.append((t, s)))
            worker.sig_log.connect(lambda lines: logs.extend(lines))
            worker._save_with_adapter(
                adapter, ["HUG"], config.AppConfig(), excluded_tokens={"HUG"})
        self.assertEqual(adapter.calls, [])
        self.assertIn(("HUG", "저장 제외"), rows)
        self.assertTrue(any("EXCLUDED_HUG" in line for line in logs))

    def test_selected_process_passes_hug_exclusion_before_download(self):
        """선택 실행 재조회 경로에서도 HUG가 PDF 출력 전에 제외되어야 한다."""
        import config
        from types import SimpleNamespace

        class Adapter:
            def adopt_login_confirmed(self, main): pass
            def select_tabletop_menu(self): pass
            def query_requests(self):
                return [bank24_adapter.RequestSummary("HUG", "주택도시보증공사")]

        worker = app_gui.Worker(
            "process", tokens=["HUG"], adapter_provider=lambda: Adapter())
        with (mock.patch("config.load_app_config", return_value=config.AppConfig()),
              mock.patch("bank24_login_flow.run_bank24_login",
                         return_value=SimpleNamespace(status="done", main_win=object())),
              mock.patch.object(worker, "_save_with_adapter") as save):
            worker._run_process()
        self.assertEqual(save.call_args.kwargs["excluded_tokens"], {"HUG"})

    def test_query_emits_masked_requests(self):
        # 실 Bank24 대신 주입한 fake adapter + fake login env 로 조회 흐름 signal 만 검증(§57).
        # 로그인은 bank24_login_flow 이식본이 수행하고, 탁상/조회는 fake adapter 가 담당.
        from tests._fakes import FakeBank24Adapter
        w = app_gui.Worker("query", adapter_provider=lambda: FakeBank24Adapter(),
                           login_env_provider=_normal_login_env)
        got = self._collect(w)
        w.run()   # 동기 실행(이벤트 루프 불필요)
        self.assertIsNotNone(got["requests"])
        self.assertIn("token", got["requests"][0])
        self.assertEqual(got["done"], ["query"])
        # 상태 진행: 연결→로그인→조회→완료
        for s in ("conn", "login", "query", "done"):
            self.assertIn(s, got["status"])
        self.assertNotIn("PWD", repr(got["requests"]))

    def test_login_flow_emits_six_step_logs(self):   # §127 GUI 단계 로그
        from tests._fakes import FakeBank24Adapter
        w = app_gui.Worker("query", adapter_provider=lambda: FakeBank24Adapter(),
                           login_env_provider=_normal_login_env)
        got = self._collect(w)
        w.run()
        flat = [line for msg in got["log"] for line in msg]
        for step in ("Bank24 실행", "로그인창 확인", "자격증명 입력",
                     "메인 창 확인", "로그인 완료", "탁상 이동 중"):
            self.assertTrue(any(step in ln for ln in flat), f"missing step log: {step}")

    def test_tabletop_not_called_before_login_done(self):  # §134 로그인 성공 전 탁상 미호출
        from tests._fakes import FakeBank24Adapter
        fake = FakeBank24Adapter()
        # 로그인 전송 실패(new_wins 비어 fallback 없음) → done 아님 → 탁상 미호출
        w = app_gui.Worker("query", adapter_provider=lambda: fake,
                           login_env_provider=_submit_fail_login_env)
        got = self._collect(w)
        w.run()
        self.assertIn("block", got["status"])        # LOGIN_SUBMIT_FAILED
        self.assertFalse(fake.on_tabletop)           # 탁상 메뉴 미선택
        self.assertIsNone(got["requests"])           # 합성 결과 없음(§49)

    def test_emergency_stop_no_query(self):
        w = app_gui.Worker("query", adapter_provider=lambda: None)
        got = self._collect(w)
        w.request_stop()      # 실행 전 긴급 중지
        w.run()
        self.assertIn("stop", got["status"])
        self.assertIsNone(got["requests"])   # 중지 → 조회 단계 미실행

    def test_blocked_status_not_overwritten_by_err(self):
        # 실제 게이트 차단(_adapter)에서 blocked 가 err 로 덮이지 않는다(§60).
        # read_only=false 로 백엔드/Bank24 실행에 도달하기 전에 차단시킨다(실 Bank24 미실행).
        import os
        import tempfile
        fd, p = tempfile.mkstemp(suffix=".ini")
        os.close(fd)
        with open(p, "w", encoding="utf-8") as f:
            f.write("[options]\nread_only = false\n")
        self.addCleanup(os.remove, p)
        w = app_gui.Worker("query", settings_path=p)
        got = self._collect(w)
        w.run()
        self.assertIn("block", got["status"])
        self.assertNotIn("err", got["status"])       # §60
        self.assertIsNone(got["requests"])           # 합성 결과 없음(§53)

    def test_no_fake_fallback_on_block(self):
        # 게이트 차단(adapter_provider 가 AutomationBlocked) 시 fake 결과 없음(§49).
        import bank24_automation

        def _blocked():
            raise bank24_automation.AutomationBlocked("REAL_BLOCKED")
        w = app_gui.Worker("query", adapter_provider=_blocked)
        got = self._collect(w)
        w.run()
        self.assertIsNone(got["requests"])   # 합성 결과 미표시(§53)
        self.assertIn("block", got["status"])   # 안전코드 → block, 일반 err 아님(§60)


    def test_save_continues_after_one_row_fails(self):
        """각 행을 독립 저장하여 앞 행 실패가 다음 행 commit을 막지 않는다."""
        import tempfile
        import config
        import tabletop_save

        class Adapter:
            def download_pdf(self, token, root, timestamp):
                return os.path.join(root, f"{token}.pdf")

        with tempfile.TemporaryDirectory() as root:
            worker = app_gui.Worker(
                "process", tokens=["ROW-1", "ROW-2"], pdf_root=root,
                allowed_roots=[root])
            rows, logs, progress = [], [], []
            worker.sig_row.connect(lambda token, status: rows.append((token, status)))
            worker.sig_log.connect(lambda lines: logs.extend(lines))
            worker.sig_progress.connect(lambda current, total: progress.append((current, total)))
            effects = [tabletop_save.SaveError("SYNTHETIC_ROW_FAILURE"),
                       tabletop_save.SaveResult(1, [])]
            with mock.patch("tabletop_save.save_pdf_batch", side_effect=effects) as save:
                worker._save_with_adapter(Adapter(), ["ROW-1", "ROW-2"], config.AppConfig())

        self.assertEqual(save.call_count, 2)
        self.assertIn(("ROW-1", "실패"), rows)
        self.assertIn(("ROW-2", "저장 완료"), rows)
        self.assertEqual(progress[-1], (2, 2))
        self.assertTrue(any(
            "성공 1건 / 실패 1건 / 저장 제외 0건" in line for line in logs))

    def _run_batch(self, effects, tokens):
        """save_pdf_batch 결과를 주입해 _save_with_adapter 배치 집계를 관찰."""
        import tempfile
        import config
        import tabletop_save

        class Adapter:
            def download_pdf(self, token, root, timestamp):
                return os.path.join(root, f"{token}.pdf")

        rows, logs, progress = [], [], []
        with tempfile.TemporaryDirectory() as root:
            worker = app_gui.Worker(
                "process", tokens=tokens, pdf_root=root, allowed_roots=[root])
            worker.sig_row.connect(lambda t, s: rows.append((t, s)))
            worker.sig_log.connect(lambda lines: logs.extend(lines))
            worker.sig_progress.connect(lambda c, t: progress.append((c, t)))
            raised = None
            with mock.patch("tabletop_save.save_pdf_batch", side_effect=effects):
                try:
                    worker._save_with_adapter(Adapter(), tokens, config.AppConfig())
                except tabletop_save.SaveError as exc:
                    raised = exc.code
        return rows, logs, progress, raised

    def test_all_excluded_batch_no_all_rows_failed(self):
        # (h) 전체 제외 배치 → ALL_ROWS_FAILED 없음, 정상 종료.
        import parsers
        effects = [parsers.ExcludedRequest(), parsers.ExcludedRequest()]
        rows, logs, progress, raised = self._run_batch(effects, ["R1", "R2"])
        self.assertIsNone(raised)
        self.assertIn(("R1", "저장 제외"), rows)
        self.assertIn(("R2", "저장 제외"), rows)
        self.assertEqual(progress[-1], (2, 2))   # 제외도 진행률 전체에 포함(§13)
        self.assertTrue(any(
            "성공 0건 / 실패 0건 / 저장 제외 2건" in line for line in logs))

    def test_mixed_success_fail_exclude_counts(self):
        # (i) 성공·실패·제외 혼합 → 각 카운트 정확, 정상 종료.
        import parsers
        import tabletop_save
        effects = [
            tabletop_save.SaveResult(1, []),        # R1 성공
            tabletop_save.SaveError("BOOM"),         # R2 실패
            parsers.ExcludedRequest(),               # R3 제외
        ]
        rows, logs, progress, raised = self._run_batch(effects, ["R1", "R2", "R3"])
        self.assertIsNone(raised)                    # 성공 존재 → ALL_ROWS_FAILED 아님
        self.assertIn(("R1", "저장 완료"), rows)
        self.assertIn(("R2", "실패"), rows)
        self.assertIn(("R3", "저장 제외"), rows)
        self.assertTrue(any(
            "성공 1건 / 실패 1건 / 저장 제외 1건" in line for line in logs))
        # 제외 로그에는 안전코드와 행 번호만(§17).
        self.assertTrue(any(
            "저장 제외(안전코드: EXCLUDED_HUG)" in line for line in logs))

    def _run_excluded_pdf(self, code):
        """제외 코드별로 다운로드된 PDF 잔존 여부를 관찰."""
        import tempfile
        import config
        import parsers
        import tabletop_save

        class Adapter:
            def download_pdf(self, token, root, timestamp):
                path = os.path.join(root, f"{token}.pdf")
                with open(path, "wb") as f:
                    f.write(b"%PDF-1.4 synthetic")
                return path

        with tempfile.TemporaryDirectory() as root:
            worker = app_gui.Worker(
                "process", tokens=["R1"], pdf_root=root, allowed_roots=[root])
            with mock.patch("tabletop_save.save_pdf_batch",
                            side_effect=parsers.ExcludedRequest(code)):
                worker._save_with_adapter(Adapter(), ["R1"], config.AppConfig())
            return os.path.exists(os.path.join(root, "R1.pdf"))

    def test_excluded_no_bank_no_branch_manager_delete_pdf(self):
        # 2026-07-28: 은행명/지점명 미상·담당자 제외 건은 PDF 를 남기지 않는다.
        for code in ("EXCLUDED_NO_BANK", "EXCLUDED_NO_BRANCH", "EXCLUDED_MANAGER"):
            self.assertFalse(self._run_excluded_pdf(code), code)

    def test_excluded_hug_keeps_pdf(self):
        # HUG 제외는 기존 동작 유지(PDF 잔존 — 삭제 대상 아님).
        self.assertTrue(self._run_excluded_pdf("EXCLUDED_HUG"))

    def test_bankonline_called_after_db_success_only(self):
        import tempfile
        import config
        import tabletop_save

        class Adapter:
            def download_pdf(self, token, root, timestamp):
                return os.path.join(root, f"{token}.pdf")

        app = config.AppConfig()
        app.bankonline = config.BankOnline(
            enabled=True,
            endpoint="https://example.invalid",
            authorization="token",
        )
        calls = []
        logs = []
        effects = [
            tabletop_save.SaveResult(1, [{
                "RequestNo": "T260704561",
                "NewMasterID": "01-20260709-001",
                "Bank": "우리은행",
            }]),
            tabletop_save.SaveError("BOOM"),
        ]
        with tempfile.TemporaryDirectory() as root:
            worker = app_gui.Worker(
                "process", tokens=["R1", "R2"], pdf_root=root, allowed_roots=[root])
            worker.sig_log.connect(lambda lines: logs.extend(lines))
            with (mock.patch("tabletop_save.save_pdf_batch", side_effect=effects),
                  mock.patch("bankonline_ts.call",
                             side_effect=lambda output, cfg, **kw: calls.append(output) or ("Y", ""))):
                worker._save_with_adapter(Adapter(), ["R1", "R2"], app)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["NewMasterID"], "01-20260709-001")
        self.assertTrue(any("BankOnline" in line for line in logs))


def _skip_if_no_qt():
    if not _QT_OK or _APP is None:
        raise unittest.SkipTest("PyQt6 사용 불가")


class TestWindow(unittest.TestCase):
    def setUp(self):
        _skip_if_no_qt()
        self.win = app_gui.build_window(real_allowed=False, mode_label="fake(테스트)")

    def tearDown(self):
        if getattr(self, "win", None) is not None:
            self.win.close()
            self.win.deleteLater()

    def test_core_widgets_exist(self):
        self.assertTrue(hasattr(self.win, "table"))
        self.assertTrue(hasattr(self.win, "badge"))
        self.assertTrue(hasattr(self.win, "progress"))
        self.assertEqual(self.win.table.columnCount(), len(app_gui.TABLE_COLS))

    def test_db_button_permanently_disabled(self):
        self.assertFalse(self.win.btn_db.isEnabled())

    def test_banner_present(self):
        self.assertIn("전체 처리", app_gui.TEST_BANNER)

    def test_geometry_matches_reference(self):
        # Y_BankAuto 기준 최소 창 크기
        self.assertEqual(self.win.minimumWidth(), 1024)
        self.assertEqual(self.win.minimumHeight(), 720)
        self.win.resize(1024, 720)
        self.win.show()
        _APP.processEvents()
        self.assertEqual(self.win.centralWidget().size().height(), 720)
        self.assertGreaterEqual(self.win.table.height(), 250)
        self.assertEqual(self.win.log_edit.parentWidget().height(), 150)
        self.assertFalse(self.win.btn_start.geometry().intersects(self.win.btn_stop.geometry()))

    def test_reset_clears_table(self):
        self.win.table.insertRow(0)
        self.win.on_reset()
        self.assertEqual(self.win.table.rowCount(), 0)

    def test_requests_populate_table_masked(self):
        rows = [{"token": "T1", "bank": "우리은행", "branch": "강남",
                 "req_no": "12****89", "status": "처리 대기"}]
        self.win._on_requests(rows)
        self.assertEqual(self.win.table.rowCount(), 1)
        self.assertEqual(self.win.table.item(0, 0).text(), "12****89")
        self.assertEqual(self.win.table.item(0, 2).text(), "우리은행")

    def test_stop_sets_badge(self):
        self.win.on_stop()
        self.assertEqual(self.win.badge._text.text(), "중단됨")

    def test_reference_default_surface(self):
        self.assertEqual(app_gui.APP_TITLE, "Bank24 탁상 데이터 추출기")
        self.assertEqual(app_gui.TABLE_COLS,
                         ["의뢰번호", "감정서번호", "은행", "BankOnline_In", "처리 결과"])
        self.assertFalse(self.win.edit_confirm.isVisible())
        self.assertFalse(self.win.btn_db.isVisible())

    # ── "즉시 1회 실행"(btn_primary) 표시 검증 (지시 §13) ──
    def test_primary_button_label_enabled_no_inline(self):
        btn = self.win.btn_start
        self.assertEqual(btn.objectName(), "btn_primary")
        self.assertTrue(btn.isEnabled())
        self.assertEqual(btn.text(), "▶  즉시 1회 실행")
        # 버튼에 인라인 스타일이 없어야 전역 규칙이 그대로 적용된다.
        self.assertEqual(btn.styleSheet(), "")

    def test_primary_button_global_rules_present(self):
        ss = self.win.styleSheet()
        self.assertIn("QPushButton#btn_primary", ss)
        self.assertIn(app_gui.C["green"], ss)   # 초록 배경
        self.assertIn("#ffffff", ss)            # 흰 글씨
        # panelBody 투명 규칙은 전역 STYLESHEET 에 있어야 한다.
        self.assertIn("QWidget#panelBody", ss)
        self.assertIn("transparent", ss)

    def test_panel_body_has_no_inline_stylesheet(self):
        # _panel() 은 더 이상 body 에 로컬 setStyleSheet 를 호출하지 않는다.
        _outer, bv = self.win._panel("검증")
        body = bv.parentWidget()
        self.assertEqual(body.objectName(), "panelBody")
        self.assertEqual(body.styleSheet(), "")

    def test_primary_button_renders_green_with_white_text(self):
        from PyQt6.QtGui import QColor
        btn = self.win.btn_start
        btn.resize(180, 42)
        btn.ensurePolished()
        self.win.show()
        _APP.processEvents()
        img = btn.grab().toImage()
        w, h = img.width(), img.height()
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        green = QColor(app_gui.C["green"])
        green_hits = white_hits = 0
        for y in range(0, h, 3):
            for x in range(0, w, 3):
                c = img.pixelColor(x, y)
                if (abs(c.red() - green.red()) < 40 and
                        abs(c.green() - green.green()) < 40 and
                        abs(c.blue() - green.blue()) < 40):
                    green_hits += 1
                if c.red() > 220 and c.green() > 220 and c.blue() > 220:
                    white_hits += 1
        # 배경 다수가 초록이어야 하고, 흰색 글자 픽셀이 존재해야 한다.
        self.assertGreater(green_hits, 0, "초록 배경 픽셀 없음")
        self.assertGreater(green_hits, white_hits, "초록 배경이 지배적이지 않음")
        self.assertGreater(white_hits, 0, "흰색 글자 픽셀 없음")

    def test_secret_inputs_block_paste_and_are_cleared(self):
        self.win.edit_pw.setText("not-a-real-password")
        self.win.edit_confirm.setText("not-a-real-confirmation")
        self.win.on_stop()
        self.assertEqual(self.win.edit_pw.text(), "")
        self.assertEqual(self.win.edit_confirm.text(), "")
        self.assertEqual(self.win.edit_pw.contextMenuPolicy(),
                         app_gui.Qt.ContextMenuPolicy.NoContextMenu)

    def test_credential_method_is_ini_only(self):
        self.win.edit_id.setText("test-user")
        self.win.edit_pw.setText("test-pass")
        with mock.patch.object(bc, "load_credentials", side_effect=bc.CredentialError) as load:
            with self.assertRaises(bc.CredentialError):
                self.win._load_selected_credentials()
            load.assert_called_once()
            self.assertEqual(load.call_args.args[0], bc.METHOD_INI)
            self.assertEqual(load.call_args.kwargs["ini_username"], "test-user")
            self.assertEqual(load.call_args.kwargs["ini_password"], "test-pass")

    def test_real_adapter_remains_fail_closed(self):
        with self.assertRaises(Exception):
            bank24_adapter.RealBank24Adapter(bank24_adapter.RealAdapterContext()).launch_or_attach()

    def test_app_gui_secret_scan_has_no_values(self):
        text = Path(app_gui.__file__).read_text(encoding="utf-8")
        findings = [item for item in security.scan_text_for_secrets(text) if item["is_value"]]
        self.assertEqual(findings, [])

    # ---- TS 전용 기능의 명확한 접근 경로(컨텍스트 메뉴/대화상자) ----
    def test_ts_features_have_menu_access(self):
        menu = self.win._build_table_menu()
        labels = [a.text() for a in menu.actions() if a.text()]
        for expected in ("전체 선택", "선택 처리 시작", "실패 재처리", "결과 초기화",
                         "SP 파라미터 미리보기…", "실제 자동화 설정…"):
            self.assertIn(expected, labels)
        db = [a for a in menu.actions() if "DB 저장" in a.text()]
        self.assertTrue(db and db[0].isEnabled())

    def test_menu_actions_execute(self):
        rows = [{"token": "T1", "bank": "우리은행", "branch": "강남",
                 "req_no": "12****89", "status": "처리 대기"}]
        self.win._on_requests(rows)
        menu = self.win._build_table_menu()
        acts = {a.text(): a for a in menu.actions() if a.text()}
        acts["전체 선택"].trigger()
        self.assertTrue(self.win._selected_tokens())
        acts["결과 초기화"].trigger()
        self.assertEqual(self.win.table.rowCount(), 0)

    def test_sp_preview_has_no_execute_path(self):
        import sp_preview
        lines = self.win._sp_preview_lines()
        blob = "\n".join(lines)
        self.assertIn("실행", blob)   # '실행 없음/차단' 안내 포함
        self.assertFalse(sp_preview.build_preview(None)["execute_enabled"])

    def test_no_overlap_and_geometry_both_sizes(self):
        for w, h in ((1024, 720), (1100, 720)):
            self.win.resize(w, h)
            self.win.show()
            _APP.processEvents()
            left = self.win.findChild(QWidget, "leftCol")
            self.assertEqual(left.width(), 330)                       # 좌측 고정폭
            self.assertEqual(self.win.log_edit.parentWidget().height(), 150)  # 로그 150
            self.assertEqual(self.win.centralWidget().height(), 720)  # 콘텐츠 geometry 불변
            # 버튼 겹침 없음, 테이블 정상 높이
            self.assertFalse(
                self.win.btn_start.geometry().intersects(self.win.btn_stop.geometry()))
            self.assertGreaterEqual(self.win.table.height(), 200)

    def test_construction_has_no_filesystem_side_effect(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ghost = os.path.join(td, "no_such_pdf_root")
            w = app_gui.build_window(real_allowed=False, pdf_root=ghost)
            try:
                self.assertFalse(os.path.exists(ghost))   # 구성 시 디렉터리 미생성
            finally:
                w.close()
                w.deleteLater()

    def test_run_log_is_written_to_pdf_folder_and_sanitized(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            self.win.pdf_root = td
            self.win._open_run_log()
            self.win._log('연락처 010-0000-0000')
            self.win._close_run_log()
            logs = list(Path(td).glob("run_*.log"))
            self.assertEqual(len(logs), 1)
            text = logs[0].read_text(encoding="utf-8")
            self.assertIn("[phone]", text)
            self.assertNotIn('010-0000-0000', text)


if __name__ == "__main__":
    unittest.main()
