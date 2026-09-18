"""카드전표 규칙 검증 — 처리한 건 표시와 분할 순번(dedup_key)의 관계.

전표일자는 사용일자가 아니라 작업일이며(2026-08-04 재무팀 확인), 이미 처리한 건은
전표 상태별로 다른 보류 문구를 받아 화면이 전송완료 건만 숨길 수 있어야 한다.
"""

from decimal import Decimal

from app.services import card_vouchers as cv


def _usage(**over):
    base = dict(
        row_no=2, card_no="5404978001283967", card_alias="법인1", user_name="홍길동",
        use_date="20260731", appr_no='REDACTED_CONFIGURE_LOCALLY78', merchant="정진식당",
        merchant_biz_no="4840300117", total=Decimal("269000"),
        supply=Decimal("244545"), vat=Decimal("24455"),
        purpose="복리후생비", deductible=True, canceled=False,
        account_code="8110000",
    )
    base.update(over)
    return cv.CardUsage(**base)


def test_processed_status_is_carried_per_voucher_state():
    """이미 처리한 건은 전표 상태에 따라 다른 문구·상태를 받는다."""
    sent, draft, failed, fresh = (
        _usage(appr_no="1"), _usage(appr_no="2"), _usage(appr_no="3"), _usage(appr_no="4"),
    )
    usages = [sent, draft, failed, fresh]
    cv.assign_split_numbers(usages)
    cv.validate(usages, known_keys={
        sent.dedup_key: "S", draft.dedup_key: "D", failed.dedup_key: "F",
    })

    assert sent.processed_status == "S"
    assert "이미 아마란스로 전송된 건" in sent.holds
    assert draft.processed_status == "D"
    assert "이미 전표로 확정된 건(미전송)" in draft.holds
    assert failed.processed_status == "F"
    assert "전표 전송에 실패한 건" in failed.holds
    # 처리 이력이 없는 건은 그대로 생성 대상이어야 한다
    assert fresh.processed_status == "" and not fresh.on_hold


def test_세무구분은_카드매입이다():
    """법인카드 사용액은 매입 — 27.카드매입으로 싣는다.

    17은 카드매출이라 부가세 신고에서 매출로 잡힌다(재무팀 수기 전표
    실측 2026-08-11: 부가세대급금 라인 taxFg=27). 공제 건의 비용·부가세
    라인 모두 같은 값이어야 한다.
    """
    usage = _usage()
    lines = cv.build_lines(
        [usage], division_code="1000", voucher_date="20260812", menu_sq=10001,
        card_partners={usage.card_no: "C1"},
        merchant_partners={usage.merchant_biz_no: "M1"},
    )

    expense, vat, payable = lines
    assert cv.TAX_FG_CARD == "27"
    assert expense["taxFg"] == "27" and vat["taxFg"] == "27"
    assert "taxFg" not in payable  # 미지급금 라인엔 세무구분 없음(수기 동일)


def test_결제카드는_부가세라인_ctNb에_싣는다():
    """세무구분 27의 ctNb는 승인번호가 아니라 결제카드(카드 거래처코드)다.

    아마란스 자동수집 전표 실측(2026-08-14, 전표 20260813-00083): 결제카드는
    부가세대급금 라인 ctNb에만 실리고, 비용 라인과 미공제 한 줄 건에는 없다.
    승인번호를 넣으면 매입부가세정보의 결제카드 칸이 빈다.
    """
    usage = _usage()
    exempt = _usage(appr_no="87654321", deductible=False)
    lines = cv.build_lines(
        [usage, exempt], division_code="1000", voucher_date="20260812", menu_sq=10001,
        card_partners={usage.card_no: "C1"},
        merchant_partners={usage.merchant_biz_no: "M1"},
    )

    expense, vat, payable, ex_expense, ex_payable = lines
    assert vat["ctNb"] == "C1"
    assert "ctNb" not in expense and "ctNb" not in payable
    assert "ctNb" not in ex_expense and "ctNb" not in ex_payable


