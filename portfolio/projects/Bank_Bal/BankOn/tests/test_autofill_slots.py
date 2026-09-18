"""다물건 전체 슬롯 입력 — 화면 물건 행을 늘려 순번대로 채운다(2026-09-16).

실측 01-2609-3-2871(하나 잠실동): 명세가 토지 1 + 건물 단가별 3 인데 종전 러너는 슬롯 1만
채우고 '나머지 수동' 비고를 남겼다. 담당자가 4행을 손으로 만들어 넣었다.
여기선 화면 조작을 가짜로 두고 **행 배정·추가·건너뜀 판단**만 고정한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import autofill_slot as A         # noqa: E402
from bankon.ui import navigate    # noqa: E402


class TestScreenSlot:
    def test_한자리_순번을_읽는다(self):
        assert A._screen_slot({"일련번호": "3"}) == 3
        assert A._screen_slot({"물건일련번호": "2"}) == 2

    def test_아홉자리_serial_은_순번이_아니다(self):
        # 하나 폼엔 일련번호가 둘 — 121877302(BANK24 자동생성)와 순번 1.
        assert A._screen_slot({"일련번호": "121877302", "일련번호_1": "1"}) == 1

    def test_없으면_None(self):
        assert A._screen_slot({"일련번호": ""}) is None

    def test_금액은_숫자만_비교한다(self):
        assert A._screen_amount({"감정평가액": "7,769,100,000"}) == "7769100000"
        assert A._screen_amount({"감정가액": "3,140,000,000"}) == "3140000000"   # 새마을 라벨


# ── 2871 모사: 토지 + 건물 단가 3개 ─────────────────────────────────────────────
OBJECTS = {
    "1": {"물건종류": "토지", "감정평가액": "7769100000", "사정면적": "165.30"},
    "2": {"물건종류": "건물", "감정평가액": "16750800", "사정면적": "31.02"},
    "3": {"물건종류": "건물", "감정평가액": "514337040", "사정면적": "680.34"},
    "4": {"물건종류": "건물", "감정평가액": "48026520", "사정면적": "98.82"},
}


class DeadGrid:
    """물건 그리드가 아닌 그리드 — 키를 눌러도 순번이 안 움직인다(하나 폼 왼쪽 그리드)."""

    def set_focus(self):
        pass


class FakeScreen:
    """물건 그리드를 흉내 낸다 — 키 입력으로 현재 행이 움직이고, 행 추가로 늘어난다."""

    def __init__(self, monkeypatch, *, rows=1, can_add=True, amounts=None, decoys=0):
        self.rows, self.current, self.can_add = rows, 1, can_add
        self.amounts = dict(amounts or {})       # 행번호 -> 화면에 이미 있는 감정평가액
        self.filled: dict[int, dict] = {}
        self.added = 0
        self.tried: list = []                    # 행 추가를 시도한 그리드 순서
        # 후보는 '오른쪽 것부터' — 진짜 물건 그리드가 뒤에 오게 두어 탐색을 강제한다.
        self.grids = [DeadGrid() for _ in range(decoys)] + [self]
        monkeypatch.setattr(A, "object_grids", lambda form: list(self.grids))
        monkeypatch.setattr(A, "send_keys", self._keys)
        monkeypatch.setattr(A.time, "sleep", lambda s: None)
        monkeypatch.setattr(A, "_add_row_on", self._add)
        monkeypatch.setattr(A.vf, "screen_values", lambda form: self._screen())
        monkeypatch.setattr(A.form, "fill", self._fill)

    def set_focus(self):
        self.focused = True

    def _keys(self, keys):
        if keys == "^{END}":
            self.current = self.rows
        elif keys == "^{HOME}":
            self.current = 1
        elif keys == "{DOWN}":
            self.current = min(self.current + 1, self.rows)

    def _add(self, form, grid, have):
        self.tried.append(grid)
        if grid is not self:
            raise RuntimeError("물건 그리드 팝업이 열리지 않음")    # 엉뚱한 그리드
        if not self.can_add:
            raise RuntimeError("물건 그리드 팝업이 열리지 않음")
        self.rows += 1
        self.added += 1
        self.current = self.rows
        return self.rows

    def _screen(self):
        return {"일련번호": str(self.current), "감정평가액": self.amounts.get(self.current, "")}

    def _fill(self, form, values, *, live, overwrite, combo_lists, **kw):
        self.filled[self.current] = values
        return []


class FakeVerify:
    COMBO_LISTS: dict = {}

    def __init__(self, reasons=None):
        self._reasons = reasons or {}

    def guard_reasons(self, ctx, values, seq):
        return self._reasons.get(seq, [])


class FakeMapping:
    def build(self, ctx, seq=None):
        return dict(OBJECTS[str(seq)])


def spec(verify=None):
    return A.Spec(bank="하나", form_class="TBNKHNB24DAMB", mapping=FakeMapping(),
                  verify=verify or FakeVerify(), kind_field="물건종류")


def test_행을_늘려_전_물건을_채운다(monkeypatch):
    screen = FakeScreen(monkeypatch, rows=1)
    s = spec()
    assert A.run_all_objects(s, None, object(), live=True, overwrite=False, total=4) == 0
    assert screen.added == 3                                   # 1행 → 4행
    assert sorted(screen.filled) == [1, 2, 3, 4]
    assert screen.filled[3]["사정면적"] == "680.34"            # 3행 = 2~9층 단가 행
    assert s.last_align["slots"].endswith("(전부)")


def test_행_추가가_안_되면_있는_행까지_채우고_사유를_남긴다(monkeypatch):
    screen = FakeScreen(monkeypatch, rows=1, can_add=False)
    s = spec()
    assert A.run_all_objects(s, None, object(), live=True, overwrite=False, total=4) == 0
    assert sorted(screen.filled) == [1]                        # 종전 동작(슬롯 1)으로 안전하게 후퇴
    assert "행 추가 실패" in s.last_align["slots"]
    assert "물건 4개 중 1개 입력" in s.last_align["slots"]


def test_이미_다른_물건_금액이_있는_행은_건드리지_않는다(monkeypatch):
    # 사람이 먼저 넣은 행(가드를 통과한 새 폼이라도 은행 선입력이 있을 수 있다) — fail-closed.
    screen = FakeScreen(monkeypatch, rows=4, amounts={2: "999,999,999"})
    s = spec()
    A.run_all_objects(s, None, object(), live=True, overwrite=False, total=4)
    assert sorted(screen.filled) == [1, 3, 4]
    assert "2행 화면 금액" in s.last_align["slots"]


def test_미지원_물건인_행만_건너뛴다(monkeypatch):
    screen = FakeScreen(monkeypatch, rows=4)
    s = spec(FakeVerify({"4": ["미지원 물건종류='기계기구'(토지·건물 아님)"]}))
    A.run_all_objects(s, None, object(), live=True, overwrite=False, total=4)
    assert sorted(screen.filled) == [1, 2, 3]
    assert "4행 보류" in s.last_align["slots"]


def test_순번을_못_읽으면_슬롯_하나로_후퇴한다(monkeypatch):
    screen = FakeScreen(monkeypatch, rows=1)
    monkeypatch.setattr(A.vf, "screen_values", lambda form: {"일련번호": ""})
    s = spec()
    A.run_all_objects(s, None, object(), live=True, overwrite=False, total=4)
    assert screen.added == 0
    assert "보류" in s.last_align["slots"]


def test_물건이_너무_많으면_자동입력하지_않는다(monkeypatch):
    FakeScreen(monkeypatch, rows=1)
    s = spec()
    assert A.run_all_objects(s, None, object(), live=True, overwrite=False,
                             total=A._MAX_ROWS + 1) == A.EXIT_UNALIGNED
    assert "상한" in s.last_align["slots"]


def test_엉뚱한_그리드가_있어도_진짜_물건_그리드를_찾는다(monkeypatch):
    """하나 폼엔 TcxGridSite 가 둘이고 왼쪽에선 아무 키도 안 먹었다(2871 실측).
    행 추가를 후보마다 시도해 **실제로 행이 늘어난 그리드**를 쓴다."""
    screen = FakeScreen(monkeypatch, rows=1, decoys=1)
    s = spec()
    A.run_all_objects(s, None, object(), live=True, overwrite=False, total=4)
    assert isinstance(screen.tried[0], DeadGrid)       # 엉뚱한 그리드를 먼저 시도했다가
    assert screen.added == 3                            # 진짜 그리드에서 3행 추가
    assert sorted(screen.filled) == [1, 2, 3, 4]
    assert s.last_align["slots"].endswith("(전부)")
