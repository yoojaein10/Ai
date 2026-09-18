"""통장 입금 목록 — 기간으로 통장 거래내역을 뽑고, 고른 줄만 감정서를 찾는다.

사이버브랜치 '거래내역조회' 화면과 같은 결로 보여주되, 거기 없는 것을 더한다:
**우리가 찾아낸 감정서번호와 그 감정서의 회계 상태**. 재무팀이 지금 손으로 하던
일이 그것이라, 목록에서 바로 보이면 옮겨 적기만 하면 된다.

목록과 찾기를 갈라 둔 이유(2026-08-05 사용자 요청): 감정서 찾기는 한 건마다
통장·원장·전표 세 DB 를 두드려 1초 안팎이 든다. 하루치 23건이면 5초를 기다려야
하는데, 재무팀이 실제로 손대는 건 그중 몇 줄뿐이다. 목록은 바로 띄우고
(0.1초), 찾기는 누른 줄에만 건다.

이 모듈도 **읽기 전용**이다. CB2_ACCT_HIS.Memo 에 쓰면 매출이 계상된다
(app/services/deposit_match.py 상단 참고).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from app.services import deposit_match, deposit_search

# 은행 코드 → 화면에 쓰는 짧은 이름. 사이버브랜치 '금융기관' 칸과 같은 자리다.
_BANKS = {
    "10000002": "산업", "10000003": "기업", "10000004": "국민", "10000007": "수협",
    "10000011": "농협", "10000020": "우리", "10000023": "SC", "10000027": "씨티",
    "10000031": "대구", "10000032": "부산", "10000034": "광주", "10000035": "제주",
    "10000037": "전북", "10000039": "경남", "10000045": "새마을", "10000048": "신협",
    "10000050": "저축", "10000064": "산림", "10000071": "우체국", "10000081": "하나",
    "10000088": "신한", "10000089": "케이뱅크", "10000090": "카카오", "10000092": "토스",
}


def _bank(code: str) -> str:
    code = (code or "").strip()
    return _BANKS.get(code, code[-4:] if len(code) > 4 else code)


# 카드사 정산을 거르는 SQL 절은 _classify 의 _CARD_RE 에서 **만들어 쓴다**.
# 손으로 '%카드%' 라고 적었더니 카드사가 아닌 거래처 '이카드밴（주）' 입금까지
# SQL 단계에서 사라졌다 (2026-08-06 실측). 잣대를 두 곳에 적으면 이렇게
# 어긋나므로, 규칙은 _CARD_RE 한 곳에만 두고 여기서는 그대로 옮긴다.
#
# SQL 절은 **거들기만 한다**. 최종 판단은 _rows_sync 안의 _CARD_RE 가 하므로,
# 낱말을 SQL 에서 빼먹어도 결과는 옳다 (읽어 오는 줄이 조금 늘 뿐이다).
# 그래서 LIKE 로 그대로 옮길 수 없는 낱말은 조용히 건너뛴다 — 정규식이
# 복잡해졌다고 화면 전체가 import 단계에서 죽는 편이 더 나쁘다.
# 반대로 SQL 이 정규식보다 넓게 자르는 것은 위 '이카드밴' 사고처럼
# 되살릴 수 없으므로 절대 안 된다.
_CARD_WORDS = [w for w in deposit_match._CARD_RE.pattern.split("|") if w]  # noqa: SLF001
_CARD_SQL = "".join(
    f"AND JEOKYO NOT LIKE '%{w}%' "
    for w in _CARD_WORDS
    if not set(w) & set("%_[]'()|*+?.\\^$")   # LIKE·정규식 특수문자가 없는 낱말만
)


# 한 번에 받아 오는 줄 수의 상한.
#
# 300 이었는데 조용히 잘리고 있었다 — 실측(2026-07) 한 달 입금이 1,095건
# (약식 422 + 나머지 673)이라 300 을 넘긴 795건이 말없이 사라졌다.
# 약식 제외 조회조건을 없애면서(2026-08-06 요청) 더 커지므로 상한을 올리고,
# 그래도 넘치면 **넘쳤다고 말한다**. 한 장에 20건씩 넘겨 보므로 화면에 그려지는
# 줄은 언제나 20개뿐이라 2,000줄을 들고 있어도 무겁지 않다.
_MAX_ROWS = 2000


# 통장 한 줄 → 화면이 쓰는 모양. 기간 조회와 번호 조회가 같은 모양을 내야
# 화면이 두 갈래를 따로 알 필요가 없다.
def _row(r: Any) -> dict:
    day = str(r[0] or "")
    time_raw = str(r[1] or "")
    return {
        "txday": f"{day[:4]}-{day[4:6]}-{day[6:]}" if len(day) == 8 else day,
        "txtime": (f"{time_raw[:2]}:{time_raw[2:4]}" if len(time_raw) >= 4 else ""),
        "bank": _bank(str(r[2] or "")),
        "acct": str(r[3] or "").strip()[-6:],
        "jeokyo": str(r[4] or "").strip(),
        "branch": str(r[5] or "").strip(),
        "amount": int(r[6] or 0),
        "memo": str(r[7] or "").strip(),
        "unique_field": str(r[8] or "").strip(),
        "inout": "입금" if str(r[9] or "").strip() == "2" else "출금",
        # 감정서가 아예 없는 유형인가(약식평가·자사이체·카드·예금이자…).
        # 화면이 이걸 알아야 **찾을 필요 없는 줄을 안 두드린다** — 미처리 80건인
        # 날에도 실제 대상은 0~24건뿐이라(2026-07 실측), 이 한 칸이 목록 자동
        # 채우기의 비용을 스무 배 가른다. _classify 는 정규식이라 DB 를 안 탄다.
        "kind": (deposit_match._classify(str(r[4] or "").strip(),
                                int(r[6] or 0)) or ("",))[0],  # noqa: SLF001
    }


# ── 번호로 찾기 ────────────────────────────────────────────────────────
# 재무팀이 의뢰번호밖에 못 받는 일이 있다 — '206732380' 하나만 들고 와서
# 그 입금이 어느 줄인지 찾아야 한다 (2026-08-06 요청).
#
# 그때 걸림돌은 **기간**이다. 번호만 아는 사람은 그 돈이 언제 들어왔는지
# 모르는데, 기간을 7월로 잡아 두면 8월 건인 '206732380' 은 안 나온다
# (실측: 그 번호는 2026-08-03 · 10,718,410원 딱 1건).
#
# 그래서 번호로 콕 집었으면 **기간을 무시**한다. 안전한 이유는 실측이다 —
# 통장은 85,817행(2023-01~)뿐이라 기간 없이 훑어도 350ms 이고,
# 9~10자리 번호는 전 기간에서 중앙 1건(최대 2건)만 걸린다.
# 자릿수가 짧으면 잡음이 는다(7자리 중앙 12건 · 4자리 중앙 90건 · 최대 406건)
# 이라 **6자리 이상**만 이 규칙을 탄다.
_NUMBERISH = re.compile(r"^[\d\s\-./]+$")
_NUMBER_MIN = 6


def _number_of(keyword: str) -> str:
    """검색어가 번호뿐이면 숫자만 남겨 돌려준다. 아니면 빈 문자열."""
    text = (keyword or "").strip()
    if not text or not _NUMBERISH.match(text):
        return ""
    digits = re.sub(r"\D", "", text)
    return digits if len(digits) >= _NUMBER_MIN else ""


def _rows_sync(date_from: str, date_to: str, only_blank: bool, limit: int,
               keyword: str = "") -> list[dict]:
    """기간 안의 통장 입금을 읽어온다 (ACCT_TXDAY 기준).

    출금(INOUT_GUBUN='1')은 아예 뺀다 — 감정서 수수료 입금이 아니라 대사
    대상이 아니고, 목록에 섞이면 금액이 우연히 같은 남의 감정서가 후보로
    딸려 온다(실측: 출금 818,400원에 후보 10건, 2026-08-05 사용자 지시).

    keyword 는 적요 부분일치다 — '세연스틸'·'부산은행'처럼 거래처 이름을
    넣어 그 기간의 거래를 좁혀 본다. 다만 keyword 가 **번호뿐**이면
    _number_rows_sync 로 넘긴다 (아래 참고).
    """
    number = _number_of(keyword)
    if number:
        return _number_rows_sync(number, limit)
    sql = (
        "SELECT TOP (?) ACCT_TXDAY, ACCT_TXTIME, BANK_CD, ACCT_NO, JEOKYO, BRANCH, "
        "TX_AMT, Memo, UNIQUE_FIELD, INOUT_GUBUN "
        "FROM dbo.CB2_ACCT_HIS "
        "WHERE INOUT_GUBUN = '2' AND ACCT_TXDAY BETWEEN ? AND ? "
        # 카드사 정산도 출금과 같이 조건 없이 뺀다 (2026-08-06 요청). 여러
        # 승인건을 묶은 금액이라 감정서 한 건에 대응되지 않는다. 실측
        # (2026-06~07, 약식 제외 500건) 14건(2.8%), 전부
        # 'BC-745827823//WON뱅킹사업부/Ｆ／Ｂ' 꼴이다.
        #
        + _CARD_SQL
    )
    args: list[Any] = [limit, date_from.replace("-", ""), date_to.replace("-", "")]
    if only_blank:
        sql += "AND (Memo IS NULL OR LTRIM(RTRIM(Memo)) = '') "
    keyword = (keyword or "").strip()
    if keyword:
        # 적요는 통장이 cp949 로 주는 값이라 LIKE 로만 본다. 와일드카드 문자는
        # 그대로 두면 사용자가 의도하지 않은 매칭이 되므로 ESCAPE 로 묶는다.
        escaped = keyword.replace("[", "[[]").replace("%", "[%]").replace("_", "[_]")
        sql += "AND JEOKYO LIKE ? "
        args.append(f"%{escaped}%")
    sql += "ORDER BY ACCT_TXDAY DESC, ACCT_TXTIME DESC"

    with deposit_match._branch_conn() as cn:  # noqa: SLF001 (같은 묶음의 읽기 전용 연결)
        cur = cn.cursor()
        cur.execute(sql, *args)
        out = []
        for r in cur.fetchall():
            jeokyo_raw = str(r[4] or "")
            if (deposit_match._CARD_RE.search(jeokyo_raw.upper())      # noqa: SLF001
                    or deposit_match._CARD_RE.search(jeokyo_raw)):      # noqa: SLF001
                continue   # 카드사 판단은 _classify 와 똑같은 잣대로 (한 곳에서만 정한다)
            out.append(_row(r))
        return out


# 번호로 콕 집었으면 기간·카드 제외를 끈다 — 카드를 걸러 두면 카드사 번호가
# 안 나온다. 지목한 줄을 우리가 숨기면 안 된다.
#
# 다만 **출금은 이 화면 전체와 마찬가지로 뺀다** (2026-08-06 요청).
# 실측(2025년 이후) 6자리 이상 번호 15,010개 중 79개가 입금·출금에 같이 있고
# 그중 70개가 '취소'인데, 짝이 되는 입금 쪽 적요에 이미 '취소된거래' 가 적혀
# 있어(예: '400577516/대체입금/취소된거래') 출금을 빼도 취소 사실은 보인다.
def _number_rows_sync(number: str, limit: int) -> list[dict]:
    """번호로 통장 전체를 훑는다. 기간·카드 거르개 없음, 입금만."""
    base = ("SELECT TOP (?) ACCT_TXDAY, ACCT_TXTIME, BANK_CD, ACCT_NO, JEOKYO, "
            "BRANCH, TX_AMT, Memo, UNIQUE_FIELD, INOUT_GUBUN "
            "FROM dbo.CB2_ACCT_HIS WHERE INOUT_GUBUN = '2' AND ")
    order = " ORDER BY ACCT_TXDAY DESC, ACCT_TXTIME DESC"
    # ① 적요에 그대로 박힌 것 (350ms). 대개 여기서 끝난다.
    # ② 못 찾으면 적요의 구분자를 걷어내고 다시 (1.4초) — 사람이 '20673-2380'
    #    처럼 끊어 적거나 적요 쪽이 끊어 놓은 경우를 흡수한다. 느리므로
    #    ①이 빈손일 때만 간다.
    stripped = ("REPLACE(REPLACE(REPLACE(REPLACE(JEOKYO,'-',''),' ',''),'.',''),'/','')")
    tries = [("JEOKYO LIKE ?", number), (f"{stripped} LIKE ?", number)]
    # ③ 그래도 없고 자릿수가 넉넉하면 앞 두 자리를 떼고 한 번 더 —
    #    감정서번호 '01-2607-3-2380' 을 넣었는데 적요에는 지사코드를 뺀
    #    '260732380' 만 있는 경우다. 빈손보다 낫고, 적요를 같이 보여주므로
    #    사람이 곧바로 가려낼 수 있다.
    #
    #    넣은 번호 그대로 찾는 ①②를 먼저 다 해 본 뒤에 온다 — 두 자리를 뗀
    #    것은 덜 미더운 짐작이라 온전한 일치를 이길 수 없다.
    if len(number) >= 10:
        tries.append(("JEOKYO LIKE ?", number[2:]))
        tries.append((f"{stripped} LIKE ?", number[2:]))

    with deposit_match._branch_conn() as cn:  # noqa: SLF001
        cur = cn.cursor()
        for where, needle in tries:
            cur.execute(base + where + order, limit, f"%{needle}%")
            rows = cur.fetchall()
            if rows:
                return [_row(r) for r in rows]
    return []


async def rows(date_from: str, date_to: str, only_blank: bool = False,
               limit: int = _MAX_ROWS, keyword: str = "") -> list[dict]:
    # 상한 + 1 까지 허용한다 — list_deposits 가 '넘쳤는지' 를 그 한 줄로 가린다.
    return await asyncio.to_thread(
        _rows_sync, date_from, date_to, bool(only_blank),
        max(1, min(int(limit), _MAX_ROWS + 1)), keyword)


async def list_deposits(date_from: str, date_to: str, only_blank: bool = False,
                        limit: int = _MAX_ROWS, keyword: str = "") -> dict[str, Any]:
    """기간 입금 목록. 감정서 찾기는 하지 않는다 — 화면이 고른 줄만 match_one 을 부른다."""
    cap = max(1, min(int(limit), _MAX_ROWS))
    # 상한을 넘겼는지 알아야 하므로 한 줄 더 받아 본다.
    items = await rows(date_from, date_to, only_blank, cap + 1, keyword)
    cut = len(items) > cap
    if cut:
        items = items[:cap]
    # 번호로 찾았으면 기간을 무시했다는 사실을, 잘렸으면 잘렸다는 사실을
    # 화면이 알아야 한다 — 조회 조건과 결과가 어긋나 보이면 사람이 못 믿는다.
    return {"items": items, "total": len(items),
            "number": _number_of(keyword),
            "truncated": cut, "limit": cap}


async def match_one(jeokyo: str, amount: int = 0, day: str = "",
                    unique_field: str = "") -> dict[str, Any]:
    """한 입금 건의 감정서 찾기 — 화면에서 줄을 눌렀을 때.

    실제 탐색은 app/services/deposit_search.py 가 한다. 여기서는 화면이 그리는
    모양(tokens · stages · items)으로 옮기기만 한다.
    """
    found = await deposit_search.find(jeokyo, amount, day or "", unique_field or "")
    items = []
    for item in found.get("items") or []:
        items.append({
            "doc_id": item["doc_id"],
            # 본사(01)가 아니면 화면이 지사 칸에 이 이름을 보여준다.
            "office": item.get("office") or "",
            "cust_name": item["cust_name"] or "",
            "submit_to": item.get("submit_to") or "",
            "debtor": item.get("debtor") or "",
            "cust_charge": item.get("cust_charge") or "",
            "recv_date": item["recv_date"],
            # 화면의 '매출총액' 칸은 입금현황과 같은 기준이어야 한다 —
            # 원장 청구금액이 아니라 요약의 매출총액이다.
            "billed": item.get("billed_total") or item.get("billed"),
            "outstanding": item.get("outstanding"),
            "word": item.get("word") or "",
            "field": item.get("field") or "",
            "field_label": item.get("field_label") or "",
            "months": item.get("months") or 0,
            "source": item.get("source") or "",
            "section": item.get("section") or "",
            "money_note": item.get("money_note") or "",
            "voucher": bool(item.get("voucher")),
            "evidence": item.get("evidence") or [],
            "also": item.get("also") or [],
        })
    return {
        "kind": found.get("kind") or "",
        "note": found.get("note") or "",
        # 약식은 감정서가 없다 - 대신 본/지사와 영업점명을 싣는다 (2026-08-06)
        "yaksik": found.get("yaksik") or {},
        "tokens": found.get("tokens") or [],
        "stages": found.get("stages") or [],
        "items": items,
    }
