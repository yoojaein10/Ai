"""입금 결과 테이블(a10_payment_status) 야간 갱신 + 배분 초안 생성 진입점."""

from app.database import get_session_factory
from app.services.gaprice_outbox import generate_gaprice_drafts
from app.services.payment_status import refresh_payment_status


def main() -> None:
    with get_session_factory()() as db:
        merged = refresh_payment_status(db)
        drafts = generate_gaprice_drafts(db)
    print(f"입금 결과 정리 완료: {merged:,}건 반영, 배분 초안 {drafts:,}건 생성")


if __name__ == "__main__":
    main()
