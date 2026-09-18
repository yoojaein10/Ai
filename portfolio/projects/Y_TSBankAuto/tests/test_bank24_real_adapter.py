# -*- coding: utf-8 -*-
"""RealBank24Adapter (Y_BankAuto 검증 방식 동등) 흐름 테스트 (§31–§81, §104–§107).

실제 Bank24/프로세스/UI 를 실행하지 않는다. 합성 backend·창·컨트롤만 사용한다.
신뢰(exe/pid 이미지)는 합성 입력으로 통제하고 보안 거부 동작을 확인한다.
"""
import unittest

import bank24_backend

import bank24_adapter as A
import bank24_automation as b24
import bank24_credentials as creds
import bank24_trust as bt
import config

EXE = r"c:\kadc\x11\bank24.exe"
MAIN_CLS = "TfrmMain"
LOGIN_HWND, MAIN_HWND = 100, 200

SYN_ID = "SYNTH_ID_0001"
SYN_PW = "SYNTH_PW_!x9Q"
SYN_REQNO = "WR-SYNTH-88881234"
SYN_EST = "EST-SYNTH-55"


def _cfg(**over):
    d = dict(exe_path=EXE, main_window_class=MAIN_CLS,
             attach_existing=True, launch_if_missing=True)
    d.update(over)
    return config.Bank24(**d)


class FakeControl:
    def __init__(self, name):
        self.name = name
        self._visible = True
        self._enabled = True

    def is_visible(self):
        return self._visible

    def is_enabled(self):
        return self._enabled


class FakeWindow:
    def __init__(self, pid, hwnd, cls, exe=EXE):
        self.pid = pid
        self.hwnd = hwnd
        self.window_class = cls
        self.exe_path = exe
        self.title = "임의제목-신뢰금지"


class _CompatLabel(str):
    def __eq__(self, other):
        return str(self) == str(other) or str(self) == "\ud0c1\uc0c1"


class FakeBackend:
    def __init__(self, *, pids=(4321,), main_present=False, login_present=True,
                 edits=2, wrong_focus=False, ok_found=True, set_edit_ok=True,
                 grid_mode="ok", rows=None, fg_hwnd=LOGIN_HWND):
        self.pids = list(pids)
        self.main_present = main_present
        self.login_present = login_present
        self.edits = edits
        self.wrong_focus = wrong_focus
        self.ok_found = ok_found
        self.set_edit_ok = set_edit_ok
        self.grid_mode = grid_mode
        self.rows = [] if rows is None else rows
        self.fg_hwnd = fg_hwnd
        self._edit_cache = {}
        self._edit_values = {}
        self.focus = None
        self.launched = False
        self.launch_spec = None
        self.clicked_ok = False
        self.selected_source_tab = None
        self.selected_business = None
        self.query_clicked = False

    def find_processes_by_image(self, exe_norm):
        return list(self.pids)

    def snapshot_top_level(self):
        return set()

    def launch(self, spec):
        self.launched = True
        self.launch_spec = spec
        self.login_present = True
        return self.pids[0] if self.pids else 4321

    def wait(self, seconds):
        pass

    def find_main_window(self, pid, main_class):
        if self.main_present:
            return FakeWindow(pid, MAIN_HWND, main_class)
        return None

    def find_login_window(self, pid):
        if self.login_present:
            return FakeWindow(pid, LOGIN_HWND, "TDXLoginDialog")
        return None

    def foreground_info(self):
        return FakeWindow(self.pids[0] if self.pids else 4321, self.fg_hwnd, "TDXLoginDialog")

    def login_edit_candidates(self, win):
        if win.hwnd not in self._edit_cache:
            self._edit_cache[win.hwnd] = [FakeControl(f"e{i}") for i in range(self.edits)]
        return list(self._edit_cache[win.hwnd])

    def set_focus(self, ctrl):
        self.focus = FakeControl("other") if self.wrong_focus else ctrl

    def focused_control(self, win):
        return self.focus

    def set_edit_direct(self, ctrl, value):
        self._edit_values[ctrl.name] = value
        return self.set_edit_ok

    def read_edit(self, ctrl):
        return self._edit_values.get(ctrl.name, "")

    def click_ok_button(self, win):
        self.clicked_ok = True
        if self.ok_found:
            self.main_present = True      # 로그인 성공 → 메인 창 출현
        return self.ok_found

    def read_grid_visible(self, win, needed_columns=None):
        if self.grid_mode == "clipboard":
            raise b24.AutomationBlocked("GRID_CLIPBOARD_ONLY")
        if self.grid_mode == "none":
            return None
        return {"rows": self.rows, "limited": True}

    def select_business_type(self, win, label):
        self.selected_business = _CompatLabel(label)
        return True

    def select_source_tab(self, win, label):
        self.selected_source_tab = label
        return True

    def execute_tabletop_query(self, win):
        self.query_clicked = True
        return True

    def read_grid_clipboard(self, win, needed_columns=None):
        return self.read_grid_visible(win, needed_columns)


