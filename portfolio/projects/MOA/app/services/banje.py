"""반제 리스트 — 외상매출금/선수금을 입금으로 상계(반제)한 내역 (본사).

- 외상매출금 반제: 외상매출금(1080000) 대변 = 잡아둔 채권을 입금으로 상계.
- 선수금 반제: 선수금(2590000) 차변 = 미리 받은 선수금을 매출로 대체.
반제일(전표일자)·감정서번호(관리번호)·거래처·금액·적요를 기간으로 조회한다.

조회 모드는 두 가지다.
- settled(반제 내역): 기간 = 반제일. 반제 전표 라인 하나가 한 행.
- open(미반제 잔액): 기간 = 발생일. 감정서 하나가 한 행이고 잔액이 남은 것만.
  반제 라인이 아예 없는 감정서는 settled에 안 잡히므로 open에서만 보인다.
"""

import re
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.office_lookup import get_office

# 표준 감정서번호(01-2601-3-0001)만 잔액·발생일이 의미 있다. 비표준('01','1' 등 묶음
# 정산 번호)은 여러 건이 한 번호에 섞여 잔액이 무의미하므로 계산하지 않는다.
_STD_RE = re.compile(r"^\d{2}-\d{4}-\w-\d{4}$")
_EMBED_RE = re.compile(r"\d{2}-\d{4}-\w-\d{4}")
# 표준번호로 시작하고 뒤에 뭔가 더 붙은 형태 ('01-2412-1-0339,0340,0341', '01-1606-8-0075-')
_HEAD_RE = re.compile(r"^(\d{2}-\d{4}-\w)-(\d{4})(.*)$")
_SEQ_RE = re.compile(r"^\d{4}$")


def _members(doc: str) -> "list[str]":
    """관리번호에 담긴 감정서번호를 뽑아낸다.

    회계 입력이 관리번호에 감정서번호 대신 여러 표기를 쓴다 (2026-07-27 전수 확인, 59종):
    - 쉼표 묶음: '01-2412-1-0339,0340,0341,0342' = 앞 접두사를 공유하는 4건의 뒤 4자리 나열
    - 앞뒤 군더더기: '??01-2007-3-3822', '매출 01-2411-4-0497', '01-1606-8-0075-', '… 사본발급비'
    - 지사명 접두: '동부13-2308-3-1152', '충남07-1403-3-0081'
    이걸 풀어야 원본/군더더기 번호로 쪼개진 발생·반제가 한 감정서로 합쳐진다.
    풀 수 없으면(‘1’, ‘01’, ‘국세청’ 등) 빈 목록.
    """
    if _STD_RE.match(doc):
        return [doc]
    head = _HEAD_RE.match(doc)
    if head:
        prefix, first, rest = head.group(1), head.group(2), head.group(3)
        found = [f"{prefix}-{first}"]
        for part in rest.lstrip(",").replace(" ", "").split(","):
            part = part.strip().lstrip("-")
            if _SEQ_RE.match(part):
                found.append(f"{prefix}-{part}")     # 뒤 4자리만 적은 묶음 표기
            elif _STD_RE.match(part):
                found.append(part)                   # 전체 번호를 그대로 나열한 경우
    else:
        found = _EMBED_RE.findall(doc)
    seen: "set[str]" = set()
    return [d for d in found if not (d in seen or seen.add(d))]


def _canonical(doc: str) -> "tuple[str, list[str]]":
    """(집계 키, 구성 감정서 목록).

    감정서 하나로 풀리면 그 번호를 키로 써서 군더더기 표기와 원래 번호를 합친다.
    여러 건 묶음이거나 못 풀면 원본을 그대로 키로 두어 서로 섞이지 않게 한다.
    """
    members = _members(doc)
    return (members[0] if len(members) == 1 else doc), members


def _search_key(value: str) -> str:
    """검색 대조용 정규화 — 구분기호를 떼고 대문자로 맞춘다.

    회계가 관리번호를 '01-2603-1-0109'·'012603-1-0109'·'매출 01-2603-1-0109'
    처럼 제각각 적어 놔서, 사람이 어떻게 치든 같은 번호로 걸리게 해야 한다.
    """
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).upper()


def _doc_matches(key: str, doc: str, members: "list[str]", raw: str) -> bool:
    """정규화한 검색어가 대표번호·구성 감정서·원본 관리번호 중 하나에 들어 있나.

    부분 일치다 — 뒤 4자리('0109')만 쳐도 찾을 수 있어야 한다.
    """
    if not key:
        return True
    return any(key in _search_key(v) for v in (doc, raw, *members) if v)

