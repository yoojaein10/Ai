"""적요 토막으로 감정서 찾기.

여기 적힌 숫자는 전부 2026-08-05 에 실제로 잰 값이다(정답지 = 재무팀이 통장
Memo 에 손으로 적어 둔 감정서번호). 규칙마다 왜 그렇게 정했는지를 근거와 함께
묶어 둔다 — 근거 없이 되돌리면 정확도가 떨어지는 자리들이다.
"""

from pathlib import Path

import pytest

from app.services import deposit_search as ds

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "app" / "services" / "deposit_search.py"


def code() -> str:
    """주석·독스트링을 걷어낸 실행 코드만.

    이 파일은 '이렇게 쓰면 안 된다'를 근거와 함께 주석에 남겨 두는 편이라,
    원문을 그대로 훑으면 설명을 코드로 착각한다.
    """
    import io
    import tokenize

    source = SOURCE.read_text(encoding="utf-8")
    out = []
    previous = tokenize.INDENT
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            continue
        # 독스트링 = 문장 첫머리에 홀로 선 문자열
        if token.type == tokenize.STRING and previous in (
                tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE, tokenize.NL):
            previous = token.type
            continue
        if token.type not in (tokenize.NL, tokenize.NEWLINE):
            previous = token.type
        out.append(token.string)
    return " ".join(out)


# ── 토막내기 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("jeokyo", "expected"), [
    ("상주시산림조합/타행환/(산림)/", ["상주시산림조합", "타행환", "산림"]),
    ("2026117733/수수료/홍천/", ["2026117733", "수수료", "홍천"]),
    ("우리은행//서여의도금융센터/대체입금", ["우리은행", "서여의도금융센터", "대체입금"]),
])
def test_적요를_슬래시로_쪼갠다(jeokyo, expected):
    """재무팀이 눈으로 하던 그 쪼개기다. '//' 는 빈 칸이라 하나로 본다."""
    assert ds.tokens(jeokyo) == expected


def test_토막을_감싼_괄호만_벗긴다():
    """여는 괄호만 보고 자르면 '(주)대화감정평가법인' 이 '주)대화감정평가법인' 이
    되어 원장 어디에도 안 걸린다."""
    assert ds.tokens("(주)대화감정평가법인/대체")[0] == "(주)대화감정평가법인"
    assert ds.tokens("상주시산림조합/(산림)/")[1] == "산림"


def test_전각_문자를_반각으로_눕힌다():
    """통장이 전각으로 내보내는 자리가 있다 ('Ｆ／Ｂ', '서울지방국세청２６０')."""
    assert "260" in "".join(ds.tokens("서울지방국세청２６０/대체"))
    # 전각 슬래시도 구분자다 — 'Ｆ／Ｂ' 는 한 글자씩이라 통째로 버려진다
    assert ds.tokens("BC-745827823//WON뱅킹사업부/Ｆ／Ｂ") == ["BC-745827823", "WON뱅킹사업부"]


def test_잘린_괄호_뒤_이름을_살린다():
    """통장 적요는 20자에서 잘린다 — '수수료입금(주식회사아우' 처럼 괄호가 안 닫힌다.
    정작 찾을 이름이 괄호 뒤에 있어서, 이걸 안 꺼내면 어디에도 안 걸린다.
    실측: 이 손질을 포함한 확장 토큰화로 3개월 창 재현율 40.0% → 55.0%."""
    words = ds.expand("수수료입금(주식회사아우//수협서초종합금융본부/대체")
    assert "주식회사아우" in words
    # 은행 접두를 뗀 형태도 함께 넣는다 — 원장에는 '서초종합금융본부' 로 있다
    assert "서초종합금융본부" in words


def test_숫자런을_따로_뽑는다():
    """5자리 이상 숫자런은 의뢰문서번호(CustDocID)로 가는 열쇠다.
    실측 40건 중 11건 적중, 그중 7건은 이 축 단독으로만 맞혔다."""
    assert "50018808" in ds.expand("계선50018808/대체입금")
    assert "2026060962" in ds.expand("2026060962//여신업무센터/대체입금")


def test_엔_앤_표기_차이도_같이_찾는다():
    """'&' 를 적요와 원장이 다르게 옮긴다 — 실측 계기(test_금액만_맞은_지사_후보는_안_보여준다
    참고): 적요 '주식회사에이치엔제이컨설팅' 는 '엔' 인데 원장 CustName 은
    '에이치앤제이컨설팅' 로 '앤' 이라 이름 축이 아예 후보를 못 냈다(2026-08-13).
    양쪽 표기를 다 넣어야 어느 쪽이 오든 걸린다."""
    words = ds.expand("주식회사에이치엔제이컨설팅/수수료/")
    assert "에이치엔제이컨설팅" in words
    assert "에이치앤제이컨설팅" in words
    # 반대 방향도 — 적요가 '앤' 으로 찍혀 오는 경우
    assert "에이치엔제이" in ds.expand("에이치앤제이/전자금융")


