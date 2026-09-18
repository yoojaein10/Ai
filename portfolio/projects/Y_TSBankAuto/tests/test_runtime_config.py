# -*- coding: utf-8 -*-
"""settings.ini 비민감 설정의 GUI 런타임 연결 격리 테스트 (지시 §35~39).

- 실제 C:\\Bank24Extractor\\settings.ini 는 읽거나 변경하지 않는다.
  settings_integrity.ensure_settings_file / check_settings 와 _pdf_paths 는 모두
  더미(temp) 값으로 monkeypatch 한다.
- 외부 연결(DB/Bank24/네트워크) 및 사용자 지정 디렉터리 생성이 없음을 확인한다.
"""
import os
import tempfile
import unittest
from unittest import mock

import app_gui
import config
import settings_integrity as si


def _fake_integrity(real_allowed=True, reasons=None):
    return si.IntegrityResult(real_allowed, list(reasons or []))


def _cfg(pdf_root="", servers=(), databases=(), db_server="",
         bank24_ready=True, read_only=True):
    c = config.AppConfig()
    c.paths = config.Paths(pdf_root=pdf_root)
    c.allowlist = config.Allowlist(servers=tuple(servers), databases=tuple(databases))
    c.db = config.DbConfig(server=db_server)
    c.options = config.Options(read_only=read_only)
    if bank24_ready:
        c.bank24 = config.Bank24(
            exe_path=r"C:\KADC\X11\Bank24.exe", main_window_class="TfrmMain")
    return c


