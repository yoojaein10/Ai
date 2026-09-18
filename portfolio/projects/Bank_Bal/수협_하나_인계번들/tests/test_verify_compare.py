"""검증 비교 정규화 — 표기 차이를 불일치로 세지 않는다.

`tools/` 는 패키지가 아니라 경로를 직접 넣어 불러온다(다른 검증 도구와 같은 방식).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import verify_fill_ibk as VI  # noqa: E402
import verify_fill_nh as VN  # noqa: E402


class TestNorm:
    def test_콤보코드와_콤마_공백을_없앤다(self):
        assert VN.norm("오병오(2893)") == "오병오"
        assert VN.norm("1,010,182,000") == "1010182000"
        assert VN.norm(" 추자동 192-3 ") == "추자동192-3"

    def test_전각을_반각으로(self):
        assert VN.norm("제２종일반주거지역") == "제2종일반주거지역"


class TestZeroPadded:
    """화면이 원본 그대로 0을 채워 넣는 칸이 있다 — `0618` 과 `618` 은 같은 지번이다.

    신한 280건 분석에서도 본번 48·부번 35건이 이 차이였고 우리 값이 맞다고 결론났다.
    """

    def test_지번은_앞의_0을_무시한다(self):
        assert VN.compare_text("본번지", "0618") == VN.compare_text("본번지", "618")
        assert VN.compare_text("부번지", "0006") == VN.compare_text("부번지", "6")

    def test_0_자체는_지킨다(self):
        assert VN.compare_text("본번지", "0000") == "0"

    def test_다른_칸은_그대로(self):
        # 등기번호는 자리수가 의미라 앞의 0을 떼면 안 된다.
        assert VN.compare_text("등기번호", "01342026003032") == "01342026003032"
        assert VN.compare_text("소유자명", "안준자") == "안준자"

    def test_숫자가_아니면_그대로(self):
        assert VN.compare_text("본번지", "산12") == "산12"

    def test_기업도_같은_규칙(self):
        # 같은 BANK24 화면이라 지번 표기 차이도 같다 — 농협에서 확인한 규칙을 옮겼다.
        assert VI.compare_text("본번지", "0618") == VI.compare_text("본번지", "618")
        assert VI.compare_text("부번지", "0000") == "0"
        assert VI.compare_text("등기번호", "01342026003032") == "01342026003032"
        assert VI.compare_text("용도지역", "제２종일반주거지역") == "제2종일반주거지역"