def test_그룹사_영문_약칭도_같이_찾는다():
    """정답지 전수(Memo 채워진 3,531건, 상한 없이 재조회) 실측: 적요 '엘지에너지솔루션'
    은 원장에 'LG에너지솔루션' 으로 실려 이름 축이 놓치는 게 3건, '지에스건설' 은
    원장 '(주)GS건설' 로 실려 2건 있었다(2026-08-13). SK·KT·DB·NH 등 원장에 영문
    표기가 많아도 정답지에서 실제 놓친 적요가 0건인 그룹사는 넣지 않았다."""
    words = ds.expand("(주)엘지에너지솔루션/채권입금/트윈타워/")
    assert "LG에너지솔루션" in words
    words = ds.expand("지에스건설(주)/FB자금/GS대기/지에스건설(주)")
    assert "GS건설" in words


# ── 불용어 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("word", [
    "대체", "대체입금", "타행환", "수수료", "현금", "창구",   # 거래유형어
    "기업", "부산", "우리은행", "새마을금고",                # 은행·지사 이름
])
def test_거래유형어와_은행이름은_1순위_근거가_못_된다(word):
    """사용자 지시는 '타행환'·'대체' 같은 토막도 검색어로 쓰라는 것이었고 그대로 재 봤다.
    결과: 40건 중 19건(47.5%)에서 1순위가 이런 말로 뽑혔고 **19건 전부 오답**이었다.
    '대체'가 3개월 창에서 겨우 6건만 걸려, '가장 적게 걸린 토막' 규칙이 오히려
    이걸 최우선으로 고른다. 그래서 검색은 하되 순위에서는 내린다."""
    assert ds.is_stop(word)


def test_진짜_이름은_불용어가_아니다():
    for word in ("상주시산림조합", "주식회사아우", "KB자산운용", "단국대구매관재1팀"):
        assert not ds.is_stop(word), word


# ── 축의 강도 ─────────────────────────────────────────────────────────────

def test_적요에_박힌_번호가_금액을_이긴다():
    """실측에서 '260730658//03143/창구' 의 1순위가 금액이 우연히 같은 남의
    감정서(01-2510-3-3432)로 뒤집힌 적이 있다. 적요에 번호가 그대로 적힌 건은
    116건 중 95.7% 가 재무팀 Memo 와 같았으므로 그쪽이 이겨야 한다."""
    number = {"field_label": "적요에 번호"}
    amount_many = {"field_label": "매출총액 일치", "amount_unique": False}
    amount_one = {"field_label": "매출총액 일치", "amount_unique": True}
    assert ds._axis_score(number) > ds._axis_score(amount_one)
    assert ds._axis_score(amount_one) > ds._axis_score(amount_many)


def test_금액은_창_안에_하나뿐일_때만_강하다():
    """실측 827건: 입금액이 매출총액과 같은 비율은 73.5% 인데, 그중 같은 금액의
    감정서가 창 안에 여럿인 게 대부분이라 **금액만으로 정답이 확정되는 건 23.5%**
    (194건)뿐이다. 그 194건은 100% 정답이었다. 55,000원 같은 정액 수수료는
    한 창에 1,844건까지 걸린다."""
    assert ds._axis_score({"field_label": "매출총액 일치", "amount_unique": True}) >= 80
    assert ds._axis_score({"field_label": "매출총액 일치", "amount_unique": False}) <= 20


def test_원문_본문은_약한_근거다():
    """본문 히트의 45.7% 만 원장 의뢰처와 일치했다 — 나머지는 등기부등본
    근저당권자 등으로 본문에만 등장한 것이다."""
    assert ds._axis_score({"field_label": "원문 본문"}) < ds._axis_score({"field_label": "의뢰처"})


# ── 검색하지 않기로 한 것들 ────────────────────────────────────────────────

def test_유치자_조사자는_뒤지지_않는다():
    """40건 표본에서 유치자(Manager)·조사자(Charge)·심사(JudgCharge)·서명평가사
    (LSigner)·접수담당(LReceiptCharge)·소유자(OwnerName)·의뢰처담당(CustCharge)은
    정답을 **한 건도** 맞히지 못했다. 통장 적요에 우리 직원 이름이 찍히지 않는다."""
    columns = {col for col, _ in ds._NAME_COLS}
    for never in ("Manager", "Charge", "ProcessCharge", "JudgCharge",
                  "LSigner", "LReceiptCharge", "OwnerName", "CustCharge",
                  "LCustCategory", "LOffice", "Building", "Client"):
        assert never not in columns, f"{never} 는 정답을 맞힌 적이 없다"


def test_실제로_맞힌_컬럼만_남긴다():
    """1년치 정답지 3,441건 실측으로 추린 축이다. Title(제목)은 뺐다 —
    1순위로 뽑혀 맞힌 게 0건, 틀린 게 55건이었다. 값이 '<채무자> 담보물' 꼴이라
    Debtor 의 그림자인데 자유기재라 엉뚱한 말이 섞인다."""
    columns = {col for col, _ in ds._NAME_COLS}
    assert columns == {"CustName", "Production", "Debtor"}
    assert "Title" not in columns, "1년치에서 0/55 였다"
    assert "_custdocid_sync" in code() and "_bigo_sync" in code()


