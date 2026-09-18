"""SQLAlchemy 2.x MSSQL 엔진과 세션 팩토리."""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings, get_settings


class Base(DeclarativeBase):
    pass


def build_database_url(settings: Settings) -> URL:
    if not settings.is_database_configured:
        raise RuntimeError(
            "MSSQL 설정이 없습니다. .env에 MSSQL_SERVER, MSSQL_DB, "
            "MSSQL_USER, MSSQL_PASSWORD를 입력하세요."
        )

    return URL.create(
        drivername="mssql+pyodbc",
        username=settings.mssql_user,
        password=settings.mssql_password.get_secret_value(),
        host=settings.mssql_server,
        port=settings.mssql_port,
        database=settings.mssql_db,
        query={
            "driver": settings.mssql_driver,
            "Encrypt": settings.mssql_encrypt,
            "TrustServerCertificate": settings.mssql_trust_server_certificate,
        },
    )


# 연결 풀 크기 (2026-08-11). 기본값 5 + 넘침 10 = **15개**였는데, 화면 하나가
# 그보다 많이 쓸 수 있었다. 개인별 매출실적을 예로 세어 보면 —
#     대시보드 1 (+ 소재지 스레드 4) · 목록 1 · 연도별 1
#     가변비 1 (+ 달 스레드 4) · 상여 1 (+ 달 스레드 3)   = 최대 16
# 한 사람이 화면 하나 여는 데 풀이 바닥나고, **화면 16개가 이 풀 하나를 같이
# 쓰므로** 다른 메뉴까지 30초를 기다리다 죽는다. 스레드를 쓰는 서비스가 넷이다
# (my_sales · appraisals · receivables · deposit_search).
#
# 늘린다고 DB 가 빨라지지는 않는다 — 프로시저는 어차피 DB CPU 에서 줄을 선다.
# 늘리는 목적은 **우리 쪽에서 줄 서다 남의 화면을 막는 일**을 없애는 것이다.
# 60개는 SQL Server 에게 부담이 아니다(연결 하나가 몇십 KB).
_POOL_SIZE = 20
_POOL_OVERFLOW = 40


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        build_database_url(get_settings()),
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=_POOL_SIZE,
        max_overflow=_POOL_OVERFLOW,
    )


def build_source_database_url(settings: Settings) -> URL:
    """원본 감정평가 DB(apworksdw)용 URL. 업무실적 매핑 SP 재현은 이 DB에서 돈다."""
    url = build_database_url(settings)
    return url.set(database=settings.mssql_source_db)


@lru_cache
def get_source_engine() -> Engine:
    """apworksdw(원본) 전용 엔진. 세션 임시테이블(#SEL)을 쓰는 읽기전용 매핑에 사용."""
    return create_engine(
        build_source_database_url(get_settings()),
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=_POOL_SIZE,
        max_overflow=_POOL_OVERFLOW,
    )


def build_gamjun_parse_url(settings: Settings) -> URL:
    '감정서 PDF 파싱 DB(192.0.2.10 gamjundw)용 URL. 읽기전용 조회에만 쓴다.'
    url = build_database_url(settings)
    return url.set(host=settings.gamjun_parse_server, database=settings.gamjun_parse_db)


@lru_cache
def get_gamjun_parse_engine() -> Engine:
    """감정서 파싱 DB 전용 엔진 (jun.case_master / document_version / page)."""
    return create_engine(
        build_gamjun_parse_url(get_settings()),
        pool_pre_ping=True,
        pool_recycle=1800,
    )


def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()

