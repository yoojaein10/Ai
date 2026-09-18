from bankon.mapping.shinhan import _below_dong


def test_below_dong():
    assert _below_dong('서울특별시 강동구 길동 415-9 "강동역에스케이리더스뷰" 제103동 제6층 제607호') == "415-9 강동역에스케이리더스뷰 제103동 제6층 제607호"
    assert _below_dong("서울특별시 강동구 길동 415-9번지 강동역에스케이리더스뷰 제103동") == "415-9 강동역에스케이리더스뷰 제103동"
    assert _below_dong("경기도 안성시 양성면 도곡리 356-2 외 1필지") == "356-2 외 1필지"
    assert _below_dong("경기도 안성시 양성면 도곡리 356-26 ") == "356-26"
    assert _below_dong("서울 강서구 마곡동 798-3 제9층 제901호") == "798-3 제9층 제901호"
    assert _below_dong("경기도 여주시 점봉동 산 12-3") == "산 12-3"
    assert _below_dong("서울 중구 을지로3가 12") == "12"
    assert _below_dong("") is None
    assert _below_dong("경기도 여주시 점봉동") is None