# ── 기간창 ────────────────────────────────────────────────────────────────

def test_창_상한은_6개월이다():
    """사용자 결정(2026-08-06, 속도 우선). 거래일−접수일 실측: 183일 93.6% ·
    366일 96.7% — 6개월 상한은 약 3%p 를 속도와 맞바꾼 것이다.
    근거 없이 12개월로 되돌리지도, 3개월로 줄이지도 말 것(3개월은 15.2% 이탈)."""
    assert ds._WINDOWS[0] == 1, "가장 좁은 창부터"
    assert ds._WINDOWS[-1] == 6, "상한 6개월 — 사용자 결정"
    assert ds._AMOUNT_MAX == 6
    assert list(ds._WINDOWS) == sorted(ds._WINDOWS), "좁은 창부터 넓혀 간다"


def test_창_끝을_거래일보다_뒤로_둔다():
    """접수·발송이 입금보다 늦는 건이 있다(실측 최대 -10일)."""
    assert ds._FORWARD_DAYS >= 8


# ── 성능이 걸린 자리 ──────────────────────────────────────────────────────

def test_감정서번호는_스캔하지_않고_짚는다():
    """RIGHT(REPLACE(DocID,'-',''),9) = :c 로 쓰면 인덱스를 못 타 뷰 73만 행을
    통째로 훑어 3~4초가 든다(실측). 지사 접두를 다 만들어 IN 으로 받으면 0.1초다."""
    assert "RIGHT(REPLACE" not in code(), "전량 스캔이 된다"
    assert ds._doc_id_candidates("260720088")[0] == "01-2607-2-0088"
    assert "10-2607-2-0088" in ds._doc_id_candidates("260720088")
    assert ds._doc_id_candidates("40057840") == [], "9자리가 아니면 번호가 아니다"


def test_원문은_CONTAINS_로만_친다():
    """실측: chunk.content LIKE '%상주시산림조합%' 19.2초 vs CONTAINS 0.02초.
    기간을 좁혀도 LIKE 는 안 줄어든다 — 전량 스캔이 먼저 돌기 때문이다."""
    source = code()
    assert "CONTAINS(ch.content" in source.replace(" ", "")
    assert "ch.content LIKE" not in source
    # 접두어 별표는 붙이지 않는다 — '"상주시산림조합*"' 33.1초 vs 0.02초
    assert '"{term}*"' not in source and "'*\"'" not in source



def test_원문_사다리_하한은_2다():
    """원래 5였다(4글자 조각이 오답 제조기라서). 그런데 제3자 입금 실패 84건 중
    45건은 입금자명이 감정서 원문에 실존하고, 그중 32건이 2~4자 인명·상호라
    하한 5에서 전멸했다. 낮춰도 안전한 이유 — 전역 히트 60 상한이 흔한 말
    ('월드' 2,374건·흔한 인명 1,071건)을 그대로 거르고, 근거 2개 tier 가 원문
    단독을 확신에서 뺀다. A/B 실측: 실패 136건 +31 회수 · 1개월 회귀 +2%p."""
    assert ds._FTS_MIN == 2
    assert ds._FTS_MAX_HITS == 60, "이 상한이 하한 2 를 안전하게 만든다"

def test_원문_검색어에서_특수문자를_걷어낸다():
    """괄호·별표·&|~, 가 든 말은 CONTAINS 에서 예외 없이 0건이 된다
    (실측 '(주)코크렙제52호' 0건 → '주' 로 잘라도 무의미, '대정이앤디(주) 우리전자'
    → '대정이앤디' 로 손질하면 3건)."""
    assert ds._fts_words(["(주)코크렙제52호"]) == ["코크렙제52호"] or \
           ds._fts_words(["(주)코크렙제52호"]) == []
    assert "대정이앤디" in ds._fts_words(["대정이앤디(주) 우리전자"])
    # 거래유형어는 원문에서 엉뚱한 감정서를 물어 온다 ('타행환' 83문서)
    assert ds._fts_words(["타행환", "대체입금"]) == []


def test_구버전_파싱본을_거른다():
    """jun.chunk 에 is_active=0 행이 68,838개(구버전) 있다 — 같이 읽으면
    같은 감정서가 유령으로 뜬다."""
    assert "ch.is_active = 1" in code()


def test_원문_조인은_case_master_로_간다():
    """벤더의 document_version.appraisal_number 는 3.7% NULL 이라 샌다.
    처음엔 apw_case(normalized_doc_id)로 갔지만, 그 미러가 2026-07-15 에 멈춰
    최근 접수분이 통째로 사각이었다 — 지금은 case_master 만 쓴다:
    chunk.master_id → case_master.doc_id, 창은 yymm(접수일의 달과 99.90% 일치)."""
    source = code()
    assert "cm.master_id = ch.master_id" in source
    assert "cm.yymm >= %s" in source
    assert "appraisal_number" not in source
    assert "apw_case" not in source, "멈춘 미러를 조인하면 최근 접수분이 사각"


