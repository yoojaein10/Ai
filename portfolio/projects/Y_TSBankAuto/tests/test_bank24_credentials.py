# -*- coding: utf-8 -*-
"""Bank24 자격증명 헬퍼 테스트 (지시 §9, §16)."""
import unittest

import bank24_credentials as bc


class TestIsolation(unittest.TestCase):
    def test_dedicated_service_and_keys(self):
        # 이 프로젝트 전용 service. 참조 프로젝트 이름을 쓰지 않는다.
        self.assertEqual(bc.KEYRING_SERVICE, "Y_TSBankAuto/Bank24")
        self.assertNotIn("BankAuto\\", bc.KEYRING_SERVICE)
        self.assertNotIn("Y_BankAuto", bc.KEYRING_SERVICE)
        self.assertTrue(bc.KEY_USERNAME and bc.KEY_PASSWORD)


class TestEnvMethod(unittest.TestCase):
    def test_env_loads(self):
        env = {bc.ENV_USERNAME: "u1", bc.ENV_PASSWORD: "p1"}
        c = bc.load_credentials(bc.METHOD_ENV, environ=env)
        self.assertEqual(c.username, "u1")
        self.assertEqual(c.use_password(), "p1")
        c.wipe()

    def test_missing_id_fail_closed(self):
        with self.assertRaises(bc.CredentialError):
            bc.load_credentials(bc.METHOD_ENV, environ={bc.ENV_PASSWORD: "p"})

    def test_missing_pw_fail_closed(self):
        with self.assertRaises(bc.CredentialError):
            bc.load_credentials(bc.METHOD_ENV, environ={bc.ENV_USERNAME: "u"})

    def test_empty_pw_rejected(self):
        with self.assertRaises(bc.CredentialError):
            bc.load_credentials(bc.METHOD_ENV,
                                environ={bc.ENV_USERNAME: "u", bc.ENV_PASSWORD: ""})

    def test_no_auto_fallback(self):
        # env 방식 선택 시 keyring 을 보지 않는다: env 비면 실패해야 한다.
        with self.assertRaises(bc.CredentialError):
            bc.load_credentials(bc.METHOD_ENV, environ={})

    def test_unknown_method(self):
        with self.assertRaises(bc.CredentialError):
            bc.load_credentials("magic", environ={})


class TestCredentialObject(unittest.TestCase):
    def test_repr_masks(self):
        c = bc.Credential("secretuser", "secretpw")
        self.assertNotIn("secret", repr(c))
        self.assertNotIn("secret", str(c))
        c.wipe()

    def test_wipe_clears(self):
        c = bc.Credential("u", "pw")
        c.wipe()
        self.assertEqual(len(c.password_bytes()), 0)
        self.assertEqual(c.username, "")

    def test_present_helper(self):
        self.assertTrue(bc.credentials_present(
            bc.METHOD_ENV, environ={bc.ENV_USERNAME: "u", bc.ENV_PASSWORD: "p"}))
        self.assertFalse(bc.credentials_present(bc.METHOD_ENV, environ={}))

    def test_ini_method_uses_only_explicit_values(self):
        c = bc.load_credentials(
            bc.METHOD_INI, ini_username="ini-user", ini_password='REDACTED_CONFIGURE_LOCALLY')
        try:
            self.assertEqual(c.username, "ini-user")
            self.assertEqual(c.use_password(), 'REDACTED_CONFIGURE_LOCALLY')
        finally:
            c.wipe()

    def test_ini_method_missing_value_fails_closed(self):
        with self.assertRaises(bc.CredentialError):
            bc.load_credentials(bc.METHOD_INI, ini_username="ini-user",
                                ini_password="")


class TestConstantTime(unittest.TestCase):
    def test_equal(self):
        self.assertTrue(bc.constant_time_equals("phrase", "phrase"))

    def test_not_equal(self):
        self.assertFalse(bc.constant_time_equals("phrase", "other"))
        self.assertFalse(bc.constant_time_equals("", "x"))


if __name__ == "__main__":
    unittest.main()
