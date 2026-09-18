"""업무용승용차 시딩 — 재무팀이 준 아마란스 차량코드 목록 + 보험 목록(현재 차).

    python -m scripts.seed_card_vehicles            # 저장 (차량번호 기준 upsert)
    python -m scripts.seed_card_vehicles --dry-run

두 대인 사람(김형수·정승훈·윤도)은 보험에 든 차만 active='Y'. 옛 차는 남기되 비활성(전표 이력 참조용).
차가 바뀌면 이 목록을 고치고 다시 돌린다 — 목록에 없는 차는 건드리지 않는다.
"""

import argparse

from app.database import get_session_factory
from app.services.card_vehicles import list_vehicles, save_vehicles

# (차량코드, 차량번호, 관리사원, 차종, 활성)
VEHICLES = [
    ("0000001998", "247로1816", "이진형", "벤츠(MAG GT43)", True),
    ("0000002163", "184서5203", "김형수", None, False),              # 옛 차 — 현재 보험은 238도8948
    ("0000002164", "126마4274", "김형식", "카니발", True),
    ("0000002165", "106버6972", "김정원", "BMW", True),
    ("0000002166", "313도5539", "신상우", "BMW", True),
    ("0000002167", "120너3686", "성지연", "벤츠", True),
    ("0000002191", "345구8642", "박중현/재무이사", "토요타", True),
    ("0000002192", "142라7891", "강무진", "벤츠", True),
    ("0000002208", "204조3545", "정승훈", None, False),              # 옛 차 — 현재 보험은 03버1733
    ("0000002209", "305더9655", "전영배", "G80", True),
    ("0000002281", "250머7400", "안창덕", "G90", True),
    ("0000002283", "132누8386", "홍창연", "BMW", True),
    ("0000002297", "117구8020", "정원정", "카이엔", True),
    ("0000002310", "257마4946", "고세욱", "레인지로버", True),
    ("0000002311", "158구1591", "현승한", "아우디", True),
    ("0000002358", "185너6287", "김민주/전략이사", "팰리세이드", True),
    ("0000002429", "222모9630", "유승연", "벤츠", True),
    ("0000002430", "238도8948", "김형수", "벤츠", True),
    ("0000002515", "202다2508", "유승민", "BMW", True),
    ("0000002553", "03버1733", "정승훈", "아이오닉9", True),
    ("0000002622", "05라0945", "윤도", "BMW", True),
    ("0000002641", "175주1905", "박용준/기획이사", "Q7", True),
    ("0000002667", "276라7433", "송정선", "벤츠", True),
    ("1", "150호8283", "서완석", None, True),
    ("2", "382루5880", "조근렬", "G90 3.5T", True),
    ("3", "194호1031", "윤도", None, False),                          # 옛 차 — 현재 보험은 05라0945
    ("4", "368로5750", "정우종/대표이사", "GV80", True),
    # 직함 카드는 카드 마스터(CB2_CARD) 사용자명이 직함으로 온다 — 2026-08-26 사용자 확인:
    # 대표이사=정우종, 재무이사=박중현, 기획이사=박용준, 전략이사=김민주 (총무이사=배재욱은 차가 없어 안 건다).
]


def main() -> None:
    parser = argparse.ArgumentParser(description="업무용승용차 시딩")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    rows = [{"car_cd": c, "plate": p, "person": n, "model": m, "active": a} for c, p, n, m, a in VEHICLES]
    if args.dry_run:
        print(f"[미리보기] {len(rows)}대 (활성 {sum(1 for r in rows if r['active'])})")
        return
    db = get_session_factory()()
    try:
        counts = save_vehicles(db, rows)
        active = [v for v in list_vehicles(db) if v["active"] == "Y"]
        print(f"[저장] 신규 {counts['inserted']} · 갱신 {counts['updated']} · 활성 {len(active)}대")
    finally:
        db.close()


if __name__ == "__main__":
    main()