def test_어디에도_쓰지_않는다():
    """통장 Memo 는 남의 시스템 입력이고 우리는 그 DB 에 sa 로 붙어 있다
    (app/services/deposit_match.py 상단)."""
    import re

    body = code()
    # SQL 키워드는 대문자로만 쓴다 — 소문자 변수명(merged)까지 잡지 않도록.
    for forbidden in ("UPDATE", "INSERT", "DELETE", "MERGE"):
        assert not re.search(rf"{forbidden}", body), f"쓰기 구문이 있다: {forbidden}"
    assert "읽기 전용" in SOURCE.read_text(encoding="utf-8")

def test_지사_감정서는_1순위로_안_올린다():
    """이 통장에 들어오는 입금은 사실상 본사 것이다 — 2026년 정답지 1,946건 중
    감정서번호 앞 두 자리가 '01'인 게 1,943건(99.8%)이고 나머지는 3건뿐이다.
    지사 후보를 1순위로 올리면 거의 언제나 틀린다(실측: 이 규칙 하나로 1순위
    정확도 75% → 78%). 후보에서 빼지는 않는다 — 그 3건이 실제로 있다."""
    assert ds._HOME_OFFICE == "01"
    assert ds._OTHER_OFFICE_PENALTY > 0
    source = code()
    assert "_OTHER_OFFICE_PENALTY" in source
    # 걸러내는 게 아니라 순위만 내린다 — WHERE 절에 지사 조건을 넣으면 안 된다
    assert "LEFT(a.DocID" not in source and "a.Office =" not in source


def test_찾은_뒤에_전표와_미수를_되짚는다():
    """이름으로 영원히 못 잡는 제3자 입금이 17.5% 인데, 재무팀이 진짜 알아야 하는
    건 '이 입금이 이미 회계에 들어갔나'다. 후보마다 같은 날 같은 금액 전표가
    있는지, 미수 잔액이 얼마인지 붙여 그 자리에서 판단이 끝나게 한다."""
    source = code()
    assert "_voucher_docs_sync" in source, "같은 날 같은 금액 전표를 본다"
    assert "_money_sync" in source, "입금현황과 같은 요약을 쓴다"
    assert "outstanding" in source and "money_note" in source


def test_원천징수_보정을_넣지_않는다():
    """실측 827건: 원천징수(3.3%·3%·2.2%)로 설명되는 건 0건, ±1,000원 차액도
    딱 1건이었다. 보정할 게 없는데 넣으면 없는 규칙을 지어내는 것이다."""
    source = code()
    for guess in ("0.033", "3.3", "0.967", "withholding"):
        assert guess not in source, f"근거 없는 보정: {guess}"


def test_전표가_하나를_가리킬_때만_강한_근거다():
    """전표는 하루치 입금 수십 건을 담은 묶음장부다. 한 전표에 달린 감정서를 다
    긁어 오면 뭉뚱그려진다 — 실측(7월 정답지 252건) 전표가 감정서를 하나만
    가리킨 게 173건(69%)이고 나머지는 최대 23개까지 딸려 왔다. 정답이 그 안에
    든 비율은 96% 지만, 여럿일 때는 '어느 것'인지를 말해 주지 못한다."""
    source = code()
    assert "unique_voucher" in source
    assert "40 if unique_voucher else 10" in source, "여럿이면 가산점만"
    assert "voucher_alone" in source, "화면이 둘을 구분할 수 있어야 한다"


def test_1년치_실측으로_정한_축_점수():
    """2025-08-06~2026-08-05 정답지 3,441건 실측 정밀도(1순위로 뽑혔을 때 맞힌 비율):
    적요에 번호 98.2% · 의뢰문서번호 91.4% · 청구금액 90.6% · 매출총액 73.3% ·
    의뢰처 56.5% · 채무자 52.6% · 원문 본문 44.2% · 비고 11.1% · 미수 잔액 1.9%.
    점수 서열이 이 순서를 따라야 한다."""
    def s(label, **kw):
        return ds._axis_score({"field_label": label, **kw})

    assert s("적요에 번호") > s("의뢰문서번호") > s("의뢰처") >= s("채무자")
    assert s("채무자") > s("원문 본문") > s("비고")
    # 미수 잔액은 단독으로 이기면 안 된다 — 1년치 1/52 였다
    assert s("미수 잔액 일치", amount_unique=True) < s("의뢰처")
    assert s("미수 잔액 일치", amount_unique=True) < s("원문 본문")



def test_원문은_이름_축이_빈손일_때_연다():
    """예전 문('후보 0건일 때만')은 554건 중 8건(1.4%)만 열렸다 — 금액 후보
    몇 개가 문을 막아, 원문에 입금자명이 실존하는 제3자 입금 45건이 영영 안
    보였다. 새 문: 이름 축 강한 히트가 없고 축점수 85+ 후보도 없으면 연다.
    A/B 실측: 실패 136건 1순위 12%→35%(+31, 잃음 0) · 1개월 83%→85%."""
    body = code().replace(" ", "")
    assert "ifnotitems" not in body[body.index("fts_words=_fts_words(names)")-300:
                                    body.index("fts_words=_fts_words(names)")],         "후보-0건 문으로 되돌리면 원문 경로가 사실상 죽는다"
    assert "notstrong_name_seen" in body
    assert "_fts_unwindowed" in body, "창 안 전패 시 창 무제한 1회"
    # 창 조인은 case_master.yymm — apw_case 미러는 2026-07-15 에 멈춰 있다
    assert "cm.yymm>=%s" in body.replace(" ","")
    assert "jun.apw_case" not in body, "멈춘 미러를 조인하면 최근 접수분이 사각"