# (계정, 차대) — 반제로 인식하는 라인
_KINDS = {
    "receivable": ("1080000", "4"),  # 외상매출금 반제 (대변)
    "advance": ("2590000", "3"),     # 선수금 반제 (차변)
}

# 화면 열 이름은 kind마다 다르다. 선수금은 돈을 먼저 받고(발생) 나중에 매출로 대체(반제)
# 하므로 '발생'이 곧 입금일이다. banje.js의 LBL과 같은 문구를 쓴다.
_LABELS = {
    "receivable": {
        "kind": "외상매출금", "gen_date": "생성일", "gen_amount": "발생금액",
        "settle_date": "입금일", "settle_amount": "반제금액",
        "last_settle": "최종반제일", "settle_cum": "반제누계",
        # 기간 기준 이름은 열 이름과 다르다 (외상매출금 반제일 = 열에선 '입금일').
        "basis_settle": "반제일", "basis_gen": "생성일",
    },
    "advance": {
        "kind": "선수금", "gen_date": "입금일", "gen_amount": "입금금액",
        "settle_date": "정산일", "settle_amount": "정산금액",
        "last_settle": "최종정산일", "settle_cum": "정산누계",
        "basis_settle": "정산일", "basis_gen": "입금일",
    },
}


def _doc_meta(
    db: Session,
    division: str,
    account: str,
    dc: str,
    gen_dc: str,
    as_of: "date | None" = None,
) -> "dict[str, dict[str, Any]]":
    """감정서(정규화 키)별 발생일·발생금액·반제누계·잔액·거래처.

    SQL은 관리번호 원본으로 묶고, 정규화 합치기는 파이썬에서 한다 (MSSQL엔 정규식이 없다).
    이렇게 해야 '매출 01-2411-4-0497'(차변 6,841만)과 '01-2411-4-0497'로 쪼개져
    한쪽은 +6,841만, 다른 쪽은 -6,841만으로 잡히던 잔액이 하나로 합쳐져 0이 된다.
    """
    params: "dict[str, Any]" = {"div": division, "acct": account, "dc": dc, "gdc": gen_dc}
    cutoff = ""
    if as_of is not None:
        cutoff = "  AND voucher_date <= :asof "
        params["asof"] = as_of
    rows = db.execute(
        text(
            "SELECT LTRIM(RTRIM(ISNULL(management_no, ''))) AS doc, "
            "MIN(CASE WHEN debit_credit = CAST(:gdc AS char(1)) THEN voucher_date END) AS gen_date, "
            "MAX(CASE WHEN debit_credit = CAST(:dc AS char(1)) THEN voucher_date END) AS last_settle, "
            "SUM(CASE WHEN debit_credit = CAST(:gdc AS char(1)) THEN amount ELSE 0 END) AS gen_amount, "
            "SUM(CASE WHEN debit_credit = CAST(:dc AS char(1)) THEN amount ELSE 0 END) AS settle_amount, "
            "MAX(NULLIF(RTRIM(partner_name), '')) AS partner, "
            "MAX(CASE WHEN debit_credit = CAST(:gdc AS char(1)) THEN remark END) AS remark "
            "FROM dbo.a10_voucher_cache "
            "WHERE division_code = CAST(:div AS varchar(10)) "
            "  AND account_code = CAST(:acct AS varchar(20)) "
            f"{cutoff}"
            "GROUP BY LTRIM(RTRIM(ISNULL(management_no, '')))"
        ),
        params,
    ).mappings().all()

    meta: "dict[str, dict[str, Any]]" = {}
    for r in rows:
        raw = (r["doc"] or "").strip()
        key, members = _canonical(raw)
        m = meta.get(key)
        if m is None:
            m = meta[key] = {
                "gen_date": None, "last_settle": None, "gen_amount": 0.0,
                "settle_amount": 0.0, "partner": "", "remark": "", "members": members,
                "raws": [],   # 이 감정서로 합쳐진 원본 관리번호들 (정규화 흔적)
            }
        m["raws"].append(raw)
        if r["gen_date"] and (m["gen_date"] is None or r["gen_date"] < m["gen_date"]):
            m["gen_date"] = r["gen_date"]
        if r["last_settle"] and (m["last_settle"] is None or r["last_settle"] > m["last_settle"]):
            m["last_settle"] = r["last_settle"]
        m["gen_amount"] += float(r["gen_amount"] or 0)
        m["settle_amount"] += float(r["settle_amount"] or 0)
        m["partner"] = m["partner"] or (r["partner"] or "").strip()
        m["remark"] = m["remark"] or (r["remark"] or "").strip()
    for m in meta.values():
        m["balance"] = m["gen_amount"] - m["settle_amount"]
    return meta


