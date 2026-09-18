"""협회 업무실적 보고 — 반월 감정서 선택 + 협회양식 매핑(읽기전용 재현).

절차:
  1) 대상 감정서 선택 — (지사, 반월, 기준)으로 DocID 목록을 고른다.
  2) 협회양식 매핑 — 원본 SP(LAW_SOURCETOLAW_NEW)의 SELECT를 읽기전용으로 재현.
     선택한 DocID를 세션 임시테이블 #SEL에 넣고 프리즈된 SQL을 돌린다.
     원본 테이블(LAW_KAPATOLAW, APW_REPAPP)에는 쓰지 않는다.

기준(basis):
  - 접수: APW_MASTER.ReceiptDate 가 반월 내
  - 전례: JUN_MASTER.JUNDATE 가 반월 내
  - 매출(입금): 반월 내 입금(APW_IW_INDATE/VIEW_INCOMMING) 또는
                (발송완료가 반월 내 AND (매출계상 반월 내 OR 발송기준 목적))
  (2026-05 상반 실파일로 recall 123/124, 셀대조 검증. work-report-kapa 메모리 참조)
"""

import calendar
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_source_engine

Basis = Literal["접수", "전례", "매출"]
Half = Literal["상반", "하반"]

# 발송완료만으로 실적에 잡는 목적(협회 CommonCode) — 원본 SP(SP_YJI_JunKais_Chk)의
# 판정을 읽기전용으로 옮긴 것. SP는 발주처가 주택도시보증공사(HUG)냐에 따라 다른
# 목록을 본다.
HUG_PRODUCTION = "주택도시보증공사"
HUG_SEND_FROM = "2026-02-27"  # SP가 HUG 갈래를 적용하는 발송일 하한
HUG_SEND_CODES = ("5A", "97", "46", "33")

# HUG가 아닌 건 — SP의 BETWEEN 범위와 목록을 그대로 옮긴다.
GENERAL_SEND_RANGES = (("21", "27"), ("31", "3C"), ("62", "67"))
GENERAL_SEND_RANGE_EXCLUDED = ("39", "3A")  # 31~3C 안에서 SP가 빼는 두 코드
GENERAL_SEND_CODES = ("72", "75", "76", "77", "92", "93", "95", "9C", "9E", "9H", "9I")

# 61(법원경매)은 SP 범위(62~67)에서 빠져 있으나 협회 제출 실파일에는 들어 있다.
# 갈래와 무관하게 넣는 예외. (2026-05 상반 실파일 recall 123/123로 확인)
SEND_BASIS_EXTRA_CODES = ("61",)

# 협회 업무실적 대상이 아닌 목적(공동주택가격 자문) — 항상 제외.
EXCLUDED_PURPOSE_CODES = ("81",)

# 유동화자산(44)은 감정평가 실적으로 협회에 보고하지 않는다 (2026-09-07 재무팀 확인,
# 01-2604-7-0035·0036 계기). 81(공동주택가격 자문)과 달리 정상 감정수수료가 있어
# 보수기준(fee_basis) 점검에는 남아야 하므로, _COMMON(= fee_basis 가 공유) 에서 빼지
# 않고 업무실적 산출(build_kapa_rows)에서만 뺀다. 매핑 결과의 PCODE = 협회 목적코드.
# ⚠ 과거 협회 보고이력(APW_REPAPP)엔 유동화자산 7건이 있으나(옛 보고분) 다른 회차라
# 이 제외와 충돌하지 않는다 — 앞으로의 산출에서만 뺀다.
NON_TARGET_PURPOSE_CODES = ("44",)

# 감정수수료 계정. 입금 신호로만 잡힌 감정서에 이 계정 계상이 한 번도 없으면
# 실비·기타수수료만 오간 건(예: 01-2604-3-1309)이라 기본 체크 해제 대상으로 표시.
# 입금원장(APW_IW_INDATE) INmoney는 대부분 비어 있어 금액으로는 못 거른다(2026-07-28 실측).
FEE_ACCOUNT_CODE = "4010001"

