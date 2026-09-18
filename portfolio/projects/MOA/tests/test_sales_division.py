from app.services.sales_division import YAK_SALES_DIVISION, sales_division


def test_감정서번호_세번째_자리로_정한다():
    # 재무팀 표(2026-08-05) 기준
    assert sales_division("01-2608-1-0001") == "01"  # 보상부문
    assert sales_division("01-2608-2-0001") == "02"  # 경매부문
    assert sales_division("01-2607-3-2220") == "03"  # 담보부문
    assert sales_division("01-2608-4-0001") == "04"  # 일반거래부문
    assert sales_division("01-2608-5-0001") == "05"  # 컨설팅부문
    assert sales_division("01-2608-6-0462") == "09"  # 약식부분(6→09)
    assert sales_division("01-2608-7-0001") == "07"  # 기타(실비)
    assert sales_division("01-2608-8-0001") == "06"  # 공시업무(8→06, 약식 아님)


def test_A는_일반거래부문():
    """표에 없던 자리 — 사용자 확정(2026-08-05). 최근 1년 818건."""
    assert sales_division("01-2607-A-0104") == "04"
    assert sales_division("01-2605-a-0079") == "04"


def test_가지번호_형식도_유형을_찾는다():
    """분할 청구 감정서(01YYMM-T-NNNN-K, 대시 없는 변형 포함) — 2026-08-13
    실증: 012603-1-0109-1 기본전표가 매출구분 없이 나가 발행 검증 오류."""
    assert sales_division("012603-1-0109-1") == "01"   # 보상부문
    assert sales_division("012607-4-023621") == "04"   # 일반거래부문
    assert sales_division("012608-A-0117-2") == "04"
    assert sales_division("012608-3-2554-1") == "03"


def test_정하지_못한_자리는_비운다():
    """틀린 구분으로 보내느니 매출구분 없이 보낸다."""
    assert sales_division("01-2608-B-0001") is None
    assert sales_division("01-2608-9-0001") is None
    assert sales_division("01-2608-0-0001") is None
    assert sales_division("400579349") is None
    assert sales_division("") is None
    assert sales_division(None) is None


def test_국민약식은_09_고정():
    assert YAK_SALES_DIVISION == "09"


def test_약식_유형은_기타수수료_계정():
    from app.services.sales_division import sales_account

    assert sales_account("01-2607-6-0442") == "4010002"
    assert sales_account("01-2607-3-2258") == "4010001"
    assert sales_account("012607-6-0442-1") == "4010002"  # 가지번호 약식
    assert sales_account("012603-1-0109-1") == "4010001"
    assert sales_account("400576463") == "4010001"  # 400은 약식 전용 경로에서 처리
    assert sales_account(None) == "4010001"
