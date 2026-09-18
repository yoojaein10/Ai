"""보수기준 자동 판별 규칙 테스트."""

from datetime import date

from app.services.fee_basis_rules import (
    detect,
    purpose_candidates,
    reappraisal_candidate,
    retro_candidate,
    text_candidates,
    verdict,
)


def codes(candidates):
    return [c["code"] for c in candidates]


class TestPurposeCandidates:
    def test_담보는_특이후보_없음(self):
        assert purpose_candidates("담보", "제1금융권담보") == []

    def test_법원경매는_대법원예규(self):
        assert 32 in codes(purpose_candidates("법원 및 공매", "법원경매"))

    def test_소송은_소송할증과_예규(self):
        found = codes(purpose_candidates("법원 및 공매", "민사소송"))
        assert 40 in found and 35 in found

    def test_공매NPL은_예규_아님(self):
        assert purpose_candidates("법원 및 공매", "공매(NPL)") == []

    def test_공시업무(self):
        assert 43 in codes(purpose_candidates("공시업무", "개별공시지가 검증"))

    def test_보상은_종량제와_종가(self):
        found = codes(purpose_candidates("보상", "협의보상(사업시행자)"))
        assert 23 in found and 38 in found

    def test_수용재결은_할증_추가(self):
        assert 11 in codes(purpose_candidates("보상", "수용재결(중토위)"))

    def test_컨설팅만_제11조_가격자문은_뺀다(self):
        """두 업무는 성격이 다르다 — 평가액 유무로 갈린다(2026-08-07 실측).

        컨설팅 771건 중 평가액 있음 53건(6.9%) → 요율체계(1) 적용 불가라 제11조가 맞다.
        가격자문 14,981건 중 9,664건(64.5%) → 요율체계가 성립하므로 단정하지 않고
        폴백(코드1)에 맡긴다. 실제로 사람도 코드1을 고른다(166건 중 165건이 평가액 있음).
        """
        assert 24 in codes(purpose_candidates("컨설팅", "기타자문및컨설팅"))
        assert 24 not in codes(purpose_candidates("가격자문", "공동주택가격 자문"))

    def test_자산재평가는_제11조(self):
        """21(자산재평가 40% 할인)은 사람이 고른 적이 0건이고 실제 할인도 안 붙는다.
        24(제11조 상담·자문)를 90건 골랐다(2026-08-07 실측)."""
        assert 24 in codes(purpose_candidates("기업관련", "자산재평가"))
        assert 21 not in codes(purpose_candidates("기업관련", "자산재평가"))

    def test_공시업무는_기타를_앞에_둔다(self):
        """개별공시지가 검증 2022~2024 158건 전부 코드37, 43은 공시업무에 10건뿐이다."""
        found = codes(purpose_candidates("공시업무", "개별공시지가 검증"))
        assert found[0] == 37 and 43 in found

    def test_임료는_임대료평가(self):
        assert 39 in codes(purpose_candidates("국공유재산", "(國)임료(사용료)"))


class TestTextCandidates:
    def test_키워드는_최소횟수를_지킨다(self):
        # 구축물은 상투 문구 오탐 방지로 3회 이상일 때만
        pages = [(1, "구축물 평가"), (2, "구축물"), (3, "구축물 배치도")]
        assert 3 in codes(text_candidates(pages))
        assert text_candidates([(1, "구축물 평가")]) == []

    def test_선하지는_한번이면_잡힌다(self):
        found = text_candidates([(4, "본건은 선하지로서 감가율을 적용")])
        assert codes(found) == [12]
        assert found[0]["page"] == 4
        assert "선하지" in found[0]["evidence"]

    def test_해체처분_1회는_법령인용_오탐으로_본다(self):
        assert text_candidates([(9, "해체처분가액으로 감정평가할 수 있다")]) == []

    def test_온천은_지명이면_무시(self):
        # '온천로 102' 같은 도로명 주소는 신호가 아니다 (실측 오탐)
        pages = [
            (1, "대전광역시 유성구 온천로 102"), (2, "온천동 소재"),
            (3, "유성온천역 인근"), (4, "온천원보호지구<온천법>"),
        ]
        assert text_candidates(pages) == []
        real = [(5, "본건 온천 이용시설"), (7, "온천 공급권 평가")]
        assert 9 in [c["code"] for c in text_candidates(real)]


class TestRetro:
    def test_6개월_이상_소급(self):
        found = retro_candidate(date(2026, 7, 1), date(2025, 10, 1))
        assert found and found["code"] == 2

    def test_6개월_미만은_무시(self):
        assert retro_candidate(date(2026, 7, 1), date(2026, 3, 1)) is None

    def test_60개월_초과는_파싱오류로_무시(self):
        assert retro_candidate(date(2026, 7, 1), date(1989, 4, 7)) is None


class TestReappraisal:
    def test_구간별_할인코드(self):
        assert reappraisal_candidate(2, "01-2604-3-0001")["code"] == 14
        assert reappraisal_candidate(5, "01-2601-3-0001")["code"] == 15
        assert reappraisal_candidate(9, "01-2510-2-0166")["code"] == 16
        assert reappraisal_candidate(23, "01-2408-3-3127")["code"] == 17

    def test_이력_없으면_무시(self):
        assert reappraisal_candidate(None, None) is None
        assert reappraisal_candidate(30, "01-2312-3-0001") is None


