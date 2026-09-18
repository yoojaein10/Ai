"""작성 폼 열기 — 앞 문서의 남은 폼을 자기 폼으로 읽지 않는다.

실증 2026-09-15: 우리 2869 를 '사람 작성'으로 제외한 뒤 그 폼 창이 닫히지 않은 채 남았고,
이어진 국민 2867·기업 2873·2836 러너가 `wait_for_window(TBNK*)` 로 **그 남은 창**을 받아
2869 의 값(감정수수료 27,811,300)을 자기 값으로 읽어 세 건 모두 오제외됐다.
→ 남은 폼은 먼저 닫고, 못 닫으면 열지 않으며(fail-closed), 여는 것도 새로 생긴 창만 채택한다.
"""
from __future__ import annotations

import pytest

from bankon.ui import driver, navigate


class FakeMain:
    handle = 123


def window(handle: int, class_name: str) -> driver.WindowRef:
    return driver.WindowRef(handle=handle, class_name=class_name, title="담보", pid=9)


STALE = window(11, "TBNKWRB24DAMB")     # 우리 2869 의 남은 폼
FRESH = window(22, "TBNKKBB24DAMB")     # 이번에 새로 열린 국민 폼


class Fake:
    """open_forms 가 돌려줄 창 목록을 단계별로 바꿔 끼운다."""

    def __init__(self, monkeypatch, *, before, after, closes_ok=True, lying_close=False):
        self.forms = list(before)
        self.after = list(after)
        self.closes_ok = closes_ok
        self.lying_close = lying_close      # 닫혔다고 보고하지만 창은 남는 경우
        self.keys: list[str] = []
        monkeypatch.setattr(navigate, "open_forms", lambda session: tuple(self.forms))
        monkeypatch.setattr(navigate, "close_forms", self._close)
        monkeypatch.setattr(navigate, "_grid", lambda session: self)
        monkeypatch.setattr(navigate, "_menu_handles", self._menus)
        monkeypatch.setattr(navigate, "send_keys", self._send)
        monkeypatch.setattr(navigate, "close_context_menu", lambda: self.keys.append("ESC"))
        monkeypatch.setattr(driver, "POLL_INTERVAL", 0)
        monkeypatch.setattr(navigate.time, "sleep", lambda s: None)

    # 그리드 스텁
    def set_focus(self):
        pass

    def _close(self, session, *, timeout=20.0):
        self.keys.append("close_forms")
        if self.lying_close:
            return ()
        if self.closes_ok:
            self.forms = []
        return tuple(self.forms)

    def _menus(self):
        return {1} if "+{F10}" in self.keys else set()

    def _send(self, keys):
        self.keys.append(keys)
        if keys == navigate.WRITE_ACCELERATOR:
            self.forms = list(self.after)


def test_남은_폼을_닫고_새로_열린_창만_채택한다(monkeypatch):
    fake = Fake(monkeypatch, before=[STALE], after=[FRESH])
    form = navigate.open_write_form(navigate.Session(FakeMain()), home=False, timeout=1)
    assert form is FRESH
    assert fake.keys.index("close_forms") < fake.keys.index("+{F10}")   # 열기 전에 정리


def test_남은_폼을_못_닫으면_열지_않는다(monkeypatch):
    fake = Fake(monkeypatch, before=[STALE], after=[FRESH], closes_ok=False)
    with pytest.raises(navigate.NavigationError) as error:
        navigate.open_write_form(navigate.Session(FakeMain()), home=False, timeout=1)
    assert "TBNKWRB24DAMB" in str(error.value)
    assert "+{F10}" not in fake.keys          # 메뉴조차 건드리지 않는다(fail-closed)


def test_새_창이_안_열리면_남은_창을_돌려주지_않는다(monkeypatch):
    """종전 버그의 핵심 — 새 폼이 안 열렸는데도 wait_for_window 가 남은 STALE 을 돌려줬다.

    닫기가 '닫혔다'고 보고했지만 창은 남은 경우(우리 폼 실측 상황)를 흉내 낸다.
    """
    fake = Fake(monkeypatch, before=[STALE], after=[STALE], lying_close=True)
    with pytest.raises(navigate.NavigationError) as error:
        navigate.open_write_form(navigate.Session(FakeMain()), home=False, timeout=0)
    assert "열리지 않았습니다" in str(error.value)
    assert "ESC" in fake.keys                 # 컨텍스트 메뉴는 정리한다
