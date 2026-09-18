"""보안 회귀 테스트 — SQL 검증기·마스킹·실행 게이트·HTTP 보호·프런트엔드 불변조건.

실행: prototype 디렉터리에서  python -m unittest discover tests -v
"""
import json
import re
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from tests._bootstrap import app


class TestValidateSelect(unittest.TestCase):
    ALLOWED = [
        "SELECT 1",
        "SELECT TOP 10 a, b FROM dbo.T WHERE a = 1 ORDER BY b",
        "WITH x AS (SELECT 1 AS n) SELECT n FROM x",
        "SELECT '문자열 안의 DROP TABLE은 무해' AS s",
        "SELECT a -- INSERT 주석은 무해\nFROM t",
        "SELECT a FROM t;",  # 후행 세미콜론 1개 허용
    ]
    BLOCKED = [
        "",
        "SELECT 1; DROP TABLE t",
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET a = 1",
        "DELETE FROM t",
        "TRUNCATE TABLE t",
        "DROP TABLE t",
        "ALTER TABLE t ADD c int",
        "CREATE TABLE t (a int)",
        "SELECT * INTO #tmp FROM t",
        "EXEC xp_cmdshell 'dir'",
        "EXECUTE sp_executesql N'SELECT 1'",
        "SELECT * FROM OPENROWSET('SQLNCLI', 'x', 'SELECT 1')",
        "WAITFOR DELAY '0:0:5'",
        "GRANT SELECT ON t TO u",
        "BACKUP DATABASE d TO DISK='x'",
        "SELECT " + "a," * 4000 + " b FROM t",  # 길이 제한
    ]

    def test_allowed(self):
        for sql in self.ALLOWED:
            self.assertIsNone(app.validate_select(sql), f"허용돼야 함: {sql[:60]}")

    def test_blocked(self):
        for sql in self.BLOCKED:
            self.assertIsNotNone(app.validate_select(sql), f"차단돼야 함: {sql[:60]}")


class TestMasking(unittest.TestCase):
    def test_literals_and_comments_removed(self):
        sql = ("SELECT * FROM users WHERE email = 'contact@example.com' AND pin = 9182"
               " -- 임시 비밀번호 hunter2\n/* 담당자 010-0000-0000 */ AND x = 'secret'")
        masked = app.mask_sql(sql)
        for leak in ('contact@example.com', "9182", "hunter2", '010-0000-0000', "secret"):
            self.assertNotIn(leak, masked, f"마스킹 누출: {leak}")
        self.assertIn("SELECT", masked)  # 구조는 보존

    def test_conn_part_injection_blocked(self):
        for bad in ("a;b", "a{b", "a}b", "a=b", "", "  "):
            with self.assertRaises(ValueError, msg=f"차단돼야 함: {bad!r}"):
                app._clean_part(bad, "서버 주소")


class TestRunGate(unittest.TestCase):
    """안전하지 않은 권한 감지 시 챗봇 SQL 실행 차단 (fail-closed)."""

    def setUp(self):
        self._saved = (app.DB_LIVE, app.SAFE_RUN, app.UNSAFE_OVERRIDE,
                       list(app.UNSAFE_REASONS))

    def tearDown(self):
        app.DB_LIVE, app.SAFE_RUN, app.UNSAFE_OVERRIDE = self._saved[:3]
        app.UNSAFE_REASONS = self._saved[3]

    def test_demo_mode_blocked(self):
        app.DB_LIVE = False
        res = app.chat_run({"sql": "SELECT 1"})
        self.assertFalse(res["ok"])

    def test_privileged_account_blocked(self):
        app.DB_LIVE = True
        app.SAFE_RUN = False
        app.UNSAFE_OVERRIDE = False
        app.UNSAFE_REASONS = ["고정 DB 역할 db_owner"]
        res = app.chat_run({"sql": "SELECT 1"})
        self.assertFalse(res["ok"])
        self.assertIn("안전하지 않은 권한", res["error"])
        self.assertIn("db_owner", res["error"])

    def test_invalid_sql_blocked_before_gate(self):
        app.DB_LIVE = True
        res = app.chat_run({"sql": "DROP TABLE t"})
        self.assertFalse(res["ok"])
        self.assertIn("실행 차단", res["error"])


