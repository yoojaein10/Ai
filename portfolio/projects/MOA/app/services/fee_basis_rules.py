"""보수기준 자동 판별 규칙 — 순수 함수 (DB 접근 없음).

수수료청구서의 보수기준 선택(APW_IW_SuSuList)이 사실상 미입력·기본값이라
(2026-07 실측 87%), 감정서의 목적·본문에서 적용 보수기준을 자동 추정한다.
코드 번호는 APW_IW_SusuWhy.Code 를 그대로 쓴다.

근거 문서: 「감정평가법인등에 관한 보수기준」 해설서(2026 수정판).
  · 제4조 수수료 체계(요율/보상종가/임대료), 제5조 150% 할증 12종,
  · 제6조 할인(재평가 90~10%·공동주택·조성용지·자산재평가 등), 제7조 보상 종량제,
  · 부록: 대법원예규(법원 경매·소송), 공시업무 수수료.
"""

import re
from datetime import date, datetime
from typing import Any

# APW_IW_SusuWhy.Code → 화면용 짧은 라벨
FEE_CODE_LABELS = {
    1: "제4조① 요율체계(기본)",
    38: "제4조②1호 보상평가 종가",
    39: "제4조②2호 임대료 평가",
    2: "제5조 할증-기준시점 6월이상 소급(150%)",
    3: "제5조 할증-특수용도 구축물(150%)",
    4: "제5조 할증-입목 등(150%)",
    5: "제5조 할증-도서지역·산림(150%)",
    6: "제5조 할증-산업체 시설(150%)",
    7: "제5조 할증-해체처분가격(150%)",
    8: "제5조 할증-도로 편입 토지(150%)",
    9: "제5조 할증-광산·광업권·온천(150%)",
    10: "제5조 할증-어장·어업권(150%)",
    11: "제5조 할증-수용·재결평가(150%)",
    40: "제5조 할증-법원 소송평가(150%)",
    12: "제5조 할증-선하지(150%)",
    13: "제6조 할인-재평가 3월내·시점동일(90%)",
    14: "제6조 할인-재평가 3월내(70%)",
    15: "제6조 할인-재평가 6월내(50%)",
    16: "제6조 할인-재평가 1년내(30%)",
    17: "제6조 할인-재평가 2년내(10%)",
    18: "제6조 할인-가치증감·개발이익환수(50%)",
    19: "제6조 할인-공동주택 10호이상(20%)",
    20: "제6조 할인-조성용지 매각(20%)",
    21: "제6조 할인-자산재평가(40%내)",
    45: "제6조 할인-1년내 재평가(60%내)",
    41: "제6조 할인-집합투자기구 편입재산(40%내)",
    42: "제6조 할인-부동산투자회사 운용자산(40%내)",
    22: "구 제3조⑥ 전주철탑부지 등 소규모",
    23: "제7조 보상평가 종량제",
    28: "제8조① 수개 물건 총액기준",
    29: "제8조①1~6호 건별기준",
    30: "제8조② 행정구역별 산정",
    31: "제8조③ 광업권·어업권·영업권 각 1물건",
    24: "제11조 상담·자문 등",
    44: "적정성 검토 수수료",
    25: "제12조 보수의 특약",
    26: "제13조 착수금",
    27: "제14조 의뢰·수임 철회시 보수",
    32: "대법원예규 §31-1 본문(20%)",
    33: "대법원예규 §31-1 단서 아파트(30%)",
    34: "대법원예규 §31-2·3(150% 할증)",
    35: "대법원예규 §32 소급감정(150~300%)",
    36: "대법원예규 §35 감정료 상하한(24만~600만)",
    37: "기타(상세 기재)",
    43: "구 공시업무 조사·평가·검증 수수료",
}