def test_원문_히트는_같은_단어_안에서_상대비교한다():
    """섹션 화이트리스트로 거르면 망한다 — 강섹션만 남기면 후보 593→202 로
    줄지만 정답 포함이 111→70 으로 무너지고 1순위가 66.0%→41.3% 가 된다.
    정답이 etc 에서만 걸리는 건은 거의 전부 감정서번호 스탬프이기 때문이다.
    대신 같은 단어 안에서만 견준다 — 오탐 -43.6%, 재현 손실 0."""
    body = code().replace(" ", "")
    assert "strong" in body and "_STRONG_SECTIONS" in body
    assert "found.extend(strongif(strongandlen(picked)>_ADAPT_MIN)elsepicked)" in body, (
        "강한 게 없거나 후보가 몇 개 안 되면 전부 남긴다")
    # 후보가 서너 개뿐인데 자르면 정답까지 날아간다 — 어려운 건 553건에서
    # 무조건 자르면 재현이 106→99 로 떨어졌다(쉬운 건만 보면 안 보이던 손해다).
    assert ds._ADAPT_MIN >= 3
    # 등기부(registry)를 지우는 조치는 아무것도 안 한 것과 같다(오탐의 5.2%)
    assert "registry" not in ds._STRONG_SECTIONS


def test_지사_이름을_함께_준다():
    """본사(01)가 아닌 후보는 화면이 지사 칸에 이름을 보여준다 (2026-08-06 요청).
    매핑은 2024년 이후 원장 실측(LEFT(DocID,2) 별 최빈 LOffice, 예외 0건)."""
    assert ds.office_name("02-2606-3-0693") == "부산경남지사"
    assert ds.office_name("10-2508-3-1088") == "북부지사"
    assert ds.office_name("01-2604-3-1065") == "본사"
    assert ds.office_name("") == ""


def test_확장_축은_기본_축이_비었을_때만_돈다():
    """고객측 전 컬럼(제목·소유자·의뢰처 담당·부서)을 모든 조회에 끼워 넣었더니
    LIKE 항이 단어당 10개로 불어 최악 186초까지 밀렸다(실측). 기본 축이 0건인
    어려운 건에만 12개월 한 번으로 돌면 흔한 조회는 그대로 빠르다."""
    assert {c for c, _ in ds._NAME_COLS} == {"CustName", "Production", "Debtor"}
    assert {c for c, _ in ds._NAME_COLS_WIDE} == {
        "Title", "OwnerName", "CustCharge", "CustPart"}
    body = code().replace(" ", "")
    assert "cols=_NAME_COLS_WIDE" in body
    # 확장 축 점수는 의뢰처·채무자를 못 이긴다 — 1년치에서 제목이 0/55 였다
    assert ds._axis_score({"field_label": "제목"}) < ds._axis_score({"field_label": "채무자"})
    assert ds._axis_score({"field_label": "소유자"}) < ds._axis_score({"field_label": "채무자"})


def test_Gemini_는_마지막_그물이다():
    """표기 차이(LH↔한국토지주택공사, 포티투닷↔42DOT)가 실패의 15%였다.
    다만 금액이 유일하게 맞으면 그게 답이라(실측 100%) Gemini 호출(~2초)이
    낭비다 — 금액 축 **뒤**에서, 믿을 만한 축이 없을 때만 부른다."""
    body = code().replace(" ", "")
    assert "_gemini_variants_sync" in body
    gem = body.index("variants=_gemini_variants_sync")
    assert body.index("pool.submit(_amount_sync,amount,day)") < gem, "금액 축이 먼저다"
    assert body.rindex("found=_bigo_sync(") > gem, "비고·원문보다는 앞이다"
    # 실패해도 조용히 빈 목록 — 외부 API 가 검색을 막으면 안 된다
    assert "return[]" in body


def test_전표_조회에_시간_상한이_있다():
    """a10_voucher_cache 는 amount 인덱스가 없어 특정 금액에서 조회가 164초까지
    밀렸다(실측). 전표는 부가 정보라 5초를 넘기면 없이 간다."""
    body = code().replace(" ", "")
    assert "job.result(timeout=5)" in body
    assert "FuturesTimeout" in body