def test_거래처는_세_라인_모두_카드사로_통일한다():
    """재무팀 요청(2026-08-19): 비용·부가세대급금 라인의 거래처도 미지급금과
    같은 카드사여야 한다. 가맹점은 적요와 부가세 라인 사업자번호(regNb)로 남는다."""
    usage = _usage()
    exempt = _usage(appr_no="87654321", deductible=False)
    lines = cv.build_lines(
        [usage, exempt], division_code="1000", voucher_date="20260812", menu_sq=10001,
        card_partners={usage.card_no: "C1"},
        merchant_partners={usage.merchant_biz_no: "M1"},
    )

    assert [line["trCd"] for line in lines] == ["C1"] * 5
    expense, vat = lines[0], lines[1]
    assert expense["regNb"] == usage.merchant_biz_no  # 가맹점 사업자번호는 유지
    assert vat["regNb"] == usage.merchant_biz_no


def test_split_numbers_are_assigned_before_dedup_key_lookup():
    """한 승인건을 쪼갠 행은 서로 다른 dedup_key를 갖는다.

    중복 조회를 순번 매기기보다 먼저 하면 두 행이 같은 키로 보여 오판정한다.
    """
    first, second = _usage(purpose="복리후생비"), _usage(purpose="여비교통비")
    cv.assign_split_numbers([first, second])

    assert first.dedup_key.endswith("-1")
    assert second.dedup_key.endswith("-2")
    assert first.dedup_key != second.dedup_key


def test_known_keys_accepts_plain_set():
    """상태를 모르는 호출자가 집합만 넘겨도 보류 처리는 유지된다."""
    usage = _usage()
    cv.assign_split_numbers([usage])
    cv.validate([usage], known_keys={usage.dedup_key})

    assert usage.on_hold
    assert "이미 전표가 생성된 건" in usage.holds


def test_복리후생비_적요에_용도_문구가_붙는다():
    """재무팀 요청(2026-08-07). 가맹점만 적으면 무슨 명목인지 안 보인다."""
    usage = _usage(
        card_no='REDACTED_CONFIGURE_LOCALLY7890123771', use_date="20260806",
        merchant="죠샌드위치&마우이포케 서초점", purpose="복리후생비",
        account_code=cv.ACCOUNT_MAP["복리후생비"],
    )

    assert usage.auto_remark == "3771.08.06. 죠샌드위치&마우이포케 서초점-사원식대 및 회식대"


def test_복리후생비가_아니면_적요는_그대로다():
    """꼬리말은 계정별로만 붙는다 — 다른 계정까지 번지면 안 된다."""
    usage = _usage(
        card_no='REDACTED_CONFIGURE_LOCALLY7890129051', use_date="20260731", merchant="카카오T일반택시",
        purpose="여비교통비", account_code=cv.ACCOUNT_MAP["여비교통비"],
    )

    assert usage.auto_remark == "9051.07.31. 카카오T일반택시"


def test_가맹점이_길어도_용도_문구는_안_잘린다():
    """아마란스 rmkDc 는 80자에서 끊긴다. 앞을 줄여서라도 꼬리말은 살려야 한다 —
    잘린 '…-사원식'은 안 붙느니만 못하다."""
    usage = _usage(
        card_no='REDACTED_CONFIGURE_LOCALLY7890123771', use_date="20260806", merchant="가" * 200,
        purpose="복리후생비", account_code=cv.ACCOUNT_MAP["복리후생비"],
    )

    assert usage.auto_remark.endswith("-사원식대 및 회식대")
    assert len(usage.auto_remark) <= cv.REMARK_MAX


def test_화면_꼬리말_표가_서버와_같다():
    """JS 와 파이썬이 따로 놀면 화면과 전송값이 어긋난다."""
    from pathlib import Path

    script = (
        Path(__file__).resolve().parent.parent
        / "desktop" / "ui" / "card-vouchers.js"
    ).read_text(encoding="utf-8")
    for account, suffix in cv.REMARK_SUFFIX.items():
        name = next(k for k, v in cv.ACCOUNT_MAP.items() if v == account)
        assert f"'{name}': '{suffix}'" in script, f"{name} 꼬리말이 JS에 없다"


def test_작성번호는_8만번대를_벗어나지_않는다():
    """카드전표 작성번호가 기본전표(10000+id)와 겹치면 전송이 막힌다.

    2026-08-14 실제 사고 — 카드전표 57번과 기본전표 57번이 둘 다 10057이었고
    전표일자까지 같아, 아마란스가 '이미 발행되어 추가입력할 수 없습니다'로 거절했다.
    """
    from app.services.card_voucher_service import MENU_SQ_BASE, MENU_SQ_SPAN

    assert (MENU_SQ_BASE, MENU_SQ_SPAN) == (80000, 10000)
    for voucher_id in (1, 57, 62, 9999, 10000, 10001, 123456):
        assert 80000 <= MENU_SQ_BASE + (voucher_id % MENU_SQ_SPAN) <= 89999


