# -*- coding: utf-8 -*-
"""Bank24 바이너리 신뢰 검증 테스트 (지시 §22–§33, §93).

실제 Bank24 프로세스/서명을 사용하지 않는다. 합성 임시 파일 + 기준 주입만 사용한다.
"""
import os
import tempfile
import unittest

import bank24_automation as b24
import bank24_trust as T
import settings_integrity as si


class _Baseline:
    """모듈 상수(APPROVED_*)를 테스트 동안 임시로 설정하고 복원한다."""

    def __init__(self, **over):
        self.over = over
        self.saved = {}

    def __enter__(self):
        for k, v in self.over.items():
            self.saved[k] = getattr(T, k)
            setattr(T, k, v)
        return self

    def __exit__(self, *a):
        for k, v in self.saved.items():
            setattr(T, k, v)


def _tmpfile(data=b"synthetic-bank24-binary"):
    fd, p = tempfile.mkstemp(suffix=".exe")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return p


class TestApprovedPath(unittest.TestCase):
    def test_not_configured(self):
        with _Baseline(APPROVED_BANK24_EXE=""):
            with self.assertRaises(T.TrustError) as e:
                T.approved_exe_norm()
            self.assertEqual(e.exception.code, "PATH_NOT_CONFIGURED")

    def test_relative_rejected(self):
        with _Baseline(APPROVED_BANK24_EXE="bank24.exe"):
            with self.assertRaises(T.TrustError) as e:
                T.approved_exe_norm()
            self.assertEqual(e.exception.code, "PATH_NOT_ABSOLUTE")


class TestBinaryFile(unittest.TestCase):
    def setUp(self):
        self.p = _tmpfile()

    def tearDown(self):
        os.remove(self.p)

    def test_missing_file(self):
        with _Baseline(APPROVED_BANK24_EXE=self.p + ".nope"):
            with self.assertRaises(T.TrustError) as e:
                T.verify_binary_file()
            self.assertEqual(e.exception.code, "PATH_NOT_FOUND")

    def test_reparse_rejected(self, ):
        with _Baseline(APPROVED_BANK24_EXE=self.p):
            orig = si._is_reparse
            si._is_reparse = lambda path: True
            try:
                with self.assertRaises(T.TrustError) as e:
                    T.verify_binary_file()
                self.assertEqual(e.exception.code, "PATH_REPARSE")
            finally:
                si._is_reparse = orig

    def test_owner_untrusted(self):
        with _Baseline(APPROVED_BANK24_EXE=self.p):
            orig = si._owner_is_trusted
            si._owner_is_trusted = lambda owner: False
            try:
                with self.assertRaises(T.TrustError) as e:
                    T.verify_binary_file()
                self.assertEqual(e.exception.code, "PATH_OWNER_UNTRUSTED")
            finally:
                si._owner_is_trusted = orig

    def test_user_writable_rejected(self):
        with _Baseline(APPROVED_BANK24_EXE=self.p):
            o1, o2 = si._owner_is_trusted, si._dacl_world_writable
            si._owner_is_trusted = lambda owner: True
            si._dacl_world_writable = lambda sd: True
            try:
                with self.assertRaises(T.TrustError) as e:
                    T.verify_binary_file()
                self.assertEqual(e.exception.code, "PATH_USER_WRITABLE")
            finally:
                si._owner_is_trusted, si._dacl_world_writable = o1, o2

    def test_valid_binary_passes(self):
        # 소유자=현재 사용자, 광역쓰기 없음(실제 임시파일) → 통과
        with _Baseline(APPROVED_BANK24_EXE=self.p):
            exe = T.verify_binary_file()
            self.assertTrue(os.path.isabs(exe))


class TestTrustBaseline(unittest.TestCase):
    def setUp(self):
        self.p = _tmpfile()
        self.h = T.sha256_of(self.p)

    def tearDown(self):
        os.remove(self.p)

    def test_no_baseline_blocks(self):
        with _Baseline(APPROVED_SHA256=frozenset(), APPROVED_PUBLISHERS=frozenset()):
            with self.assertRaises(T.TrustError) as e:
                T.verify_trust_baseline(self.p)
            self.assertEqual(e.exception.code, "NO_TRUST_BASELINE")

    def test_sha256_match(self):
        with _Baseline(APPROVED_SHA256=frozenset({self.h})):
            self.assertEqual(T.verify_trust_baseline(self.p), "sha256")

    def test_sha256_mismatch(self):
        with _Baseline(APPROVED_SHA256=frozenset({"0" * 64})):
            with self.assertRaises(T.TrustError) as e:
                T.verify_trust_baseline(self.p)
            self.assertEqual(e.exception.code, "HASH_MISMATCH")

    def test_publisher_via_injected_provider(self):
        with _Baseline(APPROVED_PUBLISHERS=frozenset({"Trusted Publisher, Inc."})):
            m = T.verify_trust_baseline(
                self.p, signer_cn_provider=lambda path: "Trusted Publisher, Inc.")
            self.assertEqual(m, "authenticode")

    def test_publisher_untrusted(self):
        with _Baseline(APPROVED_PUBLISHERS=frozenset({"Trusted Publisher, Inc."})):
            with self.assertRaises(T.TrustError) as e:
                T.verify_trust_baseline(self.p, signer_cn_provider=lambda p: "Evil Co.")
            self.assertEqual(e.exception.code, "SIG_PUBLISHER_UNTRUSTED")

    def test_static_trust_full(self):
        with _Baseline(APPROVED_BANK24_EXE=self.p, APPROVED_SHA256=frozenset({self.h})):
            tr = T.verify_static_trust()
            self.assertEqual(tr.method, "sha256")
            self.assertEqual(tr.install_dir, os.path.dirname(T._normcase(self.p)))