def test_자리바꿈_오타를_되돌려_본다():
    """은행 창구가 번호를 옮겨 적다 이웃 자리를 바꾼다 — '206732380' 은 2067이
    유효 연월이 아니라 탈락하지만, 2067→2607 을 되돌리면 01-2607-3-2380 이
    원장에 실존한다(2026-08-06 실측, Memo 는 재무팀도 못 채워 비어 있었다).
    가드: 원래 번호가 0건일 때만 · 유효 연월만 · 접수일 13개월 안만.
    미해결 60일 실측에서 엉뚱한 감정서를 문 변형은 0건."""
    body = code().replace(" ", "")
    assert "def_typo_sync(" in body
    assert "run[:i]+run[i+1]+run[i]+run[i+2:]" in body, "인접 자리바꿈"
    assert "deposit_match._valid(v[:2],v[2:4],v[4])" in body, "유효 연월·구분만"
    # 점수는 정확 일치(100)보다 낮고 의뢰문서번호(90)보다도 낮다
    assert ds._AXIS_SCORE["적요 번호 보정"] < ds._AXIS_SCORE["적요에 번호"]
    # 흐름: 원래 번호·매핑이 아무것도 못 찾았을 때만
    assert "found=_typo_sync(jeokyo,day)" in body


def test_걸린_곳은_원문일_때_절_이름을_준다():
    """화면 '걸린 곳' 칸 — 원장 계열은 '통합 데이터', 원문은 '감정서 원문 · 절'
    까지만 보여준다 (2026-08-06 요청). 절 이름은 한국어로 옮긴다."""
    assert ds._SECTION_KO["request"] == "의뢰서"
    assert ds._SECTION_KO["cover"] == "표지"
    assert ds._SECTION_KO["etc"] == "본문"
    body = code().replace(" ", "")
    assert "strong_sec" in body and "any_sec" in body, "강한 절 우선"


def test_근거_2개_규칙():
    """금액 하나만으로 찾으면 오탐이 많다(사용자 관찰, 2026-08-06). 실측이 극적으로
    확인했다 — 1순위의 정밀도: 근거 2개 이상 98% · 금액+회계 100% · 번호 단독 91% ·
    금액 단독 44% · **이름 단독 0%(0/38)**. 그래서 번호가 있거나 갈래(번호·이름·
    금액·회계)가 2개 이상이어야 확신 후보로 올라간다. 단독 후보는 버리지 않고
    순위를 내리며 화면에 '단일 근거'라고 밝힌다."""
    assert ds._tier({"evidence": ["번호"]}) == 0, "번호는 단독으로도 확신(91%)"
    assert ds._tier({"evidence": ["이름", "금액"]}) == 0
    assert ds._tier({"evidence": ["금액", "회계"]}) == 0, "실측 100%"
    assert ds._tier({"evidence": ["금액"]}) == 1, "금액 단독 44% — 내린다"
    assert ds._tier({"evidence": ["이름"]}) == 2, "이름 단독 0% — 맨 뒤"
    body = code().replace(" ", "")
    assert "_tier(item)," in body, "정렬 키의 최우선이다"


def test_근거가_하나뿐이면_후보에서_뺀다():
    """'이가윤/대체//' 88,000원이 이 규칙이 필요한 이유다 — 88,000원은 흔한 정액
    수수료라 6개월 창에 40건이 걸리는데, 그중 전표·당일완납까지 겹친 한 건만
    답이고 나머지 39건은 눈만 어지럽힌다 (2026-08-06 요청).

    실측(2개월 정답지 553건, 같은 표본 A/B): 후보 평균 4.8→1.3건(목록 1,930칸
    감소), 1순위 88.1%→87.9%(-1건), 후보 포함 89.2%→88.6%(-3건).
    금액 단독이라도 창 안에 그 금액이 하나뿐이면 실측 100% 라 남긴다."""
    keep = ds._keep_worth_showing
    two = {"doc_id": "01-0000-0-0001", "evidence": ["금액", "회계"]}
    num = {"doc_id": "01-0000-0-0002", "evidence": ["번호"]}
    amt_one = {"doc_id": "01-0000-0-0003", "evidence": ["금액"], "amount_unique": True}
    amt_many = {"doc_id": "01-0000-0-0004", "evidence": ["금액"], "amount_unique": False}
    name_only = {"doc_id": "01-0000-0-0005", "evidence": ["이름"]}
    got = [i["doc_id"] for i in keep([two, num, amt_one, amt_many, name_only])]
    assert got == ["01-0000-0-0001", "01-0000-0-0002", "01-0000-0-0003"]
    assert "01-0000-0-0004" not in got, "금액 단독·비유일은 44% — 뺀다"
    assert "01-0000-0-0005" not in got, "이름 단독은 0%(0/38) — 뺀다"


