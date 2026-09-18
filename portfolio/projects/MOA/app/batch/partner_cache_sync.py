"""거래처 캐시 적재 — 하루 한 번 아마란스 거래처를 통째로 받아둔다.

카드전표 검증이 가맹점 사업자번호로 거래처를 찾을 때 아마란스에 한 건씩
묻지 않게 하려는 것이다. 실행에 1~2분 걸리고, 실패해도 화면은 예전처럼
아마란스에 직접 물어 동작한다(느릴 뿐이다).

    python -m app.batch.partner_cache_sync
"""

from app.amaranth.client import AmaranthClient
from app.database import get_session_factory
from app.services.partner_cache import cache_status, refresh_partner_cache


def main() -> None:
    with get_session_factory()() as db:
        from scripts.find_management_numbers import _company_code

        client = AmaranthClient(db)
        before = cache_status(db)
        print(f"현재 캐시: {before['rows']:,}건 (마지막 적재 {before['synced_at']})")
        try:
            result = refresh_partner_cache(db, client, _company_code(db, client))
        except Exception as exc:  # 배치가 죽어도 다음 회차에 다시 받으면 된다
            print(f"거래처 캐시 적재 실패(옛 캐시 유지): {type(exc).__name__}: {exc}")
            raise SystemExit(1) from exc
        print(f"거래처 캐시 적재 완료: {result['stored']:,}건 (회차 {result['batch']})")


if __name__ == "__main__":
    main()