class TestHttpProtection(unittest.TestCase):
    """Host·Origin·nonce·Content-Type·본문 크기 검증 (임시 포트, 실DB·실키 미접근)."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"
        html = urllib.request.urlopen(cls.base + "/", timeout=5).read().decode("utf-8")
        m = re.search(r'window\.DBAONE_NONCE="([^"]+)"', html)
        assert m, "index.html에 nonce가 주입되지 않음"
        cls.nonce = m.group(1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _post(self, path, headers=None, body=b"{}"):
        h = {"Content-Type": "application/json", "X-DBAONE-Nonce": self.nonce}
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=body, headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_nonce_injected_and_valid_post_ok(self):
        status, body = self._post("/api/chat/reset")
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))

    def test_post_without_nonce_403(self):
        status, _ = self._post("/api/chat/reset", headers={"X-DBAONE-Nonce": "wrong"})
        self.assertEqual(status, 403)

    def test_cross_origin_403(self):
        status, _ = self._post("/api/chat/reset", headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        status, _ = self._post("/api/chat/reset", headers={"Origin": "null"})
        self.assertEqual(status, 403)

    def test_bad_host_403(self):
        status, _ = self._post("/api/chat/reset", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_bad_content_type_403(self):
        status, _ = self._post("/api/chat/reset", headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 403)

    def test_oversized_body_403(self):
        status, _ = self._post("/api/chat/reset", body=b'{"x":"' + b"a" * 70000 + b'"}')
        self.assertEqual(status, 403)

    def test_sec_fetch_cross_site_403(self):
        status, _ = self._post("/api/chat/reset", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)

    def test_knowledge_api_isolates_targets_and_keeps_global(self):
        old_target = app.TARGET_ID
        try:
            app.TARGET_ID = "A/db"
            for term, scope in (("A전용", "target"), ("공통개념", "global")):
                status, body = self._post(
                    "/api/knowledge/glossary",
                    body=json.dumps({"term": term, "mapping": "검증용", "scope": scope},
                                    ensure_ascii=False).encode("utf-8"))
                self.assertEqual(status, 200)
                self.assertTrue(body["ok"])
            _, a = self._get("/api/knowledge")
            self.assertEqual({g["term"] for g in a["glossary"]}, {"A전용", "공통개념"})

            app.TARGET_ID = "B/db"
            _, b = self._get("/api/knowledge")
            self.assertEqual({g["term"] for g in b["glossary"]}, {"공통개념"})
            status, denied = self._post(
                "/api/knowledge/glossary/delete",
                body=json.dumps({"term": "A전용", "target_id": "A/db"}).encode("utf-8"))
            self.assertEqual(status, 200)
            self.assertFalse(denied["ok"])
        finally:
            app.TARGET_ID = old_target
            k = app.load_knowledge()
            k["glossary"] = [g for g in k["glossary"]
                             if g.get("term") not in ("A전용", "공통개념")]
            app.save_knowledge(k)


class TestFrontendInvariants(unittest.TestCase):
    """JS는 직접 실행할 수 없으므로 소스 불변조건으로 검사한다."""

    @classmethod
    def setUpClass(cls):
        cls.html = (Path(app.BASE) / "static" / "index.html").read_text(encoding="utf-8")

    def test_esc_escapes_quotes(self):
        m = re.search(r"const esc = [^\n]+", self.html)
        self.assertIsNotNone(m)
        for token in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
            self.assertIn(token, m.group(0), f"esc()가 {token} 처리를 잃음")

    def test_no_string_interpolated_inline_handlers(self):
        self.assertNotIn('onclick="delGlossary(', self.html)
        self.assertNotIn('onclick="useConn(', self.html)

    def test_jpost_sends_nonce(self):
        self.assertIn("X-DBAONE-Nonce", self.html)

    def test_scalar_result_is_rendered_locally(self):
        self.assertIn("res.result_summary", self.html)
        self.assertIn("proposeGlossary", self.html)

    def test_knowledge_scope_controls_exist(self):
        self.assertIn('id="gScope"', self.html)
        self.assertIn("adoptGlossary", self.html)
        self.assertIn("data-del-target", self.html)


if __name__ == "__main__":
    unittest.main()