def _iso(value: "date | None") -> "str | None":
    return value.isoformat() if value else None


def banje_list(
    db: Session,
    kind: str,
    date_from: "date | None",
    date_to: "date | None",
    office_code: str = "10",
    date_basis: str = "settle",
    doc_query: str = "",
) -> "dict[str, Any]":
    """반제 내역 — 반제 전표 라인 1개가 1행.

    date_basis가 기간 필터를 무엇에 걸지 정한다.
    - settle(기본): 반제일(선수금은 정산일) 기준. '이번 달에 들어온 돈'을 본다.
    - gen: 감정서의 생성일(발생일, 선수금은 입금일) 기준. '그때 발생한 건이 언제 정리됐나'를 본다.
      생성일은 감정서 단위 값이라 비표준 관리번호는 의미가 없어 제외하고 규모만 돌려준다.

    doc_query(감정서번호 검색)를 주면 **기간을 아예 안 건다**. 반제가 언제 됐는지
    모르니까 찾는 것이라, 기간 안에서만 걸러 주면 작년에 반제된 건이 빠져 검색이
    쓸모없어진다 (2026-08-21 사용자 요청).
    """
    account, dc = _KINDS[kind]
    gen_dc = "3" if dc == "4" else "4"  # 발생(생성)은 반제의 반대 차대
    office = get_office(db, office_code)
    division = office.division_code if office else "1000"
    # 감정서(정규화 키)별 발생일·발생금액·잔액 (전 기간 기준). 잔액 = 발생 - 반제.
    meta = _doc_meta(db, division, account, dc, gen_dc)

    search = _search_key(doc_query)
    params: "dict[str, Any]" = {"div": division, "acct": account, "dc": dc}
    # 생성일 기준은 감정서 단위 값(meta)으로 걸러야 해서 SQL에서 기간을 못 자른다.
    # 번호 검색도 마찬가지 — 관리번호 표기가 제각각이라 SQL LIKE로는 못 거른다.
    period_sql = ""
    if not search and date_basis != "gen":
        period_sql = "  AND voucher_date BETWEEN :f AND :t "
        params["f"], params["t"] = date_from, date_to
    rows = db.execute(
        text(
            "SELECT voucher_date, LTRIM(RTRIM(ISNULL(management_no, ''))) AS doc, "
            "partner_name, amount, remark, voucher_no "
            "FROM dbo.a10_voucher_cache "
            "WHERE division_code = CAST(:div AS varchar(10)) "
            "  AND account_code = CAST(:acct AS varchar(20)) "
            "  AND debit_credit = CAST(:dc AS char(1)) "
            f"{period_sql}"
            "ORDER BY voucher_date DESC, voucher_no DESC"
        ),
        params,
    ).mappings().all()

    items = []
    excluded_count = 0
    excluded_amount = 0.0
    for r in rows:
        raw = (r["doc"] or "").strip()
        key, docs = _canonical(raw)
        m = meta.get(key, {})
        single = len(docs) == 1  # 감정서 하나로 풀린 것만 잔액·생성일이 의미 있다
        gen_date = m.get("gen_date") if single else None
        if search:
            if not _doc_matches(search, docs[0] if docs else raw, docs, raw):
                continue
        elif date_basis == "gen":
            # 생성일 기준 조회는 감정서 단위 값으로 거른다. 묶음·미해독 번호는 생성일이
            # 여러 건의 뒤섞인 값이라 기간 판정이 무의미하므로 빼고 규모만 알린다.
            in_period = m.get("gen_date") is not None and date_from <= m["gen_date"] <= date_to
            if not in_period:
                continue
            if not single:
                excluded_count += 1
                excluded_amount += float(r["amount"] or 0)
                continue
        items.append({
            "date": _iso(r["voucher_date"]),                     # 입금일(반제일)
            "doc": docs[0] if docs else raw,                     # 정규화한 대표 감정서번호
            "members": docs,                                     # 묶음이면 2건 이상
            "raw": raw if (docs[0] if docs else raw) != raw else None,  # 원본이 다를 때만
            "partner": (r["partner_name"] or "").strip() or m.get("partner", ""),
            "gen_date": _iso(gen_date),                          # 생성일(발생일)
            "gen_amount": m.get("gen_amount") if single else None,  # 발생금액(발생 차대 누계)
            "amount": float(r["amount"] or 0),                   # 반제금액
            "balance": m.get("balance") if single else None,     # 잔액(묶음은 무의미→None)
            "remark": (r["remark"] or "").strip(),
        })
    if date_basis == "gen":
        items.sort(key=lambda i: (i["gen_date"] or "", i["date"] or ""), reverse=True)
    return {
        "kind": kind,
        "mode": "settled",
        "date_basis": date_basis,
        # 번호 검색이면 기간을 안 걸었으니 기간을 알려 주지 않는다 — 화면이 안 보이는
        # 기간 조건을 그대로 써 붙이면 거짓말이 된다.
        "period": (
            None if search or date_from is None or date_to is None
            else {"from": date_from.isoformat(), "to": date_to.isoformat()}
        ),
        "doc_query": doc_query.strip(),
        "count": len(items),
        "total": sum(i["amount"] for i in items),
        "excluded": {"count": excluded_count, "amount": excluded_amount},
        "items": items,
    }