class TestDetect:
    def test_신호_없으면_기본요율(self):
        found = detect(work="담보", purpose="제1금융권담보")
        assert codes(found) == [1]

    def test_목적과_본문_후보_합치되_중복제거(self):
        found = detect(
            work="기업관련", purpose="자산재평가",
            pages=[(3, "자산재평가 목적의 감정평가")],
        )
        assert codes(found).count(24) == 1


class TestVerdict:
    def test_판정(self):
        candidates = [{"code": 1}, {"code": 24}]
        assert verdict(None, candidates) == "미입력"
        assert verdict(0, candidates) == "미입력"
        assert verdict(24, candidates) == "일치"
        assert verdict(43, candidates) == "불일치"


# ── 할인 적정성 (업무연락 제2026-38호) ──────────────────────────────────────

from app.services import fee_basis_rules as rules


def _dj(dc, **kw):
    return rules.discount_judgement(dc, **kw)["state"]


def test_할인이_없으면_판정하지_않는다():
    """x1(정가)·x0(전액무료)·할증·요율 미기재는 이 축의 대상이 아니다 —
    무료는 금액 축(fee_state), 할증은 요율 축이 이미 다룬다."""
    assert _dj(None) == ""
    assert _dj(1.0) == ""
    assert _dj(0.0) == ""
    assert _dj(1.5) == ""


def test_요율_원천_충돌은_판정_불가다():
    """청구행마다 할인이 다르면 어느 값을 검증할지 알 수 없다 — 0으로 뭉개지 않는다.

    fetch_rates 가 남기는 대표값은 '첫 행'(임의)이라 정가(x1)·NULL 일 수도 있다.
    게이트보다 conflict 를 먼저 봐야 (정가,할인) 순서에서 할인 건이 무판정으로
    사라지지 않는다 — 대표값이 무엇이든 충돌이면 판정 불가다."""
    assert _dj(0.5, conflict=True) == rules.DISCOUNT_STATE_UNKNOWN
    assert _dj(1.0, conflict=True) == rules.DISCOUNT_STATE_UNKNOWN
    assert _dj(None, conflict=True) == rules.DISCOUNT_STATE_UNKNOWN


def test_제1호_사다리_구간과_한도():
    """재의뢰 구간별 허용 최소 SusuDc. 경계값(정확히 한도)은 구간 내다."""
    six_months = [{"code": 15}]  # detect() 가 이미 구간을 갈라 준다
    assert _dj(0.5, candidates=six_months) == rules.DISCOUNT_STATE_OK
    # 6개월 구간(50%)인데 90%를 깎으면 초과 — 2026 실측 01-2605-3-1732 유형
    assert _dj(0.1, candidates=six_months) == rules.DISCOUNT_STATE_OVER
    assert _dj(0.3, candidates=[{"code": 14}]) == rules.DISCOUNT_STATE_OK


def test_제5호_자산재평가는_40_기본_1년내_60():
    """40% 이내(x0.60)가 기본, 1년 내 재의뢰(코드13~16 동반)가 확인될 때만
    60%(x0.40)까지 — 2026-02-09 신설 단서."""
    assert _dj(0.6, purpose="자산재평가") == rules.DISCOUNT_STATE_OK
    assert _dj(0.5, purpose="자산재평가") == rules.DISCOUNT_STATE_OVER
    assert _dj(0.4, purpose="자산재평가", candidates=[{"code": 14}]) == rules.DISCOUNT_STATE_OK


def test_사람이_적은_근거_코드도_인정한다():
    """detect() 가 이력을 못 찾아도 청구서에 적힌 코드(예: 15)는 근거다 —
    한도 검증은 똑같이 한다."""
    assert _dj(0.5, entered_code=15) == rules.DISCOUNT_STATE_OK
    assert _dj(0.1, entered_code=15) == rules.DISCOUNT_STATE_OVER


def test_자문류는_대상_외다():
    """시가참고·자문·공시(후보 24/37/43/44)는 요율표 밖 계약 — 할인 개념이 없다."""
    assert _dj(0.3, purpose="시가참고") == rules.DISCOUNT_STATE_EXEMPT
    assert _dj(0.3, purpose="공동주택가격 자문") == rules.DISCOUNT_STATE_EXEMPT
    assert _dj(0.3, candidates=[{"code": 24}]) == rules.DISCOUNT_STATE_EXEMPT


def test_근거없는_할인은_확인_대상이다():
    """담보처럼 할인 대상이 아닌 목적에 이력도 근거 코드도 없이 깎여 있으면
    업무연락 적발 사례2와 같은 모양 — 2026 실측 16건."""
    assert _dj(0.1, purpose="기타 담보") == rules.DISCOUNT_STATE_NO_BASIS


def test_재건축_20퍼센트_관행은_추정으로_인정한다():
    """재건축 종전·종후 x0.8 은 제3·4호(20%) 관행으로 추정 — 그보다 크게 깎이면
    추정 근거로도 설명이 안 되니 확인 대상."""
    assert _dj(0.8, purpose="주택재건축(종전)") == rules.DISCOUNT_STATE_OK
    assert _dj(0.5, purpose="주택재건축(종전)") == rules.DISCOUNT_STATE_OVER
