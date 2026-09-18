"""업무용승용차 표(a10_card_vehicle) 조회·저장 — 카드전표 차량유지비 라인의 carCd.

vehicle_map: {사람: {"plate", "car_cd"}} — active='Y' 만. 한 사람에 살아 있는 차가 둘이면 뒤 행(최근 등록)이 남는다.
  한 차를 여러 카드 사용자명이 쓰면 사람 칸에 '정우종/대표이사' 처럼 '/'로 나눠 적는다 — 이름마다 등록된다.
save_vehicles: 차량번호 기준 upsert. 목록에 없는 차는 건드리지 않는다(지우지 않는다 — 옛 차 코드가 전표 이력에 있다).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.card_vehicle import CardVehicle


def vehicle_map(db: Session) -> "dict[str, dict[str, str]]":
    rows = db.scalars(
        select(CardVehicle).where(CardVehicle.active == "Y").order_by(CardVehicle.vehicle_id)
    ).all()
    found: "dict[str, dict[str, str]]" = {}
    for row in rows:
        # 대표이사 카드는 CB2 카드 마스터 이름이 '대표이사'로 오고 본인 카드는 '정우종'으로 온다
        # (2026-08-26) — 차량번호가 유니크라 같은 차를 두 줄로 못 넣으니 '/'로 나눠 적는다.
        for name in (part.strip() for part in row.person.split("/")):
            if name:
                found[name] = {"plate": row.plate, "car_cd": row.car_cd}
    return found


def list_vehicles(db: Session) -> "list[dict[str, Any]]":
    rows = db.scalars(select(CardVehicle).order_by(CardVehicle.person, CardVehicle.vehicle_id)).all()
    return [
        {"vehicle_id": r.vehicle_id, "plate": r.plate, "car_cd": r.car_cd, "person": r.person,
         "model": r.model, "division_code": r.division_code, "active": r.active, "memo": r.memo}
        for r in rows
    ]


def save_vehicles(db: Session, rows: "list[dict[str, Any]]") -> "dict[str, int]":
    """차량번호 기준 upsert — 코드·사람·차종·활성 여부를 목록대로 맞춘다."""
    counts = {"inserted": 0, "updated": 0}
    existing = {row.plate: row for row in db.scalars(select(CardVehicle)).all()}
    for raw in rows:
        plate = str(raw.get("plate") or "").strip().replace(" ", "")
        car_cd = str(raw.get("car_cd") or "").strip()
        person = str(raw.get("person") or "").strip()
        if not plate or not car_cd or not person:
            raise ValueError(f"차량번호·차량코드·사람이 모두 있어야 합니다: {raw!r}")
        values = {
            "car_cd": car_cd, "person": person, "model": (str(raw.get("model") or "").strip() or None),
            "division_code": str(raw.get("division_code") or "1000"),
            "active": "Y" if raw.get("active", True) in (True, "Y", "y", 1) else "N",
            "memo": (str(raw.get("memo") or "").strip() or None),
        }
        row = existing.get(plate)
        if row is None:
            db.add(CardVehicle(plate=plate, **values))
            counts["inserted"] += 1
        else:
            for key, value in values.items():
                setattr(row, key, value)
            counts["updated"] += 1
    db.commit()
    return counts
