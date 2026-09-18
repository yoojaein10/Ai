# -*- coding: utf-8 -*-
"""읽기 전용 자격증명/allowlist/사전검증 테스트. 지시 §1, §4, §16."""
import os
import tempfile
import unittest

import ro_config as C


def _env(**over):
    base = {C.ENV_DB_SERVER: "s", C.ENV_DB_NAME: "d",
            C.ENV_DB_USER: "u", C.ENV_DB_PASSWORD: "p"}
    base.update(over)
    return base


class TestCredentials(unittest.TestCase):
    def test_all_present(self):
        creds = C.load_credentials(_env())
        self.assertEqual((creds.server, creds.database, creds.user), ("s", "d", "u"))

    def test_missing_fail_closed(self):
        for miss in C.CREDENTIAL_ENV_VARS:
            env = _env()
            del env[miss]
            with self.assertRaises(C.ReadOnlyConfigError):
                C.load_credentials(env)

    def test_blank_fail_closed(self):
        with self.assertRaises(C.ReadOnlyConfigError):
            C.load_credentials(_env(**{C.ENV_DB_USER: "   "}))

    def test_repr_hides_values(self):
        creds = C.load_credentials(_env(**{
            C.ENV_DB_SERVER: "SRVVAL", C.ENV_DB_NAME: "DBVAL",
            C.ENV_DB_USER: "USERVAL", C.ENV_DB_PASSWORD: "PWVAL"}))
        r = repr(creds)
        for secret in ("SRVVAL", "DBVAL", "USERVAL", "PWVAL"):
            self.assertNotIn(secret, r)
        self.assertIn("<set>", r)

    def test_only_env_source_no_ini_keyring(self):
        # 제공된 env dict 외의 소스를 읽지 않는다: 빈 dict → fail-closed
        with self.assertRaises(C.ReadOnlyConfigError):
            C.load_credentials({})


class TestIntegrationSwitch(unittest.TestCase):
    def test_default_disabled(self):
        self.assertFalse(C.integration_enabled({}))

    def test_exact_magic_required(self):
        self.assertFalse(C.integration_enabled({C.ENV_INTEGRATION: "yes"}))
        self.assertTrue(C.integration_enabled({C.ENV_INTEGRATION: C.INTEGRATION_MAGIC}))


class TestChildEnvScrub(unittest.TestCase):
    def test_db_secrets_removed(self):
        src = _env(**{C.ENV_INTEGRATION: C.INTEGRATION_MAGIC, "OTHER": "keep"})
        child = C.child_env_without_db_secrets(src)
        for name in (*C.CREDENTIAL_ENV_VARS, C.ENV_INTEGRATION):
            self.assertNotIn(name, child)
        self.assertEqual(child["OTHER"], "keep")

    def test_source_not_mutated(self):
        src = _env()
        C.child_env_without_db_secrets(src)
        self.assertIn(C.ENV_DB_USER, src)


_INI = '\n[ro_allowlist]\nconnect_hosts = dbhost.corp.local\nconnect_ips = 192.0.2.10\nverify_dns = false\nserver_identities = SQLPROD01\\INST\ndatabases = apworks42\n'


def _write_ini(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".ini", delete=False, encoding="utf-8")
    f.write(text)
    f.close()
    return f.name