# 업무 대분류(apw_masterex.LWorkinfo) 기준 판정 — 기간별 매출실적·상여·데이터품질 등
# 다른 화면이 모두 이 컬럼을 쓴다(sales_stats.CATEGORIES 14종). 협회 목적코드(PCODE)가
# 아니라 사내 대분류로 맞춘 것은 화면 간 집계가 갈리지 않게 하기 위해서다.
CONSULTING_WORK = "컨설팅"
REDEVELOPMENT_WORK = "정비사업"

# 자동 모집단이 바뀌면 보수기준 스냅숏 캐시가 옛 행 목록을 계속 내준다 — 이 값을 올려
# 배포 직후 한 번에 재생성시킨다. (fee_basis._rule_versions 가 읽는다)
POPULATION_VERSION = "wr-population/precedent-1"

# 컨설팅은 감정수수료 1천만원까지만 업무실적 대상 — **초과**만 비대상이다.
# 금액은 APW_BILL.SUSU(부가세 별도 순수수료) — 협회 양식에 찍히는 값과 같다.
#
# 경계가 '이하'인 근거는 재무팀 원본 파일 대조다(2026-08-06):
#   ★26.04월업무실적보고 상반의 컨설팅 6건 중 3건이 정확히 10,000,000원인데 파일에 들어 있다
#   (01-2601-5-0008 / 01-2601-5-0011 / 01-2603-5-0044).
#   반대로 1천만원을 넘는 컨설팅(4,750만·2,786만 등)은 03·04·05월 세 파일 통틀어 0건이다.
# 요청 문구는 '1천만원 미만'이었으나 실제 제출물은 '이하'로 운용된다 — 재무팀 확인 대기.
CONSULTING_FEE_LIMIT = 10_000_000

# 의뢰처가 시군구(관공서)인지 — 협회 의뢰처코드 62가 있지만 매핑 SQL이 그 값을
# 만들지 못해(UFN_LINKNAME 경로에 시군구가 없고 CUSTNAME에 '시군구' 문자열도 0건)
# 의뢰처명 끝단어로 판정한다. '○○시장'이 재래시장을 뜻하는 경우는 제외한다.
GOV_CUST_SUFFIXES = ("구청장", "군수", "시장", "시청", "구청", "군청")
GOV_CUST_EXCLUDE = ("전통시장", "재래시장", "시장상인", "시장번영")

# 매핑 결과의 이름 없는 컬럼(REG/EUB/SAN/BUN1/BUN2)이 오는 고정 위치.
_ADDR_COLUMNS = {18: "REG", 19: "EUB", 20: "SAN", 21: "BUN1", 22: "BUN2"}

# 평가구분(YCODE) 협회 코드표 — 양식 '협회코드' 시트의 고정 목록.
YCODE_NAMES = {
    "00": "일반실적", "10": "표준지공시지가", "15": "표준지공시지가 이의·의견",
    "20": "개별공시지가", "30": "개별공시지가 이의·의견", "32": "표준주택가격",
    "33": "표준주택가격 이의·의견", "35": "개별주택가격", "36": "개별주택가격 이의·의견",
    "38": "표준비주거평가", "39": "표준비주거평가 이의·의견", "40": "지가변동률",
    "50": "중토위", "60": "일반추천", "70": "법원감정", "80": "임대사례",
}


class OfficeNotFoundError(LookupError):
    pass


def half_month_range(year: int, month: int, half: Half) -> tuple[datetime, datetime]:
    """반월 구간 [시작 00:00, 끝 23:59:59]. 상반=1~15, 하반=16~말일."""
    if half == "상반":
        return datetime(year, month, 1), datetime(year, month, 15, 23, 59, 59)
    last = calendar.monthrange(year, month)[1]
    return datetime(year, month, 16), datetime(year, month, last, 23, 59, 59)


def quarter_bungi(year: int, month: int) -> str:
    """협회 양식 A열의 분기값. 예) 2026년 5월 → '20262' (year + 분기번호)."""
    return f"{year}{(month - 1) // 3 + 1}"


@lru_cache
def _mapping_sql_template() -> str:
    path = Path(__file__).with_name("sql") / "work_report_mapping.sql"
    return path.read_text(encoding="utf-8")