def test_내보내기_한줄이_화면_문구를_그대로_옮긴다():
    """엑셀이 화면과 다른 말을 하면 대조가 안 된다."""
    from app.routers.card_vouchers import _export_row

    row = _export_row({
        "status": "hold", "holds": ["계정 미매핑", "가맹점 거래처 없음"],
        "canceled": True, "user_name": "홍길동", "card_alias": "법인1",
        "card_no_masked": "****3967", "use_date": "20260731", "appr_time": "13:05",
        "merchant": "정진식당", "industry": "한식", "total": "269000",
        "purpose": "복리후생비", "deductible": False, "tax_info": "과세",
        "supply": "244545", "vat": "24455", "remark": "3967.07.31. 정진식당",
    })

    assert row["status_text"] == "보류"
    assert row["hold_reason"] == "계정 미매핑 / 가맹점 거래처 없음"
    assert row["canceled_text"] == "취소"
    assert row["card"] == "법인1 ****3967"
    assert row["use_date_text"] == "2026.07.31"
    assert row["deductible_text"] == "미공제"
    assert (row["total"], row["supply"], row["vat"]) == (269000.0, 244545.0, 24455.0)


def test_내보내기_토큰은_만든_사람만_받는다():
    """목록에 카드번호·가맹점이 들어 있어 남이 받으면 안 된다."""
    from app.routers.card_vouchers import _EXPORTS, export_rows

    _EXPORTS["tok"] = (9e12, 111, "", [{"status_text": "정상"}])
    try:
        assert export_rows(token="tok", usr_seq=222).status_code == 410
        assert export_rows(token="없는토큰", usr_seq=111).status_code == 410
        assert export_rows(token="tok", usr_seq=111).status_code == 200
    finally:
        _EXPORTS.pop("tok", None)


def test_DB_불러오기가_업종을_가져온다():
    """CB2_APPR의 업종은 BRANCH_TYPE에 있다 — 안 읽으면 화면이 늘 빈칸이다."""
    from app.services import card_source

    usage = card_source.row_to_usage({
        "CARD_NO": "5404-9780-0128-3967", "APPR_DATE": "20260819", "APPR_NO": "A1",
        "Use_Name": "", "CHAIN_NM": "메기나 배추", "CHAIN_ID": 'REDACTED_CONFIGURE_LOCALLY7890',
        "APPR_AMT": "11000", "APPR_TAX": "1000", "SUPPLY_AMT": "10000",
        "DEDUCT_YN": "Y", "CANCEL_YN": "N", "APPR_TIME": "130500",
        "BRANCH_TYPE": "일반음식점",
    }, 1)

    assert usage.industry == "일반음식점"
    assert "BRANCH_TYPE" in card_source._SQL, "조회에서 업종 컬럼이 빠지면 빈칸이 된다"


def test_업종_뒤_분류코드만_떼고_괄호_이름은_남긴다():
    """엑셀은 '택시', 원천은 '택시(5306)' — 표기를 맞추되 이름은 다치면 안 된다.

    2026-08-20 실측(최근 180일 110종): 괄호가 붙은 24종 중 18종이 숫자코드,
    나머지 6종은 업종명 일부였다.
    """
    from app.services.card_source import _industry

    for source, expected in (
        ("택시(5306)", "택시"),
        ("한식(2104)", "한식"),
        ("커피/음료전문점(2004)", "커피/음료전문점"),
        ("일반음식점 기타(2199)", "일반음식점 기타"),
        ("일반음식점", "일반음식점"),
        # 괄호 안이 글자면 업종명이라 그대로 둔다
        ("PG일반(비인증)", "PG일반(비인증)"),
        ("우체국(우편요금)", "우체국(우편요금)"),
        ("전자상거래(안심클릭미적용)", "전자상거래(안심클릭미적용)"),
        ("호텔(특급)", "호텔(특급)"),
        (None, ""),
    ):
        assert _industry(source) == expected, f"{source!r} 처리가 틀렸다"


