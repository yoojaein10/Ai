"""팝빌 전자세금계산서 테스트 발행 1건 (연동 검증용).

반드시 settings.popbill_is_test=True(기본)에서만 쓸 것 — 실발행이면 국세청·거래처로 나간다.
단계: (1) 잔액/단가 조회로 인증 확인 → (2) 테스트 세금계산서 1건 발행 → (3) 상태 조회.

사용법:
  python -m scripts.test_issue_taxinvoice                 # 잔액만 확인(발행 안 함)
  python -m scripts.test_issue_taxinvoice --issue         # 테스트 발행까지
"""

import argparse

from app.config import get_settings
from app.services import popbill_tax


def _fake_mgt_key() -> str:
    # 테스트용 관리번호 (회사 내 유일해야 함). 날짜 함수 금지 환경이라 고정 접두어+수동값.
    return "TEST-" + get_settings().popbill_corp_num[-4:] + "-0001"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", action="store_true", help="테스트 발행까지 수행")
    parser.add_argument("--mgtkey", default="", help="문서관리번호 직접 지정")
    parser.add_argument("--write-date", default="", help="작성일자 YYYYMMDD (기본: 오늘은 셸에서 넣기)")
    args = parser.parse_args()

    settings = get_settings()
    print(f"팝빌 설정됨={settings.is_popbill_configured}, 테스트모드={settings.popbill_is_test}, "
          f"공급자={settings.popbill_corp_num}")
    if not settings.is_popbill_configured:
        raise SystemExit("중단: .env에 POPBILL_LINK_ID·POPBILL_SECRET_KEY·POPBILL_CORP_NUM 필요")
    if not settings.popbill_is_test:
        raise SystemExit("중단: 실발행 모드다. 테스트 발행은 POPBILL_IS_TEST=true에서만 허용.")

    print("\n[1] 잔액/단가 조회 (인증 확인)")
    info = popbill_tax.check_balance()
    print(f"    잔액={info['balance']} / 발행단가={info['unit_cost']}")

    if not args.issue:
        print("\n발행은 --issue 옵션으로. 지금은 인증 확인만 완료.")
        return

    if not args.write_date:
        raise SystemExit("--write-date YYYYMMDD 필요 (예: --write-date 20260724)")

    mgt_key = args.mgtkey or _fake_mgt_key()
    print(f"\n[2] 테스트 세금계산서 발행 (관리번호 {mgt_key})")
    supplier = {
        "corp_num": settings.popbill_corp_num,
        "corp_name": "대화감정평가법인",
        "ceo_name": "대표",
        "addr": "서울특별시",
        "biz_type": "서비스", "biz_class": "감정평가",
        "contact_name": "재무팀", "tel": "02-0000-0000",
        "email": "",
    }
    receiver = {  # 팝빌 테스트용 가상 공급받는자
        "corp_num": "8888888888",
        "corp_name": "팝빌테스트거래처",
        "ceo_name": "홍길동", "addr": "서울",
        "biz_type": "제조", "biz_class": "전자",
        "contact_name": "담당", "email": "",
    }
    items = [{
        "date": args.write_date, "name": "감정평가수수료(테스트)", "spec": "",
        "qty": "1", "unit_cost": "100000", "supply_cost": 100000, "tax": 10000,
        "remark": "연동 테스트",
    }]
    inv = popbill_tax.build_taxinvoice(
        write_date=args.write_date, supplier=supplier, receiver=receiver,
        items=items, purpose="영수", memo="MOA 팝빌 연동 테스트",
    )
    result = popbill_tax.register_issue(inv, mgt_key, memo="MOA 연동 테스트")
    print(f"    발행 결과: {result}")

    if result.get("success"):
        print("\n[3] 발행 상태 조회")
        print(f"    {popbill_tax.get_info(mgt_key)}")


if __name__ == "__main__":
    main()
