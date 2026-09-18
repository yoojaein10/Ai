"""감정서 지분 — 거래처명 괄호 표기 파서와 인별 지분 결정 우선순위.

괄호 표기 변형은 2026-08-25 9개월 시트 실측에서 나온 것 그대로다. 숫자는 십분율
(5 → 50%, 2.5 → 25%, 9 → 90%), 1 이하면 비율(0.33 → 33%), 10 초과면 이미 퍼센트(안100).
"""

from app.services.bonus.shares import (
    ShareHit,
    match_note_names,
    parse_share_note,
    resolve_share,
)


def test_공백_콜론_쉼표_붙여쓰기_전부_같은_지분으로_읽는다():
    assert parse_share_note("신림제7구역 주택재개발조합 (김5 강2.5 조2.5)").shares == {"김": 50, "강": 25, "조": 25}
    assert parse_share_note("한국토지신탁 (김5:조2.5:강2.5)").shares == {"김": 50, "조": 25, "강": 25}
    assert parse_share_note("고천가구역 재개발정비사업조합(김5조2.5강2.5)").shares == {"김": 50, "조": 25, "강": 25}
    assert parse_share_note("서울주택도시공사 (이5,조5) 26.3.9 성과 비율 확정").shares == {"이": 50, "조": 50}
    assert parse_share_note("주택도시보증공사 든든전세임대 (안9:이1)").shares == {"안": 90, "이": 10}
    assert parse_share_note("(주)삼천리 (이덕권5:이준희5)").shares == {"이덕권": 50, "이준희": 50}
    assert parse_share_note("방배15재건축정비사업조합 (김0.33 강0.33 조0.33)").shares == {"김": 33, "강": 33, "조": 33}


def test_법카_꼬리는_법인카드_몫으로_따로_읽는다():
    note = parse_share_note("이지안 (HF Web 보증) (안6:황4/법카 안100)")
    assert note.shares == {"안": 60, "황": 40}
    assert note.bc == {"안": 100}
    assert parse_share_note("박경호 (HF Web 보증) (안6:황4)").bc is None


def test_퍼센트만_적힌_공동유치는_블록_주인_몫이다():
    assert parse_share_note("우리은행 여신업무센터(약수역지점)장 (50%)").shares == {"*": 50}
    assert parse_share_note("우리은행 여신업무센터(광희동금융센터) 50%").shares == {"*": 50}
    assert parse_share_note("김미경 (주택금융공사HF Web 보증 / 본사 수수료 기준 90%))").shares == {"*": 90}


def test_지분이_아닌_괄호는_무시한다():
    for text in (
        "농협은행 안산도매시장지점 (2.7입금)",
        "전북은행 원광지점 (2,3월 중복지급 재정산)",
        "영통2구역주택재건축정비사업 (17.06.08 용역계약서 작성)",
        "롯데건설주식회사 (200만원 추가 산정)",
        "세화새마을금고 (012509-4-0310-1~49합산)",
        "(주)KH엘텍(2.4입금_24년 12월 접수)",
        "반포아파트(제3주구) 주택재건축",
        "신한은행 원주금융센터",
        "",
        None,
    ):
        assert parse_share_note(text) is None, text
    assert parse_share_note("반포아파트(제3주구) 주택재건축 (강5:조5)").shares == {"강": 50, "조": 50}


def test_약칭은_블록_후보_중_성이_하나뿐일_때만_푼다():
    assert match_note_names({"김": 50, "강": 25, "조": 25}, ["김형식", "강무진", "조근렬"]) == {
        "김형식": 50, "강무진": 25, "조근렬": 25,
    }
    assert match_note_names({"이": 50}, ["이덕권", "이준희"]) == {}      # 동성 둘 → 모호
    assert match_note_names({"이덕권": 50, "이준희": 50}, ["이덕권", "이준희"]) == {"이덕권": 50, "이준희": 50}
    assert match_note_names({"*": 50, "안": 90}, ["안창덕"]) == {"*": 50, "안창덕": 90}
    assert match_note_names({"황": 40}, ["안창덕"]) == {}


def test_지분_우선순위는_승인배분_수기_시드_부킹_비율표_괄호_균등_순이다():
    common = dict(fee_total=1_000_000, names=["김형식", "강무진"])
    assert resolve_share("강무진", in_price=250_000, manual=40, **common) == ShareHit(25, "IN_PRICE")
    assert resolve_share("강무진", manual=40, seed=25, **common) == ShareHit(40, "MANUAL")
    assert resolve_share("강무진", seed=25, booking=50, **common) == ShareHit(25, "SEED")
    assert resolve_share("강무진", booking=50, charge_idx=30, **common) == ShareHit(50, "BOOKING")
    assert resolve_share("강무진", charge_idx=30, note={"강무진": 20}, **common) == ShareHit(30, "CHARGE_IDX")
    assert resolve_share("강무진", note={"강무진": 20}, **common) == ShareHit(20, "NOTE")
    assert resolve_share("강무진", note={"*": 50}, **common) == ShareHit(50, "NOTE")
    assert resolve_share("강무진", **common) == ShareHit(50, "EQUAL")
    assert resolve_share("강무진", fee_total=1_000_000, names=["강무진"]) == ShareHit(100, "EQUAL")
    assert resolve_share("강무진", fee_total=1_000_000, names=[]) == ShareHit(100, "EQUAL")
    # 승인 배분액이 있어도 순수수료가 0이면 비율을 만들 수 없다 → 다음 순위
    assert resolve_share("강무진", in_price=250_000, fee_total=0, seed=25, names=[]) == ShareHit(25, "SEED")