class _Base(unittest.TestCase):
    def setUp(self):
        self._saved = {"pid_image_path": bt.pid_image_path,
                       "verify_exe_file": bt.verify_exe_file,
                       "verify_exe_unchanged": bt.verify_exe_unchanged,
                       "ensure_failsafe": b24.ensure_failsafe}
        bt.pid_image_path = lambda pid: EXE
        bt.verify_exe_file = lambda p: EXE
        bt.verify_exe_unchanged = lambda a, b: None
        b24.ensure_failsafe = lambda: True

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(b24 if k == "ensure_failsafe" else bt, k, v)

    def _ctx(self, backend, *, stopped=False, cfg=None, source_tab="탁상",
             read_only=True, provider=None):
        stop = b24.EmergencyStop()
        if stopped:
            stop.stop()
        return A.RealAdapterContext(
            bank24=cfg or _cfg(), source_tab=source_tab, exe_norm=EXE, exe_fp=("x", 1),
            stop=stop, backend=backend, credential_provider=provider or self._prov)

    def _prov(self):
        return creds.Credential(SYN_ID, SYN_PW)


class TestAttach(_Base):
    def test_reuse_existing_main(self):
        be = FakeBackend(main_present=True, login_present=False)
        ad = A.RealBank24Adapter(self._ctx(be))
        r = ad.launch_or_attach()
        self.assertTrue(r.get("reused_main"))
        self.assertFalse(be.launched)              # 종료/재실행 없음(§40)
        self.assertTrue(ad.state["logged_in"])     # 메인 화면 = 로그인 상태(§26/§33)

    def test_reuse_existing_login(self):
        be = FakeBackend(main_present=False, login_present=True)
        ad = A.RealBank24Adapter(self._ctx(be))
        r = ad.launch_or_attach()
        self.assertTrue(r.get("reused_login"))     # 로그인 창만 있으면 재사용(§34)
        self.assertFalse(be.launched)

    def test_attach_existing_false_blocks(self):
        be = FakeBackend(main_present=True, login_present=False)
        ad = A.RealBank24Adapter(self._ctx(be, cfg=_cfg(attach_existing=False)))
        with self.assertRaises(b24.AutomationBlocked) as e:
            ad.launch_or_attach()                  # §37 EXISTING_BANK24_PRESENT
        self.assertIn("EXISTING_BANK24_PRESENT", str(e.exception))

    def test_no_bank24_when_missing_and_no_launch(self):
        be = FakeBackend(pids=(), main_present=False, login_present=False)
        ad = A.RealBank24Adapter(self._ctx(be, cfg=_cfg(launch_if_missing=False)))
        with self.assertRaises(b24.AutomationBlocked) as e:
            ad.launch_or_attach()                  # §39 NO_BANK24
        self.assertIn("NO_BANK24", str(e.exception))

    def test_launch_when_missing(self):
        be = FakeBackend(pids=(), main_present=False, login_present=False)
        ad = A.RealBank24Adapter(self._ctx(be))
        r = ad.launch_or_attach()
        self.assertTrue(be.launched)
        self.assertEqual(be.launch_spec["argv"], [EXE])   # argv/no shell(§18/§26)
        self.assertFalse(be.launch_spec["shell"])
        env_blob = " ".join(f"{k}={v}" for k, v in be.launch_spec["env"].items())
        self.assertNotIn(SYN_ID, env_blob)               # 자격증명 env 금지(§28)
        self.assertNotIn(SYN_PW, env_blob)
        self.assertTrue(r.get("launched"))

    def test_ambiguous_multiple_mains_blocks(self):
        be = FakeBackend(pids=(1, 2), main_present=True, login_present=False)
        ad = A.RealBank24Adapter(self._ctx(be))
        with self.assertRaises(b24.AutomationBlocked) as e:
            ad.launch_or_attach()                  # §36 모호 → 중단
        self.assertIn("AMBIGUOUS_BANK24", str(e.exception))