# 본문 키워드 → 후보 코드. min_hits 는 상투 문구 오탐을 줄이기 위한 최소 등장 횟수.
TEXT_SIGNALS: list[tuple[int, str, int]] = [
    (2, "소급감정", 1),
    (3, "구축물", 3),
    (4, "입목", 2),
    (5, "도서지역", 2),
    (6, "공장재단", 1),
    (7, "해체처분", 2),  # 1회는 감정평가규칙 인용 상투구(실측 오탐)
    (8, "도로에 편입", 1),
    (9, "광업권", 1),
    (9, "온천", 2),
    (10, "어업권", 1),
    (11, "수용재결", 1),
    (11, "이의재결", 1),
    (11, "토지수용위원회", 1),
    (12, "선하지", 1),
    (18, "개발이익환수", 1),
    (20, "조성용지", 1),
    # 자산재평가는 담보 감정서의 이력 언급 오탐이 많아 목적(LPurpose) 규칙만 쓴다.
    (41, "집합투자", 1),
    (42, "부동산투자회사", 1),
    # 아래 셋은 전 기간 실측 감사로 오탐 0을 확인하고 넣었다. 모두 '한 단어'가 아니라
    # 문장 조각인데, 짧게 자르면 상투구에 걸려 못 쓴다는 것이 실측으로 확인됐다.
    #
    # 수목 감정: '수목' 한 단어는 쓸 수 없다. 히트의 72.9%가 등기부 지상권 설정목적
    # 상투구('건물 기타 공작물이나 수목의 소유')라 지상권 걸린 담보 감정서마다 붙고,
    # 등장횟수 상위 6건이 전부 오탐이라 min_hits 로 분리가 안 된다(최대 정밀도 14.3%,
    # 사람이 코드1로 확정한 건과 충돌 5건). '수목 감정평가'는 명세표 제목이라
    # 2026년 파싱 1,037건에서 발화 1건·오탐 0이다. 그 건(01-2604-4-0159)은 실제로
    # 요율 1x1.5(375,000/250,000)로 150% 할증이 청구돼 코드 4가 맞음이 교차검증됐다.
    (4, "수목 감정평가", 2),
    # LH 전세사기 피해주택 매입: 보수를 협약으로 정한 건이라 제12조 특약이다.
    # '전세사기' 로 자르면 국토부 표준 임대차계약서의 '전세사기예방 체크리스트' 서식에
    # 걸려 담보·공매 감정서에서 계약서 장수만큼 반복된다(오탐 37.5%).
    (25, "피해주택 매입", 1),
    # 임대료 평가: APWorks 세부목적이 '시가참고'로 들어와 목적 규칙이 못 잡는 건이 있다.
    # '임대료'(정밀도 2.6%)·'차임'(0.8%)·'임료'('수임료' 부분문자열)는 못 쓰고,
    # '임대료 산정'도 첨부 계약서의 '월임대료 산정방법'에 걸린다. 목적 선언문 전체를
    # 쓴다 — 전 기간 파싱 8,109건에서 운영 경로 발화 45건·오탐 0이다.
    # 목적 선언은 문서당 1회라 min_hits 를 2로 올리면 재현율이 무너진다.
    (39, "임대료 산정을 위한", 1),
]

Candidate = dict[str, Any]  # {code, label, source, evidence, page}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _candidate(code: int, source: str, evidence: str, page: int | None = None) -> Candidate:
    return {
        "code": code,
        "label": FEE_CODE_LABELS.get(code, f"코드 {code}"),
        "source": source,
        "evidence": evidence,
        "page": page,
    }


def purpose_candidates(work: str | None, purpose: str | None) -> list[Candidate]:
    """업무 대분류(LWorkinfo)·세부목적(LPurpose)만으로 나오는 후보."""
    work_text, purpose_text = _text(work), _text(purpose)
    found: list[Candidate] = []

    def add(code: int, why: str) -> None:
        found.append(_candidate(code, "목적", why))

    if work_text == "법원 및 공매":
        if "소송" in purpose_text:
            add(40, f"목적 '{purpose_text}' — 법원 소송평가")
            add(35, "법원 소송감정은 대법원예규 적용(소급이면 §32)")
        elif "경매" in purpose_text:
            add(32, f"목적 '{purpose_text}' — 법원경매(아파트면 §31-1 단서 30%)")
        # 공매(NPL)는 국세징수법 수수료 — SusuWhy 코드 없음 → 기본 요율로 둔다.
    if work_text == "공시업무":
        # 실제로 고르는 값은 37('기타')이다 — 2022~2024 개별공시지가 검증 158건 전부 37,
        # 43은 공시업무에 10건뿐이다(2026-08-07 실측). 평가액이 있는 건도 0.9%라
        # 요율체계(1)도 성립하지 않는다. 37을 앞에 두고 43은 후보로 남긴다.
        add(37, f"목적 '{purpose_text}' — 공시업무(상세 기재)")
        add(43, f"목적 '{purpose_text}' — 구 §12·13 공시업무 수수료")
    if work_text == "보상":
        add(23, "보상평가 — 제7조 종량제 특례")
        add(38, "보상평가 — 제4조②1호 종가 산정")
        if any(k in purpose_text for k in ("수용재결", "이의재결")):
            add(11, f"목적 '{purpose_text}' — 재결평가 150% 할증")
    # 컨설팅만 제11조로 본다. 가격자문은 뺐다 — 두 업무는 성격이 다르다(2026-08-07 실측):
    #   컨설팅  771건 중 평가액 있음 53건(6.9%)  → 요율체계(1) 적용 자체가 불가능
    #   가격자문 14,981건 중 9,664건(64.5%)     → 요율체계가 실제로 성립
    # 가격자문은 규칙을 빼면 폴백으로 코드1이 붙고 그게 실제 관행이다(코드1 선택 166건
    # 중 165건에 평가액 있음). 반대로 컨설팅에서 코드1을 고른 2건은 둘 다 평가액이 0이라
    # 조문상 성립하지 않는 선택이다 — 사람 선택이 0건이어도 24가 맞다.
    if work_text == "컨설팅":
        add(24, f"업무 '{work_text}' — 제11조 상담·자문(평가액 없이 수임)")
    if "자산재평가" in purpose_text:
        # 21(자산재평가 40% 할인)은 사람이 고른 적이 0건이고 실제 할인도 안 붙는다.
        # 24(제11조 상담·자문)를 90건 골랐다(2026-08-07 실측).
        add(24, f"목적 '{purpose_text}' — 제11조 상담·자문")
    if work_text == "유동화자산":
        add(41, "유동화자산 — 집합투자기구면 §6②5호나목")
        add(42, "유동화자산 — 부동산투자회사면 §6②5호다목")
    if "적정성" in purpose_text:
        add(44, f"목적 '{purpose_text}'")
    if any(k in purpose_text for k in ("임료", "임대료", "사용료")):
        add(39, f"목적 '{purpose_text}' — 임대료 평가")
    return found


