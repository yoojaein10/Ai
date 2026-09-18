"""계정별 전기이월 시드 — 아마란스 계정별원장 화면에서 읽어 온 값을 넣는다.

전표 캐시가 2025-07-24 부터라 작년 말 잔액을 계산할 수 없다. 그래서 아마란스
계정별원장(ACC2050) 화면의 [전 기 이 월] 줄을 계정별로 한 번 적어 두고 쓴다.

읽어 온 조건 (2026-08-21):
    회계단위 1000.(주)대화감정평가법인 · 승인기간 2026-01-01 ~ 2026-08-20 · 세목별

아마란스는 전기이월을 **차변 칸에** 찍는다 — 음수일 수 있다. 화면에 보이는
그대로 debit 에 넣는다. '데이터가 존재하지 않습니다' 인 계정은 0 으로 둔다
(확인했다는 뜻이다 — 빠뜨린 것과 구분된다).

    python -m scripts.seed_account_opening
"""

from sqlalchemy import text

from app.database import get_session_factory

FISCAL_YEAR = 2026

# (계정, 이름, 전기이월 차변)
OPENINGS = [
    ("1410002", "경기지사",      67_960_958),
    ("1410003", "경인지사",      -4_440_281),
    ("1410004", "북부지사",     -20_011_096),
    ("1410005", "강원지사",      15_018_889),
    ("1410006", "충청지사",     -12_273_931),
    ("1410007", "충남지사(구)",           0),   # 데이터 없음
    ("1410008", "대구지사",      40_109_223),
    ("1410009", "부산지사",    -137_045_919),
    ("1410010", "경남중앙지사", 199_770_911),
    ("1410011", "호남지사",     -46_529_401),
    ("1410012", "제주지사(구)",           0),   # 데이터 없음
    ("1410013", "제주지사",      -6_076_058),
    ("1410014", "동부지사(구)",           0),   # 데이터 없음
    ("1410015", "전북지사",        -503_507),
    ("1410016", "대전세종지사",   24_597_203),
    ("1410018", "충남지사",     -10_116_472),
    ("1410019", "울산지사",      12_980_667),
    ("1410020", "경북지사",     -38_990_022),
    ("1410021", "경기서부지사",  -33_928_920),
    ("1410022", "동부지사",      -4_448_604),
]

_UPSERT = text("""
UPDATE dbo.a10_account_opening
   SET debit = :debit, credit = 0
 WHERE account_code = CAST(:code AS varchar(20)) AND fiscal_year = :yr;
IF @@ROWCOUNT = 0
    INSERT INTO dbo.a10_account_opening (account_code, fiscal_year, debit, credit)
    VALUES (CAST(:code AS varchar(20)), :yr, :debit, 0);
""")


def main() -> None:
    db = get_session_factory()()
    try:
        for code, name, debit in OPENINGS:
            db.execute(_UPSERT, {"code": code, "yr": FISCAL_YEAR, "debit": debit})
            print(f"  {code} {name:14s} {debit:>15,}")
        db.commit()
        print(f"\n{len(OPENINGS)}개 계정 전기이월({FISCAL_YEAR}) 저장 완료")
    finally:
        db.close()


if __name__ == "__main__":
    main()