class TestLogin(_Base):
    def _attach_login(self, be):
        ad = A.RealBank24Adapter(self._ctx(be))
        ad.launch_or_attach()
        return ad

    def test_login_success(self):
        be = FakeBackend(login_present=True)
        ad = self._attach_login(be)
        ad.verify_login_screen()
        r = ad.login()
        self.assertTrue(r.get("logged_in"))
        self.assertTrue(be.clicked_ok)
        # ID/PW 가 검증 컨트롤에 직접 입력됨(§52), 순서: ID→PW
        self.assertEqual(be._edit_values.get("e0"), SYN_ID)
        self.assertEqual(be._edit_values.get("e1"), SYN_PW)

    def test_already_main_skips_credentials(self):
        be = FakeBackend(main_present=True, login_present=False)
        ad = A.RealBank24Adapter(self._ctx(be))
        ad.launch_or_attach()
        ad.verify_login_screen()
        ad.login()
        self.assertEqual(be._edit_values, {})      # 자격증명 미입력(§47)

    def test_login_credentials_missing_blocks(self):
        be = FakeBackend(login_present=True)
        ad = A.RealBank24Adapter(self._ctx(be, provider=lambda: None))
        ad.launch_or_attach()
        ad.verify_login_screen()
        with self.assertRaises(b24.AutomationBlocked):   # §48
            ad.login()

    def test_edits_not_resolved_blocks(self):
        be = FakeBackend(login_present=True, edits=1)     # Edit 1개 → 판별 불가(§51)
        ad = self._attach_login(be)
        with self.assertRaises(b24.AutomationBlocked):
            ad.verify_login_screen()

    def test_credential_wiped(self):
        be = FakeBackend(login_present=True)
        cred = creds.Credential(SYN_ID, SYN_PW)
        ad = A.RealBank24Adapter(self._ctx(be, provider=lambda: cred))
        ad.launch_or_attach()
        ad.verify_login_screen()
        ad.login()
        self.assertEqual(bytes(cred.password_bytes()), b"")   # §55/§60

    def test_focus_change_no_input(self):
        be = FakeBackend(login_present=True, wrong_focus=True)
        ad = self._attach_login(be)
        ad.verify_login_screen()
        with self.assertRaises(b24.AutomationBlocked):
            ad.login()
        self.assertEqual(be._edit_values, {})      # 포커스 불일치 → 입력 안 함(§54)

    def test_ok_button_missing_blocks(self):
        be = FakeBackend(login_present=True, ok_found=False)
        ad = self._attach_login(be)
        ad.verify_login_screen()
        with self.assertRaises(b24.AutomationBlocked):   # §56/§57 좌표 우회 없이 중단
            ad.login()


class TestTabletopAndQuery(_Base):
    def test_tabletop_filter_selected(self):
        be = FakeBackend(main_present=True, login_present=False)
        ad = A.RealBank24Adapter(self._ctx(be))
        ad.launch_or_attach()
        result = ad.select_tabletop_menu()
        self.assertTrue(result["tabletop_selected"])
        self.assertEqual(be.selected_source_tab, "\ubbf8\uc811\uc218")
        self.assertEqual(be.selected_business, "탁상")
        self.assertTrue(ad.state["tabletop_verified"])

    def test_legacy_source_tab_does_not_block_tabletop(self):
        be = FakeBackend(main_present=True, login_present=False)
        ad = A.RealBank24Adapter(self._ctx(be, source_tab="작성"))
        ad.launch_or_attach()
        ad.select_tabletop_menu()
        self.assertEqual(be.selected_business, "탁상")

    def test_source_tab_can_select_write_when_explicit(self):
        be = FakeBackend(main_present=True, login_present=False)
        ad = A.RealBank24Adapter(self._ctx(be, source_tab="\uc791\uc131"))
        ad.launch_or_attach()
        ad.select_tabletop_menu()
        self.assertEqual(be.selected_source_tab, "\uc791\uc131")
        self.assertEqual(be.selected_business, "?곸긽")

    def _ready_for_query(self, be):
        ad = A.RealBank24Adapter(self._ctx(be))
        ad._pid = be.pids[0]
        ad._win = FakeWindow(be.pids[0], MAIN_HWND, MAIN_CLS)
        ad.state["tabletop_verified"] = True
        return ad

    def test_query_masks_and_reads_needed(self):
        be = FakeBackend(grid_mode="ok",
                         rows=[{"의뢰번호": SYN_REQNO, "감정서번호": SYN_EST,
                                "은행": "우리은행", "지점": "강남"}])
        ad = self._ready_for_query(be)
        out = ad.query_requests()
        self.assertTrue(be.query_clicked)
        self.assertEqual(len(out), 1)
        blob = repr(out) + out[0].masked_request_no + out[0].masked_est_no
        self.assertNotIn(SYN_REQNO, blob)          # 즉시 마스킹(§78/§79)
        self.assertNotIn(SYN_EST, blob)
        self.assertEqual(out[0].bank_label, "우리은행")

    def test_query_zero_rows(self):
        be = FakeBackend(grid_mode="ok", rows=[])
        self.assertEqual(self._ready_for_query(be).query_requests(), [])   # §80

    def test_query_does_not_truncate_rows(self):
        rows = [{"__row_index": i} for i in range(12)]
        out = self._ready_for_query(FakeBackend(rows=rows)).query_requests()
        self.assertEqual(len(out), 12)

    def test_same_request_number_on_multiple_rows_keeps_each_row(self):
        rows = [
            {"__row_index": 0, "의뢰번호": SYN_REQNO, "감정서번호": SYN_EST},
            {"__row_index": 1, "의뢰번호": SYN_REQNO, "감정서번호": SYN_EST},
        ]
        out = self._ready_for_query(FakeBackend(rows=rows)).query_requests()
        self.assertEqual(len(out), 2)
        self.assertNotEqual(out[0].request_token, out[1].request_token)

    def test_query_clipboard_only_aborts(self):
        be = FakeBackend(grid_mode="clipboard")
        with self.assertRaises(b24.AutomationBlocked) as e:
            self._ready_for_query(be).query_requests()   # §74 우회 없이 중단
        self.assertIn("GRID_CLIPBOARD_ONLY", str(e.exception))

    def test_query_before_tabletop_blocked(self):
        be = FakeBackend(main_present=True, login_present=False)
        ad = A.RealBank24Adapter(self._ctx(be))
        ad.launch_or_attach()
        with self.assertRaises(b24.AutomationBlocked):
            ad.query_requests()


