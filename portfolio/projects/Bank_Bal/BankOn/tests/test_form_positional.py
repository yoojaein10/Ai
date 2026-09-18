"""라벨이 없는 칸을 **위치**로 짚는 표기 — `소재지@물건기호~번지구분[5]`.

농협 담보 폼에는 라벨이 아예 없거나(법정동코드·소재지) 앞칸과 라벨을 나눠 쓰는
(부동산구분 ← `물건종류`) 칸이 있다. 절대좌표 대신 **위아래 라벨 사이의 순서**로
지정하므로 창 크기가 바뀌어도 견딘다. 여기서는 표기 해석만 검증한다(밴드 수집은 실폼 필요).
"""
from __future__ import annotations

from bankon.ui import form


class TestPositional:
    def test_표기를_쪼갠다(self):
        spec = form.BAND_SPEC.match("소재지@물건기호~번지구분[5]")
        assert spec is not None
        assert spec.group("name") == "소재지"
        assert spec.group("above") == "물건기호"
        assert spec.group("below") == "번지구분"
        assert spec.group("index") == "5"

    def test_보통_라벨은_위치표기가_아니다(self):
        for label in ("소재지", "감정평가액", "비   고", "대표,지사장"):
            assert form.BAND_SPEC.match(label) is None

    def test_보고서에는_앞이름만_쓴다(self):
        assert form.display_label("법정동코드@물건기호~번지구분[3]") == "법정동코드"
        assert form.display_label("소재지") == "소재지"


class TestPickFrom:
    """순번·가장자리 고르기 — 라이브와 오프라인이 **같은 규칙**을 쓰도록 한 곳에 둔 함수."""

    ROW = [(601, "법정동코드"), (907, "용도지역"), (475, "소재지"), (907, "공부면적")]

    def test_순번(self):
        assert form.pick_from(self.ROW, "0") == "법정동코드"
        assert form.pick_from(self.ROW, "3") == "공부면적"

    def test_순번이_밴드보다_크면_없음(self):
        assert form.pick_from(self.ROW, "9") is None

    def test_가장자리(self):
        assert form.pick_from(self.ROW, "왼쪽") == "소재지"
        # 907 이 둘이라 오른쪽은 못 가른다 — 짚지 않는 게 안전하다.
        assert form.pick_from(self.ROW, "오른쪽") is None

    def test_유일한_오른쪽은_짚는다(self):
        rows = [(601, "가"), (907, "나"), (475, "다")]
        assert form.pick_from(rows, "오른쪽") == "나"

    def test_빈_밴드와_모르는_토큰(self):
        assert form.pick_from([], "0") is None
        assert form.pick_from(self.ROW, "가운데") is None


class TestNhBoxLabels:
    """농협 매핑이 쓰는 위치 표기가 실제 밴드 구성과 맞아야 한다.

    실측 14건에서 `물건기호`~`번지구분` 사이는 항상 같은 7칸이다:
        0 물건종류 · 1 부동산구분 · 2 우편번호 · 3 법정동코드
        4 소재지(짧은 표기) · 5 소재지 · 6 물건표시
    """

    def test_순번이_실측_구성과_같다(self):
        from bankon.mapping import nh

        expected = {nh.BOX_KIND: 1, nh.BOX_ZIP: 2, nh.BOX_LEGAL_CODE: 3,
                    nh.BOX_SITE_SHORT: 4, nh.BOX_SITE: 5, nh.BOX_DISPLAY: 6}
        for label, index in expected.items():
            spec = form.BAND_SPEC.match(label)
            assert spec is not None, label
            assert (spec.group("above"), spec.group("below")) == ("물건기호", "번지구분")
            assert int(spec.group("index")) == index


class TestSelectComboGuard:
    """목록에 없는 값은 타이핑 전에 거부 — 접두 검색 부작용('기계기구'→'기타', 2776 실측 2026-09-07) 방지."""

    def test_목록에_없는_값은_컨트롤을_건드리지_않는다(self, monkeypatch):
        from bankon.ui import driver
        touched = []
        monkeypatch.setattr(driver, "editable", lambda c: c)
        monkeypatch.setattr(driver, "read", lambda c: "")
        monkeypatch.setattr(form, "send_keys", lambda *a, **k: touched.append(a))
        class Ctl:
            def set_focus(self): touched.append("focus")
        try:
            form.select_combo(Ctl(), "기계기구", ["대지", "건물", "국산기계", "기타"])
        except driver.ValueRejected as exc:
            assert "목록에 없는 값" in str(exc)
        else:
            raise AssertionError("거부돼야 한다")
        assert touched == []                       # 타이핑·포커스 모두 안 함
