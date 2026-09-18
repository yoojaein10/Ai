"""개요·비교표준지·원가법 파서 — 실제 의견서 조각을 픽스처로 사용."""
from __future__ import annotations

from decimal import Decimal

from bankon.parse import cost, outline, sections, standard_land

# 01-2401-1-0025 대상물건 개요 (구분건물형)
OUTLINE_FLAT = """<table><tr><td>소 재 지</td><td>서울특별시 구로구 개봉동 289-8외 1필지</td></tr>
<tr><td colspan="2"><table><tr><td>용도지역</td><td>제3종일반주거지역</td><td>토지면적(㎡)</td><td>234.4</td></tr>
<tr><td>건물용도</td><td>도시형생활주택(단지형다세대)</td><td>세대수</td><td>10세대</td></tr>
<tr><td>건물구조</td><td>철근콘크리트구조</td><td>연면적(㎡)</td><td>644.95</td></tr>
<tr><td>층</td><td>지하1층 / 지상 6층</td><td>사용승인일자</td><td>2024.01.26</td></tr></table></td></tr></table>"""

# 05-2012-4-0244 대상물건 개요 (토지+건물형)
OUTLINE_LAND = """<table><tr><td colspan="2">경기도 용인시 기흥구 보라동</td></tr>
<tr><td>토지</td><td><table><tr><td>기호</td><td>지 번</td><td>면 적(㎡)</td><td>지 목</td><td>용도지역</td><td>이용상황</td><td>도로교통</td><td>개별공시지가(원/㎡)</td></tr>
<tr><td>1</td><td>579-3</td><td>710.7</td><td>대</td><td>준주거</td><td>상업용</td><td>중로각지</td><td>2,040,000</td></tr></table></td></tr></table>"""


class TestOutline:
    def test_구분건물형을_읽는다(self):
        result = outline.parse(OUTLINE_FLAT)
        assert result.address == "서울특별시 구로구 개봉동 289-8외 1필지"
        assert result.zone == "제3종일반주거지역"
        assert result.struct == "철근콘크리트구조"
        assert result.approval_date == "2024-01-26"       # 2024.01.26 → ISO
        assert result.area_total == Decimal("644.95")
        assert result.area_land == Decimal("234.4")
        assert result.unit_count == 10                     # '10세대' → 10

    def test_층수를_지상지하로_나눈다(self):
        result = outline.parse(OUTLINE_FLAT)
        assert result.floors_text == "지하1층 / 지상 6층"
        assert result.ground_floors == 6
        assert result.basement_floors == 1

    def test_숫자만_있으면_지상층수로_본다(self):
        assert outline.Outline(floors_text="23").ground_floors == 23
        assert outline.Outline(floors_text="23").basement_floors is None

    def test_중첩표_안의_값도_찾는다(self):
        result = outline.parse(OUTLINE_LAND)
        assert result.category == "대"
        assert result.usage == "상업용"
        assert result.public_price == Decimal("2040000")

    def test_없는_항목은_None(self):
        result = outline.parse(OUTLINE_FLAT)
        assert result.road_address is None
        assert result.area_land_right is None

    def test_빈입력(self):
        assert outline.parse(None).address is None
        assert outline.parse("").struct is None


class TestDateParsing:
    def test_여러_표기를_ISO로(self):
        assert outline.to_iso_date("2024.01.26") == "2024-01-26"
        assert outline.to_iso_date("2018-12-26") == "2018-12-26"
        assert outline.to_iso_date("2007년 9월 18일") == "2007-09-18"

    def test_날짜가_아니면_None(self):
        assert outline.to_iso_date("귀 제시일") is None
        assert outline.to_iso_date("9999.99.99") is None


# 01-2401-1-0002 감정평가 개요
STANDARD = """<table><caption>&lt;경기도 여주시&gt;   (공시기준일: 2023. 01. 01.)</caption>
<tr><td>기호</td><td>소재지</td><td>면적(㎡)</td><td>지목</td><td>이용상황</td><td>용도지역</td><td>공시지가(원/㎡)</td><td>비고</td></tr>
<tr><td>A</td><td>교동 BL-단-1-25</td><td>240.6</td><td>대</td><td>주거나지</td><td>1종일주</td><td>672,800</td><td>선정</td></tr>
<tr><td>B</td><td>교동 BL-단-4-44</td><td>230.0</td><td>대</td><td>주거나지</td><td>1종일주</td><td>657,100</td><td></td></tr></table>"""


