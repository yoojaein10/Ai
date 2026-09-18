"""은행 입금 적요 → 감정서 후보 찾기.

재무팀이 지금 하는 일을 그대로 자동화한다: 통장 적요에 적힌 말들을 하나씩
감정서 원장(apw_masterex)에서 찾아 맞는 감정서번호를 고르는 일이다.
**우리는 찾아서 보여주기만 한다. 통장에 쓰지 않는다.**

쓰지 않는 이유가 있다 (2026-08-05 실측):
CB2_ACCT_HIS.Memo 는 자유 메모가 아니라 남의 시스템의 입력이다. Branch DB 의
`SP_IW_I_MAECULDOCID` 가 `WHERE memo like '01%'` 로 읽어
`APW_IW_I_MAECULDATA` 를 호출하고, 그게 매출배분(Apw_Mae_GaPrice)에 직접 쓴다.
그 잡은 지금 꺼져 있을 뿐 지워지지 않았고, 테이블에는 수정 이력 컬럼이 없어
되돌릴 수도 없다. 게다가 우리는 그 DB 에 sa 로 붙어 있다.
그래서 이 모듈은 **읽기 전용**이다.

먼저 **감정서번호가 없는 유형을 걸러낸다**. 최근 2주 미처리 227건을 보면
약식평가 160 · 자사이체 12 · 카드 10 · 지사 실적회비 6 으로 188건(83%)이 여기 속한다.
이걸 안 거르면 '못 찾음' 으로 쌓여 재무팀이 헛되이 뒤진다.

남은 39건이 진짜 대상이고, 다섯 근거로 찾는다 (실측: 확신 82% · 못 찾음 15%).
- 사이버브랜치 매핑표 (Branch DB CyberToDocid — 기록이라 가장 강하다)
- 적요에 박힌 감정서번호 (발화 32%, 그 안에서 99.8% 정확)
- 회계 전표 경유 (같은 날 같은 금액으로 보통예금에 꽂힌 전표의 관리번호)
- 미수 잔액 일치 (분납·부분입금 — 전표가 없어도 쓸 수 있는 축)
- 청구금액 일치 · 적요의 이름 ↔ 원장 의뢰인·채무자

전표 경유가 가장 크게 기여한다. 적요의 이름이 원장과 아예 다른 경우(입금자와
의뢰인이 다른 기관)가 실패의 67%였는데, 그걸 잇는 끈이다. 다만 전표는 입금
뒤에 만들어져 당일 입금에는 침묵하므로, 미수 잔액·청구금액·적요 파싱이 그날의
답을 맡는다.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from typing import Any

from sqlalchemy import text

from app.config import get_settings
from app.database import get_session_factory

# 감정서번호 압축형(연월4 + 구분1 + 일련4)을 적요에서 찾는다.
_FULL_RE = re.compile(r"(\d{2})-(\d{4})-([0-9A-Z])-(\d{4})")
_HYPHEN_RE = re.compile(r"(?<![0-9A-Z])(\d{4})[-\s]([0-9A-Z])[-\s](\d{4})(?![0-9A-Z])")
_LONG_RE = re.compile(r"(?<![0-9A-Z])(\d{2})(\d{4})([0-9A-Z])(\d{4})(?![0-9A-Z])")
_COMPACT_RE = re.compile(r"(?<![0-9A-Z])(\d{4})([0-9A-Z])(\d{4})(?![0-9A-Z])")

# 감정서번호가 아닌 숫자(여신 4005…·가상계좌 3021…·카드 7458…)를 걸러내는 관문.
# 실측: 2026년 적요의 9자리 토큰 3,435개 중 이 관문을 통과한 575개는 전부 원장에 실존했다.
_KINDS = set('REDACTED_CONFIGURE_LOCALLY78AB')


def _valid(yy: str, mm: str, kind: str) -> bool:
    year = dt.date.today().year % 100
    return "15" <= yy <= f"{year:02d}" and "01" <= mm <= "12" and kind in _KINDS


def _compacts(jeokyo: str) -> list[str]:
    """적요에서 '연월+구분+일련' 9자리 후보를 뽑는다 (확신 높은 순)."""
    text_up = (jeokyo or "").upper()
    out: list[str] = []

    def add(yy: str, mm: str, kind: str, seq: str) -> None:
        if _valid(yy, mm, kind):
            value = yy + mm + kind + seq
            if value not in out:
                out.append(value)

    for m in _FULL_RE.finditer(text_up):          # 01-2607-3-2241
        add(m.group(2)[:2], m.group(2)[2:], m.group(3), m.group(4))
    for m in _HYPHEN_RE.finditer(text_up):        # 2607-3-2241
        add(m.group(1)[:2], m.group(1)[2:], m.group(2), m.group(3))
    for m in _LONG_RE.finditer(text_up):          # 012607 3 2241
        add(m.group(2)[:2], m.group(2)[2:], m.group(3), m.group(4))
    for m in _COMPACT_RE.finditer(text_up):       # 260732241
        add(m.group(1)[:2], m.group(1)[2:], m.group(2), m.group(3))
    return out


# 적요에서 이름으로 볼 수 없는 말 — 거래유형·은행명·전산어.
_NOISE = re.compile(
    r"타행환|타행이체|타행|대체입금|대체송금|대체|인터넷입금이체|인터넷출금이체|인터넷|"
    r"전자금융|모바일|창구|여신연동|여신|수수료|감정평가비|비대면|송금|입금|출금|이체|"
    r"뱅킹|은행|지점|센터|금융센터|MB|WON|BC|KB|NH|"
    # 법인 표기 — '주식회사 지엔스인터내' 에서 '주식회사' 를 이름으로 잡으면
    # 온 세상 법인이 후보로 딸려 온다. 뒤에 붙는 실제 상호만 남긴다.
    r"주식회사|유한회사|합자회사|재단법인|사단법인|의료법인|\(주\)|㈜"
)


_CORP_FORM = re.compile(r"주식회사|유한회사|합자회사|재단법인|사단법인|의료법인|\(주\)|㈜")


def _read(jeokyo: str) -> tuple[list[str], list[str]]:
    """적요를 이름과 '뺀 말'로 가른다. 왜 뺐는지 답변에서 밝히려고 둘 다 돌려준다."""
    raw = jeokyo or ""
    names: list[str] = []
    dropped: list[str] = []
    # 괄호 안의 짧은 말은 송금 은행 약칭이다 — '(하나)', '(산림)', '(국민)'.
    # 아주 버리면 의뢰인이 실제로 그 은행인 건을 놓치고(실측 -2%p), 그대로 두면
    # 'KEB하나은행' 같은 무관한 건이 진짜 이름을 제친다. 그래서 뒤로 미뤄 약하게 쓴다.
    weak: list[str] = []
    for inner in re.findall(r"\(([^)]{1,4})\)", raw):
        token = inner.strip()
        if token and len(token) >= 2 and token not in weak:
            weak.append(token)
    stripped = re.sub(r"\([^)]{1,4}\)", " ", raw)

    for piece in re.split(r"[/\s,()]+", stripped):
        token = piece.strip()
        if not token:
            continue
        if token.isdigit():
            if token not in dropped:
                dropped.append(token)
            continue
        token = re.sub(r"[0-9]", "", token).strip()
        # 법인 표기는 앞에도 뒤에도 붙는다 — '정우에이치앤디주식회사' → '정우에이치앤디'.
        trimmed = _CORP_FORM.sub("", token).strip()
        if len(trimmed) >= 2:
            token = trimmed
        if len(token) < 2:
            if piece.strip() and piece.strip() not in dropped:
                dropped.append(piece.strip())
            continue
        if _NOISE.fullmatch(token) or (_NOISE.search(token) and len(token) <= 4):
            if token not in dropped:
                dropped.append(token)
            continue
        if token not in names:
            names.append(token)
    # 번호로 이미 쓴 숫자는 '뺀 말'이 아니다 — 같은 값을 양쪽에 적으면 모순으로 읽힌다.
    used = {c for c in _compacts(raw)}
    dropped = [d for d in dropped if not any(c in d.replace("-", "") for c in used)]
    # 진짜 이름을 먼저, 은행 약칭은 뒤에 — 순위는 이 순서를 따라간다.
    return (names + [w for w in weak if w not in names])[:4], dropped


def _names(jeokyo: str) -> list[str]:
    """적요에서 사람·상호로 볼 만한 말만 남긴다 (재무팀이 눈으로 하는 그 일)."""
    return _read(jeokyo)[0]


# 감정서번호가 아예 없는 입금 유형. 재무팀이 아무리 뒤져도 못 찾는 게 당연한 것들이라
# '못 찾았습니다' 대신 무엇인지 알려준다 (2026-08-05 실측).
_VA_RE = re.compile(r"(?<!\d)(400\d{6})(?!\d)")       # 약식평가 가상계좌
_CARD_RE = re.compile(r"하나카드|BC-|비씨카드|신한카드|국민카드|삼성카드|카드사")
# 자사 계좌 간 이체 — **이름칸이 우리 회사명(+지사명) 자체일 때만**이다 (2026-08-08).
# 예전에는 '대화감정' 이 어디든 있으면 자사이체로 봤는데, 그러면 남이 낸 돈에 우리
# 이름이 업무 설명으로 붙은 건까지 '자사이체' 로 덮어 재무팀이 아예 안 보게 된다.
# 실측(정답지 14,790건): 6건이 그렇게 가려져 있었다 —
#   '대화감정평가법인 신동아건설/대체/…' → 01-2406-3-2511 (신동아건설이 낸 돈)
#   '주식회사으뜸디앤씨 대화감정/대체/…' → 01-2406-3-2429
#   '대화감정평가수수료//SC2030/타행-E' → 01-2506-4-0190 ('수수료' 는 업무 설명)
#   '금사리(대화감정평가/우체국/…'      → 01-2407-1-0093
# 이름칸 전체 일치로 좁히면 이 4건이 살아나고, 자사이체 분류는 3년치에서 8건만 준다.
# 남는 2건('㈜대화감정평가법인/인터넷입금이체/' 6,839,800원, '(주)대화감정평가법인/
# 대체/서초/' 24,900원)은 적요가 자사이체와 글자까지 똑같아 문자로는 못 가른다.
#
# 은행이 이름을 14자에서 자르므로 '대화감정평가법인' 의 어느 지점에서 잘려도 받는다.
# 전각 괄호 '（주）' 도 실제로 온다(3년치 28건).
_SELF_RE = re.compile(
    r"^(?:[(（]주[)）]|㈜|주식회사)?\s*"
    r"대화(?:감(?:정(?:평(?:가(?:법(?:인)?)?)?)?)?)?"
    r"\s*$")
# 지사가 보내는 업무실적비·회비 — 감정서 단위가 아니라 지사 단위 정산이다.
# 실측(2026): 12건 전부 감정서번호가 아니라 지사명·'업무실적비'·'기타예수금' 이 적혔다.
_FEE_RE = re.compile(r"실적비|실적회비|업무실적|분기\s*회비|회비")
# 2026-08-07 추가. 미부착 입금 3,307건을 훑어 '아무리 뒤져도 감정서가 없는 돈'을
# 더 골라냈다. 여기 안 걸리면 화면이 '못 찾았습니다' 라고만 해서, 재무팀이
# 있지도 않은 감정서를 계속 뒤진다. 무엇인지 알려주는 게 답이 없다는 것보다 낫다.
_INTEREST_RE = re.compile(r"결산이자|이자세금|예금이자|이자지급")          # 29건
_BRANCH_SETTLE_RE = re.compile(                                     # 9건
    r"^대화(경기|충남|호남|강원|부산|대구|북부|동부|충청|제주|경남|전북|전남)")
# '세무서' 만으로 거르면 안 된다 — 세무서가 감정평가를 의뢰한 정상 건을 가로챈다
# (실측 7건: 구로세무서 01-2504-4-0135, 반포세무서 01-2307-4-0333 …).
# 환급이라고 못 박은 말이 있을 때만 거른다.
_REFUND_RE = re.compile(r"국고환급|국세환급|훈련비|고용부|고용노동")           # 4건

# ── 2026-08-08 확장. 후보 0건 164건을 훑어 '감정서가 없는 돈' 을 더 골라냈다.
#    전부 정답지 전수(2023+ 통장 71,111건 중 Memo 에 감정서번호가 박힌 14,790건)로
#    **가로채는 정상 건 0** 을 확인하고 넣었다. 넓히려는 유혹은 실측이 부정한다 —
#    아래 주석의 '넓히면 안 되는 이유' 를 지우지 마라.

# 지사 정산 — **적요 전체가 아니라 이름칸(첫 '/' 앞)만** 본다.
# 2·3번째 칸은 은행·지점명이라 '//전북/잠실'(전북은행) · 'PC대구은행/대구0310017' ·
# '수협경인지역금융본부' · '보관금/동부법/'(동부지방법원) 같은 정답지 수십 건이
# 지사명 토큰을 갖고 있다. 적요 전체를 보면 그게 다 오탐이 된다.
_OFFICE = (r"(?:경남중앙|대구경북|부산경남|대전세종|경기서부|경기북부|경기|경인|북부|강원"
           r"|충청|충남|호남|제주|동부|전북|전남|울산|경북|대구|부산|경남)")   # 긴 것 먼저
_OHEAD = rf"(?:대화[ _-]?)?(?:감정[ _-]?)?{_OFFICE}(?:지사)?"
_SETTLE = (r"(?:급여|성과상여|실적비|실적회비|업무실적|협회비|임대료|수익배분|퇴직금"
           r"|\d{1,2}(?:/\d)?\s*분기)")
_SEP = r"[ _\-()]*"
_MON = r"(?:\d{1,2}\s*월)?"
# '충청급여' · '호남4분기' · '울산지사3/4분기'
_BR_SETTLE_RE = re.compile(rf"^{_OHEAD}{_SEP}{_MON}{_SEP}{_SETTLE}")
# '8월동부급여' — 월이 지사명 앞에 온 형태
_BR_MONTH_RE = re.compile(rf"^\d{{1,2}}\s*월{_SEP}{_OHEAD}{_SEP}{_SETTLE}")
# '대화경기' · '북부_대화' — 대화와 지사명이 앞뒤로 붙는다(양방향).
# 뒤의 (?:{_SEP}(?:{_SETTLE}|$)) 를 빼면 '대화+지사명 뒤에 사람 이름' 이 딸려 온다.
# 회사명이 통째로 앞에 오는 '대화감정평가법인경기' 도 여기서 받는다 — 자사이체가
# 아니라 **지사 정산**이 맞다(지사가 본사로 보낸 돈이다).
_BR_DAEHWA_RE = re.compile(
    rf"^(?:[(（]주[)）]|㈜)?대화[ _-]?(?:감(?:정(?:평(?:가(?:법(?:인)?)?)?)?)?[ _-]?)?"
    rf"{_OFFICE}(?:지사?)?(?:{_SEP}(?:{_SETTLE}|$))"
    rf"|^{_OFFICE}[ _-]?대화(?:{_SEP}(?:{_SETTLE}|$))")
# '경기서부' · '경남중앙지사' 단독.
# **법인 접두 (주)/㈜ 를 절대 넣지 마라** — 넣으면 '(주)경인/전자금융/'(정답
# 01-2304-4-0180) 을 가로챈다. **지사명+숫자도 안 된다** — '동부103848' 처럼
# 관리번호가 붙은 정답지가 4건 있다. 끝의 (?:\d{1,2})? 는 '울산지사3/4분기' 가
# '/' 로 잘려 '울산지사3' 이 되는 경우만 흡수한다.
_BR_ALONE_RE = re.compile(rf"^{_OHEAD}(?:\d{{1,2}})?$")

# 타 감정평가법인·감정원과 주고받는 정산 — 보상·수용 공동평가의 균등배분금이 대부분이다
# (원문 01-2601-1-0020 광명-서울 고속도로 사업에 대화·공감·경기동부·대교·가람·
# 대일감정원·가온이 평가기관으로 열거돼 있고, 3개 법인이 이틀 안에 1,663,750원씩 보냈다.
# 그 금액은 우리 원장 청구금액에 전 연도 0건이다).
# **'감정평가' 키워드로 넓히면 안 된다** — 자사 제외 485건 중 372건(76.7%)이 정상
# 감정서 건이다('담보물외부감정평가수수료(은행부담)' 처럼 은행이 쓰는 업무 설명).
# **'한국감정평가사협회' 도 넣으면 안 된다** — 협회가 실제 의뢰인인 감정서가 있다
# (01-2503-4-0071 청구 17,598,900원). 세무서 사고와 같은 구조다.
# 안전한 근본 이유: 타 법인이 우리에게 의뢰하면 그 돈은 적요에 상호가 아니라
# 관리번호로 들어온다('250440139/전자금융/'). 상호만 덜렁 적힌 적요는 정산 전용이다.
_PEER_FIRM_RE = re.compile(
    r"감정평가법인?(?=/|$)"
    r"|^(?:\(주\)|㈜|주식회사)\s*[가-힣A-Za-z0-9]{1,10}감정평가(?:법인?)?(?=/|$)"
    r"|감정원(?=본사|/|$)")

# 이자 — '이자' 부분일치는 정답지 5건을 가로챈다. 필드 단위로만 본다.
_INTEREST_MORE_RE = re.compile(r"이자원가|예탁금이자|정기예금이자|\(\s*이자\s*:")
_INTEREST_FIELD_RE = re.compile(
    r"(?:^|/)\s*(?:이자|예금이자|결산이자|예금결산이자|이자수익)\s*(?:/|$)")
_LOCAL_TAX_RE = re.compile(r"주민세|자동차세")
_MISC_FIN_RE = re.compile(r"캐시백|출자배당금|펀드지급")
# 보험 — **이름만으로는 절대 안 된다.** 보험사도 담보평가를 의뢰한다.
# 이름만 쓰면 정답지 11건을 가로채고, 그 최소 금액이 883,300원이라 30만원 상한이 가른다.
_INSURE_RE = re.compile(r"해상|화재|생명|손해보험|손보|보험")
_INSURE_MAX = 300_000
# 회사가 받는 월 주차장 임대수입. '주차장' 으로 넓히지 마라 — 주차장 부지 감정 의뢰가
# 적요에 올 수 있다(현재는 '마티즈' 14건이 '주차' 전량이라 측정상 같다).
_PARKING_RE = re.compile(r"마티즈")
# '협회' 나 '협회비' 로 넓히면 정답지 3건을 가로챈다. 이 문구 통째로만.
_ASSOC_SUPPORT_RE = re.compile(r"협회보험료지원")
# 기관 묶음정산 — 감정서 수백 건을 분기마다 한 번에 정산해 보낸다.
# 기관명 단독으로 거르면 위험해서(그 기관들은 감정을 대량 의뢰한다) 적요 형태까지 못 박는다.
# 기관이 여러 건을 한 번에 정산해 보내는 돈. 감정서가 **여럿**이라 한 건으로
# 못 좁힌다 — 재무팀도 이 건들은 사이버브랜치에 번호를 안 넣는다(2025+ 35건 중
# Memo 에 감정서번호가 박힌 건 0건).
#
# 전표를 타고 감정서 목록을 뽑아 보여주는 안을 실측으로 버렸다(2026-08-08):
# 전표가 문 감정서들의 청구액 합이 입금액과 맞는 건 25건 중 2건(8.0%)뿐이다.
# 전표는 하루치 회계 처리를 묶은 장부라 같은 날 다른 입금 건이 섞여 들어온다
# (예: 2025-01-15 입금 151,476,600원에 전표가 문 감정서는 1건·청구 326,700원).
# 목록으로 내면 그 자체가 오탐이다.
_BULK_SETTLE_RE = re.compile(
    r"한국주택금융공/전자금융|주택금융공사주/전자금융|주신보집중계좌"
    r"|주택도시보증공사/FBS입금")


def _payer(jeokyo: str) -> str:
    """적요의 이름칸 — 첫 '/' 앞. 지사 규칙은 여기에만 건다."""
    return (jeokyo or "").split("/")[0].strip()


def _classify(jeokyo: str, amount: int = 0) -> "tuple[str, str] | None":
    """감정서와 무관한 입금이면 (유형, 설명)을. 아니면 None.

    amount 는 보험 규칙에만 쓴다 — 보험사도 담보평가를 의뢰하므로 이름만으로
    거를 수 없고, 30만원 상한이 정산·환급과 수수료를 가른다(실측).
    """
    text_up = (jeokyo or "").upper()
    if _VA_RE.search(jeokyo or ""):
        return ("약식평가", "약식평가 수수료를 받는 가상계좌 입금입니다. "
                          "약식평가에는 감정서번호가 없습니다 — 2026년 이런 입금 2,111건 중 "
                          "감정서번호가 적힌 건은 0건입니다.")
    if _CARD_RE.search(text_up) or _CARD_RE.search(jeokyo or ""):
        return ("카드", "카드사와 주고받는 정산 건입니다. 감정서 한 건에 대응되지 않습니다 "
                      "(대개 여러 승인건을 묶은 금액이고, 출금인 경우가 많습니다).")
    if _SELF_RE.match(_payer(jeokyo)):
        return ("자사이체", "우리 회사 계좌끼리 옮긴 돈입니다. 감정서 수수료 입금이 아닙니다.")
    if _FEE_RE.search(jeokyo or ""):
        return ("지사 실적회비", "지사가 보내는 업무실적비·회비입니다. 감정서 한 건의 "
                              "수수료가 아니라 지사 단위 정산이라 감정서번호가 없습니다 "
                              "— Memo 에는 지사명이나 '업무실적비' 를 적습니다.")
    # 아래 셋은 위 규칙보다 **뒤에** 본다. '대화충남 업무실적비' 처럼 겹치는 적요는
    # 더 구체적인 쪽(실적회비)이 답이기 때문이다.
    raw = (jeokyo or "").strip()
    if _INTEREST_RE.search(raw):
        return ("예금이자", "통장에 붙은 예금이자입니다. 감정서 수수료 입금이 아닙니다.")
    if _BRANCH_SETTLE_RE.match(raw):
        return ("지사 정산", "지사가 본사로 보낸 정산금입니다. 감정서 한 건의 수수료가 "
                           "아니라 지사 단위로 묶인 돈이라 감정서번호가 없습니다.")
    if _REFUND_RE.search(raw):
        return ("환급금", "세무서·고용노동부에서 돌려받은 돈입니다(국고환급·훈련비 등). "
                        "감정서 수수료 입금이 아닙니다.")

    # ── 아래는 2026-08-08 확장. **_SELF_RE 뒤여야 한다** — 자사 적요 1,893건이
    #    _PEER_FIRM_RE 에 걸리고 그중 2건이 정답지다.
    payer = _payer(raw)
    # 우리 이름이 들어 있으면 타법인이 아니다 — '하나(주)대화감정평가법/전자금융/'
    # 처럼 은행명이 앞에 붙어 _SELF_RE 를 못 통과한 자사 건이 여기로 새면 안 된다.
    if "대화" not in payer and _PEER_FIRM_RE.search(raw):
        return ("타법인 정산", "다른 감정평가법인·감정원과 주고받는 정산금입니다 "
                             "(보상·수용 공동평가의 균등배분금이 대부분입니다). "
                             "감정서 한 건의 수수료가 아니라 사업 단위로 묶인 돈이라 "
                             "감정서번호가 없습니다.")
    if (_BR_SETTLE_RE.match(payer) or _BR_MONTH_RE.match(payer)
            or _BR_DAEHWA_RE.match(payer) or _BR_ALONE_RE.match(payer)):
        return ("지사 정산", "지사가 본사로 보낸 정산금입니다(급여·실적비·임대료·분기 정산 등). "
                           "감정서 한 건의 수수료가 아니라 지사 단위로 묶인 돈이라 "
                           "감정서번호가 없습니다.")
    if _INTEREST_MORE_RE.search(raw) or _INTEREST_FIELD_RE.search(raw):
        return ("예금이자", "통장에 붙은 예금이자입니다. 감정서 수수료 입금이 아닙니다.")
    if _LOCAL_TAX_RE.search(raw):
        return ("지방세 환급", "주민세·자동차세 관련 환급입니다. 감정서 수수료가 아닙니다.")
    if _MISC_FIN_RE.search(raw):
        return ("금융 잡수입", "캐시백·출자배당금·펀드지급 같은 금융 잡수입입니다. "
                            "감정서 수수료가 아닙니다.")
    if _PARKING_RE.search(raw):
        return ("주차장 수입", "회사가 받는 주차장 임대수입입니다. 감정서 수수료가 아닙니다.")
    if _ASSOC_SUPPORT_RE.search(raw):
        return ("협회 지원금", "협회에서 받은 보험료 지원금입니다. 감정서 수수료가 아닙니다.")
    if _BULK_SETTLE_RE.search(raw):
        return ("기관 묶음정산", "한국주택금융공사·주택도시보증공사(HUG)·주택신용보증기금이 "
                              "감정서 수백 건을 한 번에 정산해 보낸 입금입니다. "
                              "감정서 한 건에 대응되지 않습니다.")
    if amount and 0 < amount <= _INSURE_MAX and _INSURE_RE.search(raw):
        return ("보험 정산", "보험료 정산·환급으로 보입니다(30만원 이하). "
                           "보험사도 담보평가를 의뢰하므로 금액이 크면 이 분류를 하지 않습니다.")
    return None


def _va_voucher_sync(va_no: str) -> list[dict[str, Any]]:
    """약식평가 가상계좌 번호로 전표를 찾는다 — 관리번호가 그 번호 그대로다."""
    db = get_session_factory()()
    try:
        rows = db.execute(text(
            "SELECT TOP 5 CONVERT(varchar(10), voucher_date, 120) AS d, voucher_no, "
            "amount, remark, partner_name FROM a10_voucher_cache "
            "WHERE management_no = :va ORDER BY voucher_date DESC"), {"va": va_no}).mappings().all()
        return [dict(r) for r in rows]
    finally:
        db.close()


def _voucher_docs_sync(amount: int, day: str) -> list[str]:
    """같은 날 같은 금액으로 보통예금에 꽂힌 전표를 찾아, 그 전표에 달린 감정서번호를 준다.

    적요의 이름이 원장과 아예 다른 경우(입금자와 의뢰인이 다른 기관)를 잇는 유일한
    끈이다 — 실패 원인의 67%가 그 유형이었다. 회계가 이미 판단해 태그해 둔 값이라
    정확하지만, 전표는 입금 뒤에 만들어지므로 당일 입금에는 침묵한다.
    """
    db = get_session_factory()()
    try:
        rows = db.execute(text(
            "WITH b AS (SELECT DISTINCT voucher_date, voucher_no FROM a10_voucher_cache "
            "  WHERE account_code = '1030000' AND amount = :amt "
            "    AND voucher_date BETWEEN DATEADD(day,-3,CONVERT(date,:d)) "
            "                         AND DATEADD(day,3,CONVERT(date,:d))) "
            "SELECT DISTINCT v.management_no AS doc FROM a10_voucher_cache v "
            "JOIN b ON b.voucher_date = v.voucher_date AND b.voucher_no = v.voucher_no "
            "WHERE v.management_no LIKE '__-____-_-____'"),
            {"amt": amount, "d": day}).scalars().all()
        return [str(r).strip() for r in rows if r]
    finally:
        db.close()


_UNIQUE_RE = re.compile(r"(?<!\d)(\d{20,28})(?!\d)")


def _branch_conn():
    """통장 DB(Branch) 읽기 전용 연결. 쓰기는 절대 하지 않는다."""
    import pyodbc  # noqa: PLC0415

    settings = get_settings()
    return pyodbc.connect(
        'DRIVER={%s};SERVER=%s;DATABASE=%s;UID=%s;PWD=REDACTED_CONFIGURE_LOCALLY;Encrypt=%s;'
        "TrustServerCertificate=%s;" % (
            settings.mssql_driver, settings.card_source_server, settings.card_source_db,
            settings.card_source_user, settings.card_source_password.get_secret_value(),
            settings.mssql_encrypt, settings.mssql_trust_server_certificate),
        timeout=10)


def _lookup_deposit_sync(jeokyo: str, day: str = "") -> dict[str, Any]:
    """적요만 받았을 때 통장에서 그 입금 행을 찾아 금액·거래일을 가져온다.

    금액이 있고 없고가 정확도를 가른다 (실측: 1순위 82% vs 43%). 사용자가 적요만
    붙여넣어도 우리가 직접 찾아 채우면 표 전체를 복사할 필요가 없다.
    **SELECT 만 한다** — 이 테이블에 쓰면 매출이 계상된다(모듈 상단 참고).
    """
    try:
        with _branch_conn() as cn:
            cur = cn.cursor()
            sql = ("SELECT TOP 1 TX_AMT, ACCT_TXDAY, UNIQUE_FIELD, Memo FROM dbo.CB2_ACCT_HIS "
                   "WHERE INOUT_GUBUN = '2' AND JEOKYO = ?")
            args: list[Any] = [jeokyo]
            if day:
                sql += " AND ACCT_TXDAY = ?"
                args.append(day.replace("-", ""))
            sql += " ORDER BY ACCT_TXDAY DESC"
            cur.execute(sql, *args)
            row = cur.fetchone()
            if not row:
                return {}
            txday = str(row[1] or "")
            return {"amount": int(row[0] or 0),
                    "day": f"{txday[:4]}-{txday[4:6]}-{txday[6:]}" if len(txday) == 8 else "",
                    "unique_field": str(row[2] or "").strip(),
                    "memo": str(row[3] or "").strip()}
    except Exception:
        return {}


def _cyber_docid_sync(unique_field: str) -> str:
    """사이버브랜치가 남긴 매핑표에서 감정서번호를 찾는다 (Branch DB CyberToDocid).

    통장 행(UNIQUE_FIELD) ↔ 감정서번호를 이어 둔 표다. 2023-02~2024-06 까지만
    쌓였고(9,046행) 그 뒤로 멈췄지만, **Memo 가 빈 채로 번호가 남아 있는 행이
    2,146건** 이라 그 시기 건을 뒤질 때는 정답을 바로 준다.
    """
    import pyodbc  # noqa: PLC0415

    settings = get_settings()
    conn = ('DRIVER={%s};SERVER=%s;DATABASE=%s;UID=%s;PWD=REDACTED_CONFIGURE_LOCALLY;Encrypt=%s;'
            "TrustServerCertificate=%s;" % (
                settings.mssql_driver, settings.card_source_server, settings.card_source_db,
                settings.card_source_user, settings.card_source_password.get_secret_value(),
                settings.mssql_encrypt, settings.mssql_trust_server_certificate))
    with pyodbc.connect(conn, timeout=10) as cn:
        cur = cn.cursor()
        cur.execute("SELECT TOP 1 Docid FROM CyberToDocid WHERE UNIQUE_FIELD = ? "
                    "AND Docid LIKE '__-____-_-____'", unique_field)
        row = cur.fetchone()
        return str(row[0]).strip() if row else ""


def _source_view() -> str:
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return f"[{database}].dbo.apw_masterex"


# a.Address 를 뺐다 (2026-08-11) — 뽑기만 하고 어디서도 안 읽던 값인데, 뷰의
# 계산 컬럼이라 스칼라 UDF(dbo.fnBun)를 행마다 부른다. 자세한 실측은
# deposit_search._COLS 위 주석 참고.
_COLS = ("a.DocID, CONVERT(varchar(10), a.ReceiptDate, 120) AS receipt_date, "
         "CONVERT(varchar(10), a.SendDate, 120) AS send_date, "
         "a.CustName, a.Debtor, a.Manager, a.[기초수수료] AS base_fee, "
         "a.[수수료합계] AS fee_total, a.[부가가치세] AS vat, a.[청구금액] AS billed, "
         "a.LStatus")


def _money_sync(doc_ids: list[str]) -> dict[str, dict[str, Any]]:
    """입금현황 화면과 같은 수치(매출총액·입금액·미수금)를 붙인다.

    후보를 고를 때 정작 필요한 건 '이 감정서에 아직 얼마가 안 들어왔나' 다.
    a10_receivable_summary 는 입금현황이 쓰는 그 요약이라 화면과 숫자가 갈리지 않는다.
    """
    if not doc_ids:
        return {}
    db = get_session_factory()()
    try:
        placeholders = ", ".join(f":d{i}" for i in range(len(doc_ids)))
        rows = db.execute(text(
            f"SELECT doc_id, billed_amount, received_amount, advance_amount, "
            f"outstanding_amount, overpaid_amount, "
            f"CONVERT(varchar(10), last_received_date, 120) AS last_received "
            f"FROM a10_receivable_summary WHERE doc_id IN ({placeholders})"),
            {f"d{i}": d for i, d in enumerate(doc_ids)}).mappings().all()
        return {str(r["doc_id"]).strip(): dict(r) for r in rows}
    except Exception:
        return {}
    finally:
        db.close()


def _search_sync(jeokyo: str, amount: int, day: str,
                 unique_field: str = "") -> dict[str, Any]:
    """적요 한 줄로 감정서 후보를 찾는다. 읽기 전용."""
    # 감정서번호가 없는 유형이면 헛수고를 시키지 않고 무엇인지 알려준다.
    kind = _classify(jeokyo, amount)
    if kind:
        vouchers = []
        va = _VA_RE.search(jeokyo or "")
        if va:
            try:
                vouchers = _va_voucher_sync(va.group(1))
            except Exception:
                vouchers = []
        return {"items": [], "total": 0, "names": [], "dropped": [], "compacts": [],
                "steps": [], "kind": kind[0], "kind_note": kind[1],
                "va_no": va.group(1) if va else "", "vouchers": vouchers}

    view = _source_view()
    db = get_session_factory()()
    found: dict[str, dict[str, Any]] = {}
    steps: list[str] = []  # 무엇을 어떻게 찾았는지 — 답변에서 근거로 보여준다

    def keep(row, why: str, score: int) -> None:
        doc = str(row["DocID"]).strip()
        item = found.setdefault(doc, {**dict(row), "DocID": doc, "why": [], "score": 0})
        if why not in item["why"]:
            item["why"].append(why)
        item["score"] = max(item["score"], score) + 5 * (len(item["why"]) - 1)

    try:
        # ⓪ 사이버브랜치 매핑표에 이미 답이 있나 — 있으면 그게 정답이다.
        if unique_field:
            try:
                mapped = _cyber_docid_sync(unique_field)
            except Exception:
                mapped = ""
            if mapped:
                steps.append("사이버브랜치 매핑표(CyberToDocid)에 이 통장 행이 "
                             "이미 연결돼 있었습니다 → %s" % mapped)
                rows = db.execute(text(
                    f"SELECT {_COLS} FROM {view} a WHERE a.DocID = :d"),
                    {"d": mapped}).mappings().all()
                for row in rows:
                    keep(row, "사이버브랜치 매핑", 120)

        # ① 적요에 감정서번호가 박혀 있나 — 가장 확실하다(실측 99.8%).
        compacts = _compacts(jeokyo)
        if compacts:
            steps.append("적요에서 감정서번호로 보이는 숫자 %s 을(를) 찾아 원장에 있는지 확인했습니다"
                         % ", ".join(compacts))
        for compact in compacts:
            rows = db.execute(text(
                f"SELECT {_COLS} FROM {view} a WHERE LEN(a.DocID)=14 "
                f"AND a.DocID LIKE '__-____-_-____' "
                f"AND RIGHT(REPLACE(a.DocID,'-',''), 9) = :c"), {"c": compact}).mappings().all()
            for row in rows:
                keep(row, "적요에 번호", 100)

        # ①-2 적요의 숫자가 의뢰문서번호(CustDocID)와 통째로 같은가 — 은행이 자기
        #      의뢰번호를 그대로 적어 보내는 경우다. 완전 일치라 거의 확실하다.
        #      예: 적요 '2026070809//여신업무센터/대체입금' → 01-2607-3-2289.
        #      원장 CustDocID 채움율 79%.
        refs = [t for t in re.findall(r"(?<!\d)(\d{6,20})(?!\d)", jeokyo or "")
                if len(t) >= 6]
        for ref in refs[:3]:
            rows = db.execute(text(
                f"SELECT TOP 5 {_COLS} FROM {view} a "
                f"WHERE LTRIM(RTRIM(a.CustDocID)) = :r"), {"r": ref}).mappings().all()
            if rows:
                steps.append("적요의 '%s' 를 의뢰문서번호로 보고 원장에서 찾았습니다 → %d건"
                             % (ref, len(rows)))
                for row in rows:
                    keep(row, "의뢰문서번호 일치", 110)

        # ② 청구금액이 입금액과 정확히 같은 건 (기간을 넉넉히 180일)
        if amount > 0 and day:
            rows = db.execute(text(
                f"SELECT TOP 40 {_COLS} FROM {view} a WHERE a.[청구금액] = :amt "
                f"AND a.ReceiptDate BETWEEN DATEADD(day,-180,CONVERT(date,:d)) "
                f"AND DATEADD(day,7,CONVERT(date,:d)) ORDER BY a.ReceiptDate DESC"),
                {"amt": amount, "d": day}).mappings().all()
            steps.append("청구금액이 입금액과 정확히 같은 감정서를 최근 180일에서 찾았습니다 → %d건"
                         % len(rows))
            for row in rows:
                keep(row, "금액 일치", 60)

        # ③ 회계 전표를 경유한다 — 적요 이름이 원장과 아예 다른 건을 잇는 끈이다.
        if amount > 0 and day:
            try:
                docs = _voucher_docs_sync(amount, day)
            except Exception:
                docs = []
            if docs:
                steps.append("같은 날 같은 금액(%s원)으로 통장에 꽂힌 회계 전표를 찾아 "
                             "거기 달린 감정서번호를 가져왔습니다 → %d건"
                             % (_won(amount), len(docs)))
                placeholders = ", ".join(f":d{i}" for i in range(len(docs)))
                rows = db.execute(text(
                    f"SELECT {_COLS} FROM {view} a WHERE a.DocID IN ({placeholders})"),
                    {f"d{i}": d for i, d in enumerate(docs)}).mappings().all()
                for row in rows:
                    keep(row, "회계 전표", 90)

        # ③-2 미수 잔액이 입금액과 딱 맞는 건 — 전표가 없어도 쓸 수 있는 축이다.
        #     분납·부분입금이라 청구금액과는 안 맞는 건을 여기서 줍는다.
        if amount > 0:
            try:
                rows = db.execute(text(
                    "SELECT TOP 20 s.doc_id FROM a10_receivable_summary s "
                    "WHERE s.outstanding_amount = :amt AND s.outstanding_amount > 0"),
                    {"amt": amount}).scalars().all()
            except Exception:
                rows = []
            docs = [str(r).strip() for r in rows if r]
            if docs:
                steps.append("미수 잔액이 입금액과 정확히 같은 감정서를 찾았습니다 → %d건 "
                             "(청구금액과 다른 분납·부분입금을 잡는 축)" % len(docs))
                placeholders = ", ".join(f":m{i}" for i in range(len(docs)))
                found_rows = db.execute(text(
                    f"SELECT {_COLS} FROM {view} a WHERE a.DocID IN ({placeholders})"),
                    {f"m{i}": d for i, d in enumerate(docs)}).mappings().all()
                for row in found_rows:
                    keep(row, "미수 잔액 일치", 75)

        # ④ 적요의 이름을 의뢰인·채무자에서 찾는다 (재무팀이 하던 방식).
        #    개인 이름은 대개 채무자다 — 의뢰인은 '한국주택금융공사 사장' 같은 기관이고
        #    실제로 돈을 부친 사람이 채무자 칸에 있다. 실측(정답지 250건): 이름이 발견된
        #    칸은 의뢰인 88 · 채무자 7 · 소유자 0 · 유치자 0 이었다.
        #    유치자(Manager)는 우리 직원이라 입금자와 무관해 뺐다 — 넣으면 오탐만 는다.
        #    소유자(OwnerName)는 원장 채움율이 1%뿐이라 비용만 든다.
        for rank, name in enumerate(_names(jeokyo)):
            params: dict[str, Any] = {"n": f"%{name}%"}
            amount_sql = ""
            if amount > 0:
                amount_sql = " AND a.[청구금액] = :amt"
                params["amt"] = amount
            date_sql = ""
            if day:
                date_sql = (" AND a.ReceiptDate BETWEEN DATEADD(day,-365,CONVERT(date,:d)) "
                            "AND DATEADD(day,7,CONVERT(date,:d))")
                params["d"] = day
            # 통장 이름과 원장 이름이 한 글자씩 다르다 — '상주시산림조합'(통장) 과
            # '상주산림조합장'(원장). 행정구역 표기와 직위 접미가 붙었다 떼였다 한다.
            variants = [name]
            trimmed = re.sub(r"(?<=.)[시군구도](?=.)", "", name)
            if trimmed != name and len(trimmed) >= 2:
                variants.append(trimmed)
            for column, label in (("CustName", "의뢰인"), ("Debtor", "채무자")):
                for variant in variants:
                    params["n"] = f"%{variant}%"
                    rows = db.execute(text(
                        f"SELECT TOP 20 {_COLS} FROM {view} a "
                        f"WHERE a.{column} LIKE :n{amount_sql}{date_sql} "
                        f"ORDER BY a.ReceiptDate DESC"), params).mappings().all()
                    if not rows:
                        continue
                    shown = variant if variant == name else f"{name}→{variant}"
                    steps.append("'%s' 을(를) %s에서 찾았습니다 → %d건%s"
                                 % (shown, label, len(rows),
                                    " (입금액과 청구금액이 같은 건만)" if amount > 0 else ""))
                    base = 70 if amount > 0 else 40
                    if variant != name:
                        base -= 8  # 이름을 줄여 맞춘 건 원본 일치보다 약한 근거다
                    for row in rows:
                        keep(row, f"{label} '{variant}'", base - 12 * rank)
                    break  # 원본으로 찾았으면 변형까지 볼 필요 없다
    finally:
        db.close()

    items = sorted(found.values(), key=lambda x: -x["score"])[:12]
    # 입금현황 화면과 같은 돈 수치를 붙인다 — 후보를 고를 때 정작 보는 게 미수금이다.
    money = _money_sync([i["DocID"] for i in items])
    for item in items:
        item["money"] = money.get(item["DocID"], {})
    names, dropped = _read(jeokyo)
    return {"items": items[:12], "total": len(found),
            "names": names, "dropped": dropped, "compacts": _compacts(jeokyo),
            "steps": steps}


async def find(jeokyo: str, amount: int = 0, day: str = "",
               unique_field: str = "") -> dict[str, Any]:
    """적요로 감정서 후보를 찾는다.

    금액을 안 줬으면 통장에서 그 입금 행을 찾아 직접 채운다 — 금액이 있고 없고가
    정확도를 가르기 때문이다 (실측: 1순위 82% vs 43%).
    """
    amount = int(amount or 0)
    looked = {}
    if not amount:
        looked = await asyncio.to_thread(_lookup_deposit_sync, jeokyo, day)
        amount = int(looked.get("amount") or 0)
        day = day or looked.get("day") or ""
        unique_field = unique_field or looked.get("unique_field") or ""
    result = await asyncio.to_thread(
        _search_sync, jeokyo, amount, day or "", unique_field or "")
    if looked.get("amount"):
        result["looked_up"] = {"amount": amount, "day": day,
                               "memo": looked.get("memo") or ""}
    return result


def _won(value: Any) -> str:
    return format(float(value or 0), ",.0f")


def _reason(item: dict[str, Any], amount: int) -> str:
    """이 후보가 왜 뽑혔는지 짧은 꼬리표로. 문장으로 쓰면 표가 좌우로 늘어난다."""
    why = item["why"]
    by_name = [w for w in why if w.startswith(("의뢰인 '", "채무자 '"))]
    money_ok = bool(amount) and abs(float(item.get("billed") or 0) - amount) < 1

    tags: list[str] = []
    if "사이버브랜치 매핑" in why:
        tags.append("사이버브랜치 기록")
    if "의뢰문서번호 일치" in why:
        tags.append("의뢰문서번호")
    if "적요에 번호" in why:
        tags.append("적요에 번호")
    if "회계 전표" in why:
        tags.append("전표")
    if "미수 잔액 일치" in why:
        tags.append("미수 잔액")
    if by_name:
        # "의뢰인 '최유미'" → "의뢰인 최유미"
        tags.append(by_name[0].replace("'", ""))
    if money_ok:
        tags.append("금액")
    return " + ".join(tags) if tags else " · ".join(why)


def render(result: dict[str, Any], jeokyo: str, amount: int) -> str:
    """후보와 **그렇게 고른 이유**를 함께 보여준다.

    재무팀이 손으로 하던 판단을 대신하는 것이라, 결과만 던지면 믿고 쓸 수 없다.
    적요를 어떻게 읽었는지 · 무엇으로 찾았는지 · 각 후보가 왜 뽑혔는지를 밝힌다.
    """
    items = result.get("items") or []

    looked = result.get("looked_up") or {}
    shown_amount = amount or int(looked.get("amount") or 0)
    head = f"🔎 {jeokyo.strip()}"
    if shown_amount:
        head += f" · 입금액 {_won(shown_amount)}원"
        if looked.get("day"):
            head += f" · {looked['day']}"
        if not amount:
            head += "  (통장에서 찾아 채움)"
    lines = ["**입금 적요로 찾은 감정서 후보**", "", head]
    amount = shown_amount

    # 감정서번호가 없는 유형 — 헛되이 뒤지지 않게 무엇인지부터 알려준다.
    if result.get("kind"):
        lines += ["", f"**이 입금은 '{result['kind']}' 유형이라 감정서번호가 없습니다**", "",
                  result.get("kind_note") or ""]
        vouchers = result.get("vouchers") or []
        if vouchers:
            lines += ["", "회계 전표에는 이렇게 잡혀 있습니다", "",
                      "| 전표일 | 전표번호 | 금액 | 적요 | 거래처 |", "|---|---|---|---|---|"]
            for v in vouchers:
                lines.append("| %s | %s | %s | %s | %s |" % (
                    v.get("d") or "-", v.get("voucher_no") or "-", _won(v.get("amount")),
                    (str(v.get("remark") or "-").strip() or "-")[:28],
                    (str(v.get("partner_name") or "-").strip() or "-")[:20]))
        elif result.get("va_no"):
            lines += ["", f"> 가상계좌 {result['va_no']} 는 아직 전표에 없습니다. 약식평가는 보통 "
                          "전표가 먼저(또는 당일) 만들어지는데(실측 94%), 이 건은 회계 처리 전으로 "
                          "보입니다. 하루 뒤 다시 조회하면 어느 은행·지점 건인지 나옵니다."]
        return "\n".join(lines)

    # '적요를 이렇게 읽었습니다' · '이렇게 찾았습니다' 두 블록은 뺐다 (2026-08-05 요청).
    # 표의 '근거' 열이 같은 말을 이미 하고 있어 답이 두 배로 길어지기만 했다.
    if not items:
        lines += ["", "찾지 못했습니다. 적요에 이름도 번호도 없으면 금액만으로는 "
                      "고를 수 없습니다 — 입금액을 함께 넣거나, 거래처명을 직접 물어봐 주세요."]
        return "\n".join(lines)

    # ── 가장 확실한 답이 하나면 앞세운다 ──────────────────────────────────
    best = items[0]
    if "적요에 번호" in best["why"] and len(
            [i for i in items if "적요에 번호" in i["why"]]) == 1:
        lines += ["", f"→ 적요에 번호가 적혀 있어 **{best['DocID']}** 로 봅니다. "
                      "이 경우 실측 정확도가 99.8% 입니다."]

    # 입금현황 화면과 같은 회계 열로 보여준다 — 제목·목적보다 매출총액·미수금이
    # 후보를 고르는 근거다 (2026-08-05 요청). 열 개수·구분선·셀 수를 정확히 맞춘다.
    lines += ["", f"**후보 {len(items)}건** (확신 높은 순)", "",
              "| 감정서번호 | 거래처명 | 접수일 | 매출총액 | 입금액 | 미수금 | 근거 |",
              "|---|---|---|---|---|---|---|"]
    for item in items:
        m = item.get("money") or {}
        # 매출총액은 요약(입금현황)을 우선하고, 없으면 원장 청구금액으로 채운다.
        billed = m.get("billed_amount")
        if billed is None:
            billed = item.get("billed")
        received = m.get("received_amount")
        outstanding = m.get("outstanding_amount")
        match = " ✅" if amount and abs(float(billed or 0) - amount) < 1 else ""
        lines.append("| %s | %s | %s | %s%s | %s | %s | %s |" % (
            item["DocID"],
            (str(item.get("CustName") or "-").strip() or "-")[:18],
            item.get("receipt_date") or "-",
            _won(billed), match,
            _won(received) if received is not None else "-",
            _won(outstanding) if outstanding is not None else "-",
            _reason(item, amount)))

    if result.get("total", 0) > len(items):
        lines += ["", f"> 후보가 {result['total']}건이라 상위 {len(items)}건만 보여드립니다. "
                      "입금액을 함께 넣으면 크게 좁혀집니다."]
    return "\n".join(lines)
