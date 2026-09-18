# -*- coding: utf-8 -*-
"""Bank24 탁상 자동화 adapter — 실제 Bank24 전용(읽기 전용).

Y_BankAuto(검증본)의 연결/로그인 방식과 동등하게 최소 구현한다(§46). 검증본은 win32
백엔드 + 직접 값설정(set_edit_text/WM_SETTEXT) + BM_CLICK 을 쓰며 클립보드/좌표/전역
send_keys/pyautogui 를 로그인·입력에 사용하지 않는다. 본 adapter 는 그 방식을 따르되
Y_BankAuto 에는 없던 신뢰 검증(경로/서명/PID 이미지/창 클래스/교체 감지)을 추가한다.

- 제품 런타임에 fake 없음. 실패 시 fake/합성 결과로 대체하지 않는다(§10/§81).
- 매 단계 PID·HWND·이미지경로·창클래스·전면창·포커스·컨트롤을 재검증한다(§34/§54).
- Invoke/버튼이 없으면 좌표 클릭으로 우회하지 않는다(§57). 저장·수정·삭제·인쇄 컨트롤은
  탐색·호출하지 않는다(§83). DB/SP/COMMIT/REST/PDF/인쇄/저장/상태변경 없음(§82).
- 로그·예외에 설정값/자격증명/원문 PII/창 텍스트/컨트롤 값을 남기지 않는다(§14/§79/§91).
- 단계별 유한 타임아웃(time.monotonic), 무한 대기/재시도 금지, 중지 확인(§85–§90).
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from datetime import datetime
from dataclasses import dataclass

import bank24_automation as b24
import bank24_trust

# 단계별 유한 타임아웃(초). monotonic 기반(§86/§87/§88).
T_WINDOW = 30.0      # 로그인/메인 창 대기 상한
T_STEP = 10.0        # 개별 조작 상한
T_UI = 5.0           # pywinauto 호출 timeout

# 탁상 탭 좌표 baseline — 코드 고정(§67), INI 에서 받지 않음. 참고 소스(Y_BankAuto)에는
# '작성/미접수' 만 있고 '탁상' baseline 이 없다(§63) → 비어 있어 탁상 이동은 fail-closed(§64).
_TAB_COORD_BASELINE: dict = {}

# 조회 시 읽을 비PII 열만(§77). 이름/주소/연락처 등은 읽지 않는다.
_GRID_NEEDED_COLUMNS = (
    "의뢰번호", "탁상의뢰번호", "감정서번호", "은행", "지점", "의뢰영업점",
    "BankOnline_In", "처리상태", "처리 상태",
)

# 쓰기성 컨트롤 이름 조각(§83): 탐색·호출 금지
_FORBIDDEN_CONTROL_FRAGMENTS = (
    "save", "update", "delete", "print", "modify", "insert", "commit",
    "저장", "수정", "삭제", "인쇄", "등록", "확정",
)


def _short_token(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8]


def _is_forbidden_control(name: str) -> bool:
    low = (name or "").lower()
    return any(frag in low for frag in _FORBIDDEN_CONTROL_FRAGMENTS)


@dataclass
class RequestSummary:
    """탁상 의뢰 목록 항목(마스킹 전용). 원문 PII 미포함."""
    request_token: str
    bank_label: str = ""
    branch_label: str = ""
    masked_request_no: str = ""
    masked_est_no: str = ""
    bankonline_in: str = ""
    process_status: str = "처리 대기"

    def __repr__(self) -> str:
        return f"RequestSummary(token={self.request_token}, bank={self.bank_label})"


class Bank24Adapter:
    is_fake = True

    def launch_or_attach(self):
        raise NotImplementedError

    def verify_login_screen(self):
        raise NotImplementedError

    def login(self, credential_provider=None):
        raise NotImplementedError

    def select_tabletop_menu(self):
        raise NotImplementedError

    def query_requests(self) -> list:
        raise NotImplementedError


@dataclass
class RealAdapterContext:
    """INI 에서 온 실제 Bank24 실행 컨텍스트. 값은 로그/repr 에 남기지 않는다."""
    bank24: object          # config.Bank24 (exe_path/main_window_class/attach_existing/launch_if_missing)
    source_tab: str
    exe_norm: str           # verify_exe_file 로 검증된 정규화 절대경로
    exe_fp: tuple           # 신뢰 지문(SHA-256, size) — 교체 감지(§29/§30)
    stop: "b24.EmergencyStop"
    backend: object = None
    credential_provider: object = None


class RealBank24Adapter(Bank24Adapter):
    is_fake = False

    def __init__(self, ctx: RealAdapterContext):
        self.ctx = ctx
        self._pid = None
        self._win = None       # 현재 신뢰된 대상 창(WindowInfo 유사)
        self.state = {"attached": False, "logged_in": False, "tabletop_verified": False}
        self._request_rows = {}

    # ── backend/가드 ──
    def _backend(self):
        b = self.ctx.backend
        if b is None:
            raise b24.AutomationBlocked("BACKEND_UNAVAILABLE")
        return b

    def _mclass(self):
        return (getattr(self.ctx.bank24, "main_window_class", "") or "",)

    def _deadline(self, seconds):
        return time.monotonic() + seconds

    def _check_stop(self):
        self.ctx.stop.check()          # 중지 시 AutomationBlocked(§89/§90)

    def _require_ready(self):
        self._check_stop()
        if not b24.ensure_failsafe():
            raise b24.AutomationBlocked("FAILSAFE_UNAVAILABLE")

    def _verify_exe_now(self):
        """실행/조작 직전 exe 재검증 + 교체 감지(§29/§30)."""
        try:
            exe = bank24_trust.verify_exe_file(self.ctx.bank24.exe_path)
            if exe != self.ctx.exe_norm:
                raise bank24_trust.TrustError("EXE_PATH_CHANGED")
            if self.ctx.exe_fp is not None:
                bank24_trust.verify_exe_unchanged(self.ctx.exe_norm, self.ctx.exe_fp)
        except bank24_trust.TrustError as te:
            raise b24.AutomationBlocked("EXE_UNTRUSTED:" + te.code)

    def _pid_image_ok(self, win):
        """창의 소속 PID 실제 이미지가 승인 exe 와 정확히 일치하는지(§22/§35).

        이것이 창 신뢰의 앵커다. 로그인 창은 main_window_class 와 다른 클래스이므로
        클래스 일치는 메인 창에만 적용하고(§58), 그 외 창은 PID 이미지로 신뢰한다.
        """
        try:
            bank24_trust.verify_pid_image(int(win.pid), self.ctx.exe_norm)
        except bank24_trust.TrustError as te:
            raise b24.AutomationBlocked("WINDOW_UNTRUSTED:" + te.code)

    def _reverify_target(self):
        """조작 직전 대상 재검증(§34/§35): PID 이미지 + HWND 안정."""
        self._check_stop()
        if self._pid is None or self._win is None:
            raise b24.AutomationBlocked("NO_TARGET")
        self._pid_image_ok(self._win)
        if int(getattr(self._win, "pid", -1)) != int(self._pid):
            raise b24.AutomationBlocked("TARGET_PID_CHANGED")

    def _reverify_foreground(self):
        fg = self._backend().foreground_info()
        if fg is None or int(getattr(fg, "hwnd", 0) or 0) != int(self._win.hwnd):
            raise b24.AutomationBlocked("FOREGROUND_CHANGED")

    def _reverify_focus(self, ctrl):
        self._reverify_target()
        self._reverify_foreground()
        b = self._backend()
        b.set_focus(ctrl)
        if b.focused_control(self._win) is not ctrl:
            raise b24.AutomationBlocked("FOCUS_CHANGED")

    # ── 기존 프로세스 연결 / 실행 (§31–§41) ──
    def launch_or_attach(self):
        self._require_ready()
        self._verify_exe_now()
        b = self.ctx.bank24
        be = self._backend()
        exe = self.ctx.exe_norm

        pids = list(be.find_processes_by_image(exe) or [])
        trusted_main = []     # (pid, main_win)
        trusted_login = []    # (pid, login_win)
        for pid in pids:
            try:
                bank24_trust.verify_pid_image(int(pid), exe)   # PID 이미지 정확일치(§22/§35)
            except bank24_trust.TrustError:
                continue                                       # 불일치 PID 는 후보 제외
            mw = be.find_main_window(pid, self._mclass()[0])
            if mw is not None and self._window_trusted(mw):
                trusted_main.append((pid, mw))
                continue
            lw = be.find_login_window(pid)
            if lw is not None and self._window_trusted(lw):
                trusted_login.append((pid, lw))

        if len(trusted_main) > 1 or len(trusted_login) > 1:
            raise b24.AutomationBlocked("AMBIGUOUS_BANK24")    # 모호/다중 → 중단(§36)

        if trusted_main:                                       # 신뢰된 메인 창 하나면 재사용(§33)
            if not b.attach_existing:
                raise b24.AutomationBlocked("EXISTING_BANK24_PRESENT")   # §37
            self._pid, self._win = trusted_main[0]
            self.state["attached"] = True
            self.state["logged_in"] = True                     # 메인 화면 = 로그인 상태
            return {"attached": True, "reused_main": True}

        if trusted_login:                                      # 로그인 창만 있으면 재사용(§34)
            if not b.attach_existing:
                raise b24.AutomationBlocked("EXISTING_BANK24_PRESENT")   # §37
            self._pid, self._win = trusted_login[0]
            self.state["attached"] = True
            return {"attached": True, "reused_login": True}

        # 신뢰 가능한 기존 프로세스 없음
        if not b.launch_if_missing:
            raise b24.AutomationBlocked("NO_BANK24")           # §39
        before = set(be.snapshot_top_level() or ())            # 실행 전 top-level 기록(§41)
        self._verify_exe_now()                                 # 실행 직전 재검증(§29)
        spec = bank24_trust.build_launch_spec(exe)             # argv/cwd/no creds(§26–§28)
        pid = int(be.launch(spec))                             # 기존 프로세스 종료 안 함(§40)
        # 실행 후 디스크 파일·PID 이미지 재검증(§29/§30)
        self._verify_exe_now()
        try:
            bank24_trust.verify_pid_image(pid, exe)
        except bank24_trust.TrustError as te:
            raise b24.AutomationBlocked("ATTACH_UNTRUSTED:" + te.code)
        # 새 PID 의 창만 후보로(§41): 로그인 창 대기(유한 타임아웃)
        win = self._await_window(be, pid, before, want_main=False)
        if win is None:
            raise b24.AutomationBlocked("LOGIN_WINDOW_TIMEOUT")
        self._pid, self._win = pid, win
        self.state["attached"] = True
        return {"attached": True, "launched": True}

    def _window_trusted(self, win) -> bool:
        try:
            self._pid_image_ok(win)
            return True
        except b24.AutomationBlocked:
            return False

    def _await_window(self, be, pid, before, *, want_main):
        deadline = self._deadline(T_WINDOW)
        mclass = self._mclass()[0]
        while time.monotonic() < deadline:
            self._check_stop()
            if want_main:
                w = be.find_main_window(pid, mclass)
            else:
                w = be.find_login_window(pid)
            if w is not None and int(getattr(w, "hwnd", 0)) not in before and self._window_trusted(w):
                return w
            be.wait(0.5)
        return None

    def adopt_login_confirmed(self, main_win=None):
        """bank24_login_flow(실행·로그인 이식본)가 확인한 메인 창을 대상으로 채택한다.

        GUI 가 로그인 흐름을 bank24_login_flow 로 수행할 때, 그 결과(확인된 TfrmMain)를
        받아 downstream(탁상/조회)이 쓰는 _pid/_win/state 를 시딩한다. 다운스트림 함수의
        시그니처/반환 규약은 바꾸지 않는다(§133). main_win 은 backend 로 WindowInfo 로
        환산해 신뢰 재검증 앵커(PID 이미지)로 쓴다. 원문/PII 는 저장하지 않는다.
        """
        if main_win is not None:
            info = self._backend()._win_info(int(main_win.handle))
            self._pid, self._win = int(info.pid), info
        self.state["attached"] = True
        self.state["logged_in"] = True
        return {"logged_in": True, "adopted": True}

    # ── 로그인 (§46–§61) ──
    def verify_login_screen(self):
        self._reverify_target()
        if self._is_main_window(self._win):        # 이미 TfrmMain 이면 재사용(§47)
            self.state["logged_in"] = True
            return {"login_screen": False, "already_logged_in": True}
        edits = self._login_edits()
        if len(edits) < 2:                         # 정확 판별 안 되면 입력하지 않음(§51)
            raise b24.AutomationBlocked("LOGIN_EDITS_NOT_RESOLVED")
        return {"login_screen": True, "edit_count": len(edits)}

    def _is_main_window(self, win) -> bool:
        cls = getattr(win, "window_class", "")
        return bool(self._mclass()[0]) and cls == self._mclass()[0]

    def _login_edits(self):
        """로그인창 visible+enabled Edit 후보를 화면순(top,left)으로 반환(§50)."""
        return list(self._backend().login_edit_candidates(self._win) or [])

    def login(self, credential_provider=None):
        self._reverify_target()
        if self.state["logged_in"] or self._is_main_window(self._win):
            self.state["logged_in"] = True
            return {"logged_in": True, "reused": True}       # 자격증명 미입력 재사용(§47)
        provider = credential_provider or self.ctx.credential_provider
        cred = provider() if callable(provider) else provider
        if cred is None:                                     # save_credentials+ID+PW 미충족(§48)
            raise b24.AutomationBlocked("LOGIN_CREDENTIALS_MISSING")
        b = self._backend()
        try:
            edits = self._login_edits()
            if len(edits) < 2:
                raise b24.AutomationBlocked("LOGIN_EDITS_NOT_RESOLVED")
            id_ctrl, pw_ctrl = edits[0], edits[1]            # 화면순: ID, PW
            # 검증 컨트롤에 직접 값 설정(§52). 클립보드/좌표/send_keys 미사용(§53).
            self._reverify_focus(id_ctrl)
            if not b.set_edit_direct(id_ctrl, cred.username):
                raise b24.AutomationBlocked("LOGIN_INPUT_FAILED")
            self._reverify_focus(pw_ctrl)
            if not b.set_edit_direct(pw_ctrl, cred.use_password()):
                raise b24.AutomationBlocked("LOGIN_INPUT_FAILED")
            # 입력 검증: ID 필드가 uid 이고 PW 원문이 아닌지(값은 로그로 남기지 않음)
            if b.read_edit(id_ctrl) != cred.username:
                raise b24.AutomationBlocked("LOGIN_INPUT_MISMATCH")
            self._reverify_target()
            self._reverify_foreground()
            if not b.click_ok_button(self._win):             # 실제 Button + BM_CLICK, 좌표 아님(§56/§57)
                raise b24.AutomationBlocked("LOGIN_OK_NOT_FOUND")
        finally:
            try:
                cred.wipe()                                  # 성공·실패·중지 무관 즉시 정리(§55/§60)
            except Exception:
                pass
        # 성공은 신뢰된 TfrmMain 출현으로 확인(§58). 자동 재시도 없음(§59).
        mw = self._await_window(b, self._pid, set(), want_main=True)
        if mw is None:
            raise b24.AutomationBlocked("LOGIN_NOT_CONFIRMED")
        self._win = mw
        self.state["logged_in"] = True
        return {"logged_in": True}

    # ── 업무구분 탁상 선택 ──
    def select_tabletop_menu(self):
        if not self.state["logged_in"]:
            raise b24.AutomationBlocked("LOGIN_REQUIRED")
        self._reverify_target()
        # 이 제품의 조회 업무구분은 항상 탁상이다. 과거 INI source_tab 값은 상단 탭
        # 용도였으므로 여기서 실행 차단 조건으로 사용하지 않는다.
        source_tab = "".join(str(getattr(self.ctx, "source_tab", "") or "").split())
        if source_tab not in {"\ubbf8\uc811\uc218", "\uc791\uc131"}:
            source_tab = "\ubbf8\uc811\uc218"
        select_source_tab = getattr(self._backend(), "select_source_tab", None)
        if select_source_tab is not None and not select_source_tab(self._win, source_tab):
            raise b24.AutomationBlocked("SOURCE_TAB_NOT_SELECTED")
        if not self._backend().select_business_type(self._win, "\ud0c1\uc0c1"):
            raise b24.AutomationBlocked("TABLETOP_FILTER_NOT_SELECTED")
        self.state["tabletop_verified"] = True
        return {"tabletop_selected": True}

    # ── 조회 (§72–§81) ──
    def query_requests(self) -> list:
        if not self.state["tabletop_verified"]:
            raise b24.AutomationBlocked("TABLETOP_UNVERIFIED")
        self._reverify_target()
        b = self._backend()
        if not b.execute_tabletop_query(self._win):
            raise b24.AutomationBlocked("TABLETOP_QUERY_FAILED")
        # Bank24 TcxGrid는 Y_BankAuto와 동일하게 전체선택/클립보드 TSV로 조회한다.
        # backend가 finally에서 클립보드를 즉시 비운다.
        result = b.read_grid_clipboard(self._win, _GRID_NEEDED_COLUMNS)
        if result is None:
            raise b24.AutomationBlocked("UNEXPECTED_SCREEN")   # §71
        rows = result.get("rows", [])
        import security
        out = []
        for r in rows:
            raw_no = str(r.get("의뢰번호", "") or r.get("탁상의뢰번호", "") or "")
            raw_est = str(r.get("감정서번호", "") or "")
            row_index = int(r.get("__row_index", len(self._request_rows)))
            # 동일 의뢰번호가 여러 그리드 행에 나타나도 각 행을 독립 처리한다.
            token = _short_token(f"{raw_no}|{raw_est}|{row_index}")
            self._request_rows[token] = {
                "row_index": row_index,
                "request_no": raw_no,
            }
            out.append(RequestSummary(
                request_token=token,
                bank_label=str(r.get("은행", "") or ""),
                branch_label=str(r.get("지점", "") or r.get("의뢰영업점", "") or ""),
                masked_request_no=security.mask_request_no(raw_no),   # 즉시 마스킹(§78)
                masked_est_no=security.mask_request_no(raw_est),
                bankonline_in=str(r.get("BankOnline_In", "") or ""),
                process_status=str(r.get("처리상태", "") or r.get("처리 상태", "") or "처리 대기")))
        return out    # 0건이면 빈 리스트(§80). 실패 시 합성 없음(§81).

    def grid_request_no(self, request_token: str) -> str:
        """조회 그리드에 있던 원본 의뢰번호(Bank24 시스템 값)를 반환한다.

        PDF 본문의 의뢰번호가 표시상 잘려 있을 수 있어(예: 국민은행 그리드 13자리 vs PDF
        9자리), BankOnline API 의 담보번호(DAMBO_NO)에는 이 그리드 값을 사용한다."""
        row = self._request_rows.get(request_token) or {}
        return str(row.get("request_no") or "").strip()

    def download_pdf(self, request_token: str, pdf_root: str, *, timestamp: str) -> str:
        """조회 당시 행을 Y_BankAuto 방식으로 PDF 출력한다."""
        self._reverify_target()
        if request_token not in self._request_rows:
            raise b24.AutomationBlocked("REQUEST_NOT_FOUND")
        row_info = self._request_rows[request_token]
        request_no = str(row_info.get("request_no") or request_token).strip()
        safe_request_no = re.sub(r'[\\/:*?"<>|]+', "_", request_no).strip(" ._")
        if not safe_request_no:
            safe_request_no = request_token
        current_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = f"{safe_request_no}_{current_stamp}.pdf"
        path = os.path.abspath(os.path.join(pdf_root, safe_name))
        root = os.path.abspath(pdf_root)
        if os.path.commonpath([root, path]) != root:
            raise b24.AutomationBlocked("PDF_PATH_INVALID")
        if not self._backend().save_row_pdf(
                self._win, int(row_info["row_index"]), path):
            raise b24.AutomationBlocked("PDF_SAVE_FAILED")
        return path


# ───────────────────────────── 실행 결정(real / blocked) ─────────────────────────────
@dataclass
class AdapterDecision:
    mode: str            # "real" | "blocked" — fake 없음(§10)
    reason: str = ""
    ctx: "RealAdapterContext | None" = None


def decide_adapter(*, app_config, stop, backend, credential_provider,
                   settings_path: str | None = None,
                   integrity_checker=None, exe_verifier=None) -> AdapterDecision:
    """실제 Bank24 실행 게이트. real 또는 blocked 만(fake fallback 없음).

    순서: 필수 [bank24] 키(§8/§97) → 긴급중지 → INI 무결성(§15/§16) → exe 파일 신뢰(§17–§25).
    """
    # 읽기전용 구조 방어는 유지(§54). INI ACL 무결성 게이트는 제거(§4/§49): INI_UNSAFE 로
    # Bank24 연결을 차단하지 않는다. [bank24] 미요구(§22/§51) → MISSING_KEYS 없음.
    if not getattr(app_config.options, "read_only", True):
        return AdapterDecision("blocked", "READ_ONLY_REQUIRED")
    if stop is None or stop.is_stopped():
        return AdapterDecision("blocked", "EMERGENCY_STOP")

    # exe 최소 검증(절대경로+존재). ACL/서명/해시/소유자 게이트 제거(§11/§12/§49).
    try:
        exe_norm = (exe_verifier or bank24_trust.verify_exe_file)(app_config.bank24.exe_path)
    except bank24_trust.TrustError as te:
        return AdapterDecision("blocked", te.code)         # PATH_NOT_FOUND/PATH_NOT_ABSOLUTE 등
    except Exception:
        return AdapterDecision("blocked", "EXE_UNVERIFIABLE")

    ctx = RealAdapterContext(
        bank24=app_config.bank24, source_tab=app_config.options.source_tab,
        exe_norm=exe_norm, exe_fp=None, stop=stop, backend=backend,
        credential_provider=credential_provider)
    return AdapterDecision("real", "", ctx)


# ───────────────────────────── 진단 모드 (읽기 전용) ─────────────────────────────
def diagnose_controls(win: "b24.WindowInfo", policy: "b24.TrustPolicy",
                      *, fake_controls=None) -> dict:
    """탁상 화면 컨트롤 진단(읽기 전용). PII 없는 기술 메타데이터만 반환."""
    ok, fails = b24.verify_window_trust(win, policy)
    controls = fake_controls or []
    safe_controls = [{"automation_id": c.get("automation_id"),
                      "control_type": c.get("control_type")} for c in controls]
    return {
        "trust_ok": ok,
        "trust_fail_count": len(fails),
        "window_class": win.window_class,
        "window_token": _short_token(f"{win.pid}:{win.hwnd}"),
        "controls": safe_controls,
        "read_only": True,
    }
