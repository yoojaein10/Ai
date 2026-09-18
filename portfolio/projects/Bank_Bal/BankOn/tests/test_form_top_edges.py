"""위치 표기 `위좌`/`위우` — 밴드 **최상단 행**의 왼쪽/오른쪽 칸(수협 법정동코드 시군구/읍면동, 인계본 감사 P0-2 → 이식 2026-09-10).

숫자 인덱스는 폼 변형마다 밴드 구성이 달라지면 어긋나지만 '최상단 행의 좌/우' 는 유지된다.
오프라인(화면 덤프 dict)과 라이브(컨트롤)가 같은 `pick_from` 을 쓴다.
"""
from __future__ import annotations

from bankon.ui import form


def _f(left, top, value):
    return (left, {"left": left, "top": top, "value": value})


class TestTopEdges:
    # 수협 실폼(fields_TBNKSSB24DAMB.md): 법정동 시군구(-1326,391)·읍면동(-1263,391) / 등기번호(-1036,396) / 소재지(-1452,415)
    BAND = [_f(-1326, 391, "11290"), _f(-1263, 391, "12500"), _f(-1036, 396, "11441996072170"), _f(-1452, 415, "서울 성북구 안암동5가")]

    def test_표기를_받아들인다(self):
        assert form.BAND_SPEC.match("법정동코드시군구@물건구분코드~번지구분[위좌]").group("index") == "위좌"
        assert form.display_label("법정동코드읍면동@물건구분코드~번지구분[위우]") == "법정동코드읍면동"

    def test_최상단_행의_좌우(self):
        assert form.pick_from(self.BAND, "위좌")["value"] == "11290"
        assert form.pick_from(self.BAND, "위우")["value"] == "12500"

    def test_아래_행은_3px_넘게_떨어져_있어_섞이지_않는다(self):
        # 등기번호(396)는 391 과 5px 차 — 최상단 행에 안 들어간다(들어가면 3칸이 돼 None 이 된다)
        assert form.pick_from(self.BAND, "위좌") is not None

    def test_최상단_행이_두_칸이_아니면_안_짚는다(self):
        one = [_f(-1326, 391, "a"), _f(-1036, 420, "b")]
        assert form.pick_from(one, "위좌") is None
        three = [_f(-1326, 391, "a"), _f(-1263, 392, "b"), _f(-1200, 390, "c")]
        assert form.pick_from(three, "위우") is None

    def test_top_을_모르면_안_짚는다(self):
        unknown = [(-1326, {"left": -1326, "value": "a"}), (-1263, {"left": -1263, "value": "b"})]
        assert form.pick_from(unknown, "위좌") is None

    def test_왼쪽_오른쪽은_종전대로(self):
        assert form.pick_from(self.BAND, "왼쪽")["value"] == "서울 성북구 안암동5가"
        assert form.pick_from(self.BAND, "오른쪽")["value"] == "11441996072170"


class TestReadback:
    def test_되읽기는_콤마_하이픈_공백을_무시한다(self):
        from bankon.ui import driver
        assert driver._readback_norm("103-910016-91404") == driver._readback_norm("10391001691404")   # 하나 계좌 마스크(실측 2722)
        assert driver._readback_norm("22,021,000,000") == driver._readback_norm("22021000000")
        assert driver._readback_norm("서울 성북구") == driver._readback_norm("서울성북구")
        assert driver._readback_norm("1234") != driver._readback_norm("1235")
