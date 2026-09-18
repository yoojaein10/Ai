"""업무용승용차 표 — 한 차에 여러 카드 사용자명(정우종/대표이사)을 걸 수 있다."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.card_vehicle import CardVehicle
from app.services.card_vehicles import save_vehicles, vehicle_map


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    CardVehicle.__table__.create(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_한_차에_여러_사용자명을_슬래시로_건다(db):
    """대표이사 카드는 CB2 카드 마스터에 '대표이사'로, 본인 카드는 '정우종'으로 온다 (2026-08-26).

    차량번호가 유니크라 같은 차를 두 줄로 넣을 수 없으므로 사람 칸에 '/'로 나눠 적는다.
    """
    save_vehicles(db, [
        {"car_cd": "4", "plate": "368로5750", "person": "정우종 / 대표이사", "model": "GV80"},
        {"car_cd": "0000002166", "plate": "313도5539", "person": "신상우"},
    ])
    found = vehicle_map(db)
    assert found["정우종"] == {"plate": "368로5750", "car_cd": "4"}
    assert found["대표이사"] == {"plate": "368로5750", "car_cd": "4"}
    assert found["신상우"]["car_cd"] == "0000002166"
    assert "정우종 / 대표이사" not in found, "합친 문자열 그대로는 어떤 카드와도 안 맞는다"


@pytest.mark.parametrize("plate, car_cd, names", [
    ("368로5750", "4", {"정우종", "대표이사"}),
    ("345구8642", "0000002191", {"박중현", "재무이사"}),
    ("175주1905", "0000002641", {"박용준", "기획이사"}),
    ("185너6287", "0000002358", {"김민주", "전략이사"}),
])
def test_시드_목록에_직함_카드가_본인_차에_걸려_있다(plate, car_cd, names):
    """직함 카드의 주인 (2026-08-26 사용자 확인). 총무이사=배재욱은 차가 없어 걸지 않는다."""
    from scripts.seed_card_vehicles import VEHICLES

    row = next(v for v in VEHICLES if v[1] == plate)
    assert row[0] == car_cd and row[4] is True
    assert {n.strip() for n in row[2].split("/")} == names
    assert not any("총무이사" in v[2] for v in VEHICLES)
