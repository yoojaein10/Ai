from app.services.bank_division import bank_division


def test_주요_은행_코드():
    assert bank_division("국민은행동백지점") == "040"
    assert bank_division("국민은행 상무지점") == "040"
    assert bank_division("(주)신한은행 익산금융센터") == "260"
    assert bank_division("중소기업은행 서초남지점") == "030"
    assert bank_division("우리은행 DL금융센터") == "200"
    assert bank_division("KEB하나은행 해운대동백지점") == "810"
    assert bank_division("한국산업은행") == "020"


def test_농협은_은행과_지역조합을_가른다():
    # 재무팀 주석: 120 농협회=농협은행 지점, 110 농협중=지역 조합
    assert bank_division("농협은행 일원동지점") == "120"
    assert bank_division("제천농업협동조합의림지점") == "110"
    assert bank_division("경기동부인삼농협") == "110"
    assert bank_division("구성농협 동백지점") == "110"


def test_2금융권():
    assert bank_division("사당새마을금고") == "840"
    assert bank_division("신협남서울") == "048"
    assert bank_division("이천시산림조합") == "870"
    # 축협은 160이 아니라 110 (재무팀 주석 기준, 2026-08-05 확정)
    assert bank_division("서울축산업협동조합") == "110"
    assert bank_division("서울축협염창동") == "110"
    assert bank_division("인천수협소래지점") == "070"
    assert bank_division("한국투자저축은행") == "860"
    assert bank_division("OK저축은행") == "850"


def test_은행이_아니면_기타():
    assert bank_division("주택도시보증공사") == "880"
    assert bank_division("한국주택금융공사 전북지사") == "880"
    assert bank_division("한국토지주택공사 경기남부지역본부") == "880"
    assert bank_division("제주지방법원") == "880"
    assert bank_division("현금영수증(국세청)") == "880"
    assert bank_division("기타-본사") == "880"
    assert bank_division("") == "880"
    assert bank_division(None) == "880"