def _populate_sel(cursor: Any, appcode: str, bungi: str, mon: int, doc_ids: list[str]) -> None:
    """#SEL(협회양식 매핑의 입력)을 선택된 감정서로 채운다. LAW_KAPATOLAW 대체."""
    cursor.execute(
        "CREATE TABLE #SEL(ID BIGINT, BUNGI CHAR(5), APPCODE CHAR(6), "
        "ID_NUM VARCHAR(30), FUSE CHAR(1), LINKNAME VARCHAR(200), MON INT)"
    )
    if not doc_ids:
        return
    # 감정서 수만큼 바인드를 만들면 SQL Server 한도(2100개)에 걸린다 — 500건씩 끊는다.
    # (검색으로 여러 건을 한 번에 추가하면 실제로 닿는 수치다)
    for start in range(0, len(doc_ids), 500):
        chunk = doc_ids[start:start + 500]
        placeholders = ", ".join("?" for _ in chunk)
        cursor.execute(
            f"""
            INSERT #SEL(ID, BUNGI, APPCODE, ID_NUM, FUSE, LINKNAME, MON)
            SELECT m.MASTERID, ?, ?, m.DocID, 'Y', dbo.UFN_LINKNAME(m.GUBUN_CODE), ?
            FROM APW_MASTER m
                JOIN APW_OFFICE o ON m.Office = o.OfficeID
            WHERE o.MEMBERID = ? AND m.DocID IN ({placeholders})
            """,
            [bungi, appcode, mon, appcode, *chunk],
        )


def _fetch_mapping(cursor: Any) -> tuple[list[str], list[tuple]]:
    """프리즈된 매핑 배치를 실행하고 ID_NUM 컬럼을 가진 결과셋을 돌려준다."""
    while True:
        if cursor.description and any(col[0] == "ID_NUM" for col in cursor.description):
            return [col[0] for col in cursor.description], cursor.fetchall()
        if not cursor.nextset():
            raise RuntimeError("매핑 결과셋을 찾지 못했습니다.")


def _row_to_dict(columns: list[str], row: tuple) -> dict[str, Any]:
    """이름 없는 주소 컬럼(REG/EUB/SAN/BUN1/BUN2)은 고정 위치로 이름을 붙인다."""
    result: dict[str, Any] = {}
    for index, (name, value) in enumerate(zip(columns, row)):
        key = name or _ADDR_COLUMNS.get(index, f"col{index}")
        result[key] = _serialize(value)
    return result


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        return value.strip()
    return value


def _docs_with_fee_voucher(db: Session, doc_ids: list[str]) -> set[str]:
    """감정수수료(4010001) 계상 전표가 한 번이라도 있는 감정서 (GamJunDW 전표캐시).

    management_no는 VARCHAR라 파라미터를 CAST 없이 바인드하면 NVARCHAR 변환
    풀스캔이 난다 — 자리마다 CAST(? AS VARCHAR)로 바인드한다.
    """
    found: set[str] = set()
    doc_ids = [doc for doc in doc_ids if doc]
    for chunk_start in range(0, len(doc_ids), 500):
        chunk = doc_ids[chunk_start:chunk_start + 500]
        placeholders = ", ".join(
            f"CAST(:d{i} AS VARCHAR(500))" for i in range(len(chunk))
        )
        rows = db.execute(
            text(
                "SELECT DISTINCT management_no FROM dbo.a10_voucher_cache "
                f"WHERE account_code = '{FEE_ACCOUNT_CODE}' "
                f"AND management_no IN ({placeholders})"
            ),
            {f"d{i}": doc for i, doc in enumerate(chunk)},
        )
        found.update(str(row[0]).strip() for row in rows)
    return found


def is_government_customer(cust_name: str | None) -> bool:
    """의뢰처가 시군구(관공서)인가. 의뢰처명 끝단어로 본다."""
    name = (cust_name or "").strip()
    if not name or "조합" in name:
        return False
    if any(word in name for word in GOV_CUST_EXCLUDE):
        return False
    return name.endswith(GOV_CUST_SUFFIXES)