def test_의뢰문서번호_정확일치는_창을_안_본다():
    """②-c (2026-08-11). 1순위 실패의 가장 큰 갈래가 '창 밖'이다 — 실패 421건 중
    173건(41.1%)이고 접수→입금 지연 중앙값이 377일이라 6개월 창으로는 **원리적으로**
    못 닿는다('2022070162-실비//여신업무센터/대체입금' 이 2026-02-25 에 들어온다).

    안전한 이유는 **정확일치만 쓰기 때문**이다. 창 있는 _custdocid_sync 는
    `LIKE %run%` 도 같이 치는데, 창을 걷으면 그 접두·부분일치가 남의 번호를
    무더기로 물어 온다. 정확일치만 남기면 최근1년 정답지 3,429건 전수에서
    발화 1,009건(29.4%) · 후보 1건 997건 · **단독 정밀도 995/997 = 99.80%**,
    단독인데 틀린 2건은 현행도 똑같이 틀리던 건이라 **가로채는 정답이 0** 이다.
    파이프라인 A/B(발화 가능 1,009건에서 150건 표본): 93.3% → 99.3%, 얻음 9·잃음 0.

    이 테스트가 잠그는 것 — 되돌리면 위 성적이 무너진다:
      ① LIKE 를 도로 넣지 마라 (창 없는 부분일치 = 남의 번호 무더기)
      ② 날짜 조건을 넣어 창을 되살리지 마라 (그러면 ② 와 같아져 존재 이유가 없다)
      ③ 창 있는 축이 빈손일 때만 부른다 (창 안에서 걸린 답을 밀어낼 수 없게)
    """
    # 원문에서 함수 하나를 떼어 내고, 독스트링(왜 그렇게 했는지 적어 둔 곳)은
    # 걷는다 — 설명에 'LIKE' 라는 낱말이 나오므로 그대로 훑으면 안 된다.
    src = SOURCE.read_text(encoding="utf-8")
    fn = src[src.index("def _custdocid_exact_all_sync"):]
    fn = fn[: fn.index("\ndef ", 1)]
    body = fn[fn.index('"""'):]
    body = body[body.index('"""', 3) + 3:]

    assert "LTRIM(RTRIM(a.CustDocID)) = :r" in body, "정확일치"
    assert "LIKE" not in body, "부분일치를 넣으면 창 없이 남의 번호를 물어 온다"
    assert "ReceiptDate" not in body.replace("ORDER BY a.ReceiptDate DESC", ""), \
        "창(WHERE 날짜조건)을 되살리면 ② 와 같아진다"
    assert "_NO_OB" in body, "구번호(OB…)는 여기서도 뺀다"

    # 창 있는 축이 빈손일 때만 부른다 — 창 안에서 걸린 답을 밀어낼 수 없게.
    call = src[src.index("# ②-c"): src.index("# ②-b")]
    assert "if not items and runs:" in call
    assert "_custdocid_exact_all_sync(runs)" in call
    assert "weak_runs" not in call, "상호에 붙은 숫자는 이 축에 넣지 않는다"
    assert ds._STAGE_LABEL["custdocid_all"] == "의뢰문서번호(전기간)"


def test_세금계산서_청구처는_게이트_셋을_다_건다():
    """②-d (2026-08-11). 1순위 실패의 31.4%(132건)가 '입금자 이름이 원장 어디에도
    없음'이다 — 은행이 의뢰하고 돈은 채무자·시행사가 낸다. 그 이름이 있는 곳이
    세금계산서 청구처이고, 이 표는 감정서번호를 직접 들고 있다.

    **게이트 셋은 하나도 빼면 안 된다.** 최근1년 정답지 3,429건 전수 실측:
      셋 다 걸었을 때  발화 304 · 후보1건 290 · 단독 정밀도 289/290 = **99.66%**
      금액 게이트를 빼면                              123/146 = **84.25%**  ← 합격선 미달
    단독인데 틀린 1건은 현행이 후보를 하나도 못 내던 건이라 **가로채는 정답 0**.

    잠그는 것:
      ① 금액 일치(total_am = 입금액) — 빼면 84.25% 로 무너진다
      ② 후보가 정확히 1건일 때만 — 여럿이면 침묵한다
      ③ 이름 정확일치 — LIKE 로 풀면 가로채기가 생긴다
      ④ 계산서일자 ≤ 입금일 — 미래 계산서로 맞히면 실전 재현이 안 된다
      ⑤ 파이썬·SQL 정규화가 같은 것을 지운다(한쪽만 고치면 조용히 안 걸린다)
      ⑥ **자리** — 원장 이름 축 뒤(③-c)다. 앞(②-d)에 뒀다가 A/B 에서
         얻음 0·잃음 1 이 나와 되돌렸다. 이름 축이 이미 풀던 건을 가로챈다.
    """
    src = SOURCE.read_text(encoding="utf-8")
    fn = src[src.index("def _tax_bill_sync"):]
    fn = fn[: fn.index("\ndef ", 1)]
    body = fn[fn.index('"""'):]
    body = body[body.index('"""', 3) + 3:]

    assert "total_am = :amt" in body, "① 금액 게이트 — 빼면 84.25%"
    assert "if len(docs) != 1:" in body, "② 후보 1건일 때만"
    assert "LIKE" not in body.replace(
        "appraisal_no LIKE '[0-9][0-9]-[0-9][0-9][0-9][0-9]-%'", ""), \
        "③ 이름은 정확일치 — 부분일치 금지"
    assert "bal_date <= CONVERT(date, :d)" in body, "④ 미래 계산서 금지"

    # ⑤ 두 정규화가 같은 것을 지운다.
    for token in ds._TAX_STRIP:
        assert f"'{token}'" in ds._TAX_NORM_SQL, f"SQL 정규화에 {token} 없음"
    assert ds._tax_norm("（주）대방 건설㈜") == "대방건설"
    assert ds._tax_norm("주식회사 세진종합건설") == "세진종합건설"

    # 이름 축보다 먼저, 그러나 앞선 축이 답을 냈으면 부르지 않는다.
    call = src[src.index("# ③-c"): src.index("# ④ 금액")]
    assert "if not items and names:" in call
    assert "_tax_bill_sync(names, day, amount)" in call
    assert ds._STAGE_LABEL["tax_bill"] == "세금계산서 청구처"

    # 갈래와 점수도 계약이다 — 정하지 않으면 기본 20점·갈래 없음이 되어
    # tier 2 로 숨는다(처음에 그렇게 넣었다가 A/B 에서 얻음 2 에 그쳤다).
    assert "세금계산서 청구처" in ds._NUM_LABELS, "계산서는 감정서번호를 직접 들고 있다"
    assert ds._signals({"field_label": "세금계산서 청구처"}) == ["번호"]
    assert ds._AXIS_SCORE["세금계산서 청구처"] == 75
    # 번호 축들 아래, 그리고 **금액 창안유일(80) 아래**다 — 그쪽은 실측
    # 194건 100% 로 이 축(99.66%)보다 정확하다. 88 을 줬다가 A/B 에서
    # 잃음 1 이 났고 그 1건이 정확히 금액 창안유일을 밀어낸 것이었다.
    assert ds._AXIS_SCORE["세금계산서 청구처"] < ds._AXIS_SCORE["의뢰문서번호"]
    assert ds._AXIS_SCORE["세금계산서 청구처"] < ds._AMOUNT_SCORE[0], "100% 축이 이겨야"
    assert ds._AXIS_SCORE["세금계산서 청구처"] > ds._AXIS_SCORE["의뢰처"]


