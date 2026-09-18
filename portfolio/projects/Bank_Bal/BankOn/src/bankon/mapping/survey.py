"""신한 담보 **현장조사서**(TBNKSHG24Hyun) 매핑 — 우클릭 '현장조사서 작성(E)'.

발송 실물(01-2607-3-2403, 2026-08-25 정찰)로 확정한 대응:
    현장답사일  ← 조사일(context.survey_date = 의견서/hunjang josadate)
    교통비      ← APW_Bill.YEBI(여비)
    토지조사비  ← APW_Bill.TOJOSABI
    물건조사비  ← APW_Bill.MULJOSABI
    임대차조사비← (없음 — 사람도 비움. 라벨 안내: "임대차조사비는 기타실비에 입력")
    공부발급비  ← APW_Bill.GONGBU
    기타실비    ← (비움)
    특별용역비  ← APW_Bill.YONGYEUK
    사진비      ← APW_Bill.SILBI   ★APW '기타실비' 컬럼이 화면 '사진비'로 들어간다(800·700 실측)
    예외적용    ← '미적용'(콤보, 기본값)
    부가세      ← 항목합(교통비+토지조사비+물건조사비+공부발급비+사진비+특별용역비) × 10% (원 단위 반올림)
    실비합계    ← 항목합 + 부가세 (부가세 포함, 담보 폼 '실 비'와 같은 값)
                  ※APW SILBISUM/SILBITAX 는 사진비 등이 빠져 화면과 어긋난다(2676: 52,000/5,200 vs 화면 52,900/5,290).
                    Bank24 는 저장 시 실비합계를 항목합×1.1 로 다시 계산한다(실측 58,190).
0 은 form.is_blank 가드로 비워진다(사람도 0 칸은 비움).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class SurveyCosts:
    travel: Decimal | None = None         # YEBI
    land_survey: Decimal | None = None    # TOJOSABI
    object_survey: Decimal | None = None  # MULJOSABI
    registry: Decimal | None = None       # GONGBU
    photo: Decimal | None = None          # SILBI
    special: Decimal | None = None        # YONGYEUK
    vat: Decimal | None = None            # SILBITAX
    subtotal: Decimal | None = None       # SILBISUM (세전)


SURVEY_SQL = (
    "SELECT B.YEBI, B.TOJOSABI, B.MULJOSABI, B.GONGBU, B.SILBI, B.YONGYEUK, B.SILBITAX, B.SILBISUM "
    "FROM APW_Bill B JOIN apw_Master M ON M.MasterID = B.MasterID WHERE M.DocID = ?"
)


def _dec(value) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def fetch_costs(cursor, doc_id: str) -> SurveyCosts | None:
    cursor.execute(SURVEY_SQL, doc_id)
    row = cursor.fetchone()
    if not row:
        return None
    return SurveyCosts(*[_dec(v) for v in row])


def _money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal(1)), "f")


def build(costs: SurveyCosts | None, survey_date: str | None) -> dict[str, str | None]:
    """현장조사서 화면 라벨 → 값. 라벨 공백('교 통 비')은 driver 가 무시하고 매칭한다."""
    c = costs or SurveyCosts()
    items = [c.travel, c.land_survey, c.object_survey, c.registry, c.photo, c.special]
    vat = total = None
    if any(v is not None for v in items):
        subtotal = sum((v or Decimal(0)) for v in items)
        vat = (subtotal * Decimal("0.1")).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        total = subtotal + vat
    return {
        "현장답사일": survey_date,
        "교통비": _money(c.travel),
        "토지조사비": _money(c.land_survey),
        "물건조사비": _money(c.object_survey),
        "임대차조사비": None,
        "공부발급비": _money(c.registry),
        "기타실비": None,
        "특별용역비": _money(c.special) or "0",   # 칸이 있으면 0 을 넣는다(전 은행 공통, 사용자 지시 2026-09-14). form.ZERO_ALLOWED_FULL 에 있어 0 이 실제로 써진다
        "사진비": _money(c.photo),
        "예외적용": "미적용",
        "부가세": _money(vat),
        "실비합계": _money(total),
    }