def _amount(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _scope_meta_cursor(cursor: Any, doc_ids: list[str]) -> dict[str, dict[str, Any]]:
    """화면 판정용 보조 정보 — 사내 대분류·의뢰처·선례(감정평가정보체계) 전송여부.

    매핑 SQL(work_report_mapping.sql)에는 컬럼을 끼워 넣지 않는다. _ADDR_COLUMNS가
    결과셋 18~22 '위치'를 주소 컬럼 이름으로 고정 해석해서, 중간에 컬럼이 하나만
    들어가도 REG/EUB/SAN/BUN1/BUN2가 조용히 한 칸씩 밀린다.
    """
    meta: dict[str, dict[str, Any]] = {}
    docs = [doc for doc in doc_ids if doc]
    for start in range(0, len(docs), 500):
        chunk = docs[start:start + 500]
        placeholders = ", ".join("?" for _ in chunk)
        cursor.execute(
            "SELECT RTRIM(x.DocID), RTRIM(ISNULL(x.LWorkinfo, '')), "
            "RTRIM(ISNULL(x.CustName, '')), "
            "MAX(CASE WHEN j.IsPublic = 'Y' THEN 1 ELSE 0 END), "
            "MAX(CASE WHEN j.KABAPISENDDATE IS NOT NULL THEN 1 ELSE 0 END) "
            "FROM apw_masterex x "
            "LEFT JOIN JUN_MASTER j ON j.ID_NUM = x.DocID "
            f"WHERE x.DocID IN ({placeholders}) "
            "GROUP BY RTRIM(x.DocID), RTRIM(ISNULL(x.LWorkinfo, '')), "
            "RTRIM(ISNULL(x.CustName, ''))",
            chunk,
        )
        for doc, work, cust, is_public, sent in cursor.fetchall():
            meta[str(doc).strip()] = {
                "work": (work or "").strip(),
                "cust": (cust or "").strip(),
                "is_public": bool(is_public),
                "sent": bool(sent),
            }
    return meta


def _drop_non_target_purposes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """협회 업무실적 비대상 목적(유동화자산 등) 행을 뺀다.

    PCODE 는 매핑 결과의 협회 목적코드다. 81 처럼 아예 안 나가야 하는 건이라 화면 표시가
    아니라 목록에서 제거한다. 원본·보수기준 모집단은 그대로 두고 여기(업무실적)서만 뺀다.
    """
    return [
        item
        for item in items
        if str(item.get("PCODE") or "").strip() not in NON_TARGET_PURPOSE_CODES
    ]


def _adjust_doc_ids(
    selected: list[str], extra: list[str] | None, exclude: list[str] | None
) -> list[str]:
    """자동 선택분에 수기 추가(extra)를 더하고 수기 제외(exclude)를 뺀다. 순서·중복 정리."""
    dropped = set(exclude or ())
    result = list(dict.fromkeys([*selected, *(extra or ())]))
    return [doc_id for doc_id in result if doc_id not in dropped]


def build_kapa_rows(
    db: Session, *, office_id: str, year: int, month: int, half: Half, basis: Basis,
    extra_doc_ids: list[str] | None = None, exclude_doc_ids: list[str] | None = None,
    only_doc_ids: list[str] | None = None,
) -> dict[str, Any]:
    """협회양식 데이터 행 생성. 원본 무변경(세션 임시테이블만 사용).

    extra_doc_ids: 자동선택에 없어도 수기로 추가할 감정서.
    exclude_doc_ids: 자동선택에서 수기로 뺄 감정서.
    only_doc_ids: 주면 자동선택을 아예 하지 않고 이 목록만 매핑한다 — 저장본 복원용
        (2026-09-07). 자동선택 SQL 을 건너뛰어 복원이 빠르다. 다만 NO_FEE(실비만 입금)·
        NOT_SENT 는 자동선택 맥락에서만 나오는 값이라 복원 목록에는 붙지 않는다.
        그 판단은 이미 저장된 체크 상태(excluded)에 반영돼 있다.
    """
    if not office_id.isalnum():
        raise ValueError("office_id 형식이 올바르지 않습니다.")
    start, end = half_month_range(year, month, half)
    bungi = quarter_bungi(year, month)

    # #IN(반월 내 입금 감정서)과 #SEL은 같은 물리 커넥션에서만 살아있으므로 raw로 처리한다.
    raw = get_source_engine().raw_connection()
    try:
        cursor = raw.cursor()
        appcode = _resolve_appcode_cursor(cursor, office_id)
        # 저장본 복원 — 자동선택을 돌리지 않고 저장된 목록만 매핑한다.
        if only_doc_ids is not None:
            selected: list[str] = []
            auto_extra_set: set[str] = set()
            doc_ids = _adjust_doc_ids(
                list(only_doc_ids), extra_doc_ids, exclude_doc_ids
            )
            no_fee_docs: set[str] = set()
            return _map_and_build(
                cursor, db, appcode, bungi, month, doc_ids,
                no_fee_docs, auto_extra_set,
            )
        if basis == "매출":
            _create_sales_temp(cursor, start, end)
        # 정비사업+시군구는 발송 전이라도 선례 대상이라 기준과 무관하게 합친다.
        # selected 에 넣지 않고 extra 슬롯으로 보낸다 — selected 에 넣으면 매출기준의
        # 실비만 판정(NO_FEE)에 걸려 엉뚱하게 기본 체크가 해제된다.
        selected, auto_extra = select_doc_ids_with_precedent(
            cursor, appcode, bungi, month, start, end, basis
        )
        auto_extra_set = set(auto_extra)
        doc_ids = _adjust_doc_ids(
            selected, [*(extra_doc_ids or []), *auto_extra], exclude_doc_ids
        )

        # 입금 신호로만 잡혔는데 감정수수료(4010001) 계상이 전혀 없는 건 = 실비만 입금.
        # 5월 실파일 recall 무손실 검증(2026-07-28). 수기 추가분은 검사하지 않는다.
        no_fee_docs = set()
        if basis == "매출" and selected:
            cursor.execute(
                _select_sales_send_only_sql(), [appcode, bungi, month, start, end]
            )
            send_matched = {str(row[0]).strip() for row in cursor.fetchall() if row[0]}
            deposit_only = [doc for doc in selected if doc not in send_matched]
            no_fee_docs = set(deposit_only) - _docs_with_fee_voucher(db, deposit_only)
        return _map_and_build(
            cursor, db, appcode, bungi, month, doc_ids, no_fee_docs, auto_extra_set,
        )
    finally:
        raw.close()


def _map_and_build(
    cursor: Any, db: Session, appcode: str, bungi: str, month: int,
    doc_ids: list[str], no_fee_docs: set[str], auto_extra_set: set[str],
) -> dict[str, Any]:
    """선택된 감정서를 #SEL 에 넣고 협회양식 매핑을 돌려 화면 행을 만든다.

    자동선택 경로와 저장본 복원 경로가 같은 매핑을 쓰도록 뽑아 둔 것이다.
    """
    _populate_sel(cursor, appcode, bungi, month, doc_ids)
    if not doc_ids:
        return {"bungi": bungi, "month": month, "appcode": appcode, "columns": [], "rows": []}
    sql = _mapping_sql_template().format(BUNGI=bungi, APPCODE=appcode, MON=month)
    cursor.execute(sql)
    columns, rows = _fetch_mapping(cursor)
    purpose_names = _purpose_names(cursor)
    items = [_row_to_dict(columns, row) for row in rows]
    # 유동화자산 등 협회 업무실적 비대상 목적은 목록에서 뺀다(원본·보수기준은 그대로).
    items = _drop_non_target_purposes(items)
    scope = _scope_meta_cursor(cursor, doc_ids)
    for item in items:  # 화면 표시용 키 (엑셀·협회 전송은 화이트리스트라 새지 않는다)
        doc_id = str(item.get("ID_NUM") or "").strip()
        info = scope.get(doc_id) or {}
        work = info.get("work", "")
        item["PNAME"] = purpose_names.get(str(item.get("PCODE") or "").strip(), "")
        item["YNAME"] = YCODE_NAMES.get(str(item.get("YCODE") or "").strip(), "")
        item["NO_FEE"] = doc_id in no_fee_docs
        item["WORK_INFO"] = work
        # 컨설팅 + 수수료 1천만원 이상 = 업무실적 비대상.
        # 모집단 SQL에서 빼지 않고 여기서 표시만 한다 — _select_doc_ids_cursor 는
        # fee_basis 가 그대로 import 해 쓰고 있어 건드리면 보수기준 점검 화면과
        # 실파일 recall 회귀가 같이 흔들린다. 화면은 기본 체크 해제로 보여준다.
        item["OUT_OF_SCOPE"] = bool(
            work == CONSULTING_WORK
            and _amount(item.get("SUSU")) > CONSULTING_FEE_LIMIT
        )
        # 선례(감정평가정보체계) — 대상 판정은 우리가 다시 하지 않는다.
        # JUN_MASTER.IsPublic 이 이미 사람이 내린 판정이다(실측: IsPublic='Y'의
        # 49.4%가 전송됨, 'N'은 0.2%). KABAPISENDDATE 는 실제 전송 이력이다.
        item["PRECEDENT"] = bool(info.get("is_public"))
        item["PRECEDENT_SENT"] = bool(info.get("sent")) if info.get("is_public") else None
        # 요구사항의 규칙(정비사업 + 시군구 의뢰)에는 맞는데 IsPublic 이 안 잡힌 건.
        # 판정 누락 후보라 확인만 띄운다 — 우리가 대상으로 바꾸지는 않는다.
        # (실측: 정비사업 시군구 63건 중 44건이 IsPublic='Y', 조합은 186건 중 31건)
        item["PRECEDENT_CANDIDATE"] = bool(
            not info.get("is_public")
            and work == REDEVELOPMENT_WORK
            and is_government_customer(info.get("cust"))
        )
        # 발송 전인데 선례 규칙으로 끌어온 건. 발송일·수수료·물건구분이 비어 있어
        # (미발송의 구조적 결과) 담당자가 협회 양식을 채워야 한다 — 화면에 건수로 알린다.
        item["NOT_SENT"] = doc_id in auto_extra_set
    return {
        "bungi": bungi, "month": month, "appcode": appcode,
        "columns": columns, "rows": items,
    }


# --- raw 커서 버전 헬퍼 (temp 테이블 공유를 위해 SQLAlchemy 커넥션 대신 DBAPI 커서 사용) ---

def _resolve_appcode_cursor(cursor: Any, office_id: str) -> str:
    cursor.execute("SELECT RTRIM(MEMBERID) FROM APW_OFFICE WHERE OfficeID = ?", office_id)
    row = cursor.fetchone()
    if row is None or not row[0]:
        raise OfficeNotFoundError(f"지사 매핑이 없습니다: {office_id}")
    return str(row[0]).strip()


def select_doc_ids_with_precedent(
    cursor: Any, appcode: str, bungi: str, mon: int,
    start: datetime, end: datetime, basis: Basis,
) -> tuple[list[str], list[str]]:
    """(기준별 자동선택, 정비사업 선례 추가분). 업무실적·보수기준이 같이 쓴다.

    두 화면이 같은 모집단을 봐야 한다는 원칙(2026-08-06 사용자)을 한 함수로 지킨다.
    _select_doc_ids_cursor 자체는 손대지 않는다 — 실파일 recall 회귀가 걸려 있다.
    """
    selected = _select_doc_ids_cursor(cursor, appcode, bungi, mon, start, end, basis)
    known = set(selected)
    extra = [
        doc for doc in _select_redevelopment_docs(cursor, appcode, bungi, mon, start, end)
        if doc not in known
    ]
    return selected, extra


def _select_redevelopment_docs(
    cursor: Any, appcode: str, bungi: str, mon: int, start: datetime, end: datetime
) -> list[str]:
    """정비사업 + 시군구 의뢰 — 발송 여부와 무관하게 접수 반월로 잡는다.

    도시 및 주거환경정비법에 따라 시장·군수·구청장이 의뢰한 종전·종후 자산평가는
    발송 전이라도 선례 대상이라 협회에 보고한다(2026-08-06 사용자 확인).
    현행 모집단은 _COMMON 의 Status='72'(발송완료)를 요구해서 이 건들이 통째로 빠졌다
    — 실측상 2023-01 이후 접수 7건이 전부 미보고 상태였다.

    ⚠ _COMMON 과 _select_*_sql 은 fee_basis 가 그대로 import 해 쓰므로 한 글자도
    건드리지 않는다. 여기서 **같은 조건을 복사하되 Status 절만 뺀** 별도 갈래를 만든다.
    반월 배정은 접수일이다 — 미발송 건은 전례일(JUN_MASTER.JUNDATE)이 아예 없다(전수 확인).

    축은 협회 목적코드가 아니라 사내 대분류(apw_masterex.LWorkinfo='정비사업')다.
    코드로 잡으면 93·7B·78·79 를 놓치고(실측 50건), 반대로 대분류가 보상·국공유재산인
    건이 12건 딸려온다. 시군구 판정은 매핑 SQL 이 CUSTCODE 62 를 만들지 못해
    의뢰처명으로 한다(정답지 대조 재현율 98.1%).
    """
    gov_like = " OR ".join(f"m.CustName LIKE '%{suffix}'" for suffix in GOV_CUST_SUFFIXES)
    gov_not = " AND ".join(
        f"m.CustName NOT LIKE '%{word}%'" for word in ("조합", *GOV_CUST_EXCLUDE)
    )
    cursor.execute(
        "SELECT m.DocID FROM APW_MASTER m "
        "JOIN APW_OFFICE o ON m.Office = o.OfficeID "
        "JOIN apw_masterex x ON x.DocID = m.DocID "
        "LEFT JOIN APW_Purpose p ON m.Purpose = p.Code "
        "WHERE o.MEMBERID = ? "
        # _COMMON 과 같은 조건 — Status 만 뒤집었다. 발송완료 건은 기존 갈래가 이미
        # 자기 발송 반월에 올리므로, 여기서 또 올리면 같은 건이 접수 반월에 한 번 더
        # 뜬다(실측: 15-2512-1-0381 / 02-2512-1-0174 등). NOT_SENT 라벨도 틀리게 붙는다.
        "AND ISNULL(m.[Status], '') <> '72' "
        "AND m.Result <= '10' AND m.Report = 'Y' "
        "AND ISNULL(p.CommonCode, '') NOT IN ('81') "
        "AND NOT EXISTS (SELECT 1 FROM APW_REPAPP r WHERE r.ID_NUM = m.DocID "
        "AND NOT (r.BUNGI = ? AND r.MON = ?)) "
        f"AND RTRIM(ISNULL(x.LWorkinfo, '')) = N'{REDEVELOPMENT_WORK}' "
        f"AND ({gov_like}) AND {gov_not} "
        "AND m.ReceiptDate BETWEEN ? AND ?",
        [appcode, bungi, mon, start, end],
    )
    return [str(row[0]).strip() for row in cursor.fetchall() if row[0]]


def _purpose_names(cursor: Any) -> dict[str, str]:
    """평가목적 협회코드(CommonCode) → 목적명. 화면 표시용."""
    cursor.execute(
        "SELECT RTRIM(CommonCode), MAX(RTRIM(NAME)) FROM APW_PURPOSE "
        "WHERE CommonCode IS NOT NULL AND CommonCode <> '' GROUP BY RTRIM(CommonCode)"
    )
    return {str(row[0]): str(row[1] or "") for row in cursor.fetchall()}


def _create_sales_temp(cursor: Any, start: datetime, end: datetime) -> None:
    """매출기준 보조 임시테이블.

    #IN = 반월 내 입금 감정서(입금원장+준실시간입금을 서버에서 한 번만 스캔).
    선택 쿼리가 감정서마다 입금원장을 상관 EXISTS로 뒤지면 15초가 걸려서(실측),
    윈도 대상을 먼저 모아두고 EXISTS는 임시테이블에만 건다 → 약 2초.
    """
    cursor.execute(
        "CREATE TABLE #IN(docid VARCHAR(30) PRIMARY KEY WITH (IGNORE_DUP_KEY=ON))"
    )
    cursor.execute(
        "INSERT INTO #IN SELECT DISTINCT Docid FROM APW_IW_INDATE "
        "WHERE INDATE BETWEEN ? AND ? AND Docid IS NOT NULL",
        [start, end],
    )
    cursor.execute(
        "INSERT INTO #IN SELECT DISTINCT AppCode FROM VIEW_INCOMMING "
        "WHERE InDate BETWEEN ? AND ? AND AppCode IS NOT NULL",
        [start, end],
    )


def _select_doc_ids_cursor(
    cursor: Any, appcode: str, bungi: str, mon: int, start: datetime, end: datetime, basis: Basis
) -> list[str]:
    common = [appcode, bungi, mon]  # _COMMON 의 ?,?,? 순서
    if basis == "접수":
        sql = _select_receipt_sql()
    elif basis == "전례":
        sql = _select_jun_sql()
    else:  # 매출: 입금은 #IN에 선적재, 여기선 발송(start,end) 창만 바인드
        sql = _select_sales_sql()
    cursor.execute(sql, [*common, start, end])
    return [str(row[0]).strip() for row in cursor.fetchall() if row[0]]


_COMMON = (
    "JOIN APW_OFFICE o ON m.Office = o.OfficeID "
    "LEFT JOIN APW_Purpose p ON m.Purpose = p.Code "
    "WHERE o.MEMBERID = ? AND m.[Status] = '72' AND m.Result <= '10' AND m.Report = 'Y' "
    "AND ISNULL(p.CommonCode, '') NOT IN ('81') "
    "AND NOT EXISTS (SELECT 1 FROM APW_REPAPP r WHERE r.ID_NUM = m.DocID "
    "AND NOT (r.BUNGI = ? AND r.MON = ?)) "
)


def _select_receipt_sql() -> str:
    return f"SELECT m.DocID FROM APW_MASTER m {_COMMON} AND m.ReceiptDate BETWEEN ? AND ?"


def _select_jun_sql() -> str:
    return (
        f"SELECT m.DocID FROM APW_MASTER m JOIN JUN_MASTER j ON m.DocID = j.ID_NUM {_COMMON} "
        "AND j.JUNDATE BETWEEN ? AND ?"
    )


_CC = "ISNULL(RTRIM(p.CommonCode), '')"


def _is_hug_sql() -> str:
    """SP가 HUG 갈래를 타는 조건 — 발주처가 주택도시보증공사이고 발송일이 하한 이후."""
    return f"(m.Production LIKE '%{HUG_PRODUCTION}%' AND m.SendDate >= '{HUG_SEND_FROM}')"


def _send_basis_purposes_sql() -> str:
    """발송완료만으로 실적에 잡히는 목적인지 — SP_YJI_JunKais_Chk의 두 갈래를 옮긴 것."""
    hug = _is_hug_sql()
    hug_codes = ", ".join(f"'{code}'" for code in HUG_SEND_CODES)
    ranges = " OR ".join(
        f"{_CC} BETWEEN '{low}' AND '{high}'" for low, high in GENERAL_SEND_RANGES
    )
    range_excluded = ", ".join(f"'{code}'" for code in GENERAL_SEND_RANGE_EXCLUDED)
    codes = ", ".join(f"'{code}'" for code in GENERAL_SEND_CODES)
    extra = ", ".join(f"'{code}'" for code in SEND_BASIS_EXTRA_CODES)
    return (
        f"(({hug} AND {_CC} IN ({hug_codes})) "
        f"OR (NOT {hug} AND ((({ranges}) AND {_CC} NOT IN ({range_excluded})) "
        f"OR {_CC} IN ({codes}))) "
        f"OR {_CC} IN ({extra}))"
    )


def _sales_send_branch() -> str:
    """매출기준 발송 브랜치 조건(공용) — 선택 SQL과 발송전용 SQL이 같은 문구를 쓴다.

    발송기준 목적만 본다. 예전에는 '반월 내 매출계상'도 같이 인정했는데, 그러면
    입금이 한 푼도 없는 담보·공매 건이 전표를 세웠다는 이유만으로 실적에 들어왔다
    (2026-07 하반 01-2604-3-1065 등 4건). 실적 기준은 '보상·HUG는 발송일, 그 외는
    입금'이므로 매출계상은 근거가 아니다. 2026-05 상반 실파일 recall 123/123 유지.
    """
    return (
        "(m.SendDate BETWEEN ? AND ? "
        f"AND {_send_basis_purposes_sql()})"
    )


def _select_sales_sql() -> str:
    """입금(#IN)은 미리 모아둔 임시테이블만 본다 (성능 — _create_sales_temp 참조)."""
    return (
        f"SELECT m.DocID FROM APW_MASTER m {_COMMON} AND ("
        "EXISTS (SELECT 1 FROM #IN i WHERE i.docid = m.DocID) "
        f"OR {_sales_send_branch()})"
    )


def _select_sales_send_only_sql() -> str:
    """발송 브랜치만으로도 선택되는 감정서 — 나머지(입금 신호 단독)가 수수료 계상 검사 대상."""
    return f"SELECT m.DocID FROM APW_MASTER m {_COMMON} AND {_sales_send_branch()}"