class TestAllowlist(unittest.TestCase):
    def setUp(self):
        self.ini = _write_ini(_INI)

    def tearDown(self):
        os.unlink(self.ini)

    def test_load_and_match(self):
        al = C.load_allowlist(self.ini)
        self.assertTrue(al.host_allowed("dbhost.corp.local"))
        self.assertTrue(al.host_allowed("DBHOST.CORP.LOCAL"))
        self.assertFalse(al.host_allowed("dbhost.corp.local.evil.com"))  # suffix 아님
        self.assertTrue(al.server_identity_ok("SQLPROD01\\INST"))
        self.assertTrue(al.database_ok("apworks42"))
        self.assertFalse(al.database_ok("master"))

    def test_immutable(self):
        al = C.load_allowlist(self.ini)
        with self.assertRaises(Exception):
            al.databases = ("x",)  # frozen dataclass

    def test_placeholder_rejected(self):
        for bad in ("connect_hosts = YOUR_DB_SERVER_HOST",
                    "server_identities = <server>",
                    "databases = your_db_name"):
            text = _INI
            key = bad.split(" = ")[0]
            text = "\n".join(l if not l.strip().startswith(key) else bad
                             for l in _INI.splitlines())
            p = _write_ini(text)
            try:
                with self.assertRaises(C.ReadOnlyConfigError, msg=bad):
                    C.load_allowlist(p)
            finally:
                os.unlink(p)

    def test_wildcard_rejected(self):
        text = _INI.replace("apworks42", "apworks*")
        p = _write_ini(text)
        try:
            with self.assertRaises(C.ReadOnlyConfigError):
                C.load_allowlist(p)
        finally:
            os.unlink(p)

    def test_broad_cidr_rejected(self):
        text = _INI.replace('192.0.2.10', '192.0.2.10/8')
        p = _write_ini(text)
        try:
            with self.assertRaises(C.ReadOnlyConfigError):
                C.load_allowlist(p)
        finally:
            os.unlink(p)

    def test_unspecified_ip_rejected(self):
        text = _INI.replace('192.0.2.10', "0.0.0.0/0")
        p = _write_ini(text)
        try:
            with self.assertRaises(C.ReadOnlyConfigError):
                C.load_allowlist(p)
        finally:
            os.unlink(p)

    def test_verify_dns_requires_ips(self):
        text = _INI.replace('connect_ips = 192.0.2.10', "connect_ips =").replace(
            "verify_dns = false", "verify_dns = true")
        p = _write_ini(text)
        try:
            with self.assertRaises(C.ReadOnlyConfigError):
                C.load_allowlist(p)
        finally:
            os.unlink(p)

    def test_missing_section_fail_closed(self):
        p = _write_ini("[other]\nx=1\n")
        try:
            with self.assertRaises(C.ReadOnlyConfigError):
                C.load_allowlist(p)
        finally:
            os.unlink(p)


class TestServerParse(unittest.TestCase):
    def test_plain_host(self):
        t = C.parse_server("dbhost.corp.local")
        self.assertEqual((t.host, t.instance, t.port, t.is_ip),
                         ("dbhost.corp.local", "", "", False))

    def test_host_port(self):
        t = C.parse_server("dbhost.corp.local,1433")
        self.assertEqual((t.host, t.port), ("dbhost.corp.local", "1433"))

    def test_host_instance_port(self):
        t = C.parse_server("host\\INST,1533")
        self.assertEqual((t.host, t.instance, t.port), ("host", "INST", "1533"))

    def test_ipv4(self):
        t = C.parse_server('192.0.2.10')
        self.assertTrue(t.is_ip)

    def test_ipv6_bracket(self):
        t = C.parse_server("[2001:db8::1],1433")
        self.assertTrue(t.is_ip)
        self.assertEqual(t.port, "1433")

    def test_control_char_rejected(self):
        with self.assertRaises(C.PreflightError):
            C.parse_server("host\n,1433")

    def test_bad_port_rejected(self):
        with self.assertRaises(C.PreflightError):
            C.parse_server("host,99999")


class TestPreflight(unittest.TestCase):
    def setUp(self):
        self.ini = _write_ini(_INI)
        self.al = C.load_allowlist(self.ini)

    def tearDown(self):
        os.unlink(self.ini)

    def test_host_allow_pass(self):
        t = C.preflight_check("dbhost.corp.local,1433", self.al)
        self.assertEqual(t.host, "dbhost.corp.local")

    def test_host_not_in_allowlist(self):
        with self.assertRaises(C.PreflightError):
            C.preflight_check("evil.corp.local", self.al)

    def test_no_substring_match(self):
        with self.assertRaises(C.PreflightError):
            C.preflight_check("xdbhost.corp.local", self.al)

    def test_dns_verify_all_allowed(self):
        text = _INI.replace("verify_dns = false", "verify_dns = true")
        p = _write_ini(text)
        try:
            al = C.load_allowlist(p)
            t = C.preflight_check("dbhost.corp.local", al,
                                  resolver=lambda h: ['192.0.2.10'])
            self.assertEqual(t.host, "dbhost.corp.local")
        finally:
            os.unlink(p)

    def test_dns_verify_disallowed_ip(self):
        text = _INI.replace("verify_dns = false", "verify_dns = true")
        p = _write_ini(text)
        try:
            al = C.load_allowlist(p)
            with self.assertRaises(C.PreflightError):
                C.preflight_check("dbhost.corp.local", al,
                                  resolver=lambda h: ['192.0.2.10'])
        finally:
            os.unlink(p)

    def test_dns_verify_no_resolver_aborts(self):
        text = _INI.replace("verify_dns = false", "verify_dns = true")
        p = _write_ini(text)
        try:
            al = C.load_allowlist(p)
            with self.assertRaises(C.PreflightError):
                C.preflight_check("dbhost.corp.local", al, resolver=None)
        finally:
            os.unlink(p)


if __name__ == "__main__":
    unittest.main()