class TestPidImage(unittest.TestCase):
    def test_image_mismatch(self):
        orig = T.pid_image_path
        T.pid_image_path = lambda pid: r"C:\evil\other.exe"
        try:
            with self.assertRaises(T.TrustError) as e:
                T.verify_pid_image(1234, r"C:\Bank24\Bank24.exe")
            self.assertEqual(e.exception.code, "PID_IMAGE_MISMATCH")
        finally:
            T.pid_image_path = orig

    def test_image_match(self):
        orig = T.pid_image_path
        T.pid_image_path = lambda pid: r"C:\Bank24\BANK24.EXE"   # 대소문자 무시 일치
        try:
            T.verify_pid_image(1234, r"C:\Bank24\Bank24.exe")    # 예외 없어야 함
        finally:
            T.pid_image_path = orig

    def test_bad_pid(self):
        with self.assertRaises(T.TrustError) as e:
            T.pid_image_path(0)
        self.assertEqual(e.exception.code, "PID_IMAGE_UNAVAILABLE")


class TestWindowTrust(unittest.TestCase):
    def _win(self, exe=r"C:\Bank24\Bank24.exe", cls="Bank24MainCls", pid=20, hwnd=10):
        return b24.WindowInfo(hwnd=hwnd, pid=pid, title="아무제목", window_class=cls,
                              exe_path=exe)

    _CLASSES = ("Bank24MainCls",)

    def test_no_window_class_blocks(self):
        with self.assertRaises(T.TrustError) as e:
            T.verify_window(self._win(), r"C:\Bank24\Bank24.exe", ())
        self.assertEqual(e.exception.code, "WINDOW_UNTRUSTED")

    def test_wrong_class_blocks(self):
        with self.assertRaises(T.TrustError):
            T.verify_window(self._win(cls="EvilCls"), r"C:\Bank24\Bank24.exe", self._CLASSES)

    def test_title_alone_not_trusted(self):
        # 제목이 정상이어도 exe 경로 불일치면 차단(§21/§30)
        with self.assertRaises(T.TrustError):
            T.verify_window(self._win(exe=r"C:\evil\x.exe"), r"C:\Bank24\Bank24.exe", self._CLASSES)

    def test_trusted_window_ok(self):
        orig = T.pid_image_path
        T.pid_image_path = lambda pid: r"C:\Bank24\Bank24.exe"
        try:
            T.verify_window(self._win(), r"C:\Bank24\Bank24.exe", self._CLASSES)  # 예외 없음
        finally:
            T.pid_image_path = orig


class TestLaunchSpec(unittest.TestCase):
    def test_spec_is_safe(self):
        spec = T.build_launch_spec(r"c:\bank24\bank24.exe")
        self.assertEqual(spec["argv"], [r"c:\bank24\bank24.exe"])   # 문자열 조립 아님(§18)
        self.assertEqual(spec["cwd"], r"c:\bank24")                 # 설치 폴더 고정(§24)
        self.assertFalse(spec["shell"])                            # shell=True 금지(§18)
        joined = " ".join(f"{k}={v}" for k, v in spec["env"].items()).lower()
        for bad in ("password", "pwd", "bank24_id", 'REDACTED_CONFIGURE_LOCALLY', "token"):
            self.assertNotIn(bad, joined)                          # 자격증명 env 금지(§30)


class TestVerifyExeFile(unittest.TestCase):
    """Bank24 연결 경로 exe 검증은 절대경로+존재만 확인(§11–§13). ACL/서명/해시 미검사."""

    def test_relative_rejected(self):
        with self.assertRaises(T.TrustError) as e:
            T.verify_exe_file("bank24.exe")                        # 절대경로만(§13)
        self.assertEqual(e.exception.code, "PATH_NOT_ABSOLUTE")

    def test_empty_rejected(self):
        with self.assertRaises(T.TrustError) as e:
            T.verify_exe_file("")
        self.assertEqual(e.exception.code, "PATH_NOT_CONFIGURED")

    def test_missing_file_rejected(self):
        with self.assertRaises(T.TrustError) as e:
            T.verify_exe_file(r"C:\no_such_dir_xyz\Bank24.exe")
        self.assertEqual(e.exception.code, "PATH_NOT_FOUND")

    def test_user_writable_exe_not_blocked(self):
        # 사용자 쓰기 가능한(일반 임시) exe 도 차단되지 않는다 — ACL 게이트 제거(§11/§12/§62)
        import os
        import tempfile
        fd, p = tempfile.mkstemp(suffix=".exe")
        os.close(fd)
        self.addCleanup(os.remove, p)
        self.assertEqual(T.verify_exe_file(p), T._normcase(p))


if __name__ == "__main__":
    unittest.main()
