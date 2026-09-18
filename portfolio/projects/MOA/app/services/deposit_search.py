"""적요 토막으로 감정서 찾기 — 재무팀이 손으로 하던 순서를 그대로 옮긴다.

재무팀은 통장 적요에 적힌 글자들을 하나씩 감정서 원장에서 검색해 본다.
'상주시산림조합/타행환/(산림)/' 이면 상주시산림조합 · 타행환 · 산림 을 각각
넣어 보는 식이다. 그 글자가 채무자인지 의뢰처인지 조사자인지는 **모른 채**
찾는다 — 그래서 우리도 이름이 들어갈 만한 자리를 넓게 뒤진다.

찾는 순서 (2026-08-05 실측 331건으로 정했다. 숫자는 전부 잰 값이다):
  ⓪ 적요 숫자가 감정서번호 압축형인가 — DB 조회 0회. 입금의 35.0% 가 여기서
     끝나고 그중 95.7% 가 재무팀 Memo 와 같다. 이걸 앞에 두지 않으면 쉬운 건까지
     헛돈다.
  ① 사이버브랜치 매핑표(UNIQUE_FIELD → DocID) — 있으면 그게 정답이다.
  ② 의뢰문서번호(CustDocID) 에 적요의 숫자런 — 걸리면 늘 1~3건이라 변별력이 가장 높다
     (40건 중 11건 적중, 그중 7건은 이 축 단독).
  ③ 이름 — 의뢰처(CustName·Production) · 채무자(Debtor·Title). 거래일 기준
     1 → 2 → 3 → 6 → 12개월로 창을 넓힌다. 3개월에서 멈추면 15.2% 가 구조적으로
     창 밖이다(거래일−접수일 중앙값 24일, p90 118일).
  ④ 비고(Bigo) — 앞이 전부 0건일 때만. varchar(6000) LIKE 라 비싸다.
  ⑤ 원문(gamjundw jun.chunk) — 원장이 못 찾은 건의 1/6 을 건진다.
     CONTAINS 로만 친다(LIKE 는 19~55초, CONTAINS 는 0.02초).

**넣지 않은 컬럼과 그 이유**: 유치자(Manager)·조사자(Charge)·심사(JudgCharge)·
서명평가사(LSigner)·접수담당(LReceiptCharge)·소유자(OwnerName)·의뢰처담당(CustCharge)
는 40건 표본에서 정답을 **한 건도** 맞히지 못했다. 통장 적요에 우리 직원 이름이
찍히지 않기 때문이다. 넣으면 스캔 비용과 오탐만 는다.

**거래유형어를 불용어로 두는 이유**: 사용자 지시는 '타행환'·'대체' 같은 토막도
검색어로 쓰라는 것이었고 그대로 재 봤다. 결과는 40건 중 19건(47.5%)에서 1순위가
이름이 아닌 거래유형어로 뽑혔고 **19건 전부 오답**이었다. '대체'가 3개월 창에서
겨우 6건만 걸려 '가장 적게 걸린 토막' 규칙이 오히려 이걸 최우선으로 고른다.
그래서 검색은 하되 **1순위 근거로는 쓰지 않는다**(_STOP).

이 모듈은 **읽기 전용**이다. 통장 Memo 에는 쓰지 않는다
(app/services/deposit_match.py 상단 참고).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any

from sqlalchemy import text

from app.config import get_settings
from app.database import get_session_factory
from app.services import deposit_match

logger = logging.getLogger(__name__)

# ── 적요 토막내기 ──────────────────────────────────────────────────────────
# 적요는 '/' 로 칸을 나눈다. 빈 칸이 겹쳐 '//' 가 되는 자리가 많아 여러 개를 하나로 본다.
_SPLIT = re.compile(r"/+")
# 토막을 통째로 감싼 괄호만 벗긴다. 여는 괄호만 보고 자르면
# '(주)대화감정평가법인' 이 '주)대화감정평가법인' 이 되어 어디에도 안 걸린다.
_WRAPPED = re.compile(r"^\(([^()]*)\)$|^\[([^\[\]]*)\]$")
_TRIM = re.compile(r"^[\s]+|[\s.,]+$")
# 전각 문자(Ｆ／Ｂ·２６０)는 반각으로 눕혀 비교한다.
_FULLWIDTH = {c: chr(ord(c) - 0xFEE0) for c in map(chr, range(0xFF01, 0xFF5F))}
_FULLWIDTH[chr(0x3000)] = " "
_TRANS = str.maketrans(_FULLWIDTH)

# 괄호가 열리기만 하고 안 닫힌 토막 — 통장 적요는 20자에서 잘린다.
# '수수료입금(경조루미너스' 처럼 남는데, 정작 찾을 이름은 괄호 **뒤**에 있다.
_OPEN_PAREN = re.compile(r"[(\[]([^()\[\]]+)$")
_INNER_PAREN = re.compile(r"[(\[]([^()\[\]]+)[)\]]")
# 5자리 이상 숫자런 — 의뢰문서번호(CustDocID)로 가는 열쇠다.
_DIGIT_RUN = re.compile(r"\d{5,}")
# 토막 끝에 붙은 숫자 꼬리 ('서울지방국세청260' → '서울지방국세청')
_TAIL_DIGITS = re.compile(r"\d+$")
# 은행 접두 — '수협서초종합금융본부' 는 원장에 '서초종합금융본부' 로 있다.
_BANK_PREFIX = re.compile(
    r"^(신한|국민|우리|하나|기업|농협|수협|산업|외환|씨티|SC|부산|대구|경남|광주"
    r"|전북|제주|새마을|신협|산림|우체국|카카오|토스|케이)(은행|금고|조합)?")

# 검색은 하되 **1순위 근거로는 쓰지 않는** 말. 두 부류다.
#  ① 거래유형어 — 원장 이름 컬럼엔 아예 없고(최근 1년 0건) 원문에는 엉뚱하게 걸린다.
#  ② 은행·지사·업종 이름 — 수백 건씩 걸려 후보를 못 좁힌다(실측 '기업' 946건).
_STOP = {
    # 거래유형·전산어
    "대체", "대체입금", "타행환", "타행이체", "타행대량", "타행IB", "타행FB", "타행PC",
    "전자금융", "인터넷", "인터넷입금이체", "인터넷뱅킹", "현금", "창구", "입금", "출금",
    "여신연동", "여신실행센터", "실시간이체", "디금여", "FBS입금", "보관금", "수수료",
    "수수료입금", "감정평가비", "감정료", "펌뱅킹", "지로", "자동이체", "급여", "이체",
    # 은행·금융기관 이름 단독
    "은행", "신한", "국민", "우리", "하나", "기업", "농협", "수협", "산업", "씨티",
    "부산", "대구", "경남", "광주", "전북", "제주", "새마을", "신협", "산림", "우체국",
    "신한은행", "국민은행", "우리은행", "하나은행", "기업은행", "농협은행", "수협은행",
    "산업은행", "새마을금고", "신용협동조합", "산림조합", "저축은행", "금고", "조합",
    # 우리 회사·지사
    "대화감정평가법인", "대화감정", "본사", "지사",
    "경기지사", "부산지사", "동부지사", "북부지사", "강원지사", "충청지사", "호남지사",
    "여신업무센터", "여의도대", "WON뱅킹사업부",
}
# 지사 이름은 접미만 봐도 걸러진다 ('OO지사'·'OO지점' 단독은 이름이 아니다).
_STOP_SUFFIX = ("지사", "지점장", "본부장")
# 법인표기 단독 토막 — 검색어로 넣으면 창 하나에 수십 건이 걸려 사다리를 세운다
# (실측: '주식회사' 1개월 창 59건 폭탄 히트가 비고 축 문을 영영 막았다).
# 성공 686건 중 이 토막이 정답의 근거였던 건은 0건이다.
_CORP_TOKENS = {"주식회사", "유한회사", "유한책임회사", "주식", "회사", "(주)", "(유)"}
# 괄호 없이 붙여 쓴 법인 표기 — '주식회사세민개발' 을 통째로 검색하면 어디에도 없다.
_CORP_PREFIX = re.compile(
    r"^(주식회사|유한책임회사|유한회사|합자회사|재단법인|사단법인|의료법인|사회복지법인)")
# 합성 토막 속 지점명 ('경남중앙강남지점약식' → '강남지점')
_BRANCH_RE = re.compile(r"([가-힣]{2,8})지점")
_HANGUL3 = re.compile(r"^[가-힣]{3}$")
_LETTER0 = re.compile(r"^[가-힣A-Za-z]")
# 그룹사는 적요에 한글로, 원장엔 영문 약칭으로 실린다 — 정답지 전수(Memo 채워진
# 3,531건, 상한 없이 재조회) 실측으로 잡은 표 (2026-08-13). '엘지' 적요 3건·
# 'LG' 원장 31건, '지에스' 적요 2건('지에스건설(주)/FB자금/GS대기/…' →
# 원장 '(주)GS건설') 확인. SK·KT·DB·NH·IBK·LS·HD·LIG 는 원장에 영문 표기가
# 수십~수백 건 있어도 정답지에서 실제로 놓친 적요가 0건이라 뺐다 — 원장에
# 있다고 넣는 게 아니라, **놓친 실물 건이 있어야** 넣는다.
_GROUP_ALIAS = {"엘지": "LG", "지에스": "GS"}

# 입금자명 뒤에 송금 용도를 붙여 보내는 적요가 있다. 원장에는 상호만 있으므로
# '(주)헤라몬드감정여비' 를 그대로 LIKE 하면 Debtor '주식회사헤라몬드' 를 놓친다.
# 실제 입금에서 확인된 회계 용도어만 **끝에서** 떼며, 상호 중간의 같은 글자는
# 건드리지 않는다.
_PURPOSE_SUFFIX = re.compile(
    r"(?:감정평가수수료|감정평가비|평가수수료|감정여비|감정실비|감정료|수수료입금|수수료)$")


def _normalize(value: str) -> str:
    return (value or "").translate(_TRANS).strip()


def tokens(jeokyo: str) -> list[str]:
    """적요를 '/' 로 쪼갠 토막 목록. 재무팀이 눈으로 하던 그 쪼개기다.

    >>> tokens("상주시산림조합/타행환/(산림)/")
    ['상주시산림조합', '타행환', '산림']
    """
    out: list[str] = []
    for raw in _SPLIT.split(_normalize(jeokyo)):
        word = _TRIM.sub("", _normalize(raw))
        wrapped = _WRAPPED.match(word)
        if wrapped:
            word = next(g for g in wrapped.groups() if g is not None).strip()
        # 한 글자는 어디에나 걸려 후보를 못 좁힌다.
        if len(word) < 2:
            continue
        if word not in out:
            out.append(word)
    return out


def expand(jeokyo: str) -> list[str]:
    """검색에 실제로 넣을 말들. 토막을 그대로 넣으면 놓치는 게 많아 손질한다.

    실측(40건): 손질 없이 토막만 쓰면 3개월 창 재현율 40.0%, 손질하면 55.0% 다.
    통장 적요가 20자에서 잘리는 탓에 괄호가 안 닫히고('수수료입금(경조루미너스'),
    은행 접두가 붙고('수협서초종합금융본부'), 숫자 꼬리가 남는다('서울지방국세청260').
    """
    out: list[str] = []

    def add(word: str) -> None:
        word = _TRIM.sub("", _normalize(word))
        if len(word) >= 2 and word not in out:
            out.append(word)

    for token in tokens(jeokyo):
        add(token)
        # 괄호 안쪽 — 닫힌 것도, 잘려서 안 닫힌 것도.
        for inner in _INNER_PAREN.findall(token):
            add(inner)
        open_tail = _OPEN_PAREN.search(token)
        if open_tail:
            add(open_tail.group(1))
        # 괄호를 떼어 낸 나머지 ('광성텍 (주)' → '광성텍')
        stripped = _INNER_PAREN.sub(" ", token)
        stripped = _OPEN_PAREN.sub(" ", stripped)
        for piece in re.split(r"[\s_,]+", stripped):
            add(piece)
        # 숫자런은 의뢰문서번호로 간다.
        for run in _DIGIT_RUN.findall(token):
            add(run)
        # 숫자 꼬리를 뗀 형태 / 은행 접두를 뗀 형태
        add(_TAIL_DIGITS.sub("", token))
        without_bank = _BANK_PREFIX.sub("", token)
        if without_bank != token:
            add(without_bank)
        # 법인 표기를 붙여 쓴 형태 ('주식회사컨트롤케이앤' → '컨트롤케이앤').
        # '(주)XXX' 는 위의 괄호 처리에서 이미 벗겨지지만, 괄호 없이 붙여 쓰면
        # 통째로 한 단어라 원장에도 원문에도 없는 말이 된다. 2026년 입금 중
        # 21건이 이 모양이었다 — 세민개발·골드플레이트·CMG제약·두란노서원 …
        without_corp = _CORP_PREFIX.sub("", token)
        if without_corp != token:
            add(without_corp)
    # '&' 를 적요와 원장이 다르게 옮긴다 — '에이치엔제이컨설팅'(적요) ↔
    # '주식회사 에이치앤제이파트너스'(원장 CustName) 처럼 '엔'/'앤' 한 글자
    # 차이로 갈려 LIKE 가 서로를 못 찾는다 (2026-08-13 실측·요청). 양쪽 다 넣는다.
    for word in list(out):
        if "엔" in word:
            add(word.replace("엔", "앤"))
        if "앤" in word:
            add(word.replace("앤", "엔"))
    # 그룹사는 적요에 한글로, 원장엔 영문 약칭으로 실린다.
    for word in list(out):
        for kor, eng in _GROUP_ALIAS.items():
            if word.startswith(kor):
                add(eng + word[len(kor):])
    # 송금 용도 꼬리를 뗀 상호도 함께 찾는다. 첫 확장 과정에서 '(주)'를 뗀 형태가
    # 이미 out 에 들어오므로 '(주)헤라몬드감정여비' → '헤라몬드'까지 만들어진다.
    for word in list(out):
        without_purpose = _PURPOSE_SUFFIX.sub("", word)
        if without_purpose != word:
            add(without_purpose)
    return out


def is_stop(word: str) -> bool:
    """1순위 근거로 쓰면 안 되는 말인가 (검색은 하되 순위에서 내린다)."""
    if word in _STOP:
        return True
    return any(word.endswith(s) and len(word) <= len(s) + 4 for s in _STOP_SUFFIX)


# ── 원장 조회 ─────────────────────────────────────────────────────────────
# 실측으로 남긴 축만 둔다. 어느 컬럼이 걸렸는지 화면에 보여줘야 해서 라벨을 붙인다.
# 고객측 이름이 들어갈 수 있는 컬럼 전부를 뒤진다 (2026-08-05 사용자 지시:
# "우리가 못 찾으면 사람도 못 찾아" — 후보는 넓게, 순위는 실측 점수로).
# Title 은 1년치에서 1순위 0/55, OwnerName·CustCharge 도 40건 표본에서 0건이었지만
# **후보 발굴**로는 값이 있다 — 점수를 의뢰처·채무자보다 한참 아래에 두어
# 1순위를 오염시키지 않게 한다. 직원 이름 컬럼(Manager·Charge·JudgCharge·
# LSigner·LReceiptCharge)만은 여전히 뺀다: 통장 적요에 우리 직원 이름이 찍히지
# 않아 오답과 스캔 비용(varchar 300 × 3)만 남긴다.
# 기본 축 — 1년치 실측에서 실제로 정답을 맞힌 컬럼. 모든 조회가 이걸 먼저 탄다.
_NAME_COLS: list[tuple[str, str]] = [
    ("CustName", "의뢰처"),
    ("Production", "의뢰처"),
    ("Debtor", "채무자"),
]
# 확장 축 — 기본 축이 **0건일 때만** 12개월 창 한 번으로 돈다. 모든 조회에
# 끼워 넣어 봤더니 LIKE 항이 단어당 10개로 불어 최악 186초까지 밀렸다(실측).
# 어려운 건에만 한 번 더 도는 구조면 흔한 조회는 그대로 빠르다.
_NAME_COLS_WIDE: list[tuple[str, str]] = [
    ("Title", "제목"),
    ("OwnerName", "소유자"),
    ("CustCharge", "의뢰처 담당"),
    ("CustPart", "의뢰처 부서"),
]
# 개월. 상한은 6개월 — 사용자 결정(2026-08-06, 속도 우선).
# 거래일−접수일 실측: 31일 62.0% / 92일 84.8% / 183일 93.6% / 366일 96.7%.
# 즉 6개월 상한은 12개월 대비 약 3%p(93.6→96.7)를 속도와 맞바꾼다.
# apw_masterex 는 인덱스 없는 뷰라 창이 넓을수록 스캔 뒤 걸러낼 행이 는다.
_WINDOWS = (1, 3, 6)
_FORWARD_DAYS = 8             # 접수·발송이 입금보다 늦는 건이 있다(최대 -10일)

# a.Address 를 뺐다 (2026-08-11). **죽은 값이라서 뺀 것이지 빨라져서가 아니다** —
# WHERE 절에 한 번도 안 들어갔고, deposit_list.match_one 이 화면으로 옮기는 키
# 목록에도 없었다. 뷰의 계산 컬럼이라 스칼라 UDF(dbo.fnBun)를 행마다 부른다.
#
# 조회 하나만 떼어 재면 넓은 스캔에서는 확실히 싸다(현행 · a.ADDR · 제거):
#   이름축 6개월창   3,215행 → 0.657s · 0.401s · 0.439s
#   금액축 6개월창      23행 → 0.178s · 0.180s · 0.182s   (작으면 차이 없다)
#   무제한창 이름축 54,996행 → 11.851s · 6.610s · 5.909s
# **그러나 실제 화면 경로에서는 잡음 수준이다.** 무제한창 축은 후보가 없을 때만
# 발화해서 평균에 거의 안 실린다. 2026년 정답지 30건을 건마다 A·B·B·A 로 교대해
# 재니 짝지은 차이 중앙값 -0.002s, 제거가 빠른 건 14/30(동전던지기), 총합
# 51.73s(옛것) vs 52.03s(제거). 순차로 블록을 나눠 재면 캐시 예열이 섞여 4% 쯤
# 빨라진 것처럼 보이는데 그건 측정 오류다 — **속도를 근거로 이 줄을 되돌리거나
# 비슷한 정리를 정당화하지 말 것.**
# 후보 상위 5개는 40/40 그대로였다(결과 불변 확인).
#
# 주소가 다시 필요해지면 원자료는 APW_Inventory.ADDR 이고, 뷰의 Address 는 거기에
# fnBun 과 건물명·동·층·호를 붙인 것이다 — Address 를 되살리지 말고 ADDR 을 쓸 것.
_COLS = (
    "a.DocID, CONVERT(varchar(10), a.ReceiptDate, 120) AS recv_date, "
    "a.CustName, a.Production, a.Debtor, a.CustCharge, a.LStatus, "
    "a.[수수료합계] AS fee_total, a.[부가가치세] AS vat, a.[청구금액] AS billed"
)

# 감정서번호 앞 두 자리 → 지사 이름. 2024년 이후 원장 실측으로 확정한 1:1 매핑이다
# (LEFT(DocID,2) 별 최빈 LOffice, 예외 0건). 본사(01)가 아닌 후보는 화면이
# 지사 칸에 이 이름을 보여준다 (2026-08-05 요청).
_OFFICE_NAMES = {
    "01": "본사", "02": "부산경남지사", "03": "대구경북지사", "04": "충청지사",
    "05": "경기지사", "06": "경인지사", "07": "충남지사", "08": "호남지사",
    "09": "제주지사", "10": "북부지사", "11": "강원지사", "12": "경남중앙지사",
    "13": "동부지사", "14": "전북지사", "15": "대전세종지사", "16": "울산지사",
    "17": "경북지사", "18": "경기서부지사",
}


def office_name(doc_id: str) -> str:
    return _OFFICE_NAMES.get((doc_id or "")[:2], "")


# 구번호(OB…) 제외 — 2007~2018 아카이브 18,807건인데 접수일이 통째로 비어 있어
# 기간 창을 그냥 통과한다. 최근 2년 안에는 한 건도 없어 대사 대상이 아니다.
# 조회 SQL 마다 붙인다 (2026-08-06 요청: "조회 자체에서 제외").
_NO_OB = "AND a.DocID NOT LIKE 'OB%' "


def _view() -> str:
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return f"[{database}].dbo.apw_masterex"


def _row_to_item(row: Any, word: str, field: str, label: str,
                 months: int, source: str) -> dict[str, Any]:
    billed = int(row["billed"] or 0)
    return {
        "doc_id": str(row["DocID"]).strip(),
        "office": office_name(str(row["DocID"]).strip()),
        # 회계팀이 보는 네 이름 칸 (2026-08-06): 의뢰인=CustName(직위 포함),
        # 제출처=Production(기관형 — 법원 건은 '민사22단독' 같은 담당 계),
        # 채무자=Debtor, 담당자(의뢰처)=CustCharge. 원장에 '제출처' 전용 컬럼은
        # 없어서 Production 이 그 자리다(CustName 의 직위 제거·기관형).
        "cust_name": (str(row["CustName"] or "").strip()
                      or str(row["Production"] or "").strip()),
        "submit_to": str(row["Production"] or "").strip(),
        "debtor": str(row["Debtor"] or "").strip(),
        "cust_charge": str(row["CustCharge"] or "").strip(),
        "recv_date": str(row["recv_date"] or ""),
        "billed": billed,
        "outstanding": None,     # 회계는 뒤에서 한 번에 채운다
        "received": None,
        "status": str(row["LStatus"] or "").strip(),
        "word": word,
        "field": field,
        "field_label": label,
        "months": months,
        "source": source,
        "weak": is_stop(word),
    }


def _ledger_sync(words: list[str], day: str, months: int,
                 cols: "list[tuple[str, str]] | None" = None) -> list[dict]:
    """이름 축 한 번의 조회 — 토막들을 한 스캔에 OR 로 묶는다.

    토막마다 따로 치면 (토막 10개 × 창 5단계) 스캔이 반복돼 수 초가 든다.
    한 번에 묶고, 어느 토막·어느 컬럼이 걸렸는지는 CASE 로 되짚는다.
    """
    if not words or not day:
        return []
    view = _view()
    where: list[str] = []
    params: dict[str, Any] = {"d": day, "m": months, "fwd": _FORWARD_DAYS}
    hits: list[str] = []
    name_cols = cols or _NAME_COLS
    wide = cols is not None
    for i, word in enumerate(words):
        params[f"w{i}"] = f"%{word}%"
        params[f"n{i}"] = "%" + word.replace(" ", "") + "%"
        for col, label in name_cols:
            where.append(f"a.{col} LIKE :w{i}")
            hits.append(
                f"CASE WHEN a.{col} LIKE :w{i} THEN '{i}|{col}|{label};' ELSE '' END")
        if wide:
            # 소유자는 '김   종   열' 처럼 글자 사이 패딩이 4.3% 있다(실측).
            where.append(f"REPLACE(a.OwnerName,' ','') LIKE :n{i}")
            hits.append(f"CASE WHEN REPLACE(a.OwnerName,' ','') LIKE :n{i} "
                        f"THEN '{i}|OwnerName|소유자;' ELSE '' END")
        else:
            # 무공백 비교 — '주식회사 스타위드프' ↔ '주식회사스타위드프라임'
            where.append(f"REPLACE(a.CustName,' ','') LIKE :n{i}")
            where.append(f"REPLACE(a.Production,' ','') LIKE :n{i}")
            hits.append(f"CASE WHEN REPLACE(a.CustName,' ','') LIKE :n{i} "
                        f"THEN '{i}|CustName|의뢰처;' ELSE '' END")

    sql = (
        f"SELECT TOP 60 {_COLS}, CONCAT({', '.join(hits)}) AS hit "
        f"FROM {view} a "
        f"WHERE ({' OR '.join(where)}) " + _NO_OB +
        f"AND a.ReceiptDate >= DATEADD(month, -:m, CONVERT(date, :d)) "
        f"AND a.ReceiptDate < DATEADD(day, :fwd, CONVERT(date, :d)) "
        f"ORDER BY a.ReceiptDate DESC"
    )
    db = get_session_factory()()
    try:
        rows = db.execute(text(sql), params).mappings().all()
    finally:
        db.close()

    out: list[dict] = []
    for row in rows:
        seen: set[str] = set()
        for mark in str(row["hit"] or "").split(";"):
            if not mark:
                continue
            index, col, label = mark.split("|")
            if col in seen:
                continue
            seen.add(col)
            out.append(_row_to_item(row, words[int(index)], col, label,
                                    months, "원장"))
            break   # 한 감정서는 한 번만 — 가장 먼저 걸린 축을 근거로 쓴다
    return out


_GLUED_DIGITS = re.compile(r"[가-힣A-Za-z](\d{5,})|(\d{5,})[가-힣A-Za-z]")


def _glued_digits(jeokyo: str) -> "set[str]":
    """글자에 딱 붙은 숫자런 — 상호에 섞인 코드지 문서번호가 아니다."""
    out: set[str] = set()
    for m in _GLUED_DIGITS.finditer(jeokyo or ""):
        out.add(m.group(1) or m.group(2))
    return out


def _custdocid_sync(runs: list[str], day: str, months: int) -> list[dict]:
    """의뢰문서번호 축 — 적요의 숫자런이 CustDocID 와 같거나 그 접두인가.

    걸리면 늘 1~3건이라 변별력이 가장 높다. 은행이 자기 의뢰번호를 적요에
    그대로 적어 보내는 경우다.
    """
    if not runs or not day:
        return []
    view = _view()
    where: list[str] = []
    params: dict[str, Any] = {"d": day, "m": months, "fwd": _FORWARD_DAYS}
    for i, run in enumerate(runs):
        params[f"r{i}"] = run
        params[f"p{i}"] = f"%{run}%"
        where.append(f"LTRIM(RTRIM(a.CustDocID)) = :r{i}")
        where.append(f"a.CustDocID LIKE :p{i}")
    sql = (
        f"SELECT TOP 20 {_COLS}, a.CustDocID "
        f"FROM {view} a WHERE ({' OR '.join(where)}) " + _NO_OB +
        f"AND a.ReceiptDate >= DATEADD(month, -:m, CONVERT(date, :d)) "
        f"AND a.ReceiptDate < DATEADD(day, :fwd, CONVERT(date, :d)) "
        f"ORDER BY a.ReceiptDate DESC"
    )
    db = get_session_factory()()
    try:
        rows = db.execute(text(sql), params).mappings().all()
    finally:
        db.close()
    out = []
    for row in rows:
        ref = str(row["CustDocID"] or "")
        word = next((r for r in runs if r in ref), runs[0])
        out.append(_row_to_item(row, word, "CustDocID", "의뢰문서번호",
                                months, "원장"))
    return out


def _custdocid_exact_all_sync(runs: list[str]) -> list[dict]:
    """의뢰문서번호 **정확일치**를 창 없이 한 번 더 — 오래 묵은 건을 위해서다.

    왜 창을 없애나: 1순위 실패의 가장 큰 갈래가 '창(6개월) 밖'이다(실패 421건 중
    173건 = 41.1%). 은행 수수료는 접수하고 한참 뒤에 들어온다 — 접수→입금 지연
    중앙값 377일, 최소 184일이라 6개월 창으로는 **원리적으로** 닿지 않는다.

    왜 안전한가: 위 _custdocid_sync 와 달리 `LIKE %run%` 을 **쓰지 않는다.**
    접두·부분일치는 창이 없으면 남의 번호를 무더기로 물어 온다. 정확일치만 남기면
    최근1년 정답지 3,429건 전수에서
        발화 1,009건(29.4%) · 후보 1건 997건 · **단독 정밀도 995/997 = 99.80%**
        후보수 분포 {1: 997, 2: 11, 3: 1}
    이고, 단독인데 틀린 2건은 **현행도 똑같이 틀리던 건**이라 가로채는 정답이 0이다
    ('2025375359/수수료/양재동/' · '2026170297/수수료/디금여/' — 둘 다 적요의 번호가
    실제로 그 다른 감정서의 CustDocID 라 재무팀 Memo 쪽 오기로 보인다).

    창 있는 축이 빈손일 때만 부른다 — 창 안에서 걸린 답을 밀어낼 수 없다.
    """
    if not runs:
        return []
    view = _view()
    where = " OR ".join(f"LTRIM(RTRIM(a.CustDocID)) = :r{i}" for i in range(len(runs)))
    params: dict[str, Any] = {f"r{i}": run for i, run in enumerate(runs)}
    sql = (f"SELECT TOP 20 {_COLS}, a.CustDocID FROM {view} a "
           f"WHERE ({where}) " + _NO_OB + "ORDER BY a.ReceiptDate DESC")
    db = get_session_factory()()
    try:
        rows = db.execute(text(sql), params).mappings().all()
    finally:
        db.close()
    out = []
    for row in rows:
        ref = str(row["CustDocID"] or "").strip()
        word = next((r for r in runs if r == ref), runs[0])
        out.append(_row_to_item(row, word, "CustDocID", "의뢰문서번호",
                                0, "원장"))
    return out


# 세금계산서 청구처 이름을 맞춰 볼 때 지우는 것들. 양쪽(적요 토막·청구처)에
# 똑같이 적용해야 해서 SQL 쪽 _TAX_NORM_SQL 과 짝을 이룬다 — 한쪽만 고치지 말 것.
_TAX_STRIP = ("（주）", "(주)", "㈜", "주식회사", " ")


def _tax_norm(value: str) -> str:
    out = str(value or "")
    for token in _TAX_STRIP:
        out = out.replace(token, "")
    return out.strip()


_TAX_NORM_SQL = "receiver_name"   # 발급 원장의 공급받는자 (2026-09-09, TAMS 캐시 → 원장)
for _t in _TAX_STRIP:
    _TAX_NORM_SQL = f"REPLACE({_TAX_NORM_SQL}, '{_t}', '')"


def _tax_bill_sync(names: list[str], day: str, amount: int) -> list[dict]:
    """세금계산서 청구처 축 — 돈 낸 사람 이름이 원장에 없을 때의 마지막 열쇠.

    왜 필요한가: 1순위 실패의 31.4%(132건)가 '입금자 이름이 원장 어디에도 없음'이다.
    은행이 감정을 의뢰하고 돈은 채무자·시행사가 내는 식이라 원장 이름 칸으로는
    영영 못 찾는다. 그런데 **세금계산서 청구처(company_nm)에는 그 이름이 있다** —
    청구는 돈 내는 쪽에 하기 때문이다. 그리고 이 표는 감정서번호를 직접 들고 있어
    주소 같은 것을 거칠 필요가 없다.

    **게이트 셋을 다 걸어야 한다. 하나라도 빼면 합격선 아래로 떨어진다.**
      ① 계산서 합계금액 = 입금액. 뺐을 때 단독 정밀도 99.66% → **84.25%**.
      ② 후보가 **정확히 1건**일 때만 말한다. 여럿이면 침묵한다.
      ③ 이름 **정확일치**(정규화 후). 부분일치로 풀면 가로채기가 생긴다.
      + 계산서일자 ≤ 입금일. 미래 계산서로 맞히면 실전에서 재현이 안 된다.

    실측(최근1년 정답지 3,429건 전수, 게이트 셋 다 건 상태):
      발화 304건 · 후보 1건 290건 · **단독 정밀도 289/290 = 99.66%**
      후보에 정답 302/304 · 후보수 분포 {1: 290, 2: 2, 3: 1, 4: 3}
    단독인데 틀린 1건('고양동부새마을금고/현금/4030-001/' 853,400원)은 **현행이
    후보를 하나도 못 내던 건**이라 가로채는 정답이 0이다. 그 건은 계산서가
    01-2607-2-0081 에 발행돼 있고 Memo 만 …0080 이라 Memo 쪽이 의심스럽다.

    한계: 발화율이 8.9%뿐이다. 천장은 이 표(정답 감정서의 90.8%가 실려 있다)가
    아니라 **적요**에 있다 — 회사명이 적요에 아예 없는 건(가상계좌 숫자·은행
    지점명만 찍힌 적요)에서 끊긴다.
    """
    keys = [k for k in {_tax_norm(n) for n in names} if len(k) >= 2]
    if not keys or not day or not amount:
        return []
    where = " OR ".join(f"{_TAX_NORM_SQL} = :k{i}" for i in range(len(keys)))
    params: dict[str, Any] = {f"k{i}": k for i, k in enumerate(keys)}
    params["amt"] = amount
    params["d"] = day
    sql = (f"SELECT DISTINCT LTRIM(RTRIM(doc_id)) AS no "
           f"FROM dbo.a10_issued_taxinvoice "
           f"WHERE ({where}) AND total = :amt AND is_test = 0 AND doc_type = N'세금계산서' "
           f"AND write_date <= CONVERT(date, :d) "
           f"AND doc_id LIKE '[0-9][0-9]-[0-9][0-9][0-9][0-9]-%'")
    db = get_session_factory()()
    try:
        rows = db.execute(text(sql), params).all()
    finally:
        db.close()
    docs = sorted({str(r[0]).strip() for r in rows if r[0]})
    if len(docs) != 1:          # ② 하나로 좁혀지지 않으면 말하지 않는다
        return []
    return _by_doc_ids_sync(docs, keys[0], "세금계산서 청구처", "세금계산서")


def _by_doc_ids_sync(doc_ids: list[str], word: str, label: str,
                     source: str) -> list[dict]:
    """감정서번호를 이미 아는 경우 — 원장에서 표시할 값만 채운다."""
    if not doc_ids:
        return []
    view = _view()
    params = {f"d{i}": d for i, d in enumerate(doc_ids)}
    holes = ", ".join(f":d{i}" for i in range(len(doc_ids)))
    db = get_session_factory()()
    try:
        rows = db.execute(text(
            f"SELECT TOP 40 {_COLS} FROM {view} a WHERE a.DocID IN ({holes}) "
            + _NO_OB),
            params).mappings().all()
    finally:
        db.close()
    return [_row_to_item(r, word, "DocID", label, 0, source) for r in rows]


# ── 원문(gamjundw jun) 조회 ────────────────────────────────────────────────
# 원장이 못 찾은 건의 1/6 을 건진다. 실측 상한이 20.8% 인데 실측치가 16.7% 라
# 알고리즘을 더 짜내도 남는 게 별로 없다 — 그래도 마지막 그물로 둔다.
#
# 지켜야 할 것 (전부 실측으로 정했다):
#  · CONTAINS 로만 친다. LIKE '%단어%' 는 19~55초고 기간을 좁혀도 안 줄어든다.
#  · 접두어 별표를 붙이지 않는다. '"상주시산림조합*"' 33.1초 vs '"상주시산림조합"' 0.02초.
#  · 괄호·따옴표·별표·&|~, 가 든 말은 예외 없이 0건이라 미리 걷어낸다.
#  · 한글 워드브레이커가 긴 합성어를 못 끊는다 — 앞에서부터 7→6→5 글자로 줄여 본다.
#    4글자 이하로는 내려가지 않는다('우리0'·'농협00' 같은 쓰레기가 오답을 만든다).
#  · 전역 히트 60건을 넘는 말은 변별력이 없어 버린다.
#  · ch.is_active = 1 — 구버전 파싱본 68,838행이 유령으로 뜬다.
#  · 조인은 chunk.master_id → case_master → apw_case. 벤더가 쓰는
#    document_version.appraisal_number 는 3.7% 가 NULL 이라 그만큼 샌다.
# 원문 안에서 '이 감정서의 것'이라고 말해 주는 자리들. 나머지(특히 etc)에는
# 등기사항증명서·토지이용계획확인서·건축물대장 같은 공부(公簿)가 통째로 실려 있어,
# 적요의 기관명이 남의 감정서 본문에 얼마든지 등장한다.
# 실측(150건): 후보 한 건이 정답일 확률이 request 50.7% · 강섹션 25.2% ·
# etc 뿐 11.7% · 약섹션만 3.4% 로 4배 이상 갈린다.
#
# 다만 **걸러내면 안 된다**. 강섹션만 남기면 후보가 593→202 로 줄지만 정답 포함이
# 111→70 으로 무너지고 1순위가 66.0%→41.3% 로 떨어진다. 정답이 etc 에서만 걸리는
# 건은 거의 전부 감정서번호·의뢰문서번호 숫자 토막이고(접수번호 스탬프가 etc 로
# 태깅된다), 그게 가장 정확한 근거이기 때문이다.
# 그래서 '같은 단어 안에서 상대비교'만 한다 — 오탐 -43.6%, 재현 손실 0.
_STRONG_SECTIONS = ("request", "cover", "summary", "appraisal_table", "detail", "photo")
_STRONG_SQL = ", ".join(f"'{s}'" for s in _STRONG_SECTIONS)
# 화면 '걸린 곳' 칸용 — 원문 히트는 어느 절에서 걸렸는지까지만 보여준다 (2026-08-06).
_SECTION_KO = {
    "request": "의뢰서", "cover": "표지", "summary": "요약",
    "appraisal_table": "감정평가표", "detail": "내역", "photo": "사진",
    "registry": "등기부", "calculation_basis": "산출근거", "location_map": "위치도",
    "statement": "명세표", "attachment": "첨부", "etc": "본문",
}

_FTS_BAD = re.compile(r"[\"'*&|~,()\[\]{}<>?:!]")
# 사다리 하한 2 — 원래 5였는데, 제3자 입금 실패 84건 중 45건은 입금자명이
# 감정서 원문에 실존하고 그중 32건이 2~4자 인명·상호라 하한 5에서 전멸했다.
# 낮춰도 안전한 이유: 전역 히트 60 상한이 '월드'(2,374건)·흔한 인명(1,071건)
# 같은 일반어를 그대로 거르고, 근거 2개 tier 가 원문 단독을 확신에서 뺀다.
# A/B 실측: 실패 136건 +31 회수, 1개월 회귀 +2%p, 잃음 1.
_FTS_MIN = 2
_FTS_MAX_HITS = 60    # 전역 히트가 이보다 많으면 변별력이 없다.
                      # 1200 까지 올려 봤지만 후보만 늘고 1순위는 그대로였다
                      # (히트가 큰 말은 '토지정보과'·'도시개발과' 같은 부서명이다).
_ADAPT_MIN = 3        # 섹션 상대비교는 후보가 이보다 많을 때만 자른다


def _fts_words(words: list[str]) -> list[str]:
    """CONTAINS 에 넣을 수 있게 손질한 말들. 못 넣을 말은 버린다."""
    out: list[str] = []
    for word in words:
        if is_stop(word):
            continue          # 거래유형어는 원문에서 엉뚱한 감정서를 물어 온다
        clean = _FTS_BAD.sub(" ", word).split()
        if not clean:
            continue
        first = clean[0]
        if len(first) < _FTS_MIN or first.isdigit():
            continue
        if first not in out:
            out.append(first)
    return out


def _norm_doc_id(value: Any) -> str:
    """원문 DB 의 감정서번호를 원장 표기로 맞춘다.

    원장(apw_masterex)은 종별 문자를 **항상 대문자**로 쓴다 — 정상 번호 668,460건
    중 소문자는 0건이다. 반면 원문(jun.case_master)에는 소문자가 343건 있다
    ('01-2602-a-0017'). 그대로 두면 원장 조회는 대소문자 무시라 행은 찾아지지만,
    돌아온 대문자 번호로 by_word 를 되짚을 때 키가 안 맞아 **근거 단어와 섹션이
    통째로 사라진다.** 정답지의 9.2%(70/758)가 A·B 종별이라 무시할 수 없다.
    """
    return str(value or "").strip().upper()


def _fts_sync(words: list[str], day: str,
              months: int) -> "tuple[list[dict], list[tuple[str, str, int]]]":
    """원문 검색. (후보, 사다리) 를 돌려준다 — 사다리는 창 무제한 재시도가 쓴다.

    창은 jun.case_master.yymm(감정서번호의 접수년월)으로 건다 — jun.apw_case
    미러가 2026-07-15 에 멈춰 있어 그걸 조인하면 최근 접수분이 통째로 사각이다.
    yymm 은 접수일의 달과 99.90% 일치한다(실측 12,657/12,670).
    """
    from app.services import gamjun_chat  # noqa: PLC0415 (벤더 준비를 재사용한다)

    vendor = gamjun_chat._vendor()  # noqa: SLF001
    try:
        base = dt.date.fromisoformat(day)
    except ValueError:
        return [], []
    lo_d = base - dt.timedelta(days=months * 31)
    hi_d = base + dt.timedelta(days=_FORWARD_DAYS)
    lo, hi = (f"{lo_d.year % 100:02d}{lo_d.month:02d}",
              f"{hi_d.year % 100:02d}{hi_d.month:02d}")

    found: list[dict] = []
    ladder: list[tuple[str, str, int]] = []
    for word in words:
        term, hits = word, 0
        # 사다리 — 긴 합성어는 워드브레이커가 못 끊어 0건이 된다.
        while len(term) >= _FTS_MIN:
            rows = vendor._run_query(  # noqa: SLF001
                "SELECT COUNT(DISTINCT ch.master_id) AS n FROM jun.chunk ch "
                "WHERE ch.is_active = 1 AND CONTAINS(ch.content, %s)",
                (f'"{term}"',))
            hits = int((rows or [{}])[0].get("n") or 0)
            if hits:
                break
            term = term[:-1]
        ladder.append((word, term, hits))
        if not hits or hits > _FTS_MAX_HITS:
            continue
        rows = vendor._run_query(  # noqa: SLF001
            "SELECT TOP 20 cm.doc_id AS doc_id, cm.yymm, "
            f"MAX(CASE WHEN ch.section_type IN ({_STRONG_SQL}) THEN 1 ELSE 0 END) AS strong, "
            f"MAX(CASE WHEN ch.section_type IN ({_STRONG_SQL}) THEN ch.section_type END) AS strong_sec, "
            "MIN(ch.section_type) AS any_sec "
            "FROM jun.chunk ch "
            "JOIN jun.case_master cm ON cm.master_id = ch.master_id "
            "WHERE ch.is_active = 1 AND CONTAINS(ch.content, %s) "
            "AND cm.yymm >= %s AND cm.yymm <= %s "
            "GROUP BY cm.doc_id, cm.yymm ORDER BY cm.yymm DESC",
            (f'"{term}"', lo, hi))
        picked = [{"doc_id": _norm_doc_id(r.get("doc_id")),
                   "word": term, "hits": hits,
                   "section": _SECTION_KO.get(
                       str(r.get("strong_sec") or r.get("any_sec") or "").strip(), ""),
                   "strong": bool(r.get("strong"))} for r in rows or []]
        # 같은 단어 안에서 상대비교한다 — 강한 자리에 걸린 감정서가 하나라도 있으면
        # 본문 잡동사니(etc)에서만 걸린 것들은 버린다. 하나도 없으면 전부 남긴다.
        # 다만 후보가 _ADAPT_MIN 개 이하면 자르지 않는다 — 정답까지 날아간다
        # (어려운 건 553건 실측에서 무조건 자르면 재현 106→99).
        strong = [p for p in picked if p["strong"]]
        found.extend(strong if (strong and len(picked) > _ADAPT_MIN) else picked)
    return found, ladder


def _fts_unwindowed(ladder: list) -> list[dict]:
    """창 무제한 원문 1회 — 창 안 전패 + 다른 답 없음일 때만. 전역 60히트 이하의
    변별력 있는 말만 쓰므로 안전하다."""
    from app.services import gamjun_chat  # noqa: PLC0415

    vendor = gamjun_chat._vendor()  # noqa: SLF001
    found: list[dict] = []
    for _word, term, hits in ladder:
        if not hits or hits > _FTS_MAX_HITS:
            continue
        rows = vendor._run_query(  # noqa: SLF001
            "SELECT DISTINCT TOP 60 cm.doc_id AS doc_id FROM jun.chunk ch "
            "JOIN jun.case_master cm ON cm.master_id = ch.master_id "
            "WHERE ch.is_active = 1 AND CONTAINS(ch.content, %s)",
            (f'"{term}"',))
        for r in rows or []:
            found.append({"doc_id": _norm_doc_id(r.get("doc_id")),
                          "word": term, "hits": hits, "section": "",
                          "strong": False})
    return found


def _bigo_sync(words: list[str], day: str, months: int) -> list[dict]:
    """비고(varchar 6000) — 앞 단계가 전부 0건일 때만 친다. 스캔이 비싸다."""
    if not words or not day:
        return []
    view = _view()
    where = []
    params: dict[str, Any] = {"d": day, "m": months, "fwd": _FORWARD_DAYS}
    for i, word in enumerate(words):
        params[f"w{i}"] = f"%{word}%"
        where.append(f"a.Bigo LIKE :w{i}")
    sql = (
        f"SELECT TOP 20 {_COLS}, a.Bigo FROM {view} a "
        f"WHERE ({' OR '.join(where)}) " + _NO_OB +
        f"AND a.ReceiptDate >= DATEADD(month, -:m, CONVERT(date, :d)) "
        f"AND a.ReceiptDate < DATEADD(day, :fwd, CONVERT(date, :d)) "
        f"ORDER BY a.ReceiptDate DESC"
    )
    db = get_session_factory()()
    try:
        rows = db.execute(text(sql), params).mappings().all()
    finally:
        db.close()
    out = []
    for row in rows:
        bigo = str(row["Bigo"] or "")
        word = next((w for w in words if w in bigo), words[0])
        out.append(_row_to_item(row, word, "Bigo", "비고", months, "원장"))
    return out


# ── 금액 축 ───────────────────────────────────────────────────────────────
# 실측(827건, 2026-05~08): 입금액이 매출총액과 정확히 같은 비율은 73.5% 다.
# 그런데 **금액만으로 정답이 확정되는 건 23.5%(194/827)** 뿐이다 — 나머지는
# 같은 금액의 감정서가 창 안에 여러 건 있다(중앙값 3건, 최대 1,844건).
# 55,000원·1,100,000원 같은 정액 수수료가 후보를 수천 건으로 부풀리기 때문이다.
# 그래서 규칙은 하나다: **창 안에 같은 금액이 하나뿐일 때만 강한 근거**로 쓰고,
# 여럿이면 이름 축을 확증하는 가산점으로만 쓴다. 그 194건은 100% 정답이었다.
#
# 넣지 않은 보정과 그 이유: 원천징수(3.3%·3%·2.2%)로 설명되는 건 207건 중 0건,
# 펌뱅킹 수수료 같은 정액 차액도 ±1,000원 차이가 딱 1건뿐이었다. 보정할 게 없다.
_AMOUNT_MAX = 6           # 개월. 금액 축은 한 번만 훑는다 (상한 6개월 — 사용자 결정).
_AMOUNT_UNIQUE_MAX = 3    # 이보다 많이 걸리면 '금액이 같다'는 말에 힘이 없다


def _amount_sync(amount: int, day: str, months: int = _AMOUNT_MAX) -> list[dict]:
    """입금액과 금액이 맞는 감정서. 매출총액·청구금액·미수 잔액 세 자리를 본다.

    매출총액과 청구금액을 둘 다 보는 이유: 두 값이 갈리는 건은 740건 중 14건뿐이지만
    그중 7건은 입금액이 **청구금액과만** 맞고 매출총액과는 20만원씩 어긋나 있었다.
    """
    if not amount or not day:
        return []
    view = _view()
    params = {"amt": amount, "d": day, "m": months, "fwd": _FORWARD_DAYS}
    sql = (
        f"SELECT TOP 40 {_COLS}, a.[매출총액] AS gross, "
        f"CASE WHEN a.[매출총액] = :amt THEN '매출총액' "
        f"     WHEN a.[청구금액] = :amt THEN '청구금액' ELSE '' END AS which "
        f"FROM {view} a "
        f"WHERE (a.[매출총액] = :amt OR a.[청구금액] = :amt) " + _NO_OB +
        f"AND a.ReceiptDate >= DATEADD(month, -:m, CONVERT(date, :d)) "
        f"AND a.ReceiptDate < DATEADD(day, :fwd, CONVERT(date, :d)) "
        f"ORDER BY a.ReceiptDate DESC"
    )
    db = get_session_factory()()
    try:
        rows = db.execute(text(sql), params).mappings().all()
    finally:
        db.close()
    unique = len(rows) == 1
    out = []
    for row in rows:
        item = _row_to_item(row, f"{amount:,}원", "금액",
                            str(row["which"] or "금액") + " 일치", months, "금액")
        # 창 안에 하나뿐이면 그게 답이다(실측 194건 100%). 여럿이면 가산점일 뿐.
        item["amount_unique"] = unique
        item["weak"] = not unique
        out.append(item)
    return out


def _balance_sync(amount: int, day: str, months: int = _AMOUNT_MAX) -> list[dict]:
    """미수 잔액이 입금액과 같은 감정서 — 분납의 **마지막 잔금**을 잡는 축이다.

    실측: 2회차 이후 108행 중 잔액축이 맞은 25행은 **전부 마지막 회차**였고
    중간 회차는 0/58 이었다. 부분입금이 남은 잔액과 같아지는 건 정의상 마지막
    한 번뿐이라, 이 축은 분납을 '찾는' 축이 아니라 '끝내는' 축이다.
    """
    if not amount or not day:
        return []
    view = _view()
    params = {"amt": amount, "d": day, "m": months, "fwd": _FORWARD_DAYS}
    sql = (
        f"SELECT TOP 40 {_COLS} FROM {view} a "
        f"JOIN a10_receivable_summary s ON s.doc_id = a.DocID "
        f"WHERE s.outstanding_amount = :amt AND s.outstanding_amount > 0 " + _NO_OB +
        f"AND a.ReceiptDate >= DATEADD(month, -:m, CONVERT(date, :d)) "
        f"AND a.ReceiptDate < DATEADD(day, :fwd, CONVERT(date, :d)) "
        f"ORDER BY a.ReceiptDate DESC"
    )
    db = get_session_factory()()
    try:
        rows = db.execute(text(sql), params).mappings().all()
    finally:
        db.close()
    unique = len(rows) == 1
    out = []
    for row in rows:
        item = _row_to_item(row, f"{amount:,}원", "미수잔액", "미수 잔액 일치",
                            months, "금액")
        item["amount_unique"] = unique
        item["weak"] = not unique
        out.append(item)
    return out


# ── 회계 확증 — 찾은 뒤에 '이게 맞나'를 돈으로 되짚는다 ──────────────────────
# 이름으로 영원히 못 잡는 건이 17.5% 다(실측 40건 중 7건). 전부 제3자 입금이라
# 적요 이름이 원장 어디에도 없다 — '동통영새마을금고' 가 보냈는데 원장 의뢰처는
# '원광새마을금고이사장 외' 인 식이다. 그런 건은 돈으로만 이어진다.
# 그래서 금액은 **거르는 조건이 아니라 확증·순위 재료**로 쓴다.
def _money_marks(item: dict, amount: int, money: dict, day: str = "") -> None:
    """후보 한 건에 회계 상태와 금액 관계를 적어 넣는다."""
    item["_day"] = day
    item["billed_total"] = int(money.get("billed_amount") or 0)
    item["received"] = int(money.get("received_amount") or 0)
    item["advance"] = int(money.get("advance_amount") or 0)
    item["outstanding"] = int(money.get("outstanding_amount") or 0)
    item["last_received"] = money.get("last_received") or ""

    total = item["billed_total"]
    outstanding = item["outstanding"]
    item["money_score"] = 0
    item["money_note"] = ""
    if not amount:
        return
    if total and amount == total:
        item["money_note"] = "입금액 = 매출총액 (완납)"
        item["money_score"] = 60
    elif total and 0 < abs(amount - total) <= 1000:
        # 10원·100원짜리 잔차 — 입금자가 끝자리를 올리거나 깎은 것이다.
        # '묶음일 수 있음'으로 뭉개면 오해를 부른다(2026-08-06, 2380 건 10원 차이).
        item["money_note"] = f"매출총액과 {abs(amount - total):,}원 차이 (사실상 완납)"
        item["money_score"] = 50
    elif outstanding and amount == outstanding:
        item["money_note"] = "입금액 = 미수 잔액 (잔금)"
        item["money_score"] = 55
    elif outstanding and 0 < amount < outstanding:
        item["money_note"] = "미수 잔액보다 적음 (분할입금일 수 있음)"
        item["money_score"] = 15
    elif total and amount > total:
        item["money_note"] = "매출총액보다 많음 (여러 건 묶음일 수 있음)"
        item["money_score"] = 5
    # 회계가 이미 답을 냈나 — 이 감정서가 입금 당일에 완납 처리됐으면 재무팀이
    # 전표로는 붙여 놓고 Memo 만 안 적은 것이다. 우리 답의 가장 강한 확증이다.
    if (item.get("outstanding") == 0 and item.get("received")
            and (money.get("last_received") or "") == (item.get("_day") or "")):
        item["money_note"] = ((item["money_note"] + " · ").lstrip(" ·")
                             + "입금 당일 회계 완납 처리됨")
        item["money_score"] += 30


def _voucher_docs_cached(amount: int, day: str) -> list[str]:
    """같은 날 같은 금액 전표에 달린 감정서번호. 한 조회 안에서 한 번만 부른다.

    a10_voucher_cache 는 amount 인덱스가 없어 특정 금액에서 164초까지 밀린 실측이
    있다. 전표는 부가 정보라 5초를 넘기면 없이 간다 — 그 예산은 그대로 둔다.
    (미부착 120건 실측으로는 평균 0.06초·최대 0.18초라 예산에 거의 안 닿는다.)
    """
    if not amount or not day:
        return []
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            job = pool.submit(deposit_match._voucher_docs_sync, amount, day)  # noqa: SLF001
            return job.result(timeout=5)
    except FuturesTimeout:
        logger.warning("[deposit-search] 전표 조회 5초 초과 — 전표 없이 답한다")
    except Exception:
        logger.exception("[deposit-search] 전표 조회 실패")
    return []


def _enrich_sync(items: list[dict], amount: int, day: str,
                 voucher_docs: "list[str] | None" = None) -> None:
    """후보들에 회계 수치와 전표 유무를 붙인다 (한 번에 모아서 조회한다)."""
    doc_ids = [i["doc_id"] for i in items]
    if not doc_ids:
        return
    money = deposit_match._money_sync(doc_ids)  # noqa: SLF001
    for item in items:
        _money_marks(item, amount, money.get(item["doc_id"], {}), day)

    # 같은 날 같은 금액의 전표가 이미 있나 — '이 입금이 벌써 회계에 들어갔나'다.
    # 재무팀이 두 번 계상하지 않으려면 이걸 그 자리에서 봐야 한다.
    #
    # 다만 전표는 하루치 입금 수십 건을 담은 묶음장부라, 한 전표에 달린 감정서를
    # 다 긁어 오면 뭉뚱그려진다. 실측(7월 정답지 252건): 전표가 감정서를 **하나만**
    # 가리킨 게 173건(69%)이고 나머지는 최대 23개까지 딸려 왔다. 정답이 그 안에
    # 든 비율은 96% 지만, 여럿일 때는 '어느 것'인지를 말해 주지 못한다.
    # 그래서 금액과 같은 규칙을 쓴다 — 하나뿐일 때만 강한 근거다.
    # 발견 단계(⑧)가 이미 조회했으면 그 결과를 물려받는다 — 같은 질의를 두 번 하지 않는다.
    if voucher_docs is None:
        voucher_docs = _voucher_docs_cached(amount, day)
    unique_voucher = len(set(voucher_docs)) == 1
    voucher_set = set(voucher_docs)
    for item in items:
        hit = item["doc_id"] in voucher_set
        item["voucher"] = hit
        item["voucher_alone"] = hit and unique_voucher
        if hit:
            item["money_score"] += 40 if unique_voucher else 10
            note = item.get("money_note") or ""
            tail = ("같은 날 같은 금액 전표 있음" if unique_voucher
                    else f"전표 있음 (그 전표에 감정서 {len(voucher_set)}건)")
            item["money_note"] = (note + " · " + tail).strip(" ·")


# ── 조립 ──────────────────────────────────────────────────────────────────
# 축마다 실측 정확도가 다르다. 그 차이를 점수로 박아 둔다 — 안 그러면
# '금액이 우연히 같은 남의 감정서'가 '적요에 번호가 그대로 적힌 감정서'를 이긴다
# (실제로 260730658 건에서 그렇게 뒤집혔다).
_AXIS_SCORE = {
    "적요에 번호": 100,        # 실측 116건 중 95.7% 가 재무팀 Memo 와 같았다
    "사이버브랜치 매핑": 100,   # 이미 이어 둔 것이라 사실상 정답
    "적요 번호 보정": 85,      # 자리바꿈을 되돌린 번호가 원장에 실존 — 오탐 실측 0건
    "의뢰문서번호 접두": 65,    # 'LH_서울' → CustDocID '서울매입약정지원2팀-3799'
    "전기간 이름": 50,         # 창 밖(1년+) 정확 일치 — 60건 상한으로 흔한 말 차단
    "의뢰문서번호": 90,        # 걸리면 늘 1~3건. 40건 중 11건 적중(단독 7)
    # 세금계산서가 청구처와 감정서번호를 한 장에 들고 있다 — 사실상 번호 축이다.
    # 게이트 셋(금액 일치·후보 1건·이름 정확일치)을 다 건 상태의 단독 정밀도
    # 289/290 = 99.66%. 그래도 **금액 창안유일(80)보다 아래**에 둔다 — 그쪽은
    # 실측 194건 100% 라 이 축보다 정확하다. 88 을 줬다가 A/B 에서 잃음 1 이
    # 났고, 그 1건이 정확히 금액 창안유일을 밀어낸 것이었다. 올리지 말 것.
    "세금계산서 청구처": 75,
    "의뢰처": 60,            # 1년치 240/425 = 56.5%
    "채무자": 55,            # 1년치 30/57 = 52.6%
    "소유자": 35,            # 후보 발굴용 — 1순위는 의뢰처·채무자를 못 이긴다
    "의뢰처 담당": 35,
    "원문 본문": 30,          # 1년치 23/52 = 44.2%. 본문 히트는 절반이 오탐이다
    "제목": 22,              # 1년치 1순위 0/55 — 후보로만 남긴다
    "의뢰처 부서": 20,
    "비고": 10,              # 1년치 2/18 = 11.1%. 마지막 그물일 뿐이다
}
# 미수 잔액은 따로 둔다. 1년치 재측정에서 1순위로 뽑혀 맞힌 게 1건, 틀린 게
# 51건이다. 부분입금이 남은 잔액과 같아지는 건 정의상 마지막 회차뿐이라,
# 대부분은 '우연히 잔액이 그 금액인 남의 감정서'가 걸린다.
# 후보로는 남기되(진짜 잔금일 때 필요하다) 단독으로는 이기지 못하게 둔다.
_BALANCE_SCORE = (20, 5)
# 매출총액·청구금액은 창 안에 하나뿐일 때만 강하다(실측 194건 100%).
_AMOUNT_SCORE = (80, 10)


# 이 통장에 들어오는 입금은 사실상 본사 것이다 — 2026년 정답지 1,946건 중
# 감정서번호 앞 두 자리가 '01'(본사)인 게 1,943건(99.8%)이고 나머지는 3건뿐이다.
# 그래서 지사 감정서를 1순위로 올리면 거의 언제나 틀린다. 후보에서 빼지는 않고
# (그 3건이 실제로 있다) 순위만 내린다.
# 주의: 다른 지사 계좌로 이 화면을 확장하면 이 가정은 그 자리에서 깨진다.
_HOME_OFFICE = "01"
_OTHER_OFFICE_PENALTY = 35


def _axis_score(item: dict) -> int:
    label = item.get("field_label") or ""
    if label in _AXIS_SCORE:
        return _AXIS_SCORE[label]
    if label.startswith("미수 잔액"):
        return _BALANCE_SCORE[0 if item.get("amount_unique") else 1]
    # 금액 계열은 '창 안에 하나뿐인가'가 전부다 — 유일하면 실측 100%,
    # 여럿이면 (중앙값 3건·최대 1,844건) 단독 근거가 못 된다.
    if "일치" in label:
        return _AMOUNT_SCORE[0 if item.get("amount_unique") else 1]
    return 20


# 근거의 갈래 — 순위와 화면 표시가 같이 쓴다.
# 실측(1개월 정답지 291건, 1순위 기준): 근거 2개 이상 98% · 금액+회계 100% ·
# 번호 단독 91% · 금액 단독 44% · **이름 단독 0%(0/38)**. 그래서 규칙은:
# 번호가 있거나 갈래가 2개 이상이어야 확신 후보다. 단독 후보는 버리지 않고
# (후보는 넓게 — 사용자 방침) 순위를 내리고 화면에 '단일 근거'라고 밝힌다.
_NUM_LABELS = {"적요에 번호", "사이버브랜치 매핑", "적요 번호 보정", "의뢰문서번호",
               # 계산서 한 장에 청구처와 감정서번호가 같이 적혀 있다. 단독
               # 정밀도 99.66%(289/290) — 이 집합에서 가장 높다.
               "세금계산서 청구처"}
_NAME_LABELS = {"의뢰처", "채무자", "제목", "소유자", "의뢰처 담당", "의뢰처 부서",
                "비고", "원문 본문", "의뢰문서번호 접두", "전기간 이름", "이름 표기",
                "의뢰문서번호(추정)"}


# 표기 차이를 걷어낸 형태. '(주)한강이앰피' 와 '한강이앰피 주식회사' 를 같게 본다.
# 법인 표기·공백·기호를 빼고 대문자로 눕힌다.
_CANON_DROP = re.compile(
    r"주식회사|유한책임회사|유한회사|합자회사|재단법인|사단법인|의료법인|사회복지법인"
    r"|\(주\)|\(유\)|㈜|㈜")
_CANON_STRIP = re.compile(r"[^0-9A-Za-z가-힣]")
_CANON_MIN = 4      # 3글자 이하는 흔해서 남의 이름에 우연히 박힌다


def _canon(value: str) -> str:
    return _CANON_STRIP.sub("", _CANON_DROP.sub("", value or "")).upper()


def _name_echo(item: dict, canon_words: "set[str]") -> str:
    """이 후보의 원장 이름 칸이, 적요 토막과 표기만 다른 같은 말인가.

    맞으면 걸린 원장 값을 돌려준다. 양방향으로 본다 — 통장이 20자에서 잘려
    원장 이름이 더 길 때도(포함), 통장 쪽이 더 길 때도(역포함) 있다.
    """
    for key in ("cust_name", "submit_to", "debtor", "cust_charge"):
        raw = (item.get(key) or "").strip()
        canon = _canon(raw)
        if len(canon) < _CANON_MIN:
            continue
        for word in canon_words:
            # 양쪽 다 하한을 넘어야 한다. 호출부에서도 거르지만 여기서 한 번 더 —
            # 짧은 말은 남의 상호에 우연히 박힌다('대한' 이 '대한전선' 에 걸리듯).
            if len(word) < _CANON_MIN:
                continue
            if word in canon or canon in word:
                return raw
    return ""


def _exact_debtor_mark(items: list[dict], jeokyo: str) -> int:
    """용도 꼬리를 뗀 입금자와 채무자가 정확히 같은 유일한 본사 건을 표시한다.

    이름 단독 후보는 보통 오탐이라 화면에서 숨긴다. 하지만 첫 적요 칸이
    '<상호>감정여비'이고, 꼬리를 뗀 상호가 Debtor와 정확히 같으며, 6개월 창에서
    그 감정서가 하나뿐인 경우는 단순 부분 문자열 히트와 다르다. 이 좁은 조건만
    별도 근거로 인정한다.
    """
    first = next(iter(tokens(jeokyo)), "")
    stem = _PURPOSE_SUFFIX.sub("", first)
    if stem == first:
        return 0
    wanted = _canon(stem)
    if len(wanted) < _CANON_MIN:
        return 0
    matched = [item for item in items
               if str(item.get("doc_id") or "").startswith(f"{_HOME_OFFICE}-")
               and not any(word in str(item.get("status") or "")
                           for word in ("반려", "취소"))
               and _canon(item.get("debtor") or "") == wanted]
    if len({item["doc_id"] for item in matched}) != 1:
        return 0
    for item in matched:
        item["_exact_debtor"] = True
    return 1


# ── 재보고 버린 축 (2026-08-08). 다시 시도하지 말라고 실측을 남긴다 ──────────
# · **이웃 줄 전파** — 같은 적요·같은 금액의 다른 입금이 이미 단 번호를 물려받기.
#   ±30일 70.5%(44건) · ±90일 60.6% · ±366일 56.7%. 미부착 4,689건 중 답이 나오는
#   건은 29건(0.6%)뿐이다. 오답이 체계적이다 — 같은 고객이 같은 금액으로 **다른**
#   감정서를 여러 번 낸다('주식회사세진종합건설' 3,520,000원이 01-2308-3-3936 과
#   01-2308-3-3937 로 갈리고, 'LH_서울' 5,500,000원은 셋으로 갈린다).
# · **같은 날 쪼개진 입금 묶기** — 같은 날·같은 적요·같은 금액 묶음 619개 중
#   번호가 둘 이상 달린 24개를 보니 전부 같은 번호인 건 13개(54.2%)뿐이다.
#   'LH_서울' 처럼 한 날 여러 감정서 대금을 같은 금액으로 나눠 보내는 곳이 있다.
#   ('우리은행//잠실나루역지점/대체입금' 1,693,860원 × 20줄이 전부
#    01-2511-3-3832 인 건 사실이지만, 그건 예외지 규칙이 아니다.)
#
# ── 재무팀 수작업을 축으로 옮기려다 기각 (2026-08-11) ────────────────────────
# 재무팀은 ① 입금자 법인 소재지를 인터넷에서 찾아 접수내역을 소재지로 뒤지고
# ② 은행에 전화해 어느 지점에서 입금됐는지 묻는다. 둘 다 축으로 못 세운다.
#
# · **소재지 축** — 없는 건 '주소 구하는 방법'이 아니라 **의뢰처 주소 컬럼 자체**다.
#   접수내역의 ADDR·Address 는 '감정 대상 물건 소재지'라, 법인 소재지로 뒤지면
#   법인 주소로 물건 주소를 뒤지는 일이 된다. 천장이 획득률이 아니라 구조에 있다 —
#   **주소를 완벽히 안다고 가정한 오라클에서도 시군구 일치 26.6%(46/173)**.
#   신탁사·건설사·은행지점은 본점이 강남·여의도인데 물건은 전국이다.
#   정답지 최근1년 3,445건 전수(현행 1순위 87.8%)의 실패 421건에 걸어 보니
#   **추가로 풀리는 건 0건**, 단독 정밀도는 읍면동 10.0%(1/10)·이론상한 2.1%.
#   그리고 붙이면 오히려 나빠진다 — 이미 맞는 3,024건 중 365건(12.07%)에서 발화해
#   전부 오답을 끌고 오고, 그중 **19건은 그 오답이 입금액과도 맞아 '소재지+금액'
#   두 갈래 → _tier()=0 확신 배지로 승격**된다. 지금 _keep_worth_showing 이 tier 1 로
#   눌러 둔 금액 단독 오답의 잠금을 푸는 쪽으로 작동한다.
# · **입금 지점(CB2_ACCT_HIS.BRANCH) 축** — 컬럼은 있고 목록 조회가 이미 읽어
#   화면 '지점' 열에 그린다(deposit_list.py). 배관은 한 줄이면 뚫리지만 값이 안 된다.
#   최근2년 30,465건 중 실제 지점명꼴은 18.9%, 정답지로 좁히면 10.7%다(40.5%가
#   국민은행 본부 부서명 — 대출실·담보관·가치평). 게다가 **'물건 근처 지점에서
#   부친다'는 전제가 틀렸다** — 정답지 837건에서 지점토막이 물건 소재지에 걸리는 건
#   6.7%, 원장 의뢰처 이름에 걸리는 건 68.0%다. 즉 그 값은 '입금 지점'이 아니라
#   대부분 '의뢰한 은행 영업점'이라 아래 _branch_tokens 이 이미 쓰는 정보와 겹친다.
#   적요에 없는 '새 정보'만 떼어 재면 단독 정밀도 **0.0%(0/28)**.
#   (수서역↔용산구, 명동역↔종로구, 창동↔서초구 — 개인이 자기 생활권 지점에서 부친다.)
#
# 개인이 자기 감정을 스스로 의뢰하고 스스로 입금한 건. 실측(2024+ 정답지 651건,
# 1개월창): 원장이 그 이름으로 한 건만 낼 때 정밀도가
#   전체 90.4% → **본사(01-)만 97.0% → 본사 + 이름이 의뢰인칸이면 192/192 = 100%**.
# 오답이 지사 건으로 몰리는 건 이 통장이 본사 통장이기 때문이다 — 정답 651건이
# 전부 01- 이었다(예외 0건). 그래서 **본사 + 의뢰인칸 + 창 안 유일** 셋을 다 요구한다.
# '이지안/타행이체/기업은행(2421)/' 807,400원이 이 규칙이 필요한 이유다 —
# 원장 01-2605-3-1707 의 의뢰인이 정확히 '이지안' 인데, 청구액(779,900)이 입금액과
# 달라 이름 하나뿐이라 tier 2 로 숨어 있었다.
_PERSON_RE = re.compile(r"^[가-힣]{2,4}$")
# 성씨로 시작하지 않으면 사람 이름으로 보지 않는다. 상호 토막('대왕'·'현대')을
# 사람으로 오인하면 남의 감정서를 확신 후보로 올린다.
_SURNAMES = set(
    "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차"
    "주우구나민진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육"
    "인맹제모탁국어은편용")
_PERSON_STOP = {"대체", "현대", "우리은행", "국민은행", "신한은행", "하나은행",
                "농협", "수협", "기업은행", "새마을", "우체국", "카카오",
                "케이뱅크", "토스", "대왕", "우리", "국민", "신한", "하나"}


def _person_payer(jeokyo: str) -> str:
    """적요 이름칸이 개인 이름이면 그 이름, 아니면 빈 문자열."""
    payer = (jeokyo or "").split("/")[0].strip()
    if payer in _PERSON_STOP or not _PERSON_RE.match(payer):
        return ""
    return payer if payer[0] in _SURNAMES else ""


def _self_client_mark(items: list[dict], jeokyo: str) -> int:
    """본인 의뢰 건에 '본인' 근거를 붙인다. **창 안에 하나뿐일 때만.**

    새 조회를 하지 않는다 — 이미 뽑아 둔 후보 중에서 고른다.
    """
    payer = _person_payer(jeokyo)
    if not payer:
        return 0
    mine = [i for i in items
            if str(i.get("doc_id") or "").startswith(f"{_HOME_OFFICE}-")
            and (i.get("cust_name") or "").strip() == payer]
    # **감정서 단위로 센다.** items 에는 1·3·6개월 창이 같은 감정서를 세 번 담는다
    # — 줄 수로 세면 유일한 건도 '셋'이 되어 규칙이 통째로 안 먹는다.
    if len({i["doc_id"] for i in mine}) != 1:
        return 0        # 둘 이상이면 사람이 고른다 — 확신을 주지 않는다
    # _rank 는 먼저 만난 줄을 대표로 남기므로 같은 감정서의 줄을 모두 표시한다.
    for item in mine:
        item["_self_client"] = True
    return 1


def _signals(item: dict) -> list[str]:
    sig = set()
    for label in item.get("_labels") or {item.get("field_label") or ""}:
        if label in _NUM_LABELS:
            sig.add("번호")
        elif label in _NAME_LABELS:
            sig.add("이름")
        elif label.endswith("일치"):
            sig.add("금액")
    note = item.get("money_note") or ""
    # 금액 신호는 **실제 금액 관계**에서만 나온다 (2026-08-08).
    # 예전에는 '완납'·'잔금'·'차이' 를 통째로 봤는데, 회계 꼬리말
    # '입금 당일 회계 완납 처리됨' 에도 '완납' 이 들어 있어 **한 문장이 금액과
    # 회계 두 신호를 다 만들었다.** 그러면 근거가 둘이 되어 tier 0 으로 올라온다.
    # 실측 피해: '주식회사 엘앤씨이에' 3,121,800원에서 원문이 물어온 오답
    # 01-2603-3-0848 이 이 꼬리말만으로 근거 3개를 얻어, 매출총액이 정확히 맞는
    # 정답 01-2603-3-0706 을 2순위로 밀어냈다.
    # _money_marks 가 쓰는 문구는 셋뿐이다 — '입금액 = 매출총액 (완납)',
    # '매출총액과 N원 차이 (사실상 완납)', '입금액 = 미수 잔액 (잔금)'.
    if "입금액 = " in note or "매출총액과" in note:
        sig.add("금액")
    if item.get("voucher") or "회계 완납" in note:
        sig.add("회계")
    if item.get("_self_client"):
        sig.add("본인")
    if item.get("_exact_debtor"):
        sig.add("입금자")
    return sorted(sig)


def _tier_precheck(item: dict) -> bool:
    """전표 발견을 열기 전에 보는 판정 — '이미 화면에 낼 만한 후보가 있나'.

    _enrich_sync 전이라 회계 수치가 아직 안 붙었다. 그래서 _keep_worth_showing 과
    같은 잣대(번호 / 근거 2개 / 창 안 유일한 금액)를 **지금 아는 정보만으로** 본다.
    """
    sig = set(_signals(item))
    if "번호" in sig or "본인" in sig or "입금자" in sig or len(sig) >= 2:
        return True
    return "금액" in sig and bool(item.get("amount_unique"))


def _tier(item: dict) -> int:
    """0 = 확신(번호·본인 또는 갈래 2+) · 1 = 금액 단독(44%) · 2 = 이름 단독(0%)."""
    sig = set(item.get("evidence") or [])
    if "번호" in sig or "본인" in sig or "입금자" in sig or len(sig) >= 2:
        return 0
    return 1 if "금액" in sig else 2


def _rank(items: list[dict]) -> list[dict]:
    """후보 순서. 축의 강도 → 근거 겹침 → 돈 → 좁은 창 → 최근 접수 순.

    같은 감정서가 여러 축에서 걸리면 그만큼 위로 올린다 — 이름도 맞고 금액도
    맞으면 그게 답일 확률이 훨씬 높다.
    """
    merged: dict[str, dict] = {}
    for item in items:
        key = item["doc_id"]
        kept = merged.get(key)
        if kept is None:
            item["_labels"] = {item.get("field_label") or ""}
            merged[key] = item
            continue
        kept.setdefault("_labels", {kept.get("field_label") or ""}).add(
            item.get("field_label") or "")
        mark = f"{item['field_label']} {item['word']}".strip()
        also = kept.setdefault("also", [])
        if mark and mark not in also:
            also.append(mark)
        kept["money_score"] = max(kept.get("money_score", 0),
                                  item.get("money_score", 0))
        kept["months"] = min(kept.get("months") or 99, item.get("months") or 99)
        kept["amount_unique"] = (kept.get("amount_unique")
                                 or item.get("amount_unique", False))
        # 더 센 축으로도 걸렸으면 그쪽을 대표 근거로 삼는다.
        if _axis_score(item) > _axis_score(kept):
            kept["word"] = item["word"]
            kept["field"] = item["field"]
            kept["field_label"] = item["field_label"]
            kept["source"] = item["source"]
            kept["weak"] = item.get("weak", False)

    for item in merged.values():
        item["evidence"] = _signals(item)

    def order(item: dict) -> tuple:
        penalty = (0 if str(item.get("doc_id") or "")[:2] == _HOME_OFFICE
                   else _OTHER_OFFICE_PENALTY)
        return (
            _tier(item),                           # 근거 2개 규칙이 최우선이다
            1 if item.get("weak") else 0,          # 거래유형어로만 걸린 건 뒤로
            -(_axis_score(item) + item.get("money_score", 0)
              + 25 * len(item.get("also", [])) - penalty),
            item.get("months") or 99,              # 좁은 창이 먼저
            -_date_key(item.get("recv_date")),     # 최근 접수가 먼저
        )

    return sorted(merged.values(), key=order)


def _date_key(value: str) -> int:
    try:
        return int((value or "").replace("-", "") or 0)
    except ValueError:
        return 0


_STAGE_LABEL = {"number": "적요 번호", "cyber": "사이버브랜치 매핑",
                "typo": "적요 번호 보정",
                "custdocid": "의뢰문서번호", "custdocid_weak": "의뢰문서번호(추정)",
                "custdocid_all": "의뢰문서번호(전기간)",
                "name": "원장 이름",
                "wide": "원장 전 컬럼", "cd_prefix": "의뢰문서번호 접두",
                "gemini": "표기 변형", "person2": "인명 접두",
                "amount": "금액", "balance": "미수 잔액",
                "bigo": "원장 비고", "fts": "감정서 원문",
                "tax_bill": "세금계산서 청구처",
                "fts_uw": "원문 전기간", "unlimited": "전기간 이름",
                "exact_debtor": "입금자·채무자 정확일치",
                "self_client": "본인 의뢰"}


# 감정서번호 앞 두 자리(지사)는 적요에 안 실린다. 그래서 압축형 9자리로는
# 어느 지사 것인지 모른다 — 있을 수 있는 접두를 다 만들어 IN 으로 짚는다.
# RIGHT(REPLACE(DocID,'-',''),9) = :c 로 쓰면 인덱스를 못 타 뷰 73만 행을
# 통째로 훑어 3~4초가 든다(실측). 같은 답을 IN 으로 받으면 0.1초다.
_OFFICE_PREFIXES = tuple(f"{n:02d}" for n in range(1, 20))


def _doc_id_candidates(compact: str) -> list[str]:
    """'260720088' → ['01-2607-2-0088', '02-2607-2-0088', …]"""
    if len(compact) != 9 or not compact[:4].isdigit():
        return []
    body = f"{compact[:4]}-{compact[4]}-{compact[5:]}"
    return [f"{prefix}-{body}" for prefix in _OFFICE_PREFIXES]


def _number_sync(compacts: list[str]) -> list[dict]:
    if not compacts:
        return []
    wanted: dict[str, str] = {}
    for compact in compacts:
        for doc_id in _doc_id_candidates(compact):
            wanted[doc_id] = compact
    if not wanted:
        return []
    view = _view()
    doc_ids = list(wanted)
    params = {f"d{i}": d for i, d in enumerate(doc_ids)}
    holes = ", ".join(f":d{i}" for i in range(len(doc_ids)))
    db = get_session_factory()()
    try:
        rows = db.execute(text(
            f"SELECT TOP 10 {_COLS} FROM {view} a WHERE a.DocID IN ({holes}) "
            + _NO_OB),
            params).mappings().all()
    finally:
        db.close()
    return [_row_to_item(r, wanted.get(str(r["DocID"]).strip(), ""), "DocID",
                         "적요에 번호", 0, "원장") for r in rows]


# ── Gemini 표기 변형 — 이름으로 못 찾은 건의 마지막 그물 ────────────────────
# 실측(40건)에서 실패의 15%가 순전히 표기 차이였다: 'LH_서울'↔한국토지주택공사
# 서울지역본부, '포티투닷'↔42DOT, '(주)엘지에너지솔루션'↔LG에너지솔루션,
# '가산디지금융센터'↔가산디지털금융센터. 규칙 사전으로는 끝이 없어서,
# 이름 축이 전부 빈 건에 한해 Gemini 에게 변형 표기를 물어 한 번 더 두드린다.
# 벤더(gamjun_search.py:623)와 같은 REST 호출이라 새 의존성은 없다.
_GEMINI_MODEL = "gemini-2.5-flash-lite"
_GEMINI_TIMEOUT = 6.0

_VARIANT_PROMPT = (
    "은행 통장 적요에 적힌 입금자 표기다. 감정평가법인 원장에서 이 입금자를 "
    "찾으려 한다. 원장에는 정식 명칭이나 다른 표기로 적혀 있을 수 있다.\n"
    "적요: {jeokyo}\n"
    "입금자로 보이는 토막: {names}\n\n"
    "이 입금자의 다른 표기를 최대 5개 제시하라. 규칙:\n"
    "- 약칭이면 정식 명칭 (예: LH → 한국토지주택공사, 농협 → 농업협동조합)\n"
    "- 한글 음차면 원어 표기, 원어면 한글 표기 (예: 포티투닷 → 42DOT)\n"
    "- 잘린 말이면 온전한 말 (예: 가산디지금융센터 → 가산디지털금융센터)\n"
    "- (주)·주식회사 등 법인 표기는 떼거나 붙인 형태\n"
    "- 확신 없는 추측은 넣지 마라. 은행 이름·거래유형어는 제외하라.\n"
    "2글자 이상 문자열만, JSON 배열로만 답하라."
)


def _gemini_variants_sync(jeokyo: str, names: list[str]) -> list[str]:
    """입금자 표기의 변형 목록. 키가 없거나 실패하면 조용히 빈 목록."""
    key = get_settings().gemini_api_key.get_secret_value()
    if not key or not names:
        return []
    try:
        import httpx  # noqa: PLC0415 (벤더가 이미 쓰는 의존성)

        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{_GEMINI_MODEL}:generateContent")
        body = {
            "contents": [{"parts": [{"text": _VARIANT_PROMPT.format(
                jeokyo=jeokyo[:100], names=", ".join(names[:5]))}]}],
            "generationConfig": {
                "temperature": 0.0, "maxOutputTokens": 256,
                "responseMimeType": "application/json",
                "responseSchema": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
        }
        response = httpx.post(url, json=body, headers={"x-goog-api-key": key},
                              timeout=_GEMINI_TIMEOUT)
        response.raise_for_status()
        raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        import json as _json  # noqa: PLC0415

        variants = _json.loads(raw)
        out = []
        for v in variants if isinstance(variants, list) else []:
            word = _TRIM.sub("", _normalize(str(v)))
            if len(word) >= 2 and word not in names and not is_stop(word):
                out.append(word)
        return out[:5]
    except Exception:
        logger.debug("[deposit-search] Gemini 변형 조회 실패 — 건너뛴다")
        return []


def _windows(fn, words: list[str], day: str):
    """창을 좁은 것부터 차례로 두드린다 — 걸리면 거기서 멈춘다.

    세 창을 동시에 던져도 봤는데 빨라지지 않았다(오히려 느려진 건도 있다).
    apw_masterex 가 인덱스 없는 뷰라 창 하나가 곧 73만 행 스캔이고, 셋을 같이
    던지면 같은 뷰를 두고 서로 CPU 를 다툰다. 좁은 창에서 걸리는 게 절반이 넘어
    (창1 재현 32.5% · 창3 40.0%) 차례로 두드리는 편이 실제로 일을 덜 한다.
    """
    for months in _WINDOWS:
        yield months, fn(words, day, months)


# ── 어려운 건용 보조 축 (2026-08-06 글자-전용 검수에서 발굴·실측) ─────────────
# A/B: 실패 136건 1순위 12%→35%(+31, 잃음 0) · 1개월 정답지 83%→85%(+8/−1).

def _branch_tokens(names: list[str]) -> list[str]:
    """합성 토막에서 지점명을 꺼낸다 — '경남중앙강남지점약식' 은 통째로는 어디에도
    없지만 '강남지점' 은 원장 CustName 에 그대로 있다."""
    out: list[str] = []
    for word in names:
        for m in _BRANCH_RE.finditer(word):
            run = m.group(1)
            for k in range(2, min(6, len(run)) + 1):
                cand = run[-k:] + "지점"
                if (cand != word and cand not in names and cand not in out
                        and not is_stop(cand)):
                    out.append(cand)
    return out[:6]


def _confirmed(doc_ids: "set[str]", amount: int) -> bool:
    """후보 중에 돈으로 확증되는 것이 있나 — 매출총액 ±1,000원 또는 미수 잔액 일치.

    사다리 확증-계속(E1)의 판정이다: 좁은 창의 이름 히트가 돈으로 확증되면 거기서
    멈추고, 아니면 다음 창도 두드린다. '고려산업(주)' 이 1개월 창의 엉뚱한 6건에
    막혀 74일 전 접수분(3개월 창)에 못 간 실패가 이 판정으로 풀렸다.
    """
    if not amount or not doc_ids:
        return False
    money = deposit_match._money_sync(list(doc_ids)[:60])  # noqa: SLF001
    for m in money.values():
        billed = int(m.get("billed_amount") or 0)
        outstanding = int(m.get("outstanding_amount") or 0)
        if billed and abs(amount - billed) <= 1000:
            return True
        if outstanding and amount == outstanding:
            return True
    return False


def _custdocid_prefix_sync(names: list[str], day: str, amount: int) -> list[dict]:
    """글자 토막이 의뢰문서번호의 **접두**인가 — 'LH_서울' 은 이름 축엔 없지만
    CustDocID '서울매입약정지원2팀-3799' 의 접두와 맞는다. 금액 일치 행을
    앞세워 오탐을 누른다(실측: 정답 7/9 이 입금액=매출총액, top1 훼손 0)."""
    toks = [w.replace(" ", "") for w in names
            if not is_stop(w) and _LETTER0.match(w) and len(w.replace(" ", "")) >= 2][:5]
    if not toks or not day:
        return []
    view = _view()
    where, params = [], {"d": day, "m": _WINDOWS[-1], "fwd": _FORWARD_DAYS,
                         "amt": amount or -1}
    for i, t in enumerate(toks):
        params[f"p{i}"] = t + "%"
        where.append(f"LTRIM(a.CustDocID) LIKE :p{i}")
    sql = (f"SELECT TOP 40 {_COLS}, a.CustDocID FROM {view} a "
           f"WHERE ({' OR '.join(where)}) " + _NO_OB +
           f"AND a.ReceiptDate >= DATEADD(month, -:m, CONVERT(date, :d)) "
           f"AND a.ReceiptDate < DATEADD(day, :fwd, CONVERT(date, :d)) "
           f"ORDER BY CASE WHEN a.[매출총액] = :amt OR a.[청구금액] = :amt "
           f"THEN 0 ELSE 1 END, a.ReceiptDate DESC")
    db = get_session_factory()()
    try:
        rows = db.execute(text(sql), params).mappings().all()
    finally:
        db.close()
    out = []
    for row in rows:
        ref = str(row["CustDocID"] or "").strip()
        word = next((t for t in toks if ref.startswith(t)), toks[0])
        out.append(_row_to_item(row, f"{word}… ({ref})", "CustDocID",
                                "의뢰문서번호 접두", _WINDOWS[-1], "원장"))
    return out


def _person_prefix_sync(names: list[str], day: str) -> list[dict]:
    """3글자 인명의 앞 2글자 접두 — '장재훈' 입금인데 원장은 '장재준'(1자 차이·
    가족 대납)인 유형. 이름 축이 빈손이고 돈 확증도 없을 때만 돈다."""
    toks = [w for w in names if _HANGUL3.match(w) and not is_stop(w)]
    if not toks or not day:
        return []
    view = _view()
    where, params = [], {"d": day, "m": _WINDOWS[-1], "fwd": _FORWARD_DAYS}
    for i, t in enumerate(toks[:3]):
        params[f"p{i}"] = t[:2] + "%"
        for col, _label in _NAME_COLS:
            where.append(f"a.{col} LIKE :p{i}")
    sql = (f"SELECT TOP 20 {_COLS} FROM {view} a WHERE ({' OR '.join(where)}) " + _NO_OB +
           f"AND a.ReceiptDate >= DATEADD(month, -:m, CONVERT(date, :d)) "
           f"AND a.ReceiptDate < DATEADD(day, :fwd, CONVERT(date, :d)) "
           f"ORDER BY a.ReceiptDate DESC")
    db = get_session_factory()()
    try:
        rows = db.execute(text(sql), params).mappings().all()
    finally:
        db.close()
    out = []
    for row in rows:
        for t in toks:
            got = None
            for col, label in _NAME_COLS:
                if str(row[col] or "").replace(" ", "").startswith(t[:2]):
                    got = (col, label)
                    break
            if got:
                out.append(_row_to_item(row, f"{t}→{t[:2]}*", got[0], got[1],
                                        _WINDOWS[-1], "원장"))
                break
    return out


def _unlimited_sync(names: list[str], day: str) -> list[dict]:
    """전기간 이름 조회 1회 — 창 밖 실패(접수 1년+ 뒤 입금, '(주)두원아이텍코리아'
    733일)용. 모든 축이 빈손이고 돈 확증도 없을 때만 돈다. 60건 상한에 닿으면
    너무 흔한 말('서울')로 보고 통째로 버린다 — 오탐만 늘기 때문이다.
    비용: apw_masterex 전량 스캔 1회 6.6~9.0초(실측) — 어차피 빈손으로 끝나던
    건에서만 문다."""
    if not names or not day:
        return []
    view = _view()
    where, params = [], {}
    for i, w in enumerate(names[:6]):
        if is_stop(w):
            continue
        params[f"w{i}"] = f"%{w}%"
        for col, _label in _NAME_COLS:
            where.append(f"a.{col} LIKE :w{i}")
    if not where:
        return []
    sql = (f"SELECT TOP 60 {_COLS} FROM {view} a WHERE ({' OR '.join(where)}) " + _NO_OB +
           f"ORDER BY a.ReceiptDate DESC")
    db = get_session_factory()()
    try:
        rows = db.execute(text(sql), params).mappings().all()
    finally:
        db.close()
    if len(rows) >= 60:
        return []
    out = []
    for row in rows:
        for w in names[:6]:
            got = None
            for col, _label in _NAME_COLS:
                if w.replace(" ", "") in str(row[col] or "").replace(" ", ""):
                    got = col
                    break
            if got:
                out.append(_row_to_item(row, w, got, "전기간 이름", 99, "원장"))
                break
    return out


def _unlimited_prefix4(names: list[str], day: str) -> list[dict]:
    """전기간 조회가 빈손이면 토막 앞 4글자로 한 번 더 — '노량진2구역...' 처럼
    뒷부분이 원장 표기와 다른 긴 합성 토막용 (전기간 9히트 실측)."""
    toks = [w[:4] for w in names
            if len(w) >= 5 and not is_stop(w) and not is_stop(w[:4])]
    toks = [t for t in toks if len(t) >= 3]
    return _unlimited_sync(toks, day) if toks else []


_RUN9 = re.compile(r"(?<!\d)(\d{9})(?!\d)")


def _typo_sync(jeokyo: str, day: str) -> list[dict]:
    """적요의 9자리 숫자가 감정서번호의 **자리바꿈 오타**인지 본다.

    은행 창구가 번호를 손으로 옮겨 적다 이웃 자리를 바꾼다 — '206732380' 은
    2067이 유효한 연월이 아니라 번호 후보에서 탈락하지만, 2067→2607 을 되돌리면
    01-2607-3-2380(난곡새마을금고)이 원장에 실존한다(2026-08-06 실측).
    이런 건은 재무팀도 못 풀어서 Memo 가 비어 있다 — 정답지에 안 잡히는 유형이다.

    안전장치: ⓪ 원래 번호가 원장에서 아무것도 못 찾았을 때만 돌고,
    변형은 유효 연월·구분을 통과해야 하며, 접수일이 입금일 기준 13개월 안이어야
    한다. 미해결 60일 실측에서 엉뚱한 감정서를 문 변형은 0건이었다.
    """
    if not day:
        return []
    variants: dict[str, tuple[str, str]] = {}   # doc_id → (원래 런, 보정 런)
    for run in _RUN9.findall(_normalize(jeokyo)):
        raw = set(deposit_match._compacts(run))  # noqa: SLF001 (이미 시도한 형태)
        for i in range(len(run) - 1):
            if run[i] == run[i + 1]:
                continue
            v = run[:i] + run[i + 1] + run[i] + run[i + 2:]
            if v in raw:
                continue
            if not deposit_match._valid(v[:2], v[2:4], v[4]):  # noqa: SLF001
                continue
            for doc_id in _doc_id_candidates(v):
                variants.setdefault(doc_id, (run, v))
    if not variants:
        return []
    found = _by_doc_ids_sync(list(variants), "", "적요 번호 보정", "원장")
    out = []
    try:
        base = dt.date.fromisoformat(day)
    except ValueError:
        return []
    floor_key = int((base - dt.timedelta(days=190)).strftime("%Y%m%d"))
    ceil_key = int((base + dt.timedelta(days=_FORWARD_DAYS)).strftime("%Y%m%d"))
    for item in found:
        recv = _date_key(item.get("recv_date"))
        # 접수가 창(6개월+α) 밖이면 우연의 일치로 본다.
        if not recv or recv < floor_key or recv > ceil_key:
            continue
        run, v = variants[item["doc_id"]]
        item["word"] = f"{run} → {v}"
        out.append(item)
    return out


# ── 약식(KB 탁상) — 감정서가 아니라 '어느 지사가 어느 영업점 건을 했나' ────
#
# 약식평가에는 감정서번호가 없다. 재무팀이 필요한 것도 번호가 아니라
# **본/지사와 영업점명**뿐이다 (2026-08-06 요청).
# 적요의 가상계좌(400+6자리)가 곧 국민은행 탁상감정 의뢰번호라 그것 하나로 푼다.
#
# ▸ 영업점명은 **약식 전표와 같은 경로**로 얻는다 (deposit_vouchers.py 의
#   약식 전표 조립부 — 줄번호는 자주 바뀌니 APW_TS_Master 로 찾을 것).
#   ① APW_TS_Master.CustName  ② 없으면 KB_Code → a10_kb_branch_map.branch_name
#   실측(2025-08~2026-08 고유 계좌 3,909개): ① 81.9% + ② 16.9% = 98.8%.
#
#   BANK_KB_REQUEST_MASTER 의 BillName 을 쓰면 안 된다. 그것은 세금계산서
#   **청구처**(BillRND·BillBoss·BillAddr 와 한 묶음)이지 영업점이 아니다.
#   실측: 둘 다 있는 3,201개 중 91개(2.84%)가 서로 다른 지점을 가리킨다
#   ('국민은행 모란역(점)' vs '국민은행－성남종합금융센터'). 전표는 ①을 쓰므로
#   BillName 을 쓰면 같은 입금이 화면과 전표에서 다른 지점으로 보인다.
#   이름은 한 곳에서만 정한다. (KB_Name 은 암호값이라 못 쓴다 — kb_branch_map.py)
#
#   ②를 ①보다 먼저 쓰지도 않는다. 매핑표는 코드별 다수결로 시드한 것이라
#   둘 다 있는 3,050개 중 79개(2.59%)에서 ①과 갈린다 — '국민은행 행신동(점)'을
#   '국민은행 아웃바운드지원부지점'으로, '세종한누리'를 '세종'으로 뭉갠다.
#
# ▸ 본/지사는 BANK_KB_MASTER.OfficeID → BANK_KB_AccOffice.Names.
#   실측(2024-08~2026-07 입금 13,406건) 100%, 한 계좌에서 갈린 것 0건.
#   분포는 본사 79.1% · 부산경남 8.5% · 경인 6.7% · 제주 2.1% · 경북 1.6% ·
#   울산 1.2% · 경남중앙 0.8%.
#   APW_TS_Master.Office 는 쓰지 않는다 — 400번호 44,670행이 **전부 '10'(본사)**라
#   지사가 구분되지 않는다(실측). 그쪽은 전표의 회계단위용 값이다.
#
# BANK_KB_* · APW_TS_Master 는 원장과 같은 DB(apworksdw), a10_kb_branch_map 은
# 우리 DB 라 세션 하나로 다 읽는다. **SELECT 만 한다**.
_YAKSIK_CACHE: dict[str, dict[str, str]] = {}
_YAKSIK_CACHE_MAX = 5000

# 지점명은 **한 건씩 묻지 않고 통째로 담는다**. APW_TS_Master(1,453,159행)에는
# HFDocid 인덱스가 없고 ORDER BY TS_SEQ DESC 가 역방향 스캔을 부른다 —
# 실측으로 한 건 4~5초다. 반면 400번호 전체(44,656개)를 한 번에 긁으면 396ms,
# 메모리 861KB 다. 담아 두고 30분마다 다시 읽는다.
_TS_BRANCH: dict[str, str] = {}
_TS_BRANCH_AT = 0.0
_TS_BRANCH_TTL = 1800.0


def _ts_branches() -> dict[str, str]:
    """400번호 → 영업점명 (APW_TS_Master). 통째로 담아 두고 30분마다 갱신."""
    global _TS_BRANCH, _TS_BRANCH_AT  # noqa: PLW0603
    now = time.monotonic()
    if _TS_BRANCH and now - _TS_BRANCH_AT < _TS_BRANCH_TTL:
        return _TS_BRANCH
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    db = get_session_factory()()
    try:
        rows = db.execute(text(
            f"SELECT HFDocid, CustName FROM [{database}].dbo.APW_TS_Master "
            f"WHERE HFDocid LIKE '400%' "
            f"  AND CustName IS NOT NULL AND CustName <> ''")).all()
    except Exception:
        logger.exception("약식 지점명 적재 실패")
        return _TS_BRANCH          # 옛 값이라도 쓴다
    finally:
        db.close()
    fresh: dict[str, str] = {}
    for va, name in rows:
        key = str(va or "").strip()
        if key:
            fresh.setdefault(key, str(name or "").strip())
    _TS_BRANCH = fresh
    _TS_BRANCH_AT = now
    return _TS_BRANCH


def _yaksik_sync(jeokyo: str) -> dict[str, str]:
    """약식 입금의 본/지사와 영업점명. 못 찾으면 빈 값."""
    hit = deposit_match._VA_RE.search(jeokyo or "")  # noqa: SLF001
    if not hit:
        return {}
    va = hit.group(1)
    cached = _YAKSIK_CACHE.get(va)
    if cached is not None:
        return dict(cached)

    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    out = {"va": va}
    try:
        out["branch"] = _ts_branches().get(va, "")
    except Exception:
        logger.exception("약식 지점명 조회 실패")
        out["branch"] = ""

    db = get_session_factory()()
    try:
        # 한 계좌에 BANK_KB_MASTER 행이 둘씩 달린다(접수·완료). 지사는 어느
        # 행이나 같지만(실측 충돌 0건) 최근 것을 집는다.
        out["office"] = str(db.execute(text(
            f"SELECT TOP 1 o.Names FROM [{database}].dbo.BANK_KB_MASTER m "
            f"LEFT JOIN [{database}].dbo.BANK_KB_AccOffice o "
            f"  ON o.OfficeID = m.OfficeID "
            f"WHERE m.RequestNM = :va ORDER BY m.MasterID DESC"),
            {"va": va}).scalar() or "").strip()
        if not out["branch"]:
            # 2차 경로 — 전표가 쓰는 그 매핑표 (seed_kb_branch_map)
            kb_code = str(db.execute(text(
                f"SELECT TOP 1 KB_Code "
                f"FROM [{database}].dbo.BANK_KB_REQUEST_MASTER "
                f"WHERE LTRIM(RequestNm) = :va ORDER BY SEQ DESC"),
                {"va": va}).scalar() or "").strip()
            if kb_code:
                out["branch"] = str(db.execute(text(
                    "SELECT TOP 1 branch_name FROM a10_kb_branch_map "
                    "WHERE kb_code = :c AND active = 'Y'"),
                    {"c": kb_code}).scalar() or "").strip()
    except Exception:
        # 곁가지다 — 여기서 막히더라도 '약식' 배지까지는 떠야 한다.
        logger.exception("약식 지사 조회 실패")
    finally:
        db.close()

    if len(_YAKSIK_CACHE) < _YAKSIK_CACHE_MAX:
        _YAKSIK_CACHE[va] = dict(out)
    return out


def _search_sync(jeokyo: str, amount: int, day: str,
                 unique_field: str = "") -> dict[str, Any]:
    """적요 한 줄 → 감정서 후보. 무엇을 얼마나 뒤졌는지도 함께 돌려준다."""
    kind = deposit_match._classify(jeokyo, amount)  # noqa: SLF001
    if kind:
        out = {"kind": kind[0], "note": kind[1], "tokens": tokens(jeokyo),
               "stages": [], "items": []}
        # 약식이면 감정서 대신 '어느 지사·어느 영업점' 을 돌려준다.
        if kind[0] == "약식평가":
            out["yaksik"] = _yaksik_sync(jeokyo)
        return out

    words = expand(jeokyo)
    # 의뢰문서번호로 쓸 숫자런 — **글자에 붙은 것은 뺀다** (2026-08-08).
    # '농협000546' 의 000546, '(주)득금26024' 의 26024 는 의뢰문서번호가 아니라
    # 상호에 붙은 코드다. 그런데 이 축은 _NUM_LABELS 라 걸리면 tier 0 으로
    # **단독 표시**되고, 걸리는 순간 뒤의 이름·금액 축이 닫힌다 — 오탐이 가장
    # 비싸게 먹히는 자리다.
    # 실측(정답지 758건): 이 축이 발화한 8건 중 정답은 2건(25%)뿐이었고,
    # 오탐 6건은 전부 글자에 붙은 숫자였다(농협000546·000069·000675·000029·
    # 000017·득금26024). 정답 2건은 전부 슬래시로 구분된 독립 칸이었다
    # ('동작신협//01174/창구', '…//01093/창구'). 붙은 것만 빼면 2/2 = 100% 다.
    glued = _glued_digits(jeokyo)
    digits = [w for w in words if w.isdigit() and len(w) >= 5]
    runs = [w for w in digits if w not in glued]        # 독립 칸 — 번호로 믿는다
    weak_runs = [w for w in digits if w in glued]       # 상호에 붙음 — 강등해 쓴다
    # 법인표기 단독 토막은 검색어에서 뺀다 — '주식회사' 하나가 1개월 창 59건을
    # 물어 사다리를 세운다(실측). 지점명 재분해는 합성 토막용이다.
    names = [w for w in words if not w.isdigit() and w not in _CORP_TOKENS]
    names = names + _branch_tokens(names)
    stages: list[dict] = []
    items: list[dict] = []

    def note(source: str, months: int, hits: int) -> None:
        stages.append({"source": _STAGE_LABEL.get(source, source),
                       "months": months, "hits": hits})

    # ⓪ 적요에 감정서번호가 박혀 있나 — DB 조회 1회, 입금의 35% 가 여기서 끝난다.
    compacts = deposit_match._compacts(jeokyo)  # noqa: SLF001
    if compacts:
        found = _number_sync(compacts)
        note("number", 0, len(found))
        items.extend(found)

    # ① 사이버브랜치가 이미 이어 둔 게 있나 — 있으면 그게 정답이다.
    if not items and unique_field:
        try:
            mapped = deposit_match._cyber_docid_sync(unique_field)  # noqa: SLF001
        except Exception:
            mapped = ""
        if mapped:
            found = _by_doc_ids_sync([mapped], unique_field,
                                     "사이버브랜치 매핑", "매핑표")
            note("cyber", 0, len(found))
            items.extend(found)

    # ①-b 숫자는 있는데 아무것도 못 찾았으면 — 자리바꿈 오타일 수 있다.
    if not items:
        found = _typo_sync(jeokyo, day)
        if found:
            note("typo", 0, len(found))
            items.extend(found)

    # ② 의뢰문서번호 — 걸리면 늘 1~3건이라 변별력이 가장 높다.
    if not items and runs:
        for months, found in _windows(_custdocid_sync, runs, day):
            note("custdocid", months, len(found))
            if found:
                items.extend(found)
                break

    # ②-c 창을 걷어낸 의뢰문서번호 **정확일치**. 창 있는 축이 빈손일 때만 —
    #     오래 묵은 은행 수수료(접수→입금 지연 중앙값 377일)가 여기서 걸린다.
    #     정확일치만 쓴다(LIKE 금지). 실측·안전성 논거는 위 함수 주석 참고.
    if not items and runs:
        found = _custdocid_exact_all_sync(runs)
        note("custdocid_all", 0, len(found))
        if found:
            items.extend(found)

    # ②-b 상호에 붙은 숫자('농협000546'·'(주)득금26024')로도 한 번 본다. 다만
    #     **번호로 믿지 않는다.** 이 축은 _NUM_LABELS 라 걸리면 tier 0 으로 단독
    #     표시되고 그 순간 뒤의 이름·금액 축이 닫히는데, 붙은 숫자는 대개 농협
    #     여신연동의 내부 코드지 의뢰문서번호가 아니다.
    #     실측(정답지 758건, 창 사다리 전체): 붙은 숫자로 걸린 13건 중 정답은
    #     1건(7.7%)뿐이고, 독립 칸으로 걸린 5건은 2건(40%)이다.
    #     그래서 후보로는 받되 라벨을 '의뢰문서번호(추정)' 로 낮춰 이름 갈래로
    #     보낸다 — 단독이면 tier 2 로 숨고, 금액·회계와 겹칠 때만 올라온다.
    #     이렇게 하면 '계선50018808/여신연동/농협001316/' 처럼 붙은 숫자가 정답을
    #     물어 온 건도 잃지 않는다(그 건은 금액·회계가 같이 붙어 근거 3개가 된다).
    if not items and weak_runs:
        for months, found in _windows(_custdocid_sync, weak_runs, day):
            if found:
                for item in found:
                    item["field_label"] = "의뢰문서번호(추정)"
                    item["weak"] = True
                note("custdocid_weak", months, len(found))
                items.extend(found)
                break

    # ③ 이름 — 창 1→3→6개월 확증-계속 사다리. 좁은 창의 히트가 돈(매출총액
    #    ±1,000원·미수잔액)으로 확증되면 멈추고, 아니면 다음 창도 두드리며 후보를
    #    누적한다. 예전엔 히트만 있으면 멈춰서 '고려산업(주)' 이 1개월 창의 엉뚱한
    #    6건에 막혀 74일 전 접수분에 못 갔다.
    strong_name_seen = False
    if not items and names:
        collected: list[dict] = []
        for months in _WINDOWS:
            found = _ledger_sync(names, day, months)
            strong = [f for f in found if not f["weak"]]
            note("name", months, len(strong))
            if strong:
                collected.extend(found)
                strong_name_seen = True
                if not amount or _confirmed({f["doc_id"] for f in strong}, amount):
                    break
        if collected:
            items.extend(collected)

    # ③-a 기본 축이 비었으면 — 고객측 나머지 컬럼 전부를 최대 창 한 번으로.
    if not items and names:
        found = _ledger_sync(names, day, _WINDOWS[-1], cols=_NAME_COLS_WIDE)
        strong = [f for f in found if not f["weak"]]
        note("wide", _WINDOWS[-1], len(strong))
        if strong:
            items.extend(found)
            strong_name_seen = True

    # ③-b 의뢰문서번호 접두 — 'LH_서울' 이 CustDocID '서울매입약정지원2팀-…' 에
    #     걸리는 축. 강한 축(번호류 90+)이 이미 답을 냈으면 순위를 못 바꾸니 생략.
    strong_pre = any(_axis_score(i) >= 90 for i in items)
    if names and not strong_pre:
        found = _custdocid_prefix_sync(names, day, amount)
        if found:
            note("cd_prefix", _WINDOWS[-1], len(found))
            items.extend(found)

    # ③-c 세금계산서 청구처 — **이름 축이 원장에서 못 찾았을 때** 부른다.
    #     이 축이 존재하는 이유가 '입금자 이름이 원장 어디에도 없음'(실패의 31.4%)
    #     이므로 원장 이름 축 **뒤**가 제자리다. 앞에 뒀다가 실측으로 되돌렸다 —
    #     발화 284건에서 40건을 A/B 하니 얻음 0·잃음 1 이었다(이름 축이 이미
    #     풀던 건을 가로챘다). 격리 정밀도 99.66% 는 축의 성적이지 배치의 근거가
    #     아니다. **다시 앞으로 옮기지 말 것.**
    if not items and names:
        found = _tax_bill_sync(names, day, amount)
        note("tax_bill", 0, len(found))
        if found:
            items.extend(found)

    # ④ 금액 — 이름으로 영원히 못 잡는 제3자 입금이 17.5% 인데, 그런 건은 돈으로만
    #    이어진다. 창 안에 같은 금액이 하나뿐이면 그게 답이고(실측 194건 100%),
    #    여럿이면 이름 축을 확증하는 가산점이다.
    if amount and not strong_pre:
        with ThreadPoolExecutor(max_workers=2) as pool:
            amount_job = pool.submit(_amount_sync, amount, day)
            balance_job = pool.submit(_balance_sync, amount, day)
            by_amount, by_balance = amount_job.result(), balance_job.result()
        note("amount", _AMOUNT_MAX, len(by_amount))
        items.extend(by_amount)
        if by_balance:
            note("balance", _AMOUNT_MAX, len(by_balance))
            items.extend(by_balance)

    # 여기서부터는 '돈으로 확증된 후보가 있으면' 폴백 축을 잠근다 — 폴백이
    # 확증된 정답 위로 올라타 1순위를 뺏는 훼손(실측 7~8건)을 막는 게이트다.
    money_locked = (_confirmed({i["doc_id"] for i in items}, amount)
                    if items else False)

    # ④-a 3글자 인명 앞 2글자 접두 — '장재훈' 입금, 원장은 '장재준'(가족 대납).
    if names and not strong_name_seen and not money_locked:
        found = _person_prefix_sync(names, day)
        if found:
            note("person2", _WINDOWS[-1], len(found))
            items.extend(found)

    # ④-b 여기까지도 믿을 만한 후보가 없으면 — 표기 차이일 수 있다. Gemini 에게
    #     변형을 받아 최대 창으로 한 번 더 두드린다 (실패의 15%가 표기 차이).
    #     금액 축 **뒤**에 두는 이유: 금액이 유일하게 맞으면 그게 답이라(실측 100%)
    #     2초짜리 Gemini 호출이 낭비다.
    if (names and not money_locked
            and not any(_axis_score(i) >= 55 for i in items)):
        variants = _gemini_variants_sync(jeokyo, [n for n in names if not is_stop(n)])
        if variants:
            found = _ledger_sync(variants, day, _WINDOWS[-1])
            note("gemini", _WINDOWS[-1], len(found))
            for item in found:
                item["word"] = item["word"] + " (표기 변형)"
            items.extend(found)

    # ⑤ 비고 — 이름 축이 강한 히트를 못 냈으면 연다. '후보 0건'으로 좁혀 두면
    #    금액 후보 몇 개가 문을 막아, Bigo 에만 적힌 정답이 영영 안 나온다(실측).
    if names and not strong_name_seen:
        found = _bigo_sync([n for n in names if not is_stop(n)], day, _WINDOWS[-1])
        note("bigo", _WINDOWS[-1], len(found))
        items.extend(found)

    # ⑥ 원문 — **항상 연다** (2026-08-08).
    #    원래는 '이름 축 강한 히트가 없고 축점수 85+ 후보도 없을 때'만 열었다. 그런데
    #    원장 이름이 **오답 하나**를 물어도 strong_name_seen 이 서서 원문이 통째로
    #    닫혔다. 실측: 실패 33건 중 9건은 정답이 원문에 있었고, 그중 5건은 원장 이름
    #    축이 먼저 걸려 원문이 아예 안 돌았다('광주중앙새마을금고' 는 원장에서 56건이
    #    걸렸는데 정답이 그 안에 없고, 원문에서는 1건으로 정확히 좁혀진다).
    #
    #    **표시 규칙은 손대지 않는다.** '원문 본문' 은 _NAME_LABELS 라 단독이면 신호가
    #    '이름' 하나뿐 → _tier 2 → _keep_worth_showing 이 계속 숨긴다. 금액·회계 신호와
    #    겹쳐 근거 2개가 될 때만 tier 0 으로 올라온다. 즉 이 변경은 **교차 근거를
    #    만들어 줄 뿐 단독 후보를 새로 노출하지 않는다** — 오탐이 늘지 않는 구조다.
    #    원문 단독 표시는 따로 재봤고 기각했다: 히트 상한·섹션 제한을 어떻게 걸어도
    #    최고 88.5%(69/78)라 합격선(90%)에 못 미친다.
    fts_words = _fts_words(names)
    if fts_words:
        months = _WINDOWS[-1]
        try:
            raw, ladder = _fts_sync(fts_words, day, months)
        except Exception:
            logger.exception("[deposit-search] 원문 조회 실패")
            raw, ladder = [], []
        note("fts", months, len(raw))
        # 창 안에서 전패했고 다른 답도 없으면 — 창 무제한으로 한 번 더
        # (60히트 이하의 변별력 있는 말만이라 안전하다).
        if (not raw and not money_locked
                and not any(_axis_score(i) >= 55 for i in items)):
            try:
                raw = _fts_unwindowed(ladder)
            except Exception:
                raw = []
            note("fts_uw", 99, len(raw))
        if raw:
            by_word: dict[str, tuple[str, str]] = {}
            for hit in raw:
                by_word.setdefault(hit["doc_id"],
                                   (hit["word"], hit.get("section") or ""))
            found = _by_doc_ids_sync(list(by_word), "", "원문 본문", "원문")
            for item in found:
                word, section = by_word.get(item["doc_id"], ("", ""))
                item["word"] = word
                item["section"] = section
                item["months"] = months
            items.extend(found)

    # ⑦ 전기간 이름 — 창 밖 실패('(주)두원아이텍코리아' 733일)용 마지막 그물.
    #    모든 축이 빈손이고 돈 확증도 없을 때만 전량 스캔 1회(6.6~9초 실측).
    if (names and not money_locked
            and not any(_axis_score(i) >= 55 for i in items)):
        found = _unlimited_sync(names, day) or _unlimited_prefix4(names, day)
        if found:
            note("unlimited", 99, len(found))
            items.extend(found)

    # ⑧ 전표 발견 (2026-08-08). 지금까지 전표는 **표시**에만 썼다 — _enrich_sync 가
    #    이미 후보에 든 건에 voucher=True 를 붙일 뿐이라, 전표가 가리키는 감정서가
    #    어느 축에도 안 걸리면 그 정보가 통째로 버려졌다.
    #
    #    회계가 이미 판단해 태그해 둔 값이라 근거로서 강하다. 실측(정답지 758건):
    #    전표가 감정서를 **하나만** 가리킨 324건에서 정답이 318건 = 98.1%.
    #    여럿을 가리킬 때(383건)는 '어느 것'인지 말해 주지 못하므로 넣지 않는다 —
    #    금액 축과 같은 규칙이다.
    #
    #    순환에 주의해야 한다. 정답지는 재무팀이 이미 처리한 입금이라 전표가 그
    #    처리의 산물일 수 있다. 실제로 발화율이 정답지 93.3% vs 미부착 29.8% 로
    #    크게 다르다. 그래도 미부착 833건 중 103건(12.4%)이 1건으로 확정되고,
    #    그 전표는 입금 처리와 무관하게 회계가 먼저 끊어 둔 것이다.
    #
    #    비용: 미부착 120건 실측 평균 0.06초·최대 0.18초. _enrich_sync 가 이미 같은
    #    조회를 하므로 결과를 물려받아 **추가 조회는 하지 않는다**.
    #    **마지막 그물로만 쓴다.** 전표가 가리키는 감정서를 무조건 넣으면, 이미
    #    답을 맞히고 있던 조회를 뒤엎는다 — 실측: '신영부동산신탁주식회/인터넷입금이체/'
    #    는 매출총액 일치로 01-2602-4-0054(정답)를 1순위로 내고 있었는데, 같은 날
    #    같은 금액 전표가 가리킨 01-2603-4-0084 가 '금액+회계' 두 근거를 얻어
    #    그 위로 올라탔다. 전표는 하루치 입금을 묶은 장부라 같은 금액이 겹치면
    #    엉뚱한 줄을 짚는다. 그래서 **믿을 만한 후보가 이미 있으면 넣지 않는다.**
    voucher_docs = _voucher_docs_cached(amount, day)
    already_sure = any(_tier_precheck(i) for i in items)
    if len(set(voucher_docs)) == 1 and not already_sure:
        only = next(iter(set(voucher_docs)))
        if only not in {i["doc_id"] for i in items}:
            found = _by_doc_ids_sync([only], "", "회계 전표", "전표")
            if found:
                note("voucher", 0, len(found))
                items.extend(found)

    # ⑨ 표기 교차 (2026-08-08). **새 조회를 하지 않는다** — 이미 뽑아 둔 후보에
    #     '적요 이름과 표기만 다른 같은 말' 이 있으면 이름 신호를 하나 더 붙인다.
    #     그러면 금액 단독(tier 1, 창 안 유일할 때만 보임)이던 후보가 금액+이름
    #     (tier 0)이 되어 확신 후보로 올라온다.
    #
    #     후보 자체를 새로 만들지 않으므로 **오탐 표면이 넓어지지 않는다** — 이미
    #     금액이 맞아 후보에 들어온 건 중에서 근거를 하나 더 찾아 주는 것뿐이다.
    #     걸러내는 조건은 _canon(법인표기·공백·기호 제거 후 대문자)과 4글자 하한.
    #     3글자 이하를 허용하면 흔한 상호 토막이 남의 감정서에 우연히 박힌다.
    canon_words = {c for c in (_canon(n) for n in names) if len(c) >= _CANON_MIN}
    if canon_words:
        echoed = 0
        for item in items:
            if "이름" in set(_signals(item)):
                continue        # 이미 이름 근거가 있으면 더할 게 없다
            hit = _name_echo(item, canon_words)
            if not hit:
                continue
            item["_labels"] = ({item.get("field_label") or ""} | {"이름 표기"})
            item["word"] = (item.get("word") or "") + f" · 표기 {hit}"
            echoed += 1
        if echoed:
            note("canon", 0, echoed)

    # ⑨-b '<입금자>감정여비'처럼 송금 용도를 상호 뒤에 붙인 건. 용도 꼬리를
    # 뗀 값이 Debtor와 정확히 같고 본사 감정서가 하나뿐일 때만 확정 근거로 쓴다.
    if _exact_debtor_mark(items, jeokyo):
        note("exact_debtor", 0, 1)

    # ⑩ 본인 의뢰 (2026-08-08). 개인이 자기 감정을 스스로 의뢰하고 스스로 낸 돈.
    #     이름 하나뿐이라 지금까지 tier 2 로 숨어 있었는데, **본사 + 의뢰인칸 +
    #     창 안 유일** 세 조건을 다 채우면 실측 192/192(100%) 라 확신 후보로 올린다.
    #     ⑨와 마찬가지로 새 조회를 하지 않는다.
    if _self_client_mark(items, jeokyo):
        note("self_client", 0, 1)

    _enrich_sync(items, amount, day, voucher_docs)
    return {"kind": "", "note": "", "tokens": tokens(jeokyo),
            "stages": stages, "items": _keep_worth_showing(_rank(items))[:20]}


def _keep_worth_showing(ranked: list[dict]) -> list[dict]:
    """근거가 하나뿐이라 못 믿을 후보는 아예 안 보여준다 (2026-08-06 요청).

    실측 정밀도: 근거 2개 이상 98% · 번호 단독 91% · **금액 단독 44%** ·
    **이름 단독 0%(0/38)**. 다만 금액 단독이라도 창 안에 그 금액이 하나뿐이면
    실측 100% 라 남긴다.

    '이가윤/대체//' 88,000원이 이 규칙이 필요한 이유다 — 88,000원은 흔한 정액
    수수료라 6개월 창에 40건이 걸리는데, 그중 전표·당일완납까지 겹친 한 건만
    답이고 나머지 39건은 눈만 어지럽힌다.

    금액 단독은 **본사 건일 때만** 남긴다 (2026-08-13). 이 통장은 사실상 본사
    것이라 정답의 99.8% 가 '01-' 인데(_OTHER_OFFICE_PENALTY 주석), 지사 건이 금액만
    우연히 맞아 혼자 살아남으면 감점이 아무 소용이 없다 — 경쟁자가 없어 그대로
    1순위가 된다. 실측: 1순위가 지사로 뜬 80건 중 맞은 건 **3건(3.8%)** 뿐이고,
    그 3건은 번호나 갈래 2개로 걸린 것이라 이 규칙에 안 걸린다.

    정답지 전수(최근1년 3,416건) A/B:
      걷어낸 후보 77개(74건) 중 **정답이었던 것 0개**
      1순위 얻음 +1 · 잃음 0 · 후보 잃음 0
    걷어낸 뒤 후보가 0이 되는 건이 22건 있는데, 원래 **틀린 것만 보이던 자리**다.
    틀린 번호를 내미는 것보다 '못 찾았습니다'가 낫다 — 이 화면의 일은 번호 하나를
    옮겨 적는 것이고, 잘못 옮겨 적는 게 가장 비싼 실수다.

    같이 잰 안 하나는 **기각**했다: 이름 단독(tier 2)도 후보로 함께 보여주기.
    1순위는 그대로였지만 후보를 더한 1,595건 중 정답을 더한 건 8건뿐이고
    **1,587건(99%)은 틀린 후보만 붙었다.** 8건 얻자고 잡음을 1,587건에 뿌리는 셈이라
    이 화면에는 맞지 않는다. 되살리려면 그 비율부터 뒤집어야 한다.
    """
    keep = []
    for item in ranked:
        doc_id = str(item.get("doc_id") or "")
        if doc_id.upper().startswith("OB"):
            continue          # 구번호는 어느 경로로 새어 들어와도 보여주지 않는다
        tier = _tier(item)
        if tier == 0:                      # 번호가 있거나 갈래 2개 이상
            keep.append(item)
        elif (tier == 1 and item.get("amount_unique")
                and doc_id.startswith(f"{_HOME_OFFICE}-")):
            keep.append(item)              # 창 안 유일한 금액 — 단, 본사 건만
    return keep


async def find(jeokyo: str, amount: int = 0, day: str = "",
               unique_field: str = "") -> dict[str, Any]:
    """적요 → 감정서 후보 (읽기 전용)."""
    return await asyncio.to_thread(
        _search_sync, jeokyo, int(amount or 0), day or "", unique_field or "")