# 지명·법령 오탐 방지: 키워드 바로 뒤에 이 글자가 오면 무시
# (실측: '온천로 102' 도로명, '유성온천역' 역명, '온천원보호지구'·'온천법' 지역지구 표기)
_PLACE_SUFFIX_EXCLUDE = {"온천": "로동길역원법"}


def text_candidates(pages: list[tuple[int, str]]) -> list[Candidate]:
    """감정서 본문(파싱 페이지)에서 키워드로 잡는 후보. 근거 발췌를 함께 담는다."""
    joined_hits: dict[tuple[int, str], list[tuple[int, str]]] = {}
    for page_no, content in pages:
        if not content:
            continue
        for code, keyword, _min_hits in TEXT_SIGNALS:
            exclude_next = _PLACE_SUFFIX_EXCLUDE.get(keyword, "")
            start = 0
            while True:
                pos = content.find(keyword, start)
                if pos < 0:
                    break
                start = pos + len(keyword)
                next_char = content[start:start + 1]
                if exclude_next and next_char in exclude_next:
                    continue
                excerpt = _excerpt(content, pos, len(keyword))
                joined_hits.setdefault((code, keyword), []).append((page_no, excerpt))

    found: list[Candidate] = []
    seen_codes: set[int] = set()
    for code, keyword, min_hits in TEXT_SIGNALS:
        hits = joined_hits.get((code, keyword), [])
        if len(hits) < min_hits or code in seen_codes:
            continue
        seen_codes.add(code)
        page_no, excerpt = hits[0]
        found.append(
            _candidate(code, "본문", f"'{keyword}' {len(hits)}회 — {excerpt}", page_no)
        )
    return found


def _excerpt(content: str, pos: int, length: int, margin: int = 30) -> str:
    lo, hi = max(0, pos - margin), min(len(content), pos + length + margin)
    snippet = re.sub(r"\s+", " ", content[lo:hi]).strip()
    return f"…{snippet}…"


def months_elapsed(start: date, end: date) -> int:
    """start 부터 end 까지 **완전히 지난** 개월 수. 일자까지 본다.

    달력 월만 빼면 2025-11-26 → 2026-05-12 가 6개월이 되는데 실제로는 5개월 16일이라
    제5조제2항제1호의 '6월 이상'에 미달한다(실측으로 4건이 이렇게 잘못 잡혔다).
    """
    months = (end.year - start.year) * 12 + end.month - start.month
    if end.day < start.day:
        months -= 1
    return months


