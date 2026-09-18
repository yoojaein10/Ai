"""수집해 둔 콤보 선택지 읽기 — 자동선택의 빠른 길에 쓰인다."""
from __future__ import annotations

from bankon.ui import combos

SAMPLE = """# 농협 담보 콤보 선택지 (TBNKNHB24DAMB)

## 번지구분  (TcxDBLookupComboBox, 현재값='일반', 좌표=1019,498)
- 일반
- 산
- 기타

## 물건종류  (TcxDBLookupComboBox, 현재값='답', 좌표=546,412)
- 대
- 답

## 물건종류  (TcxDBLookupComboBox, 현재값='토지', 좌표=1019,429)
- 토지
- 건물

## 대표,지사장2  (TcxDBLookupComboBox, 현재값='', 좌표=455,206)
- (수집 실패)
"""


class TestParse:
    def test_라벨별_항목을_읽는다(self):
        table = combos._parse(SAMPLE)
        assert table["번지구분"] == ("일반", "산", "기타")

    def test_같은_라벨은_먼저_나온_것(self):
        # `driver.find_by_label` 도 첫 라벨을 집으므로 규칙을 맞춘다.
        table = combos._parse(SAMPLE)
        assert table["물건종류"] == ("대", "답")

    def test_수집_실패는_담지_않는다(self):
        assert "대표,지사장2" not in combos._parse(SAMPLE)

    def test_없는_폼은_빈_결과(self):
        assert combos.for_form("TBNK없는폼") == {}
        assert combos.items_for("TBNK없는폼", "번지구분") == ()


class TestRealFile:
    """실제 수집물이 있으면 그대로 읽히는지."""

    def test_농협_목록(self):
        table = combos.for_form("TBNKNHB24DAMB")
        if not table:
            return                       # 아직 수집 안 한 환경이면 건너뛴다
        assert "일반" in table.get("번지구분", ())
        assert "대" in table.get("공부지목", ())
        assert "일반주거지역" in table.get("용도지역", ())
        assert len(table.get("심사자", ())) > 50      # 직원 목록
