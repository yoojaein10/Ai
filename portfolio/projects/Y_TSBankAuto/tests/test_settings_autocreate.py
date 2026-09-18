# -*- coding: utf-8 -*-
"""settings.ini 자동 생성 격리 테스트 (지시 §16).

- 모든 테스트는 tempfile 경로만 사용한다. 실제 C:\\Bank24Extractor\\settings.ini 는
  읽거나 변경하지 않는다.
- 검증: 없으면 기본 생성 / 기존 보존 / 시크릿 없음 / 동시 생성 충돌 / 생성 실패 시 real 차단.
"""
import configparser
import os
import shutil
import tempfile
import unittest

import config
import settings_integrity as si


class TestAutoCreate(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="yts_autocreate_")
        # 아직 존재하지 않는 하위 디렉터리 + 파일 (dir 자동 생성 경로도 검증)
        self.path = os.path.join(self.root, "Bank24Extractor", "settings.ini")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_fixed_path_is_bank24extractor(self):
        self.assertEqual(
            si.resolve_settings_path(), r"C:\Bank24Extractor\settings.ini")
        self.assertTrue(si.resolve_settings_path().endswith("settings.ini"))

    def test_creates_default_when_missing(self):
        created, reason = si.ensure_settings_file(self.path)
        self.assertTrue(created, reason)
        self.assertEqual(reason, "created")
        self.assertTrue(os.path.isfile(self.path))
        # UTF-8 로 파싱 가능하고 필수 섹션 존재
        cfg = configparser.ConfigParser()
        cfg.optionxform = str
        read = cfg.read(self.path, encoding="utf-8")
        self.assertTrue(read)
        for sec in ("database", "allowlist", "paths", "safety"):
            self.assertTrue(cfg.has_section(sec), sec)

    def test_existing_file_preserved(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        original = "[database]\nserver = keep-me\n"
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(original)
        created, reason = si.ensure_settings_file(self.path)
        self.assertFalse(created)
        self.assertEqual(reason, "exists")
        # 내용이 절대 변경/병합되지 않는다.
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), original)

    def test_second_call_does_not_overwrite(self):
        # 동시 실행/재실행 시 두 번째 호출은 기존 파일을 덮지 않는다.
        c1, _ = si.ensure_settings_file(self.path)
        self.assertTrue(c1)
        before = open(self.path, encoding="utf-8").read()
        c2, reason2 = si.ensure_settings_file(self.path)
        self.assertFalse(c2)
        self.assertIn(reason2, ("exists", "race"))
        after = open(self.path, encoding="utf-8").read()
        self.assertEqual(before, after)

    def test_default_ini_has_no_secrets(self):
        si.ensure_settings_file(self.path)
        cfg = configparser.ConfigParser()
        cfg.optionxform = str
        cfg.read(self.path, encoding="utf-8")
        # 민감 키는 존재하지 않거나 빈 값이어야 한다.
        db = cfg["database"]
        self.assertEqual(db.get("server", ""), "")
        self.assertEqual(db.get("database", ""), "")
        self.assertNotIn("password", {k.lower() for k in db})
        self.assertNotIn("username", {k.lower() for k in db})
        self.assertNotIn("uid", {k.lower() for k in db})
        # allowlist 비어 있음 → real 대상 미승인(fail-closed)
        al = cfg["allowlist"]
        self.assertEqual(al.get("servers", ""), "")
        self.assertEqual(al.get("databases", ""), "")
        # 원문에 흔한 시크릿/PII 토큰이 없어야 한다.
        raw = open(self.path, encoding="utf-8").read().lower()
        for tok in ("pwd=", "password =", "apikey", "api_key", "secret",
                    "10.40.", "192.168.", "@", "://"):
            self.assertNotIn(tok, raw, tok)

    def test_default_ini_keeps_fail_closed_config(self):
        # 생성 후에도 승인 절차 우회 없음: allow_commit/autocommit False, allowlist 빈값.
        si.ensure_settings_file(self.path)
        app = config.load_app_config(self.path)
        self.assertFalse(app.safety.allow_commit)
        self.assertFalse(app.safety.autocommit)
        self.assertTrue(app.safety.rollback_test)
        self.assertEqual(app.allowlist.servers, ())
        self.assertEqual(app.allowlist.databases, ())
        self.assertEqual(app.db.server, "")

    def test_unsafe_nonlocal_path_not_created_blocks_real(self):
        # UNC(비로컬) 경로: 생성하지 않고 안전 실패 → 파일 없음 → 무결성이 real 차단.
        unc = r"\\server\share\Bank24Extractor\settings.ini"
        created, reason = si.ensure_settings_file(unc)
        self.assertFalse(created)
        self.assertTrue(reason.startswith("unsafe:"), reason)
        # 무결성 게이트: 파일 없음 → real 차단, fake 는 허용
        result = si.evaluate(si.gather_facts(unc))
        self.assertFalse(result.real_allowed)
        self.assertTrue(result.fake_allowed)

    def test_creation_failure_blocks_real(self):
        # 생성 실패(부모가 파일이라 디렉터리 생성 불가) → 파일 없음 → real 차단.
        blocker = os.path.join(self.root, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("x")
        bad = os.path.join(blocker, "settings.ini")  # blocker 는 파일이라 하위 생성 불가
        created, reason = si.ensure_settings_file(bad)
        self.assertFalse(created)
        self.assertTrue(reason.startswith("unsafe:"), reason)
        self.assertFalse(os.path.exists(bad))
        result, _ = si.check_settings(bad)
        self.assertFalse(result.real_allowed)

    def test_no_reparse_on_normal_temp_path(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.assertFalse(si._path_has_reparse(os.path.dirname(self.path)))


if __name__ == "__main__":
    unittest.main()