def banje_open_list(
    db: Session,
    kind: str,
    date_from: "date | None" = None,
    date_to: "date | None" = None,
    office_code: str = "10",
    include_nonstd: bool = False,
    as_of: "date | None" = None,
    doc_query: str = "",
) -> "dict[str, Any]":
    """미반제(잔액) 리스트 — 기준일 시점에 잔액이 남은 감정서 전부.

    조회 조건은 잔액 기준일(as_of) 하나다. 발생일 기간을 걸면 '작년에 발생해서
    아직 안 들어온 건'이 빠져 잔액 합계가 어긋나므로 기본은 기간 무제한이고,
    date_from/date_to를 주면 그때만 발생일로 좁힌다.

    as_of는 잔액 기준일. 그 날까지의 전표만 넣고 누적 발생 - 누적 반제를 계산하므로
    '2025-12-31 시점 잔액'처럼 과거 시점으로 끊어 볼 수 있다. 기본은 오늘(현재 잔액).
    반제 누계·최종 반제일도 같은 기준일로 잘린다.

    비표준 관리번호('01', '2012년표준지공시지가' 등 묶음 정산 번호)는 여러 건이
    한 번호에 섞여 잔액이 무의미하므로 기본 제외하고, 제외 규모를 함께 돌려준다.

    doc_query(감정서번호 검색)는 발생일 기간·비표준 제외보다 먼저 건다. 찾는 번호가
    비표준이라고 검색 결과에서 통째로 사라지면 "왜 안 나오냐"가 된다.
    잔액이 0인 감정서는 이 화면 뜻(미반제)상 목록에 안 넣되, 몇 건이 그래서 빠졌는지는
    settled_only로 알려 준다 — 그래야 '반제 내역에서 보라'고 안내할 수 있다.
    """
    as_of = as_of or date.today()
    account, dc = _KINDS[kind]
    gen_dc = "3" if dc == "4" else "4"  # 발생(생성)은 반제의 반대 차대
    office = get_office(db, office_code)
    division = office.division_code if office else "1000"

    # 정규화 키로 합쳐야 '매출 01-…'처럼 쪼개진 발생·반제가 한 감정서로 상계된다.
    meta = _doc_meta(db, division, account, dc, gen_dc, as_of=as_of)

    search = _search_key(doc_query)
    items: "list[dict[str, Any]]" = []
    excluded_count = 0
    excluded_amount = 0.0
    settled_only = 0   # 검색어엔 걸렸는데 잔액이 0이라 목록에 못 넣은 감정서
    for key, m in meta.items():
        docs = m["members"]
        if search and not _doc_matches(
            search, docs[0] if docs else key, docs, ", ".join(m["raws"])
        ):
            continue
        if m["balance"] <= 0:
            if search:
                settled_only += 1
            continue
        if not search and date_from and date_to and (
            m["gen_date"] is None or not (date_from <= m["gen_date"] <= date_to)
        ):
            continue
        single = len(docs) == 1
        if not single and not include_nonstd and not search:
            excluded_count += 1
            excluded_amount += m["balance"]
            continue
        display = docs[0] if docs else key
        others = [x for x in m["raws"] if x != display]
        items.append({
            "doc": display,
            "members": docs,
            "raw": ", ".join(others) if others else None,   # 합쳐진 원본 표기
            "partner": m["partner"],
            "gen_date": _iso(m["gen_date"]),          # 발생일
            "date": _iso(m["last_settle"]),           # 최종 반제일
            "gen_amount": m["gen_amount"],
            "amount": m["settle_amount"],             # 반제 누계
            "balance": m["balance"],                  # 남은 잔액
            "std": single,
            "remark": m["remark"],
        })
    items.sort(key=lambda i: i["gen_date"] or "")
    return {
        "kind": kind,
        "mode": "open",
        "period": (
            {"from": date_from.isoformat(), "to": date_to.isoformat()}
            if date_from and date_to and not search else None
        ),
        "as_of": as_of.isoformat(),
        "doc_query": doc_query.strip(),
        "settled_only": settled_only,
        "count": len(items),
        "total": sum(i["balance"] for i in items),
        "excluded": {"count": excluded_count, "amount": excluded_amount},
        "items": items,
    }


