# -*- coding: utf-8 -*-
"""테스트 격리 가드 검증 (S18) 및 Bank24 비활성 확인 (S10)."""
import unittest

import bank24_automation as b24


class TestIsolationGuards(unittest.TestCase):
    def test_real_pyodbc_connect_fails(self):
        try:
            import pyodbc
        except Exception:
            self.skipTest("pyodbc 미설치")
        with self.assertRaises(AssertionError):
            pyodbc.connect("DSN=whatever")

    def test_network_blocked(self):
        import urllib.request
        with self.assertRaises(AssertionError):
            urllib.request.urlopen("http://example.com")


class TestBank24Disabled(unittest.TestCase):
    def test_real_automation_disabled(self):
        self.assertFalse(b24.ENABLE_REAL_AUTOMATION)

    def test_send_keys_blocked(self):
        win = b24.WindowInfo(hwnd=1, pid=2, title="Bank24",
                             window_class="X", exe_path=r"C:\Bank24\Bank24.exe")
        policy = b24.TrustPolicy(exe_path_allow=(r"C:\Bank24\Bank24.exe",),
                                 window_class_allow=("X",))
        stop = b24.EmergencyStop()
        with self.assertRaises(b24.AutomationBlocked):
            b24.send_keys_guarded(win, policy, "abc", stop)

    def test_trust_requires_more_than_title(self):
        # 제목만 맞고 실행경로가 다르면 신뢰 실패
        win = b24.WindowInfo(hwnd=1, pid=2, title="Bank24",
                             window_class="X", exe_path=r"C:\evil\fake.exe")
        policy = b24.TrustPolicy(exe_path_allow=(r"C:\Bank24\Bank24.exe",),
                                 window_class_allow=("X",))
        ok, fails = b24.verify_window_trust(win, policy)
        self.assertFalse(ok)
        self.assertTrue(any("실행경로" in f for f in fails))

    def test_emergency_stop(self):
        stop = b24.EmergencyStop()
        stop.stop()
        with self.assertRaises(b24.AutomationBlocked):
            stop.check()


if __name__ == "__main__":
    unittest.main()