class TestValidatePdfRoot(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="yts_rt_")
        self.approved = os.path.join(self.root, "Y_TSBankAuto")
        os.makedirs(self.approved, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def test_inside_approved_ok(self):
        cand = os.path.join(self.approved, "pdf_custom")
        got = app_gui._validate_pdf_root(cand, self.approved)
        self.assertEqual(got, os.path.normpath(os.path.abspath(cand)))
        # 검증만으로 디렉터리를 만들지 않는다.
        self.assertFalse(os.path.exists(cand))

    def test_outside_approved_rejected(self):
        outside = os.path.join(self.root, "elsewhere", "pdf")
        self.assertIsNone(app_gui._validate_pdf_root(outside, self.approved))

    def test_parent_ref_rejected(self):
        self.assertIsNone(
            app_gui._validate_pdf_root(self.approved + r"\..\evil", self.approved))

    def test_relative_rejected(self):
        self.assertIsNone(app_gui._validate_pdf_root(r"pdf\sub", self.approved))

    def test_env_and_home_tokens_rejected(self):
        self.assertIsNone(app_gui._validate_pdf_root(r"%LOCALAPPDATA%\x", self.approved))
        self.assertIsNone(app_gui._validate_pdf_root(r"$HOME/x", self.approved))
        self.assertIsNone(app_gui._validate_pdf_root(r"~\x", self.approved))

    def test_unc_rejected(self):
        self.assertIsNone(
            app_gui._validate_pdf_root(r"\\server\share\pdf", self.approved))

    def test_other_drive_rejected(self):
        approved_c = 'C:\\Users\\PUBLIC_USER\\AppData\\Local\\Y_TSBankAuto'
        self.assertIsNone(app_gui._validate_pdf_root(r"D:\pdf", approved_c))

    def test_empty_rejected(self):
        self.assertIsNone(app_gui._validate_pdf_root("", self.approved))

    def test_reparse_ancestor_rejected(self):
        # 승인 루트 자체를 reparse 로 보이게 하여 거부되는지 확인(실제 링크 생성 없이 patch).
        cand = os.path.join(self.approved, "pdf")
        with mock.patch.object(si, "_path_has_reparse", return_value=True):
            self.assertIsNone(app_gui._validate_pdf_root(cand, self.approved))


class TestResolveRuntime(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="yts_rt2_")
        self.approved = os.path.join(self.root, "Y_TSBankAuto")
        self.default_pdf = os.path.join(self.approved, "pdf")
        os.makedirs(self.approved, exist_ok=True)
        self.ini = os.path.join(self.approved, "settings.ini")   # 더미 경로(실제 파일 아님)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def _patches(self, app_config, integrity=None, load_raises=False):
        integrity = integrity or _fake_integrity(True)
        load = (mock.Mock(side_effect=RuntimeError("parse"))
                if load_raises else mock.Mock(return_value=app_config))
        return (
            mock.patch.object(si, "ensure_settings_file", return_value=(False, "exists")),
            mock.patch.object(si, "check_settings", return_value=(integrity, self.ini)),
            mock.patch.object(config, "load_app_config", load),
            mock.patch.object(app_gui, "_pdf_paths",
                              return_value=(self.approved, self.default_pdf)),
            load,
        )

    def _run(self, **kw):
        p_ensure, p_check, p_load, p_paths, load = self._patches(**kw)
        with p_ensure, p_check, p_load, p_paths:
            rc = app_gui._resolve_runtime()
        return rc, load

    def test_load_called_once_with_resolved_path(self):
        rc, load = self._run(app_config=_cfg())
        self.assertEqual(load.call_count, 1)
        load.assert_called_once_with(self.ini)
        self.assertIs(rc.app_config, load.return_value)

    def test_empty_pdf_root_uses_default(self):
        rc, _ = self._run(app_config=_cfg(pdf_root=""))
        self.assertEqual(rc.pdf_root, self.default_pdf)
        self.assertFalse(rc.pdf_root_from_ini)
        self.assertTrue(rc.real_allowed)   # 안전 기본값은 real 을 막지 않는다(다른 게이트 통과 시)

    def test_ini_pdf_root_ignored_for_fixed_operating_share(self):
        cand = os.path.join(self.approved, "pdf_alt")
        rc, _ = self._run(app_config=_cfg(pdf_root=cand))
        self.assertEqual(rc.pdf_root, self.default_pdf)
        self.assertFalse(rc.pdf_root_from_ini)
        self.assertFalse(os.path.exists(cand))   # 로드 중 디렉터리 미생성

    def test_ini_pdf_root_does_not_override_fixed_operating_share(self):
        outside = os.path.join(self.root, "outside", "pdf")
        rc, _ = self._run(app_config=_cfg(pdf_root=outside))
        self.assertEqual(rc.pdf_root, self.default_pdf)   # 안전 기본값 폴백
        self.assertFalse(rc.pdf_root_from_ini)
        self.assertTrue(rc.real_allowed)

    def test_parse_failure_falls_back_blocks_real(self):
        rc, _ = self._run(app_config=_cfg(), load_raises=True)
        self.assertIsInstance(rc.app_config, config.AppConfig)   # 안전 기본값
        self.assertFalse(rc.real_allowed)
        self.assertEqual(rc.mode_label, "차단됨(설정 필요)")

    def test_ini_acl_does_not_block_real(self):
        # INI ACL 무결성으로 real 을 막지 않는다(§4)
        rc, _ = self._run(app_config=_cfg(), integrity=_fake_integrity(False))
        self.assertTrue(rc.real_allowed)

    def test_no_bank24_section_still_real(self):
        # [bank24] 섹션 없이도(필수 키 없음) real 허용(§2/§3)
        rc, _ = self._run(app_config=_cfg(bank24_ready=False))
        self.assertTrue(rc.real_allowed)

    def test_read_only_false_blocks_real(self):
        rc, _ = self._run(app_config=_cfg(read_only=False))      # §42
        self.assertFalse(rc.real_allowed)

    def test_ini_allowlist_and_db_do_not_affect_real_gate(self):
        # INI 의 allowlist/db 대상이 real 게이팅을 확장·우회하지 못한다:
        # 같은 무결성/스위치 조건에서 allowlist 유무와 무관하게 결과가 동일해야 한다.
        rc_empty, _ = self._run(app_config=_cfg(servers=(), databases=(), db_server=""))
        rc_full, _ = self._run(app_config=_cfg(
            servers=('192.0.2.10', "evil"), databases=("x",), db_server='192.0.2.10'))
        self.assertEqual(rc_empty.real_allowed, rc_full.real_allowed)
        # rc 는 병합된 권위 allowlist 를 만들지 않는다(그대로 app_config 만 보관).
        self.assertFalse(hasattr(rc_full, "allowlist"))


class TestWindowWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
            cls.app = QApplication.instance() or QApplication([])
            cls.ok = True
        except Exception:
            cls.ok = False

    def test_app_config_passed_to_window(self):
        if not self.ok:
            self.skipTest("Qt 불가")
        cfg = _cfg(pdf_root="")
        win = app_gui.build_window(real_allowed=False, mode_label="fake(테스트)",
                                   app_config=cfg)
        try:
            self.assertIs(win.app_config, cfg)
        finally:
            win.close(); win.deleteLater()

    def test_login_ini_settings_populate_gui(self):
        if not self.ok:
            self.skipTest("Qt 불가")
        cfg = _cfg()
        cfg.login = config.Login(save_credentials=True, bank24_id="test-user",
                                  bank24_pw="test-pass")
        win = app_gui.build_window(real_allowed=False, mode_label="fake(테스트)",
                                   app_config=cfg)
        try:
            self.assertEqual(win.edit_id.text(), "test-user")
            self.assertTrue(win.chk_save_cred.isChecked())
            self.assertEqual(win.edit_pw.text(), "test-pass")
        finally:
            win.close(); win.deleteLater()


class TestCredentialKeysScoped(unittest.TestCase):
    def test_only_supported_database_credentials_are_loaded(self):
        root = tempfile.mkdtemp(prefix="yts_cred_")
        try:
            ini = os.path.join(root, "settings.ini")
            with open(ini, "w", encoding="utf-8") as f:
                f.write(
                    "[database]\nserver =\nbank24_id = secretID\n"
                    "password = secretPW\napi_key = KEY123\n"
                    "[bank24]\nid = u\npw = p\n")
            app = config.load_app_config(ini)
            # DB 저장용 password만 지원하며 repr에는 노출하지 않는다.
            self.assertEqual(app.db.password, "secretPW")
            self.assertFalse(hasattr(app.db, "bank24_id"))
            self.assertFalse(hasattr(app.db, "api_key"))
            # 잘못된 섹션의 자격증명 값은 AppConfig에 실리지 않는다.
            self.assertNotIn("secretPW", repr(app))
            self.assertNotIn("secretID", repr(app))
            self.assertNotIn("KEY123", repr(app))
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