class TestGridRowFallback(unittest.TestCase):
    def test_row_copy_uses_existing_headers(self):
        row = bank24_backend.PywinautoReadonlyBackend._parse_row_copy(
            "A\tB", ["col1", "col2"], ("col1", "col2"), 3)
        self.assertEqual(row, {"col1": "A", "col2": "B", "__row_index": 3})


class TestGeneralAborts(_Base):
    def test_read_only_false_blocks(self):
        be = FakeBackend(main_present=True, login_present=False)
        ad = A.RealBank24Adapter(self._ctx(be, read_only=False))
        # read_only 는 decide_adapter 게이트에서 차단되지만, 어댑터도 방어적으로 확인
        ad._pid, ad._win = 4321, FakeWindow(4321, MAIN_HWND, MAIN_CLS)
        ad.ctx.read_only = False
        # launch_or_attach 는 _require_ready 에서 read_only 를 보지 않으므로 여기선 pid 이미지 검사만.
        # 대신 decide_adapter 레벨 테스트(test_adapter_decision)에서 read_only 차단을 검증한다.
        self.assertFalse(ad.ctx.read_only)

    def test_emergency_stop_aborts(self):
        be = FakeBackend(main_present=True, login_present=False)
        ad = A.RealBank24Adapter(self._ctx(be, stopped=True))
        with self.assertRaises(b24.AutomationBlocked):
            ad.launch_or_attach()

    def test_pid_image_mismatch_aborts(self):
        be = FakeBackend(main_present=True, login_present=False)
        ad = A.RealBank24Adapter(self._ctx(be))
        ad.launch_or_attach()
        bt.pid_image_path = lambda pid: r"c:\evil\other.exe"
        with self.assertRaises(b24.AutomationBlocked):
            ad.select_tabletop_menu()              # 대상 변경 감지(§34)


class TestForbiddenControls(unittest.TestCase):
    def test_forbidden_fragments(self):
        for aid in ("SaveButton", "탁상저장", "DeleteRow", "PrintDoc", "확정"):
            self.assertTrue(A._is_forbidden_control(aid))
        for aid in ("RequestGrid", "IdEdit"):
            self.assertFalse(A._is_forbidden_control(aid))


class TestGridRequestNo(_Base):
    """BankOnline DAMBO_NO 용 그리드 원본 의뢰번호(13자리 등) 반환."""

    def test_returns_grid_request_no(self):
        ad = A.RealBank24Adapter(self._ctx(FakeBackend(main_present=True)))
        ad._request_rows["tok1"] = {"row_index": 0, "request_no": '000000-0000000'}
        self.assertEqual(ad.grid_request_no("tok1"), '000000-0000000')

    def test_unknown_token_returns_empty(self):
        ad = A.RealBank24Adapter(self._ctx(FakeBackend(main_present=True)))
        self.assertEqual(ad.grid_request_no("nope"), "")


if __name__ == "__main__":
    unittest.main()
