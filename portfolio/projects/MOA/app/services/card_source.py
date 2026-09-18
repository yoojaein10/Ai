"""카드내역 원천 DB(Branch.dbo.CB2_APPR, 카드사 API 수집분) → CardUsage 변환.

재무팀 엑셀 업로드와 같은 파이프라인(card_vouchers)에 태우기 위한 읽기 전용 조회.
dedup_key가 카드번호·사용일·승인번호로 만들어지므로 같은 승인건이 엑셀과 DB
양쪽에서 와도 전표는 한 번만 생성된다.

엑셀과 다른 점:
  - 사용용도: DB의 USE_CD는 숫자코드고 채움율도 낮아 비워 둔다 →
    '계정 미매핑' 보류로 표시되고 화면에서 담당자가 지정한다.
  - 사용자: CB2_CARD.USER_NM을 (BANK_CD, CARD_NO)로 연결해 우선 사용한다.
    카드 마스터에 이름이 없을 때만 승인행 Use_Name, 과거 결제 이력 순으로 보완한다.
  - 공제여부: DB는 Y/X/N — Y만 공제대상으로 본다.
  - 지사 카드 제외: 원천에는 지사 카드가 섞여 온다(2026-08-20 실측, 8/1~8/19
    1,043건 중 195건). 카드전표는 본사 전용이라 본사 사업자번호(Sa_No)로 거른다.
  - Bank_Cd='Excel'(과거 수기 업로드분)은 제외한다 — 사업자번호·공제여부가
    전부 비어 있어 쓸 수 없고, 재무팀 엑셀 업로드 경로와 중복이다 (2026-08-03,
    7월 실측: Excel 1,095건 전부 사업자번호 없음·공제Y 0건).
"""

from __future__ import annotations

import re
import time
from decimal import Decimal
from typing import Any

import pyodbc

from app.config import get_settings
from app.services.card_vouchers import CardUsage

MAX_ROWS = 2000  # 한 번에 불러올 최대 건수 — 넘으면 기간을 좁혀 다시 조회하게 한다


class CardSourceError(Exception):
    """카드내역 DB 조회 실패."""


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _text(value: Any) -> str:
    return str(value or "").strip()


