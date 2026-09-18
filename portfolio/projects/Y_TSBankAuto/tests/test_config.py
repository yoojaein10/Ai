# -*- coding: utf-8 -*-
"""설정/시크릿 fail-closed 테스트 (fake provider 만 사용)."""
import os
import tempfile
import unittest

import config


class FakeSecretProvider(config.SecretProvider):
    def __init__(self, store):
        self._store = store

    def get_secret(self, name):
        return self._store.get(name)


class TestBank24Options(unittest.TestCase):
    """[bank24]/[options] 파싱·필수값 검사 (지시 §8/§58). 값은 로그로 남기지 않는다."""

    def _write(self, text):
        fd, p = tempfile.mkstemp(suffix=".ini")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.remove, p)
        return p

    def test_bank24_uses_code_constants_not_ini(self):
        # INI [bank24] 가 있어도 무시하고 코드 상수를 쓴다(§1/§13)
        p = self._write(
            "[options]\nsource_tab = 탁상\n"
            "[bank24]\nexe_path = C:\\evil\\other.exe\nmain_window_class = Evil\n")
        app = config.load_app_config(p)
        self.assertEqual(app.bank24.exe_path, config.BANK24_EXE_PATH)
        self.assertEqual(app.bank24.main_window_class, config.BANK24_MAIN_WINDOW_CLASS)
        self.assertEqual(app.options.source_tab, "\ubbf8\uc811\uc218")

    def test_no_bank24_section_no_missing_keys(self):
        # [bank24] 섹션이 없어도 MISSING_KEYS 없음(§2/§3)
        p = self._write("[login]\nsave_credentials = false\n")
        app = config.load_app_config(p)
        self.assertEqual(config.missing_bank24_keys(app), [])
        self.assertEqual(config.REQUIRED_BANK24_KEYS, ())

    def test_load_does_not_modify_ini(self):
        # 설정 로드가 INI 를 생성·수정·병합하지 않는다(§11)
        p = self._write("[login]\nsave_credentials = true\nbank24_id = u\n"
                        "[bank24]\nexe_path = C:\\evil\\other.exe\n")
        before = open(p, encoding="utf-8").read()
        config.load_app_config(p)
        self.assertEqual(open(p, encoding="utf-8").read(), before)

    def test_login_still_read_from_ini(self):
        # [login] 의 save_credentials/id/pw 는 여전히 INI 에서 읽는다(§10)
        p = self._write('[login]\nsave_credentials = true\nbank24_id = uid1\nREDACTED_CONFIGURE_LOCALLY = pw1\n')
        app = config.load_app_config(p)
        self.assertTrue(app.login.save_credentials)
        self.assertEqual(app.login.bank24_id, "uid1")

    def test_defaults_when_section_absent(self):
        p = self._write("[login]\nsave_credentials = false\n")
        app = config.load_app_config(p)
        self.assertEqual(app.options.source_tab, "\ubbf8\uc811\uc218")   # 기본
        self.assertEqual(set(config.missing_bank24_keys(app)),
                         set(config.REQUIRED_BANK24_KEYS))


class TestSecrets(unittest.TestCase):
    def test_fail_closed_no_secrets(self):
        p = FakeSecretProvider({})
        with self.assertRaises(config.ConfigError):
            config.require_db_credentials(p)

    def test_fail_closed_empty_password(self):
        p = FakeSecretProvider({config.ENV_DB_USER: "u", config.ENV_DB_PASSWORD: ""})
        with self.assertRaises(config.ConfigError):
            config.require_db_credentials(p)

    def test_ok_with_fake_secrets(self):
        p = FakeSecretProvider({config.ENV_DB_USER: "u", config.ENV_DB_PASSWORD: "pw"})
        user, pwd = config.require_db_credentials(p)
        self.assertEqual((user, pwd), ("u", "pw"))

    def test_dbconfig_password_is_not_repr_exposed(self):
        db = config.DbConfig()
        db.password = "SYNTH_SECRET"
        self.assertNotIn("SYNTH_SECRET", repr(db))
        self.assertNotIn("PWD", db.odbc_parts_nonsecret())
        self.assertNotIn("UID", db.odbc_parts_nonsecret())


class TestCommitEnv(unittest.TestCase):
    def test_magic_required(self):
        old = os.environ.get(config.ENV_ALLOW_COMMIT)
        try:
            os.environ.pop(config.ENV_ALLOW_COMMIT, None)
            self.assertFalse(config.commit_env_ok())
            os.environ[config.ENV_ALLOW_COMMIT] = "true"
            self.assertFalse(config.commit_env_ok())
            os.environ[config.ENV_ALLOW_COMMIT] = config.COMMIT_MAGIC
            self.assertTrue(config.commit_env_ok())
        finally:
            if old is None:
                os.environ.pop(config.ENV_ALLOW_COMMIT, None)
            else:
                os.environ[config.ENV_ALLOW_COMMIT] = old


class TestLoadIniExample(unittest.TestCase):
    def test_load_example(self):
        ex = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "settings.ini.example")
        app = config.load_app_config(ex)
        self.assertEqual(app.office, "10")
        self.assertEqual(app.app_code, "300611")
        self.assertTrue(app.safety.rollback_test)       # 기본 안전값
        self.assertFalse(app.safety.allow_commit)
        self.assertEqual(app.db.encrypt, "yes")
        self.assertEqual(app.db.trust_server_certificate, "false")

    def test_load_login_ui_settings_without_password(self):
        fd, path = tempfile.mkstemp(suffix=".ini")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("[login]\nsave_credentials = true\n"
                        'bank24_id = test-user\nREDACTED_CONFIGURE_LOCALLY = test-pass\n')
            app = config.load_app_config(path)
            self.assertTrue(app.login.save_credentials)
            self.assertEqual(app.login.bank24_id, "test-user")
            self.assertEqual(app.login.bank24_pw, "test-pass")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