def retro_candidate(
    receipt_date: date | datetime | None, appraisal_date: date | datetime | None
) -> Candidate | None:
    """기준시점이 접수일보다 6개월 이상 과거면 제5조 소급 할증 후보.

    '6월 이상'은 달력 월 뺄셈이 아니라 실제 경과 기간으로 본다(months_elapsed).

    기준시점은 PDF 파싱값이라 사용승인일 등을 잘못 읽은 경우가 있어(1978년 등 실측)
    60개월을 넘는 소급은 신호로 잡지 않는다.
    """
    if not receipt_date or not appraisal_date:
        return None
    receipt = receipt_date.date() if isinstance(receipt_date, datetime) else receipt_date
    basis = appraisal_date.date() if isinstance(appraisal_date, datetime) else appraisal_date
    months = months_elapsed(basis, receipt)
    if not 6 <= months <= 60:
        return None
    return _candidate(
        2, "시점", f"기준시점 {basis.isoformat()} — 접수일보다 {months}개월 소급"
    )


def reappraisal_candidate(
    months_ago: int | None,
    prior_doc_id: str | None,
    *,
    same_price_point: bool | None = None,
) -> Candidate | None:
    """동일 지번의 과거 감정(24개월 내)이 있으면 제6조 재평가 할인 후보.

    3개월 이내는 기준시점이 같으냐로 코드가 갈린다(코드표 문구 그대로).
    same_price_point 를 안 주면 예전처럼 14 로 둔다 — 다만 그 경우 코드 13 은
    어떤 입력으로도 나오지 않는다(2026-08-07 조사에서 이 구멍이 확인됐다).

    실측으로 분리가 깨끗하다: 간격 3개월 이내 확정 할인 185건에서 기준시점 동일
    55건 중 44건(80%)이 SusuDc 0.10 이고, 시점이 다른 130건에서는 0.30 이 75건이며
    0.30 인 39건 중 시점 동일은 0건이다.
    """
    if months_ago is None or not prior_doc_id or months_ago > 24:
        return None
    if months_ago <= 3:
        code = 13 if same_price_point else 14
    elif months_ago <= 6:
        code = 15
    elif months_ago <= 12:
        code = 16
    else:
        code = 17
    return _candidate(
        code, "이력", f"{months_ago}개월 전 동일물건·동일의뢰인 감정 {prior_doc_id}"
    )


def detect(
    *,
    work: str | None,
    purpose: str | None,
    receipt_date: date | datetime | None = None,
    appraisal_date: date | datetime | None = None,
    pages: list[tuple[int, str]] | None = None,
    reappraisal_months: int | None = None,
    reappraisal_doc_id: str | None = None,
    reappraisal_same_price_point: bool | None = None,
) -> list[Candidate]:
    """감정서 하나의 보수기준 후보 목록. 특이 후보가 없으면 기본 요율체계(1)."""
    found = purpose_candidates(work, purpose)
    retro = retro_candidate(receipt_date, appraisal_date)
    if retro:
        found.append(retro)
    reapp = reappraisal_candidate(
        reappraisal_months, reappraisal_doc_id,
        same_price_point=reappraisal_same_price_point,
    )
    if reapp:
        found.append(reapp)
    if pages:
        existing = {c["code"] for c in found}
        found.extend(c for c in text_candidates(pages) if c["code"] not in existing)
    if not found:
        found.append(_candidate(1, "기본", "특이 신호 없음 — 기본 요율체계"))
    return found


def verdict(entered_code: int | None, candidates: list[Candidate]) -> str:
    """입력값과 자동판별 비교: 일치 / 불일치 / 미입력."""
    if not entered_code:  # 0 또는 None = 수수료청구서에서 안 고름
        return "미입력"
    if any(c["code"] == entered_code for c in candidates):
        return "일치"
    return "불일치"


# ── 할인 적정성 (업무연락 제2026-38호, 2026-07-03) ─────────────────────────
# 협회가 변칙적 수수료 할인(제6조제2항 제1호·제5호 오적용)에 배정제한을 최대
# 2배로 강화했다(징계규정 2026-06-23 개정). 이 축은 "밴드 밑으로 깎았다면 그
# 할인이 조문상 허용된 할인인가"를 검사한다. SusuDc 는 지불 배수라 조문 할인율의
# 여수가 허용 최소값이 된다 (90% 할인 → x0.10).
#
# 실측(2026-01~08 본사): 부분할인 81건 중 근거 코드가 기록된 건은 1건뿐이었고,
# 시제품 판정으로 한도 초과 의심 2건·근거 없음 16건이 나왔다.

DISCOUNT_STATE_OK = "구간 내"
DISCOUNT_STATE_OVER = "한도 초과 의심"
DISCOUNT_STATE_NO_BASIS = "근거 없음"
DISCOUNT_STATE_EXEMPT = "대상 외"
DISCOUNT_STATE_UNKNOWN = "판정 불가"

