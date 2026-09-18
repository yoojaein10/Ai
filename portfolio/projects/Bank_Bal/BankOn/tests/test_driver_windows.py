"""find_windows 제목 필터 — `TfrmMain` 이 ApWorks 와 겹치는 실측 사고의 회귀 방지.

2026-08-24: cli open 이 ApWorks 의 TfrmMain("ApWorks - [메인리스트]")에 붙어
'감정서조회' 칸을 못 찾고 죽었다. 메인 창은 제목 힌트로도 걸러야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from bankon.ui import driver


@dataclass
class FakeElement:
    class_name: str
    name: str
    handle: int
    process_id: int


def _fake_elements(monkeypatch, elements):
    monkeypatch.setattr(driver, "find_elements", lambda **kwargs: elements)


APWORKS = FakeElement("TfrmMain", "ApWorks - [메인리스트]", 0x100, 111)
BANK24 = FakeElement("TfrmMain", "BANK24 - [금융기관온라인 메인]", 0x200, 222)


def test_title_hint_excludes_apworks(monkeypatch):
    _fake_elements(monkeypatch, [APWORKS, BANK24])
    found = driver.find_windows(driver.MAIN_CLASS, title_any=driver.MAIN_TITLE_HINTS)
    assert [w.handle for w in found] == [0x200]


def test_title_hint_matches_alt_title(monkeypatch):
    # 로그인 직후엔 제목이 '금융기관온라인(BANK ONLINE) X11' 꼴이기도 하다.
    alt = FakeElement("TfrmMain", "금융기관온라인(BANK ONLINE) X11", 0x300, 333)
    _fake_elements(monkeypatch, [APWORKS, alt])
    found = driver.find_windows(driver.MAIN_CLASS, title_any=driver.MAIN_TITLE_HINTS)
    assert [w.handle for w in found] == [0x300]


def test_no_hint_keeps_old_behaviour(monkeypatch):
    _fake_elements(monkeypatch, [APWORKS, BANK24])
    found = driver.find_windows(driver.MAIN_CLASS)
    assert len(found) == 2


def test_bank24_missing_returns_empty(monkeypatch):
    _fake_elements(monkeypatch, [APWORKS])
    found = driver.find_windows(driver.MAIN_CLASS, title_any=driver.MAIN_TITLE_HINTS)
    assert found == ()
