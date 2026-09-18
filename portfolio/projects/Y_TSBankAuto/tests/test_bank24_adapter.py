# -*- coding: utf-8 -*-
"""Bank24 adapter 진단/인터페이스 및 테스트용 fake 흐름 (지시 §4/§57)."""
import os
import tempfile
import unittest

import bank24_adapter as A
import bank24_automation as b24
from tests._fakes import FakeBank24Adapter


def _policy():
    return b24.TrustPolicy(exe_path_allow=(r"C:\Bank24\Bank24.exe",),
                           window_class_allow=("TabletopCls",))


def _win(exe=r"C:\Bank24\Bank24.exe", cls="TabletopCls"):
    return b24.WindowInfo(hwnd=10, pid=20, title="Bank24", window_class=cls, exe_path=exe)


class TestFakeAdapterFlow(unittest.TestCase):
    """제품 런타임에 없는(테스트 전용) fake adapter 흐름 유지(§4)."""

    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        for f in os.listdir(self.root):
            os.remove(os.path.join(self.root, f))
        os.rmdir(self.root)

    def test_flow(self):
        ad = FakeBank24Adapter()
        ad.launch_or_attach()
        ad.verify_login_screen()
        ad.login()
        ad.select_tabletop_menu()
        reqs = ad.query_requests()
        self.assertTrue(reqs)
        path = ad.download_pdf(reqs[0].request_token, self.root, timestamp="20260701")
        self.assertTrue(os.path.isfile(path))

    def test_query_before_menu_blocked(self):
        ad = FakeBank24Adapter()
        ad.login()
        with self.assertRaises(b24.AutomationBlocked):
            ad.query_requests()


class TestProductHasNoFake(unittest.TestCase):
    """제품 모듈(bank24_adapter)에는 fake adapter 가 없어야 한다(§1/§52)."""

    def test_no_fake_in_product_module(self):
        self.assertFalse(hasattr(A, "FakeBank24Adapter"))
        self.assertFalse(hasattr(A, "select_adapter"))
        self.assertFalse(hasattr(A, "automation_switch_enabled"))


class TestDiagnostic(unittest.TestCase):
    def test_no_text_value_pii(self):
        diag = A.diagnose_controls(_win(), _policy(), fake_controls=[
            {"automation_id": "X", "control_type": "Button",
             "text": '홍길동 010-0000-0000', "value": "secret"}])
        self.assertTrue(diag["read_only"])
        for c in diag["controls"]:
            self.assertNotIn("text", c)
            self.assertNotIn("value", c)
        self.assertEqual(len(diag["window_token"]), 8)
        blob = repr(diag)
        self.assertNotIn("홍길동", blob)
        self.assertNotIn('010-0000-0000', blob)


if __name__ == "__main__":
    unittest.main()