def test_금액만_맞은_지사_후보는_안_보여준다():
    """2026-08-13. 이 통장은 사실상 본사 것이라 정답의 99.8% 가 '01-' 이다.
    그런데 지사 건이 금액만 우연히 맞아 **혼자** 살아남으면 _OTHER_OFFICE_PENALTY
    35점이 아무 소용이 없다 — 경쟁자가 없으니 그대로 1순위가 된다.

    실측으로 잡은 계기: '주식회사 에이치앤제/전자금융/' 100만원(2026-08-13)에
    강원지사 11-2605-A-0016(함영미)이 금액만 맞아 유일 후보로 떴다. 정답은
    본사 01-2608-4-0278(에이치앤제이컨설팅, 전날 접수·청구 0원인 선수금)이었다.

    정답지 전수(최근1년 3,416건) A/B:
      1순위가 지사로 뜬 80건 중 맞은 것 **3건(3.8%)** — 그 셋은 번호·갈래 2개로
      걸린 것이라 이 규칙에 안 걸린다.
      걷어낸 후보 77개(74건) 중 **정답이었던 것 0개** · 1순위 +1 · 잃음 0.

    함께 잰 '이름 단독도 후보로 보여주기'는 **기각**했다 — 후보를 더한 1,595건 중
    정답을 더한 건 8건뿐이고 1,587건(99%)은 틀린 후보만 붙었다.
    """
    def item(doc_id, **over):
        base = {"doc_id": doc_id, "field_label": "매출총액 일치",
                "amount_unique": True, "evidence": ["금액"]}
        base.update(over)
        return base

    # 금액 단독 — 본사는 남고 지사는 사라진다.
    kept = ds._keep_worth_showing([item("11-2605-A-0016"), item("01-2608-4-0278")])
    assert [k["doc_id"] for k in kept] == ["01-2608-4-0278"]
    assert ds._keep_worth_showing([item("11-2605-A-0016")]) == [], "지사 단독이면 아무것도 안 남는다"

    # 근거가 둘이면 지사라도 남는다 — 실측에서 맞았던 3건이 이 부류다.
    two = item("11-2505-3-0429", evidence=["금액", "이름"])
    assert ds._keep_worth_showing([two]) == [two]
    # 번호로 걸린 지사 건도 남는다.
    num = {"doc_id": "17-2506-3-0436", "field_label": "적요에 번호", "evidence": ["번호"]}
    assert ds._keep_worth_showing([num]) == [num]

    # 규칙이 코드에 남아 있는지 — 본사 상수를 쓰고, 이름 단독은 여전히 숨긴다.
    import re

    src = SOURCE.read_text(encoding="utf-8")
    body = src[src.index("def _keep_worth_showing"):]
    nxt = re.search(r"\n(?:async )?def ", body[1:])   # 다음 함수는 async def 다
    body = body[: nxt.start() + 1] if nxt else body
    body = body[body.index('"""'):]
    body = body[body.index('"""', 3) + 3:]
    assert 'doc_id.startswith(f"{_HOME_OFFICE}-")' in body, "본사 판정은 상수로"
    assert "tier == 2" not in body, "이름 단독을 되살리려면 측정부터 (1,587건 잡음)"
