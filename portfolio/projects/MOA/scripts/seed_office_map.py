"""a10_office_map 시드: 지사↔감정서번호 접두사(확정 규칙) + Amaranth 회계단위 매칭.

재실행 가능(upsert). 매칭 실패 지사는 division_code=NULL로 남고 수동 UPDATE 안내를 출력한다.

실행: python -m scripts.seed_office_map
"""

from sqlalchemy import select

from app.database import get_session_factory
from app.models.office_map import OfficeMap
from app.services.office_lookup import match_offices_to_divisions

# APWorks 감정서번호 채번 프로시저 기준 확정 매핑 (구제주 20은 폐기).
OFFICE_DOCID_PREFIX = {
    "10": "01", "11": "05", "12": "06", "13": "10", "14": "11",
    "15": "04", "16": "07", "17": "03", "18": "02", "19": "08",
    "21": "12", "22": "09", "23": "13", "24": "14", "25": "15",
    "26": "16", "27": "17", "28": "18",
}

# Amaranth 이름 매칭과 무관하게 확정된 회계단위.
# 본사 = 1000: Amaranth 사업장 목록의 본점(fillYn=1)이자 실제 본사 전표(01-)가 쓰는 divCd.
FIXED_DIVISION_CODES = {"10": "1000"}


def main() -> None:
    db = get_session_factory()()
    try:
        matched = match_offices_to_divisions(db)
        matched_by_office = {item["office_code"]: item for item in matched["items"]}
        print(f"Amaranth 사업장 매칭 소스: {matched['source']}")

        unmatched: list[str] = []
        for office_id, prefix in OFFICE_DOCID_PREFIX.items():
            info = matched_by_office.get(office_id, {})
            division_code = FIXED_DIVISION_CODES.get(office_id) or info.get("division_code")
            row = db.scalars(
                select(OfficeMap).where(OfficeMap.office_id == office_id)
            ).first()
            if row is None:
                row = OfficeMap(office_id=office_id)
                db.add(row)
            row.office_name = info.get("office_name") or row.office_name or office_id
            row.docid_prefix = prefix
            row.division_code = division_code
            row.division_name = info.get("division_name")
            row.active = "Y"
            row.sort_order = info.get("sort_order")
            if not division_code:
                unmatched.append(f"{office_id}({row.office_name})")
        db.commit()

        rows = db.scalars(select(OfficeMap).order_by(OfficeMap.sort_order)).all()
        print(f"시드 완료: {len(rows)}개 지사")
        for row in rows:
            print(
                f"  {row.office_id} {row.office_name:<12} prefix={row.docid_prefix} "
                f"division={row.division_code or '-'} ({row.division_name or '미매칭'})"
            )
        if unmatched:
            print("\n[주의] Amaranth 회계단위 미매칭 지사 — 수동 지정 필요:")
            for name in unmatched:
                print(f"  - {name}")
            print(
                "  예) UPDATE dbo.a10_office_map SET division_code = '코드' "
                "WHERE office_id = '지사코드'"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
