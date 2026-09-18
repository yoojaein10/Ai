

def test_지사_접두사는_하이픈을_요구하지_않는다():
    """재무팀이 잔금·분할 건에 쓰는 '012603-1-0109-1' 은 앞 하이픈이 없다.

    '01-%' 로 거르면 이런 번호가 통째로 빠져 입금 현황·미수금·입금발송내역·챗봇
    어디에도 안 나온다 (2026-08-20 제보). 실측: 1,098건 · 입금 102.3억 ·
    미수 5.69억이 빠져 있었다.
    """
    from app.services.receivables import management_no_filter

    _sql, params = management_no_filter(["01"])
    assert params == {"docid_prefix": "01_%"}, "하이픈을 붙이면 분할 건이 사라진다"

    sql, params = management_no_filter(["01", "05"])
    assert params == {"docid_prefix_0": "01_%", "docid_prefix_1": "05_%"}
    # varchar 컬럼에 CAST 없이 바인드하면 전 행 형변환이 일어나 몇 초씩 걸린다
    assert sql.count("CAST(") == 2
    # 접두사 두 자리뿐인 행(01·02·04·10·11·13)은 감정서가 아니라 잘못 들어간 값이다.
    # '01' 한 행에만 입금 36.8억이 붙어 있어 합계를 흔든다 (2026-08-20 사용자 지시).
    assert all(value.startswith(("01_", "05_")) for value in params.values())
