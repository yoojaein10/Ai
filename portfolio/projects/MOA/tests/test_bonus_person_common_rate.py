"""사람 표 공통건 요율(common_rate) — 비우면 규칙/기본 3%, 채우면 그 사람의 공(X) 행 요율."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import BonusPerson
from app.services.bonus import persons
from app.services.bonus.schedule import BonusMasterError


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[BonusPerson.__table__])
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


def test_공통건_요율은_비울_수_있고_채우면_저장된다(db):
    saved = persons.save_persons(db, [
        {"person": "이영은", "kind": "ASSOCIATE", "pay_ratio": 0.7, "tax_rate": 0.30, "common_rate": 10},
        {"person": "유영조", "kind": "SHAREHOLDER", "common_rate": "3"},
        {"person": "강무진", "kind": "SHAREHOLDER"},
    ], usr_seq=7)
    by = {p["person"]: p for p in saved}
    assert by["이영은"]["common_rate"] == 10.0 and by["유영조"]["common_rate"] == 3.0 and by["강무진"]["common_rate"] is None
    persons.save_persons(db, [{"person": "이영은", "kind": "ASSOCIATE", "pay_ratio": 0.7, "tax_rate": 0.30, "common_rate": ""}], usr_seq=7)
    assert persons.list_persons(db)[0]["common_rate"] is None                       # 비우면 규칙으로
    with pytest.raises(BonusMasterError):
        persons.save_persons(db, [{"person": "이영은", "kind": "ASSOCIATE", "common_rate": 150}], usr_seq=7)