def test_빈_사용자를_카드_이력에서_채운다():
    """카드사 API는 명의자를 거의 안 준다 — 우리 전표 이력으로 메운다."""
    from datetime import date
    from decimal import Decimal

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models.card_voucher import CardVoucher, CardVoucherItem
    from app.services.card_voucher_service import CardVoucherService

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    CardVoucher.__table__.create(engine)
    CardVoucherItem.__table__.create(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.add(CardVoucher(id=1, voucher_date=date(2026, 7, 1), division_code="1000",
                       menu_sq=80001, item_count=1, total_amount=Decimal("1"), status="S"))
    # 같은 카드에 옛 이름과 새 이름이 함께 있으면 최근(id 큰 쪽)이 이겨야 한다
    for iid, name in ((1, "옛사람"), (2, "새사람")):
        db.add(CardVoucherItem(
            id=iid, voucher_id=1, dedup_key=f"K{iid}", card_no="5404978001283967",
            card_alias="법인1", user_name=name, use_date="20260701", appr_no=str(iid),
            total=Decimal("1"), merchant="가", merchant_biz_no='REDACTED_CONFIGURE_LOCALLY7890',
            purpose="복리후생비", account_code="8110000", deductible=True,
            supply=Decimal("1"), vat=Decimal("0"), remark="r"))
    db.commit()

    blank = _usage(card_no="5404978001283967", user_name="", card_alias="")
    typed = _usage(card_no="5404978001283967", user_name="직접입력", card_alias="")
    other = _usage(card_no="9999999999999999", user_name="", card_alias="")
    CardVoucherService(db, client=object())._fill_card_owners([blank, typed, other])

    assert (blank.user_name, blank.card_alias) == ("새사람", "법인1")
    assert typed.user_name == "직접입력", "이미 있는 이름을 덮으면 안 된다"
    assert other.user_name == "", "이력에 없는 카드는 빈칸 그대로 둔다"
    db.close(); engine.dispose()


def test_아는_가맹점은_아마란스에_다시_묻지_않는다():
    """가맹점 조회는 한 건에 한 왕복(0.22초)이라 한 달치면 그것만 2분이 걸린다.

    2026-08-20 실측: 이력으로 거르니 이틀치 107→44회, 19일치 575→134회.
    """
    from datetime import date
    from decimal import Decimal

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models.card_voucher import CardVoucher, CardVoucherItem
    from app.services.card_voucher_service import CardVoucherService

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    CardVoucher.__table__.create(engine)
    CardVoucherItem.__table__.create(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.add(CardVoucher(id=1, voucher_date=date(2026, 7, 1), division_code="1000",
                       menu_sq=80001, item_count=1, total_amount=Decimal("1"), status="S"))

    def _item(iid, biz_no, code, name):
        return CardVoucherItem(
            id=iid, voucher_id=1, dedup_key=f"K{iid}", card_no="5404978001283967",
            card_alias="법인1", user_name="홍길동", use_date="20260701", appr_no=str(iid),
            total=Decimal("1"), merchant=name, merchant_biz_no=biz_no,
            merchant_partner_code=code, purpose="복리후생비", account_code="8110000",
            deductible=True, supply=Decimal("1"), vat=Decimal("0"), remark="r")

    db.add(_item(1, "1118513651", "0000059718", "옛이름"))
    db.add(_item(2, "1118513651", "0000059718", "에이치베이커리"))   # 최근 값이 이겨야 한다
    db.add(_item(3, "4840300117", "", "코드 없는 건"))              # 코드 없으면 안 쓴다
    db.commit()

    found = CardVoucherService(db, client=object())._known_merchants(
        {"1118513651", "4840300117", "9999999999", "짧은번호"}
    )

    assert found["1118513651"] == {"code": "0000059718", "name": "에이치베이커리"}
    assert "4840300117" not in found, "거래처코드가 없는 이력은 쓰면 안 된다"
    assert "9999999999" not in found and "짧은번호" not in found
    db.close(); engine.dispose()


def test_자동등록을_켜면_캐시의_없음을_믿지_않는다():
    """캐시가 낡은 사이 남이 등록해 둔 가맹점을 또 등록하면 거래처가 둘로 갈린다.

    그래서 자동 등록 회차에는 반드시 아마란스에 확인한다 (조회는 느려지지만
    중복 등록보다 낫다).
    """
    import inspect

    from app.services.card_voucher_service import CardVoucherService

    source = inspect.getsource(CardVoucherService.analyze_usages)

    assert "trust_absence = not auto_register and partner_cache.is_fresh" in source, (
        "자동 등록 회차에도 '없음'을 믿으면 거래처가 중복 등록된다"
    )
    assert "None if trust_absence else self.find_merchant" in source
