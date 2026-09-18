# -*- coding: utf-8 -*-
"""decide_adapter 실행 게이트 테스트 (지시 §8/§42/§49).

모드는 real 또는 blocked 뿐이며, 게이트 실패 시 fake 로 대체하지 않는다.
"""
import unittest

import bank24_adapter as A
import bank24_automation as b24
import bank24_trust as bt
import config


def _app(read_only=True, **bank_over):
    app = config.AppConfig()
    app.options = config.Options(read_only=read_only, source_tab="탁상")
    b = dict(exe_path=r"c:\kadc\x11\bank24.exe", main_window_class="TfrmMain")
    b.update(bank_over)
    app.bank24 = config.Bank24(**b)
    return app


def _stop(stopped=False):
    s = b24.EmergencyStop()
    if stopped:
        s.stop()
    return s


def _decide(app, **kw):
    kw.setdefault("stop", _stop())
    kw.setdefault("backend", object())
    kw.setdefault("credential_provider", lambda: None)
    kw.setdefault("integrity_checker", lambda: (True, "OK"))
    kw.setdefault("exe_verifier", lambda p: r"c:\bank24\bank24.exe")
    return A.decide_adapter(app_config=app, **kw)


class TestDecision(unittest.TestCase):
    def test_read_only_required(self):
        d = _decide(_app(read_only=False))
        self.assertEqual((d.mode, d.reason), ("blocked", "READ_ONLY_REQUIRED"))

    def test_no_bank24_section_not_blocked(self):
        # [bank24] 미요구 → MISSING_KEYS 없이 real(§2/§3/§22)
        app = config.AppConfig()   # 기본 상수 Bank24, INI [bank24] 없음
        app.options = config.Options(read_only=True, source_tab="탁상")
        d = _decide(app)
        self.assertEqual(d.mode, "real")

    def test_uses_code_constant_exe_path(self):
        # 고정 실행 경로/창 클래스 상수를 사용한다(§1/§4/§9)
        seen = {}
        app = config.AppConfig()
        app.options = config.Options(read_only=True, source_tab="탁상")

        def _ver(path):
            seen["path"] = path
            return path
        d = _decide(app, exe_verifier=_ver)
        self.assertEqual(seen["path"], config.BANK24_EXE_PATH)
        self.assertEqual(d.ctx.bank24.main_window_class, config.BANK24_MAIN_WINDOW_CLASS)

    def test_emergency_stop_blocks(self):
        d = _decide(_app(), stop=_stop(stopped=True))
        self.assertEqual((d.mode, d.reason), ("blocked", "EMERGENCY_STOP"))

    def test_ini_acl_does_not_block(self):
        # INI ACL 무결성으로 Bank24 연결을 차단하지 않는다(§4). integrity_checker 는 무시됨.
        d = _decide(_app(), integrity_checker=lambda: (False, "INI_UNSAFE"))
        self.assertEqual(d.mode, "real")

    def test_exe_untrusted_blocks(self):
        def _bad(p):
            raise bt.TrustError("PATH_USER_WRITABLE")
        d = _decide(_app(), exe_verifier=_bad)
        self.assertEqual((d.mode, d.reason), ("blocked", "PATH_USER_WRITABLE"))

    def test_all_pass_yields_real(self):
        d = _decide(_app())
        self.assertEqual(d.mode, "real")
        self.assertIsNotNone(d.ctx)
        self.assertEqual(d.ctx.exe_norm, r"c:\bank24\bank24.exe")
        self.assertEqual(d.ctx.source_tab, "\ubbf8\uc811\uc218")

    def test_mode_never_fake(self):
        for app in (_app(read_only=False), _app(exe_path=""), _app()):
            self.assertIn(_decide(app).mode, ("real", "blocked"))


if __name__ == "__main__":
    unittest.main()
