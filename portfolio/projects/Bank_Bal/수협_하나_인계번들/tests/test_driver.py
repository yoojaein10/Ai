"""화면 제어 기본기 — 입력칸 판별과 콤보 표기 비교.

창을 띄우지 않고 순수 함수만 검증한다(라벨 짝짓기·값 주입은 실폼이 필요해 제외).
"""
from __future__ import annotations

from bankon.ui import driver


class TestWindowMatches:
    """메인 창은 클래스만으로 잡으면 안 된다.

    실측(2026-09-08): BANK24 가 꺼진 상태에서 `TfrmMain` 만으로 찾으니 다른 Delphi 프로그램의
    창('위치도_New')이 잡혀 그 창에 조작이 갈 뻔했다. 제목 `BANK24` 를 같이 걸어야 한다.
    """

    def test_클래스만_주면_다른_프로그램도_잡힌다(self):
        assert driver.window_matches("TfrmMain", "위치도_New", "TfrmMain")

    def test_제목까지_주면_BANK24만_잡힌다(self):
        assert driver.window_matches("TfrmMain", "BANK24 - [금융기관온라인 메인]", "TfrmMain", driver.MAIN_TITLE)
        assert not driver.window_matches("TfrmMain", "위치도_New", "TfrmMain", driver.MAIN_TITLE)
        assert not driver.window_matches("TfrmMain", "ApWorks", "TfrmMain", driver.MAIN_TITLE)

    def test_클래스는_접두_일치(self):
        assert driver.window_matches("TBNKSSB24DAMB", "", "TBNK")
        assert not driver.window_matches("TcxGridSite", "", "TBNK")


class TestIsInput:
    """`find_by_label` 이 **입력칸만** 후보로 봐야 한다.

    실측(농협 2686): `표준지소재지` 가 `TPanel`(금액이 그려진 컨테이너)을 짚어, 덮어쓰기를
    켰다면 금액 자리에 주소를 타이핑할 뻔했다. 컨테이너를 거르면 그 경로가 막힌다.
    """

    def test_입력칸은_받는다(self):
        for name in ("TcxDBTextEdit", "TcxDBCurrencyEdit", "TcxDBDateEdit",
                     "TcxDBLookupComboBox", "TcxComboBox", "TcxDBMemo",
                     "TcxDBMaskEdit", "TcxSpinEdit", "TcxCheckBox", "TcxRadioGroup"):
            assert driver.is_input(name), name

    def test_컨테이너와_라벨은_거른다(self):
        for name in ("TPanel", "TcxLabel", "TLabel", "TStaticText", "TcxGridSite",
                     "TcxButton", "TGroupBox", "TfrmMain", ""):
            assert not driver.is_input(name), name

    def test_내부_편집칸은_거른다(self):
        # `editable()` 이 알아서 안쪽으로 내려가므로 후보로 잡으면 안 된다.
        assert not driver.is_input("TcxCustomInnerTextEdit")
        assert not driver.is_input("TcxCustomInnerDateEdit")


class Box:
    """rectangle() 흉내 — 좌표만 있으면 되는 순수 판정을 시험한다."""

    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


class TestLabelRank:
    """라벨↔칸 짝짓기 — 1픽셀 겹침으로 위 칸을 집던 버그를 막는다.

    실측 국민 `비   고`: 라벨(2593,855)~(2713,871) 이 바로 위 `총세대수` 칸
    (2719,836)~(2839,856) 과 **1px** 겹쳐 '같은 줄'로 잡혔고, 진짜 비고 칸
    (2593,873)~(2839,893) 은 '바로 아래'라 우선순위에서 밀렸다.
    """

    LABEL = Box(2593, 855, 2713, 871)          # 라벨 `비   고`
    ABOVE = Box(2719, 836, 2839, 856)          # 총세대수 칸 — 1px 만 겹친다
    BELOW = Box(2593, 873, 2839, 893)          # 진짜 비고 칸

    def test_1픽셀만_겹친_위칸은_같은_줄이_아니다(self):
        assert driver.label_rank(self.LABEL, self.ABOVE) is None

    def test_바로_아래칸을_짚는다(self):
        rank = driver.label_rank(self.LABEL, self.BELOW)
        assert rank is not None and rank[0] == 1

    def test_진짜_같은_줄은_그대로_잡는다(self):
        same_row = Box(2719, 850, 2839, 875)   # 라벨 중심(863)이 안에 들어온다
        rank = driver.label_rank(self.LABEL, same_row)
        assert rank == (0, 2719 - 2713)

    def test_같은_줄이_아래보다_먼저다(self):
        same_row = Box(2719, 850, 2839, 875)
        assert driver.label_rank(self.LABEL, same_row)[0] < \
            driver.label_rank(self.LABEL, self.BELOW)[0]

    def test_너무_멀면_아니다(self):
        far = Box(2713 + driver.MAX_LABEL_GAP + 1, 850, 3200, 875)
        assert driver.label_rank(self.LABEL, far) is None

    def test_왼쪽_칸은_아니다(self):
        left = Box(2300, 850, 2500, 875)
        assert driver.label_rank(self.LABEL, left) is None


class TestComboText:
    """콤보 표시값은 `이름(코드)` 라 코드를 떼고 비교해야 한다."""

    def test_내부코드를_뗀다(self):
        assert driver.combo_text("오병오(2893)") == "오병오"
        assert driver.combo_text("김치암(4189)") == "김치암"

    def test_코드가_없으면_그대로(self):
        assert driver.combo_text("일반") == "일반"
        assert driver.combo_text("일반주거지역") == "일반주거지역"

    def test_공백과_전각을_맞춘다(self):
        assert driver.combo_text("제２종일반주거지역") == "제2종일반주거지역"
        assert driver.combo_text(" 대 ") == "대"

    def test_숫자_괄호가_이름의_일부면_안_뗀다(self):
        # 코드는 **끝**에 붙는다. 중간 괄호는 이름이다.
        assert driver.combo_text("오피스텔(업무용)") == "오피스텔(업무용)"
        assert driver.combo_text("숙박시설(호텔,여관등)") == "숙박시설(호텔,여관등)"

    def test_빈값(self):
        assert driver.combo_text("") == "" and driver.combo_text(None) == ""
