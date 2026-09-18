# -*- coding: utf-8 -*-
"""single-flight 락 테스트 (지시 §7, §16).

- 결정적 이름(무작위 아님), Local 네임스페이스, Global 금지.
- 파일락 중복 차단, 모든 경로 해제.
"""
import os
import tempfile
import unittest

import single_flight as sf


class TestName(unittest.TestCase):
    def test_deterministic_and_local(self):
        n1 = sf.mutex_name("S-1-5-21-1", "app")
        n2 = sf.mutex_name("S-1-5-21-1", "app")
        self.assertEqual(n1, n2)                 # 무작위 아님(결정적)
        self.assertTrue(n1.startswith("Local\\"))
        self.assertNotIn("Global\\", n1)

    def test_differs_by_sid(self):
        self.assertNotEqual(sf.mutex_name("S-1-5-21-1"),
                            sf.mutex_name("S-1-5-21-2"))

    def test_current_sid_nonempty(self):
        self.assertTrue(sf.current_user_sid())


class TestFileBackend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self.tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._old
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_second_acquire_blocked(self):
        a = sf.SingleFlight(backend="file", sid="TESTSID")
        b = sf.SingleFlight(backend="file", sid="TESTSID")
        self.assertTrue(a.acquire())
        try:
            self.assertFalse(b.acquire())        # 이미 보유 → 차단
        finally:
            a.release()

    def test_release_allows_reacquire(self):
        a = sf.SingleFlight(backend="file", sid="TESTSID")
        self.assertTrue(a.acquire())
        a.release()
        b = sf.SingleFlight(backend="file", sid="TESTSID")
        self.assertTrue(b.acquire())             # 해제 후 재획득 가능
        b.release()

    def test_context_manager_releases_on_exception(self):
        try:
            with sf.SingleFlight(backend="file", sid="TESTSID"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        # 예외 경로에서도 해제되어 재획득 가능해야 한다.
        c = sf.SingleFlight(backend="file", sid="TESTSID")
        self.assertTrue(c.acquire())
        c.release()

    def test_context_manager_blocks_second(self):
        with sf.SingleFlight(backend="file", sid="TESTSID"):
            with self.assertRaises(sf.SingleFlightError):
                with sf.SingleFlight(backend="file", sid="TESTSID"):
                    pass

    def test_lock_file_under_user_dir(self):
        p = sf.lock_file_path("TESTSID")
        self.assertTrue(p.startswith(self.tmp))  # 사용자 전용 로컬 경로


if __name__ == "__main__":
    unittest.main()