def banje_export(
    db: Session,
    kind: str,
    mode: str,
    date_from: "date | None",
    date_to: "date | None",
    office_code: str = "10",
    date_basis: str = "settle",
    include_nonstd: bool = False,
    as_of: "date | None" = None,
    doc_query: str = "",
) -> "tuple[str, list[tuple[str, str]], list[dict[str, Any]]]":
    """엑셀 내보내기용 (파일명, 컬럼, 행) — 화면에 보이는 표와 같은 구성.

    데스크톱 앱(pywebview)은 브라우저식 다운로드를 못 해서 화면에서 만든 CSV를
    저장할 수 없다. 그래서 서버가 파일을 만들어 주고 A10_DOWNLOAD가 받아간다.
    """
    lb = _LABELS[kind]
    doc_query = (doc_query or "").strip()
    if mode == "open":
        data = banje_open_list(
            db, kind, date_from, date_to, office_code, include_nonstd, as_of, doc_query
        )
        columns = [
            ("doc", "감정서번호"), ("partner", "거래처"),
            ("gen_date", lb["gen_date"]), ("date", lb["last_settle"]),
            ("gen_amount", lb["gen_amount"]), ("amount", lb["settle_cum"]),
            ("balance", "잔액"), ("remark", "적요"),
            ("members_text", "구성 감정서"), ("raw", "원본 관리번호"),
        ]
        period = f"{date_from}_{date_to}_" if data.get("period") else ""
        name = f"{lb['kind']}미반제_{period}기준{data['as_of']}"
    else:
        data = banje_list(db, kind, date_from, date_to, office_code, date_basis, doc_query)
        columns = [
            ("doc", "감정서번호"), ("partner", "거래처"),
            ("gen_date", lb["gen_date"]), ("date", lb["settle_date"]),
            ("gen_amount", lb["gen_amount"]), ("amount", lb["settle_amount"]),
            ("balance", "잔액"), ("remark", "적요"),
            ("members_text", "구성 감정서"), ("raw", "원본 관리번호"),
        ]
        basis = lb["basis_gen"] if date_basis == "gen" else lb["basis_settle"]
        name = f"{lb['kind']}반제_{basis}기준_{date_from}_{date_to}"

    # 번호 검색은 기간을 안 걸었으므로 파일명에도 기간 대신 검색어를 남긴다.
    if doc_query:
        # 시트 이름에 못 쓰는 글자를 뺀다 (openpyxl이 \ / : * ? [ ] 에서 터진다).
        safe = re.sub(r'[\\/:*?"<>|\[\]]', "", doc_query)[:40]
        name = f"{lb['kind']}{'미반제' if mode == 'open' else '반제'}_검색_{safe}"

    # 엑셀에서 날짜로 인식되게 ISO 문자열을 date로 되돌린다 (없으면 빈 칸).
    # 묶음 표기는 풀어낸 감정서 목록과 원본 관리번호를 함께 남겨 추적이 끊기지 않게 한다.
    rows = [
        {**item,
         "gen_date": date.fromisoformat(item["gen_date"]) if item.get("gen_date") else None,
         "date": date.fromisoformat(item["date"]) if item.get("date") else None,
         "members_text": ", ".join(item.get("members") or []) if len(item.get("members") or []) > 1 else ""}
        for item in data["items"]
    ]
    return name, columns, rows
