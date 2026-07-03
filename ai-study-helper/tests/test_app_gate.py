"""PIN 게이트 E2E: 실제 앱 스크립트(streamlit_app.py)를 AppTest로 구동해 검증.

브라우저 없이 Streamlit 위젯 상호작용(입력·클릭·리런)을 재현한다 —
게이트가 화면 단에서 실제로 막는지/통과시키는지를 코드 레벨에서 고정.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))  # 앱과 같은 방식으로 pin_auth 모듈 로드

import pin_auth  # noqa: E402  (sys.modules에 선등록 → 앱도 같은 인스턴스 사용)

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(ROOT / "app" / "streamlit_app.py")


@pytest.fixture(autouse=True)
def isolated_users(tmp_path, monkeypatch):
    monkeypatch.setattr(pin_auth, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(pin_auth, "WRONG_PIN_DELAY_SEC", 0)
    yield


def _run_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    return at


def test_gate_shown_before_login():
    at = _run_app()
    assert "user_id" not in at.session_state
    # 게이트 화면: 입장 버튼은 있고, 사이드바(자료 목록)는 없어야 한다
    assert any("입장" in (b.label or "") for b in at.button)
    assert len(at.sidebar.button) == 0


def test_enter_with_wrong_pin_blocked():
    at = _run_app()
    at.text_input(key="pin-enter").set_value("9999")
    at.button(key="btn-enter").click().run()
    assert "user_id" not in at.session_state
    assert any("등록되지 않은" in str(e.value) for e in at.error)


def test_register_then_enter_and_isolation():
    # 등록 (형식·중복 검사는 test_pin_auth.py에서 검증 — 여기선 화면 흐름)
    at = _run_app()
    at.text_input(key="pin-new").set_value("0704")
    at.text_input(key="pin-new2").set_value("0704")
    at.button(key="btn-new").click().run()
    assert "user_id" in at.session_state
    user_id = at.session_state["user_id"]

    # 재접속 후 같은 PIN으로 입장 → 같은 사용자
    at2 = _run_app()
    at2.text_input(key="pin-enter").set_value("0704")
    at2.button(key="btn-enter").click().run()
    assert at2.session_state["user_id"] == user_id


def test_register_mismatch_rejected():
    at = _run_app()
    at.text_input(key="pin-new").set_value("0704")
    at.text_input(key="pin-new2").set_value("0705")
    at.button(key="btn-new").click().run()
    assert "user_id" not in at.session_state
    assert any("일치하지 않습니다" in str(e.value) for e in at.error)
