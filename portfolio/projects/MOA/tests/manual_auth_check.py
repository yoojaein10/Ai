"""실제 Amaranth 인증/조회 수동 확인 스크립트.

이 스크립트는 읽기 전용 회사조회 API를 호출한다. 실행 전 `a10_api_log` 테이블이
필요하므로 먼저 `python -m scripts.create_tables`를 실행한다.
"""

from app.amaranth.client import AmaranthClient
from app.config import get_settings
from app.database import get_session_factory


def main() -> None:
    settings = get_settings()
    if not settings.is_amaranth_configured:
        raise SystemExit("Amaranth 설정이 완전하지 않습니다. .env를 확인하세요.")
    if not settings.is_database_configured:
        raise SystemExit("MSSQL 설정이 완전하지 않습니다. .env를 확인하세요.")

    with get_session_factory()() as db:
        payload = AmaranthClient(db, settings=settings).post(
            "/apiproxy/api16S08",
            json_body={"groupSeq": settings.a10_group_seq},
        )

    print("인증 및 회사조회 성공")
    result_data = payload.get("resultData")
    count = len(result_data) if isinstance(result_data, list) else None
    if count is not None:
        print(f"조회된 회사 수: {count}")


if __name__ == "__main__":
    main()