def _amount(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return Decimal("0")


# 업종 뒤에 붙는 분류코드 — '택시(5306)'의 (5306). 괄호 안이 글자인 것은
# 업종명의 일부라 건드리면 안 된다 ('PG일반(비인증)', '우체국(우편요금)').
_INDUSTRY_CODE = re.compile(r"\(\s*\d+\s*\)\s*$")


def _industry(value: Any) -> str:
    """업종 표기를 재무팀 엑셀과 맞춘다 — 엑셀은 '택시', 원천은 '택시(5306)'.

    2026-08-20 실측(최근 180일 110종): 괄호가 붙은 24종 중 18종이 숫자코드,
    6종은 업종명 일부였다.
    """
    return _INDUSTRY_CODE.sub("", _text(value)).strip()


def _format_time(value: Any) -> str:
    """APPR_TIME을 엑셀 승인시간과 같은 HH:MM:SS로 맞춘다 (형식이 다르면 원문 유지)."""
    t = _digits(value)
    if len(t) == 6:
        return f"{t[:2]}:{t[2:4]}:{t[4:6]}"
    return _text(value)


# 과세정보 — CB2_APPR.CHAIN_TYPE(가맹점 과세유형 코드).
#
# 코드표를 못 찾았다 — Branch DB 에는 BankCode·DZ_Code 뿐이고, 카드정보.xlsx 는
# CB2_CARD 명세뿐이다. 대신 여신금융협회 표준(1=일반과세·2=간이과세·3=면세)에
# 데이터가 그대로 맞아떨어져 2026-08-21 사용자 결정으로 그 이름을 붙였다.
#
# 근거 (본사 2026-05 이후 실측). 부가세와 공제가 **동시에** 맞는다 —
# 간이과세자·면세사업자는 매입세액 공제가 안 되므로 이 모양이어야 한다.
#   코드  건수    부가세있음  공제Y   가맹점
#    1   3,819    3,695    1,701   SK주유소 등          → 일반과세
#    2      33        0        0   일식·일반음식점        → 간이과세
#    3      14        0        0   정육·농수산·의원       → 면세
#    4       5        0        0   비영리·사찰           → 면세(비영리)
#    0      38        0        0   전기차충전·유흥주점·Google  ← 미확인
#    7      25       25        6   단란주점·포장마차·커피      ← 미확인(부가세는 있다)
#    6       1        0        0   주차장(상인회)            ← 미확인
#
# 모르는 코드에 이름을 붙이지 않는다 — 재무팀이 잘못된 글자를 믿게 된다.
# 카드사·재무팀 확인이 오면 아래 표에 한 줄씩 채우면 된다.
_TAX_INFO_LABELS = {
    "1": "일반과세",
    "2": "간이과세",
    "3": "면세",
    "4": "면세(비영리)",
}


def tax_info_label(value: Any) -> str:
    """과세유형 코드 → 화면 글자. 뜻이 확인된 코드만 이름으로 바꾼다."""
    code = _text(value)
    if not code:
        return ""
    return _TAX_INFO_LABELS.get(code, f"코드 {code}")


def row_to_usage(row: dict[str, Any], row_no: int) -> CardUsage:
    """CB2_APPR 1행 → CardUsage. 엑셀 파서와 같은 정규화 규칙을 쓴다."""
    usage = CardUsage(
        row_no=row_no,
        card_no=_digits(row.get("CARD_NO")),
        card_alias="",
        user_name=_text(row.get("Use_Name")),
        use_date=_digits(row.get("APPR_DATE"))[:8],
        appr_no=_text(row.get("APPR_NO")),
        merchant=_text(row.get("CHAIN_NM")),
        merchant_biz_no=_digits(row.get("CHAIN_ID")),
        total=_amount(row.get("APPR_AMT")),
        supply=_amount(row.get("SUPPLY_AMT")),
        vat=_amount(row.get("APPR_TAX")),
        purpose="",
        deductible=_text(row.get("DEDUCT_YN")).upper() == "Y",
        canceled=_text(row.get("CANCEL_YN")).upper() in ("Y", "1"),
        appr_time=_format_time(row.get("APPR_TIME")),
        # 업종은 BRANCH_TYPE에 들어온다 — 엑셀의 '업종' 칸과 같은 자리다.
        industry=_industry(row.get("BRANCH_TYPE")),
        # 과세정보는 CHAIN_TYPE(가맹점 과세유형 코드)이다. 2026-08-21 재무팀이
        # 채워 넣어 본사 8월 937건 전부에 값이 있다. 코드 뜻은 tax_info_label 참조.
        tax_info=tax_info_label(row.get("CHAIN_TYPE")),
    )
    usage.remark = usage.auto_remark
    return usage


_SQL = """
SELECT a.CARD_NO, a.APPR_DATE, a.APPR_TIME, a.APPR_NO,
       COALESCE(NULLIF(RTRIM(c.USER_NM), ''), NULLIF(RTRIM(a.Use_Name), '')) AS Use_Name,
       a.CHAIN_NM, a.CHAIN_ID, a.APPR_AMT, a.APPR_TAX, a.SUPPLY_AMT,
       a.DEDUCT_YN, a.CANCEL_YN, a.BRANCH_TYPE, a.CHAIN_TYPE
FROM dbo.CB2_APPR a
LEFT JOIN dbo.CB2_CARD c
  ON c.BANK_CD = a.Bank_Cd AND c.CARD_NO = a.CARD_NO
WHERE a.APPR_DATE >= ? AND a.APPR_DATE <= ? AND LEN(a.APPR_DATE) = 8
  AND ISNULL(RTRIM(a.Bank_Cd), '') <> 'Excel'
-- 최근 승인분부터 본다 (화면·엑셀이 이 순서를 그대로 쓴다).
ORDER BY a.APPR_DATE DESC, a.APPR_TIME DESC, a.APPR_NO DESC
"""

# 본사 사업자번호 조건. Sa_No 가 varchar 라 CAST 를 붙여야 인덱스를 쓴다
# (안 붙이면 파라미터가 NVARCHAR 로 가서 풀스캔한다).
_HQ_FILTER = "  AND RTRIM(a.Sa_No) = CAST(? AS varchar(300))\n"


# 카드번호 → 명의자. 결제 이력에서 되짚는 것이라 명부는 아니다 — 카드를 넘기면
# 옛 이름이 남으므로 최근 승인분을 이긴 것으로 본다(실측 167장 중 22장이 이름 둘 이상).
_OWNER_SQL = """
SELECT CARD_NO, RTRIM(Use_Name) AS Use_Name, MAX(APPR_DATE) AS last_date, COUNT(*) AS cnt
FROM dbo.CB2_APPR
WHERE ISNULL(RTRIM(Use_Name), '') <> '' AND LEN(APPR_DATE) = 8
GROUP BY CARD_NO, RTRIM(Use_Name)
"""

OWNER_CACHE_TTL = 900   # 명의자는 자주 바뀌지 않는다 — 전표 만드는 동안만 잡아 둔다
_owner_cache: "tuple[float, dict[str, str]] | None" = None


def _conn_str(settings) -> str:
    return (
        f"DRIVER={{{settings.mssql_driver}}};"
        f"SERVER={settings.card_source_server};DATABASE={settings.card_source_db};"
        f"UID={settings.card_source_user};"
        f"PWD={settings.card_source_password.get_secret_value()};"
        f"Encrypt={settings.mssql_encrypt};"
        f"TrustServerCertificate={settings.mssql_trust_server_certificate};"
    )


def fetch_card_owners() -> dict[str, str]:
    """카드번호 → 명의자. 조회에 실패하면 빈 dict — 화면은 그대로 동작한다.

    한 번 훑는 데 0.3초라(458행) 그때그때 다시 묻지 않고 잠시 보관한다.
    """
    global _owner_cache
    now = time.monotonic()
    if _owner_cache is not None and now - _owner_cache[0] < OWNER_CACHE_TTL:
        return _owner_cache[1]

    settings = get_settings()
    if not settings.is_card_source_configured:
        return {}
    try:
        with pyodbc.connect(_conn_str(settings), timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute(_OWNER_SQL)
            rows = cursor.fetchall()
    except pyodbc.Error:
        # 명의자는 있으면 좋은 값이지 없으면 못 쓰는 값이 아니다.
        return _owner_cache[1] if _owner_cache else {}

    best: dict[str, tuple[str, int, str]] = {}
    for card_no, name, last_date, count in rows:
        card = _digits(card_no)
        if len(card) < 10:
            continue
        rank = (str(last_date or ""), int(count or 0))
        current = best.get(card)
        if current is None or rank > (current[0], current[1]):
            best[card] = (rank[0], rank[1], _text(name))
    owners = {card: name for card, (_d, _c, name) in best.items()}
    _owner_cache = (now, owners)
    return owners


def fetch_usages(date_from: str, date_to: str) -> list[CardUsage]:
    """승인일(YYYYMMDD) 기간으로 CB2_APPR을 조회해 CardUsage 목록으로 만든다."""
    settings = get_settings()
    if not settings.is_card_source_configured:
        raise CardSourceError("카드내역 DB 설정이 없습니다 (.env의 CARD_SOURCE_*).")
    conn_str = _conn_str(settings)
    sql, params = _SQL, [date_from, date_to]
    hq_reg_no = (settings.card_source_hq_reg_no or "").strip()
    if hq_reg_no:
        marker = "-- 최근 승인분부터"
        sql = sql.replace(marker, _HQ_FILTER + marker, 1)
        params.append(hq_reg_no)
    try:
        with pyodbc.connect(conn_str, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchmany(MAX_ROWS + 1)
    except pyodbc.Error as exc:
        raise CardSourceError(f"카드내역 DB 조회에 실패했습니다: {exc}") from exc
    if len(rows) > MAX_ROWS:
        raise CardSourceError(
            f"기간 내 카드내역이 {MAX_ROWS}건을 넘습니다. 기간을 좁혀 조회하세요."
        )
    return [
        row_to_usage(dict(zip(columns, row)), row_no)
        for row_no, row in enumerate(rows, start=1)
    ]