class TestStandardLand:
    def test_선정된_표준지만_고른다(self):
        result = standard_land.parse(STANDARD)
        assert result.found
        assert result.address == "교동 BL-단-1-25"
        assert result.price == Decimal("672800")           # B(657,100)가 아니다
        assert result.base_date == "2023-01-01"            # caption 에서
        assert result.zone == "1종일주"

    def test_선정표시가_없으면_첫후보를_쓴다(self):
        # 실측 0625·1674: 후보 2행·비고 '-' 인데 화면은 기호 A(첫 행)를 채택.
        # 감정사가 관련도순으로 나열해 A를 주 표준지로 쓴다.
        no_mark = STANDARD.replace("<td>선정</td>", "<td></td>")
        result = standard_land.parse(no_mark)
        assert result.address == "교동 BL-단-1-25"      # A(첫 행)
        assert result.price == Decimal("672800")        # B(657,100)가 아니다

    def test_비교표준지_표가_아니면_건너뛴다(self):
        other = "<table><tr><td>기호</td><td>지번</td></tr><tr><td>1</td><td>579-3</td></tr></table>"
        assert not standard_land.parse(other).found

    def test_후보가_하나면_선정표시없이도_쓴다(self):
        # 실측 0668: 단일 표준지 표는 비고가 '-' 라 '선정' 표시가 없다.
        # 공시기준일도 caption 이 아니라 표 바깥 인라인에 있어 원문에서 뽑는다.
        single = ("(공시기준일: 2025. 1. 1.)"
                  "<table><tr><td>기호</td><td>소재지</td><td>공시지가(원/㎡)</td><td>비고</td></tr>"
                  "<tr><td>A</td><td>팔곡이동 372-1</td><td>1,161,000</td><td>-</td></tr></table>")
        result = standard_land.parse(single)
        assert result.address == "팔곡이동 372-1"
        assert result.price == Decimal("1161000")
        assert result.base_date == "2025-01-01"        # 표 바깥 인라인에서


# 13-2602-3-0101 감정평가액 산출 과정
COST_TABLE = """<table><tr><td>기 호</td><td>층</td><td>용 도</td><td>재조달원가(원/㎡)</td><td>잔존연수</td><td>내용연수</td><td>산정단가(원/㎡)</td><td>결정단가(원/㎡)</td></tr>
<tr><td>가</td><td>지하1층</td><td>대피소, 보일러실</td><td>700,000</td><td>16</td><td>45</td><td>248,888</td><td>248,000</td></tr>
<tr><td>가</td><td>지상1층</td><td>근린생활시설</td><td>1,100,000</td><td>16</td><td>45</td><td>391,111</td><td>391,000</td></tr>
<tr><td>가</td><td>지상2,3층</td><td>주택</td><td>1,400,000</td><td>16</td><td>45</td><td>497,777</td><td>497,000</td></tr></table>"""

# 참고표 — 대상물건 값이 아니다(결정단가 컬럼 없음)
REFERENCE_TABLE = """<table><tr><td>용도</td><td>구조</td><td>급수</td><td>표준단가(원/㎡)</td><td>내용연수</td></tr>
<tr><td>공공청사</td><td>철근콘크리트조</td><td>2급</td><td>1,519,000</td><td>55(50~60)</td></tr></table>"""


class TestCost:
    def test_층별_행을_읽는다(self):
        layers = cost.parse(COST_TABLE)
        assert len(layers) == 3
        assert layers[0].floor == "지하1층"
        assert layers[0].useful_years == 45
        assert layers[0].remaining_years == 16
        assert layers[0].unit_price == Decimal("248000")

    def test_대표층은_단가가_가장_큰_층(self):
        best = cost.representative(cost.parse(COST_TABLE))
        assert best.unit_price == Decimal("497000")
        assert best.use == "주택"

    def test_참고표는_무시한다(self):
        # 결정단가 컬럼이 없으면 대상물건 산출표가 아니다.
        assert cost.parse(REFERENCE_TABLE) == ()

    def test_참고표와_섞여있어도_산출표만_고른다(self):
        layers = cost.parse(REFERENCE_TABLE + "\n" + COST_TABLE)
        assert len(layers) == 3
        assert layers[0].useful_years == 45

    def test_원가법이_아니면_빈결과(self):
        assert cost.parse("") == ()
        assert cost.representative(()) is None


class TestSections:
    def test_문단_제목으로_나눈다(self):
        result = sections.split(["대상물건 개요", "본문A", "감정평가 개요", "본문B"])
        assert [s.title for s in result] == ["대상물건 개요", "감정평가 개요"]
        assert result[0].body == "본문A"

    def test_박스형_제목표도_제목으로_인식한다(self):
        paragraphs = ["<table><tr><td>기준가치 및 감정평가 조건</td></tr></table>", "본문"]
        # 알려진 제목과 정확히 같지 않으면(띄어쓰기 차이) 제목이 아니다.
        assert sections.split(paragraphs) == ()
        paragraphs = ["<table><tr><td>그 밖의 사항</td></tr></table>", "본문"]
        assert [s.title for s in sections.split(paragraphs)] == ["그 밖의 사항"]

    def test_셀이_많은_표는_제목이_아니다(self):
        big = "<table><tr><td>그 밖의 사항</td><td>a</td><td>b</td><td>c</td></tr></table>"
        assert sections.split([big]) == ()

    def test_같은_제목이_여러번이면_본문이_긴것(self):
        result = sections.split(["감정평가액 결정", "짧음", "감정평가액 결정", "아주 긴 본문입니다"])
        assert sections.find(result, "감정평가액 결정").body == "아주 긴 본문입니다"

    def test_없는_섹션은_None(self):
        assert sections.find(sections.split(["대상물건 개요", "x"]), "그 밖의 사항") is None