# 할인 근거 코드 → 허용 최소 SusuDc. 제1호 사다리(13~17)는 detect() 가 재의뢰
# 간격·기준시점으로 이미 구간을 갈라 주므로 코드만 보면 된다.
DISCOUNT_FLOOR_BY_CODE = {
    13: 0.10, 14: 0.30, 15: 0.50, 16: 0.70, 17: 0.90,  # 제1호 재의뢰 사다리
    18: 0.50,                                           # 제2호 가치증감(50%)
    19: 0.80, 20: 0.80,                                 # 제3·4호 공동주택·조성용지(20%)
    21: 0.60, 41: 0.60, 42: 0.60,                       # 제5호 가·나·다목(40% 이내)
    45: 0.40,                                           # 제5호 단서 1년 내(60% 이내)
}
# 요율표 밖 계약 — 상담·자문(24)/공시(37·43)/적정성 검토(44)는 할인 개념이 없다.
_DISCOUNT_EXEMPT_CODES = {24, 37, 43, 44}
# 재건축 종전·종후, (공)·(國) 매입매각 등에 붙는 x0.8 은 제3·4호(20%) 관행으로
# 추정한다 — detect() 목적 규칙에는 없어서 여기서만 힌트로 인정한다(실측 10건).
_DISCOUNT_20PCT_HINTS = ("재건축", "재개발", "매입매각", "취득처분", "조성")


def discount_judgement(
    susu_dc: "float | None",
    *,
    conflict: bool = False,
    candidates: "list[Candidate] | None" = None,
    entered_code: "int | None" = None,
    purpose: "str | None" = None,
    work: "str | None" = None,
) -> "dict[str, str]":
    """할인이 걸린 건의 조문 적합성. {'state','note'} — 할인이 없으면 빈 상태.

    0원(전액무료)·할증(x1 초과)은 이 축의 대상이 아니다 — 무료는 금액 축의
    fee_state('0원 청구 확인')가, 할증은 요율 축이 이미 다룬다.

    conflict 를 먼저 본다 — fetch_rates 는 청구행이 충돌하면 '첫 행'(ORDER BY 가
    없어 임의)의 SusuDc 를 남기므로, 게이트를 먼저 타면 (정가,할인) 순서일 때
    할인 건이 무판정으로 사라지고 순서가 바뀌면 판정 불가가 뜨는 비결정 동작이
    된다(2026-08-10 배포 전 리뷰에서 확정).
    """
    if conflict:
        return {"state": DISCOUNT_STATE_UNKNOWN, "note": "요율 원천 충돌 — 청구행마다 할인이 다릅니다"}
    if susu_dc is None or susu_dc <= 0 or susu_dc >= 1:
        return {"state": "", "note": ""}

    purpose_text = _text(purpose)
    codes = {c["code"] for c in (candidates or [])}
    if entered_code:
        codes.add(entered_code)

    floors: "list[tuple[float, str]]" = []
    for code in sorted(codes & set(DISCOUNT_FLOOR_BY_CODE)):
        floors.append((DISCOUNT_FLOOR_BY_CODE[code], FEE_CODE_LABELS.get(code, f"코드 {code}")))
    # 제5호 목적(자산재평가·집합투자·리츠): 기본 40%, 1년 내 재의뢰가 확인되면
    # 60%까지(단서, 2026-02-09 신설 — 코드 45). 재의뢰 12개월 이내 = 코드 13/14/15/16.
    if "자산재평가" in purpose_text or _text(work) == "유동화자산" or codes & {41, 42}:
        floors.append((0.60, "제6조②5호 40% 이내"))
        if codes & {13, 14, 15, 16}:
            floors.append((0.40, "제6조②5호 단서 1년 내 60% 이내"))
    if not floors and any(hint in purpose_text for hint in _DISCOUNT_20PCT_HINTS):
        floors.append((0.80, "제6조②3·4호(20%) 추정"))

    if floors:
        floor, basis = min(floors)
        if susu_dc + 1e-6 < floor:
            return {
                "state": DISCOUNT_STATE_OVER,
                "note": f"{basis} — 허용 x{floor:g} 미만으로 깎임 (실제 x{susu_dc:g})",
            }
        return {"state": DISCOUNT_STATE_OK, "note": basis}

    if codes & _DISCOUNT_EXEMPT_CODES or "자문" in purpose_text or "시가참고" in purpose_text:
        return {"state": DISCOUNT_STATE_EXEMPT, "note": "요율표 밖 계약(자문·공시 등)"}

    return {
        "state": DISCOUNT_STATE_NO_BASIS,
        "note": f"x{susu_dc:g} 할인인데 재의뢰 이력·할인 대상 목적이 없음 — 사유 확인",
    }
