'감정서 조회 챗봇.\n\n질문을 필터로 바꿔(Gemini) 감정서 DB(`192.0.2.10 / gamjundw` 의 jun 스키마)를 찾고\n마크다운으로 답한다. 실제 조회는 `app/vendor/gamjun_search.py` 가 한다 — 본서버 챗봇과\n같은 코드라 답이 갈리지 않는다. 그 모듈은 손대지 않고 여기서 감싼다.\n\n**본문 키워드 검색은 뺐다.** 벤더 모듈의 키워드 절이\n`LIKE OR (FTS 서브쿼리 IN)` 형태라 OR가 해시 세미조인을 막아 20~40초씩 걸리고,\n한 번은 CPU를 35분 태웠다(app/vendor/README.md 실측표). 소재지·물건종류·목적·기간·\n금액·평가사·감정서번호 검색은 1~4초로 잘 되므로 그것만 연다.\n\n응답 시간의 대부분(1.2초 중 ~1초)은 Gemini 필터 추출 왕복이다. 그래서\n① 같은 질문은 캐시로 바로 답하고(예시 버튼이 특히 덕을 본다),\n② 감정서번호만 묻는 질문은 Gemini 를 아예 건너뛴다.\n'

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.money_chat import office_scope

# 벤더 모듈이 읽는 환경변수. import 전에 채워야 모듈 전역 상수에 들어간다.
_READY = False

# 화면이 지원한다고 말하는 조건. 여기 없는 필터는 답변에서 빼고 안내한다.
SUPPORTED_FILTERS = (
    "region", "regions", "category_use", "categories", "purpose", "client",
    "person", "owner", "debtor", "doc_id", "status", "office", "fee_kind",
    "sort", "want_agg", "group_by", "date_ym_from", "date_ym_to",
    "value_min", "value_max", "fee_min", "fee_max", "area_min", "area_max",
    "unit_min", "unit_max", "_recent", "limit",
)
# 본문(jun.chunk)을 뒤져야 하는 필터 — 지금은 못 쓴다. zone(용도지역)도 본문
# LIKE 전량 스캔이라 같은 급이다 (실측: region 0.3초 vs zone 40초 시한초과).
CONTENT_FILTERS = ("keywords", "want_content", "zone")

_UNSUPPORTED_NOTE = (
    "본문 내용 검색(건물명·평가방법·용도지역 같은 낱말)은 아직 준비 중이라 이번 답에서는 뺐습니다. "
    "소재지·물건종류·목적·기간·평가액·평가사·감정서번호로 물어봐 주세요."
)

# 답변 캐시. 감정서 DB는 하루 단위 배치라 10분이면 낡을 일이 없지만,
# 회계(a10_*)는 10분 주기 배치 + 화면이 라이브 조회라 돈 답변은 60초만 잡는다
# — 챗봇이 화면과 다른 숫자를 10분씩 반복하면 안 된다 (2026-08-04 검토 #5).
_CACHE: dict[tuple[str, str], tuple[float, float, dict[str, Any]]] = {}
_CACHE_TTL = 600.0
_MONEY_CACHE_TTL = 60.0
_CACHE_MAX = 200

_DOC_ID_RE = re.compile(r"\b(\d{2}-\d{4}-[0-9A-Z]-\d{4}(?:-\d+)?)\b")

# 사용자 → 소속 지사. 화면이 보내는 office_code 를 믿지 않고 서버가 직접 푼다
# (2026-08-05: 개발자도구로 office_code 를 바꿔 다른 지사를 보는 구멍을 막는다).
_USER_CACHE: dict[str, tuple[float, "str | None"]] = {}
_USER_TTL = 600.0

# Gemini 필터 추출 캐시 — 같은 질문의 재추출 왕복(~1초)을 아낀다. 답변 캐시(10분)와
# 달리 추출 결과는 데이터 신선도와 무관해 더 오래 들고 있어도 된다. 키에 날짜를 넣어
# '이번 달'류가 자정을 넘겨 낡지 않게 한다.
_XCACHE: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
_XCACHE_TTL = 1800.0
_XCACHE_MAX = 300

# 소속 필터 가속 — 벤더 SQL 의 오피스 서브쿼리는 APW_MASTEREX(HEAP, 73만 행) 전량
# 스캔 + LIKE '%라벨%' 문자열 매칭이라 매 질의 ~0.4초를 문다. 그 테이블은 남의 DB
# (APWORKSDW)라 인덱스를 못 걸어, 우리 DB(gamjundw)에 (DocID, LOffice) 스냅샷을 두고
# 서브쿼리를 바꿔치기한다. LOffice 실측값은 정확 라벨 20종뿐이라, LIKE 의 contains
# 의미를 "값 목록에서 미리 매칭 → IN(등호 시크)"로 그대로 보존하며 인덱스를 태운다
# (제주지사 → 구제주지사 포함 유지). 실측 0.37초 → 0.004초.
# 벤더 파일은 그대로고, 스냅샷이 없거나 낡으면 원본 서브쿼리로 동작한다 (무해 폴백).
_OFFICE_SUBQ = (
    "a.doc_id_raw IN (SELECT axo.DocID FROM APWORKSDW.dbo.APW_MASTEREX axo "
    "WHERE axo.LOffice LIKE %s)"
)
_SNAPSHOT: dict[str, Any] = {"stamp": 0.0, "ok": False, "busy": False, "values": []}
_SNAP_TTL = 6 * 3600.0


def _office_of_user_sync(usr_seq: str) -> "str | None":
    """USR_SEQ → OFFICE_ID. users.py 와 같은 판정(fail-closed: 재직·사용중만)."""
    from sqlalchemy import text  # noqa: PLC0415
    from app.database import get_session_factory  # noqa: PLC0415

    source = get_settings().mssql_source_db
    if not source.replace("_", "").isalnum():
        return None
    db = get_session_factory()()
    try:
        row = db.execute(
            text(
                f"SELECT RTRIM(OFFICE_ID) AS office, RTRIM(USE_YN) AS use_yn, "
                f"RTRIM(RTRM_FL) AS rtrm_fl "
                f"FROM [{source}].dbo.TMWCMN_USR_BAC_INFO WHERE USR_SEQ = :usr"
            ),
            {"usr": int(usr_seq)},
        ).mappings().first()
        if row and row["use_yn"] == "Y" and row["rtrm_fl"] == "0":
            return str(row["office"])
        return None
    finally:
        db.close()


async def office_for_user(usr_seq: "str | int | None") -> "str | None":
    """사용자 소속 지사 코드. 모르는 사용자·퇴사자는 None (조회 거부)."""
    usr = str(usr_seq or "").strip()
    if not usr.isdigit():
        return None
    hit = _USER_CACHE.get(usr)
    if hit and time.time() - hit[0] < _USER_TTL:
        return hit[1]
    try:
        office = await asyncio.to_thread(_office_of_user_sync, usr)
    except Exception:
        # DB 순단이 화면을 통째로 막으면 안 된다 — 낡은 캐시라도 있으면 쓴다.
        return hit[1] if hit else None
    _USER_CACHE[usr] = (time.time(), office)
    return office


def _view_all_sync(usr_seq: str) -> bool:
    """이 사용자가 전 지사를 볼 수 있나. 다른 화면과 같은 판정을 쓴다
    (users.py: 본사(10) 이거나 a10_user_permission.view_all_offices='Y')."""
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    from app.database import get_session_factory  # noqa: PLC0415
    from app.models.user_permission import UserPermission  # noqa: PLC0415

    source = get_settings().mssql_source_db
    if not source.replace("_", "").isalnum():
        return False
    db = get_session_factory()()
    try:
        row = db.execute(
            text(
                f"SELECT RTRIM(OFFICE_ID) AS office, RTRIM(USR_ID) AS usr_id "
                f"FROM [{source}].dbo.TMWCMN_USR_BAC_INFO WHERE USR_SEQ = :usr"
            ),
            {"usr": int(usr_seq)},
        ).mappings().first()
        if not row:
            return False
        if str(row["office"]) == "10":
            return True
        permission = db.scalars(
            select(UserPermission).where(
                UserPermission.usr_id == row["usr_id"], UserPermission.active == "Y"
            )
        ).first()
        return bool(permission and permission.view_all_offices == "Y")
    finally:
        db.close()


_VIEWALL_CACHE: dict[str, tuple[float, bool]] = {}


async def resolve_office(
    usr_seq: "str | int | None", requested: str = ""
) -> "str | None":
    """화면이 고른 지사를 **권한 안에서만** 받아들인다.

    다른 조회 화면과 같은 규칙이다 — 본사·전체조회 권한자는 지사를 골라 볼 수 있고,
    지사 사용자는 셀렉트를 못 바꾼다(화면이 disabled). 화면 값을 그대로 믿으면
    개발자도구로 남의 지사를 볼 수 있으니 서버가 다시 판정한다.
    """
    own = await office_for_user(usr_seq)
    if own is None:
        return None
    want = (requested or "").strip()
    if not want or want == own:
        return own
    return want if await can_view_all(usr_seq) else own


_MENU_CACHE: "dict[str, tuple[float, bool]]" = {}


async def can_view_all(usr_seq: "str | int | None") -> bool:
    """전 지사를 볼 수 있나 (본사이거나 view_all_offices='Y').

    통장 입금 목록처럼 **지사로 나눌 수 없는** 회사 전체 데이터의 문지기다 —
    한 계좌에 전 지사 수수료가 섞여 들어오니 지사별로 자를 방법이 없다.
    """
    usr = str(usr_seq or "").strip()
    if not usr.isdigit():
        return False
    hit = _VIEWALL_CACHE.get(usr)
    if hit and time.time() - hit[0] < _USER_TTL:
        return hit[1]
    try:
        view_all = await asyncio.to_thread(_view_all_sync, usr)
    except Exception:
        view_all = False
    _VIEWALL_CACHE[usr] = (time.time(), view_all)
    return view_all


def _menu_ok_sync(usr_seq: str, menu_key: str) -> bool:
    """이 사람에게 그 메뉴가 켜져 있나. 실패하면 False (막는 쪽)."""
    from app.database import get_session_factory  # noqa: PLC0415
    from app.services.users import UserContextService  # noqa: PLC0415

    db = get_session_factory()()
    try:
        context = UserContextService(db)._resolve(str(usr_seq))  # noqa: SLF001
    except Exception:
        return False
    finally:
        db.close()
    return bool((context.get("menu_permissions") or {}).get(menu_key, False))


async def can_menu(usr_seq: "str | int | None", menu_key: str) -> bool:
    """메뉴 권한 확인. 화면은 메뉴를 숨기지만 API 는 그것과 무관하게 열려 있었다 —
    주소를 아는 사람은 그냥 부를 수 있었다 (2026-08-07 점검).

    화면 숨김과 같은 잣대(menu_permissions)를 서버에서 다시 본다.
    """
    usr = str(usr_seq or "").strip()
    if not usr.isdigit():
        return False
    key = f"{usr}:{menu_key}"
    hit = _MENU_CACHE.get(key)
    if hit and time.time() - hit[0] < _USER_TTL:
        return hit[1]
    try:
        ok = await asyncio.to_thread(_menu_ok_sync, usr, menu_key)
    except Exception:
        ok = False
    _MENU_CACHE[key] = (time.time(), ok)
    return ok


def _snapshot_refresh_sync() -> bool:
    """(DocID, LOffice) 스냅샷을 MERGE 로 맞춘다. 벤더처럼 pymssql 직결 —
    vendor.run_query 는 SELECT 전용이라 못 쓴다."""
    import pymssql  # noqa: PLC0415

    settings = get_settings()
    cn = pymssql.connect(
        server=settings.gamjun_parse_server, user=settings.mssql_user,
        password=settings.mssql_password.get_secret_value(),
        database=settings.gamjun_parse_db, charset="utf8",
        timeout=180, login_timeout=10, autocommit=True,
    )
    try:
        cur = cn.cursor()
        cur.execute(
            "IF OBJECT_ID('dbo.a10_office_doc') IS NULL "
            "BEGIN "
            "  CREATE TABLE dbo.a10_office_doc ("
            "    DocID varchar(40) NOT NULL PRIMARY KEY, LOffice nvarchar(100) NULL); "
            "  CREATE INDEX ix_a10_office_doc_loffice ON dbo.a10_office_doc (LOffice); "
            "END"
        )
        # 원본과 콜레이션이 다를 수 있어 비교·삽입 모두 우리 DB 기본으로 굳힌다.
        cur.execute(
            "MERGE dbo.a10_office_doc AS t "
            "USING (SELECT DocID COLLATE DATABASE_DEFAULT AS DocID, "
            "              MAX(LOffice) COLLATE DATABASE_DEFAULT AS LOffice "
            "       FROM APWORKSDW.dbo.APW_MASTEREX WHERE DocID IS NOT NULL "
            "       GROUP BY DocID) AS s "
            "ON t.DocID = s.DocID "
            "WHEN MATCHED AND ISNULL(t.LOffice, N'') <> ISNULL(s.LOffice, N'') "
            "  THEN UPDATE SET LOffice = s.LOffice "
            "WHEN NOT MATCHED BY TARGET THEN INSERT (DocID, LOffice) VALUES (s.DocID, s.LOffice) "
            "WHEN NOT MATCHED BY SOURCE THEN DELETE;"
        )
        cur.execute("SELECT DISTINCT LOffice FROM dbo.a10_office_doc WHERE LOffice IS NOT NULL")
        values = [str(row[0]).strip() for row in cur.fetchall()]
        _SNAPSHOT["values"] = [v for v in values if v]
        return bool(_SNAPSHOT["values"])
    finally:
        cn.close()


async def _office_snapshot_ready() -> bool:
    """스냅샷이 신선하면 True. 낡았으면 백그라운드로 갱신하고 이번 질의는 원본으로."""
    if time.time() - _SNAPSHOT["stamp"] < _SNAP_TTL:
        return bool(_SNAPSHOT["ok"])
    if not _SNAPSHOT["busy"]:
        _SNAPSHOT["busy"] = True

        async def _job() -> None:
            try:
                ok = await asyncio.to_thread(_snapshot_refresh_sync)
                _SNAPSHOT["stamp"], _SNAPSHOT["ok"] = time.time(), ok
            except Exception:
                _SNAPSHOT["stamp"], _SNAPSHOT["ok"] = time.time(), False
            finally:
                _SNAPSHOT["busy"] = False

        asyncio.get_running_loop().create_task(_job())
    return bool(_SNAPSHOT["ok"])


def _swap_office_sql(sql: str, params: tuple, label: str) -> tuple[str, tuple]:
    """오피스 서브쿼리를 스냅샷 IN(등호) 시크로 바꾼다 — 의미는 LIKE 와 동일.

    LIKE '%라벨%' 이 실제로 맞출 값(contains)을 스냅샷의 실측 값 목록에서 미리 골라
    IN 목록으로 넣는다. 값 목록·파라미터가 안 맞으면 원본 그대로 (무해 폴백).
    """
    if _OFFICE_SUBQ not in sql:
        return sql, params
    matches = [v for v in _SNAPSHOT["values"] if label in v]
    like_param = "%" + label + "%"
    param_list = list(params)
    if not matches or like_param not in param_list:
        return sql, params
    placeholders = ", ".join(["%s"] * len(matches))
    fast = ("a.doc_id_raw IN (SELECT axo.DocID FROM dbo.a10_office_doc axo "
            f"WHERE axo.LOffice IN ({placeholders}))")
    index = param_list.index(like_param)
    param_list[index:index + 1] = matches
    return sql.replace(_OFFICE_SUBQ, fast), tuple(param_list)


async def _office_gate(vendor, doc_id: str, label: str, prefix: str) -> bool:
    """이 감정서를 이 소속이 열어도 되나. 현행 번호는 접두사로 즉답,
    구번호(OB1·400·200… 2007~2018 아카이브)는 원장 소속(LOffice)으로 판정한다
    — 목록(LOffice 기준)에는 나오는데 카드는 못 여는 모순을 없앤다."""
    doc = doc_id.strip()
    if not prefix:  # 전체 조회 권한으로 보는 중 — 지사 제한 없음
        return True
    if doc.startswith(prefix + "-"):
        return True
    try:
        rows = await vendor.run_query(
            "SELECT TOP 1 LOffice FROM APWORKSDW.dbo.APW_MASTEREX WHERE DocID = %s",
            (doc,),
        )
    except Exception:
        return False  # 판정 불가면 닫는다
    return bool(rows) and label in str(rows[0].get("LOffice") or "")


# 원문 DB가 어디까지 담고 있나. 적재가 멈추면(2026-08-05 실측: 7/21 이후 정지)
# 최근 건이 통째로 빠지는데, 그 사실을 답변이 스스로 밝혀야 사용자가 챗봇을
# 의심하지 않는다. 하루 한 번만 재면 충분하다.
_COVERAGE: dict[str, tuple[float, "str | None"]] = {}
_COVERAGE_TTL = 3600.0


async def _jun_coverage() -> "str | None":
    """원문 DB에 들어 있는 가장 최근 접수일 (YYYY-MM-DD). 모르면 None."""
    hit = _COVERAGE.get("all")
    if hit and time.time() - hit[0] < _COVERAGE_TTL:
        return hit[1]
    try:
        rows = await _vendor().run_query(
            "SELECT CONVERT(varchar(10), MAX(receipt_date), 120) d FROM jun.apw_case "
            "WHERE receipt_date IS NOT NULL AND receipt_date <= GETDATE()", ())
        value = str(rows[0]["d"]) if rows and rows[0].get("d") else None
    except Exception:
        return hit[1] if hit else None  # 못 재면 조용히 생략한다
    _COVERAGE["all"] = (time.time(), value)
    return value


async def _coverage_note() -> str:
    """적재가 며칠 이상 밀렸을 때만 붙이는 안내. 하루치 지연은 굳이 말하지 않는다."""
    day = await _jun_coverage()
    if not day:
        return ""
    try:
        behind = (dt.date.today() - dt.date.fromisoformat(day)).days
    except ValueError:
        return ""
    if behind < 3:
        return ""
    return (f"감정서 원문 DB는 {day} 접수분까지 들어와 있습니다(현재 {behind}일 지연). "
            "그 이후 접수 건은 이 검색에 잡히지 않습니다 — 감정서 번호로 물으면 "
            "접수 정보는 원장에서 찾아 드립니다.")


# ── 이름 검색 복원 + 오타 보정 ─────────────────────────────────────────────
# "신한은행" 처럼 축을 안 밝힌 이름은 Gemini 가 본문 키워드로 넣는데, 본문 검색을
# 막아 놨으니 그대로 사라져 "못 알아들었습니다"가 나왔다. 실측으로 이름이 어느
# 축인지는 건수로 갈린다: 신한은행 = 의뢰인 17,863 · 채무자 2 · 소유자 4.
# 그래서 남은 낱말을 네 축에 동시에 물어보고 가장 많이 걸리는 축에 배정한다.
_NAME_AXES = (
    ("client", "client_name", "의뢰인"),
    ("debtor", "debtor_name", "채무자"),
    ("owner", "owner_name", "소유자"),
    ("person", "appraiser", "평가사"),
)
# 질문에서 조건이 될 수 없는 말. 이것만 남으면 축 조회를 걸지 않는다.
_STOP_TERMS = {
    "감정서", "감정", "조회", "목록", "리스트", "보여줘", "보여줘요", "알려줘", "알려줘요",
    "찾아줘", "찾아", "검색", "건수", "건", "얼마", "얼마야", "있어", "있어?", "없어",
    "뭐야", "뭐", "좀", "그", "이", "저", "관련", "내역", "정보", "자료", "최근", "전체",
    "요약", "요약해줘", "상세", "카드", "지사", "본사", "것", "거", "수", "개",
    # 축 이름 자체. 빼두지 않으면 '채무자 조회'의 '채무자'를 거래처명으로 착각한다
    # (실측: client_name LIKE '%채무자%' 가 2건 걸려 엉뚱한 답이 나갔다).
    "채무자", "의뢰인", "의뢰", "소유자", "소유주", "평가사", "감정평가사", "담당", "담당자",
    "거래처", "유치자", "물건", "종별", "목적", "지역", "소재지", "주소", "평가액", "금액",
}
_NAME_LISTS: dict[tuple[str, str], tuple[float, list[str]]] = {}
_NAME_LIST_TTL = 3600.0

_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"


def _ro(word: str) -> str:
    """받침에 맞는 조사 — '채무자로' / '의뢰인으로'. 어색한 '채무자으로'를 막는다."""
    last = (word or "").strip()[-1:]
    if not last:
        return "로"
    code = ord(last) - 0xAC00
    if not 0 <= code < 11172:
        return "로"
    jong = code % 28
    return "로" if jong in (0, 8) else "으로"  # 받침 없음·ㄹ 받침은 '로'


def _jamo(text: str) -> str:
    """한글을 자모로 편다. '은'과 '안'은 음절로는 남남이지만 자모로는 한 끗이라,
    오타를 잡아내려면 이 단위로 재야 한다 (실측: 신한안행↔신한은행 음절 0.75 자모 0.92,
    김철수↔김수영 음절 0.67 자모 0.62 — 자모라야 진짜 오타와 남의 이름이 갈린다)."""
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(_CHO[code // 588])
            out.append(_JUNG[(code % 588) // 28])
            jong = _JONG[code % 28]
            if jong != " ":
                out.append(jong)
        elif not ch.isspace():
            out.append(ch)
    return "".join(out)


def _leftover_terms(question: str, spec: dict[str, Any]) -> list[str]:
    """질문에서 아직 조건으로 안 쓰인 낱말. 이게 이름일 가능성이 있다."""
    used = " ".join(str(v) for v in spec.values() if isinstance(v, str))
    terms = []
    for raw in re.split(r"[\s,·/]+", question):
        token = re.sub(r"[^0-9A-Za-z가-힣()]+$", "", raw).strip()
        if len(token) < 2 or token in _STOP_TERMS or token in used:
            continue
        if _DOC_ID_RE.search(token):
            continue
        terms.append(token)
    return terms[:3]


async def _axis_hits(vendor, term: str, prefix: str) -> "list[tuple[str, int, str]]":
    """이 낱말이 각 이름 축에 몇 건이나 있나 — 네 축을 동시에 센다 (~0.3초)."""
    async def count(column: str) -> int:
        try:
            rows = await vendor.run_query(
                "SELECT COUNT(*) n FROM jun.apw_case WHERE doc_id_raw LIKE %s "
                f"AND {column} LIKE %s",
                (prefix + "-%", "%" + term + "%"),
            )
            return int(rows[0]["n"]) if rows else 0
        except Exception:
            return 0

    counts = await asyncio.gather(*(count(col) for _key, col, _ko in _NAME_AXES))
    hits = [(key, n, ko) for (key, _col, ko), n in zip(_NAME_AXES, counts) if n > 0]
    hits.sort(key=lambda x: -x[1])
    return hits


async def _name_list(vendor, column: str, prefix: str) -> list[str]:
    """오타 보정용 이름 목록 (소속 범위). 21,160개를 0.37초에 읽어 1시간 캐시한다."""
    key = (prefix, column)
    hit = _NAME_LISTS.get(key)
    if hit and time.time() - hit[0] < _NAME_LIST_TTL:
        return hit[1]
    try:
        rows = await vendor.run_query(
            f"SELECT DISTINCT {column} AS v FROM jun.apw_case WHERE doc_id_raw LIKE %s "
            f"AND {column} IS NOT NULL AND {column} <> ''",
            (prefix + "-%",),
        )
        names = [str(r["v"]).strip() for r in rows if r.get("v")]
    except Exception:
        return hit[1] if hit else []
    _NAME_LISTS[key] = (time.time(), names)
    return names


def _closest(term: str, names: list[str], floor: float) -> "tuple[str, float] | None":
    """자모 기준 최유사 이름. 후보를 먼저 줄여 2만 개도 0.01초에 끝난다."""
    import difflib  # noqa: PLC0415

    head = term[:1]
    pool = [n for n in names if n and (n[:1] == head or term[:2] in n)]
    if not pool:
        pool = names
    target = _jamo(term)
    best, score = None, 0.0
    for name in pool:
        # 상호 뒤에는 지점·직위가 길게 붙는다('신한은행 미금동지점장'). 친 만큼만
        # 견줘야 한다 — 여유를 4자만 줘도 뒤쪽 군더더기가 유사도를 0.91에서 0.77로
        # 깎아 진짜 오타를 놓친다.
        ratio = difflib.SequenceMatcher(None, target, _jamo(name)[: len(target)]).ratio()
        if ratio > score:
            best, score = name, ratio
    return (best, score) if best and score >= floor else None


async def _resolve_names(
    vendor, question: str, spec: dict[str, Any], prefix: str
) -> tuple[dict[str, Any], str]:
    """축을 안 밝힌 이름을 살려낸다. 못 찾으면 오타로 보고 가까운 이름으로 한 번 더.

    이미 이름 조건이 있으면 건드리지 않는다 — 사용자가 지목한 축이 우선이다.
    """
    # 벤더의 라벨 복구는 '의뢰인' 뒤 단어를 그대로 집는다 — '의뢰인 조회'가
    # client='조회' 가 되어 엉뚱한 2건이 나갔다. 뜻 없는 말이면 조건에서 뺀다.
    spec = {k: v for k, v in spec.items()
            if not (k in ("client", "debtor", "owner", "person")
                    and str(v).strip() in _STOP_TERMS)}
    if any(spec.get(k) for k, _c, _ko in _NAME_AXES):
        return spec, ""
    terms = _leftover_terms(question, spec)
    if not terms:
        return spec, ""

    for term in terms:
        hits = await _axis_hits(vendor, term, prefix)
        if hits:
            key, count, ko = hits[0]
            spec = {**spec, key: term}
            # 어느 축으로 봤는지는 답변의 조건 칩(🔎 의뢰 최유미)에 이미 드러난다.
            # 문구로 또 말하면 군더더기다 (2026-08-05 요청).
            return spec, ""

    # 어느 축에도 없다 → 오타일 수 있다. 사람 이름은 남의 자료를 보여줄 위험이 있어
    # 상호(의뢰인)보다 훨씬 엄격하게 본다.
    for term in terms:
        for key, column, ko in (("client", "client_name", "의뢰인"),
                                ("debtor", "debtor_name", "채무자")):
            floor = 0.85 if key == "client" else 0.94
            names = await _name_list(vendor, column, prefix)
            found = _closest(term, names, floor)
            if not found:
                continue
            name, _score = found
            # 상호는 지점명까지 붙어 있어 통째로 넣으면 너무 좁다 — 사용자가 친 만큼만.
            value = name[: len(term)].strip() if key == "client" else name
            # 실제로 무엇으로 찾았는지를 그대로 밝힌다 — 고른 후보('신한은행 일산중앙지점장')를
            # 보여주면 그 지점만 찾은 줄로 오해한다.
            return {**spec, key: value}, (
                f"'{term}'(으)로는 찾지 못해 {ko} '{value}'{_ro(value)} 찾았습니다."
            )
    return spec, ""


# 통장 적요를 붙여넣었나. 적요는 '이혜일/타행MB/(하나)/' 처럼 슬래시로 나뉜 꼴이라
# 보통 질문과 구별된다. '적요' 라고 적어 주는 경우도 받는다.
_JEOKYO_RE = re.compile(r"적요\s*[:：]?\s*(.+)", re.S)
# 묻는 말투 — 적요에는 이런 말이 안 붙는다 (적요는 은행이 찍는 고정 문구다).
# '비교' 는 뒤에 어미가 붙을 때만 본다 — 그냥 두면 '여비교통비'(경비 항목)가 걸린다.
_ASKING_RE = re.compile(
    r"보여줘|알려줘|찾아줘|비교(?=해|하|할|한)|어때|얼마|몇\s*건|무엇|뭐야|해줘|주세요|"
    r"어디|누구|언제|어떻게|목록|건수|집계|평균|합계")
_MONEY_RE = re.compile(r"(?:입금(?:액)?|금액)\s*[:：]?\s*([\d,]{4,})|([\d,]{6,})\s*원")


def _deposit_day(text: str) -> str:
    """입력에서 거래일을 찾는다 (YYYY-MM-DD 로). 없으면 빈 문자열.

    표를 통째로 붙여넣으면 UNIQUE_FIELD 안에 거래일이 박혀 있다
    ('0448420101128982202608050' → 20260805). 그것까지 읽는다.
    """
    m = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", text or "")
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        # 8자리 붙임(20260805) — 긴 숫자열 안에 박힌 것도 찾는다.
        best = None
        for cand in re.finditer(r"20[0-3]\d(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])", text or ""):
            best = cand.group(0)  # 뒤쪽 것이 대개 거래일이다 (UNIQUE_FIELD 끝)
        if not best:
            return ""
        y, mo, d = int(best[:4]), int(best[4:6]), int(best[6:8])
    try:
        value = dt.date(y, mo, d)
    except ValueError:
        return ""
    # 말도 안 되는 날짜는 버린다 (미래거나 10년 넘게 과거)
    today = dt.date.today()
    if value > today or (today - value).days > 3650:
        return ""
    return value.isoformat()


def _deposit_intent(question: str) -> "tuple[str, int, str] | None":
    """붙여넣은 적요·금액·거래일을 뽑는다. 적요가 아니면 None.

    재무팀은 세 가지 방식으로 넣는다 — 표의 한 행을 통째로, 적요 칸만, 조각만.
    거래일이 중요하다. 없으면 오늘로 보는데, 지난 입금을 조회하면 전표를 못 찾아
    적중률이 82%에서 47%로 떨어진다 (실측).
    """
    q = (question or "").strip()
    money = 0
    day = _deposit_day(q)
    if day:
        # 날짜 표기는 적요 본문에서 뺀다 — 남겨 두면 이름으로 읽힌다.
        q = re.sub(r"20\d{2}[-./]\d{1,2}[-./]\d{1,2}", " ", q).strip()

    # ⓪ 표의 한 행을 통째로 붙여넣은 경우.
    #    '400578562/대체입금/ <탭> 2 <탭> 55000.00 <탭> 574539214.00 <탭> Y <탭> 대출실 …'
    #    적요 칸은 슬래시가 있는 조각이고, 금액은 그 뒤 숫자 칸들 중 가장 작은 값이다
    #    (잔액·계좌번호가 훨씬 크다). 이걸 못 가르면 계좌번호를 금액으로 읽는다.
    fields = [f.strip() for f in re.split(r"	| {2,}", q) if f.strip()]
    if len(fields) >= 3:
        jeokyo_field = next((f for f in fields if f.count("/") >= 2), "")
        if jeokyo_field:
            numbers = []
            for f in fields:
                if f is jeokyo_field:
                    continue
                token = f.replace(",", "")
                if re.fullmatch(r"\d{4,15}(\.\d+)?", token):
                    numbers.append(int(float(token)))
            # 입금액은 잔액보다 작다. 만원 이상 값 중 가장 작은 것을 고른다.
            candidates = [n for n in numbers if n >= 10000]
            return jeokyo_field, (min(candidates) if candidates else 0), day

    match = _MONEY_RE.search(q)
    if match:
        raw = match.group(1) or match.group(2) or ""
        try:
            money = int(raw.replace(",", ""))
        except ValueError:
            money = 0
        q = q[: match.start()] + q[match.end():]
    elif "/" not in q:
        # 라벨 없이 금액만 적기도 한다 ('상주시산림조합 2576200').
        # 슬래시가 있으면 적요를 붙여넣은 것이므로 그 안의 숫자를 금액으로 읽지 않는다
        # — '400563506/대체입금/' 의 가상계좌 번호를 4억으로 읽던 사고를 막는다.
        from app.services.deposit_match import _compacts as _cp  # noqa: PLC0415

        for bare in re.finditer(r"(?<![\d,])[\d,]{6,13}(?![\d,])", q):
            token = bare.group(0)
            if _cp(token):
                continue
            try:
                value = int(token.replace(",", ""))
            except ValueError:
                continue
            if value >= 10000:  # 만원 미만은 금액으로 보지 않는다
                money = value
                q = q[: bare.start()] + q[bare.end():]
                break
    labelled = _JEOKYO_RE.search(q)
    if labelled:
        body = labelled.group(1).strip()
        return (body, money, day) if body else None
    body = q.strip()
    if not body or len(body) > 120 or _ASKING_RE.search(body):
        return None
    # 완전한 감정서번호(01-2607-3-2237)는 카드로 보여주는 게 맞다 — 여기서 가로채지 않는다.
    if _DOC_ID_RE.search(body):
        return None
    # ① 적요를 통째로 붙여넣은 경우. 실측(2026년 입금 6,640건): 적요는 100% 가
    #    슬래시 2~3개라 이 표식 하나로 전부 잡힌다.
    if body.count("/") >= 2:
        return body, money, day
    # ② 슬래시 없이 적요의 앞 조각만 물어보기도 한다 (재무팀 실사용).
    #    금액을 함께 줬거나, 감정서번호로 보이는 숫자가 있으면 입금 조회로 본다.
    #    이름만 덜렁 넣은 건 여기서 받지 않는다 — 그건 평소 감정서 검색이 더 낫다.
    from app.services.deposit_match import _compacts  # noqa: PLC0415

    if money or _compacts(body):
        return body, money, day
    return None


# 상세 카드에서 뺄 안내·부가 블록 (2026-08-05 사용자 요청).
# 회계 항목을 보러 온 사람에게 원문 정리 상태·문서 구성·안내 권유는 군더더기다.
_CARD_NOISE = (
    "물건 내역 표는 원문이 정리된",
    "감정평가 의견 내용이 궁금하시면",
    "본사 감정서부터 채우는 중",
)
_CARD_DROP_SECTIONS = ("문서 구성",)
# '### 물건 내역 (원문 p.1)', '### 금액 산출 (원문 p.21)' 같은 원문 발췌 절.
# 파싱 표가 '-' 투성이라 읽기도 어렵고, 회계를 보러 온 사람에겐 방해만 된다.
_CARD_EXCERPT_RE = re.compile(r"\(원문\s*p")


async def _add_money_columns(markdown: str) -> str:
    """목록 표 오른쪽에 회계 열(매출총액·미수금)을 덧붙인다.

    벤더가 그린 표는 감정서 정보만 있는데, 이 화면을 보는 사람은 돈도 같이 본다
    (2026-08-05 요청). 벤더 파일은 못 고치니 만들어진 마크다운에 열을 덧댄다.
    숫자는 입금현황이 쓰는 요약(a10_receivable_summary)이라 화면과 갈리지 않는다.
    """
    lines = markdown.split("\n")
    head_at = next((i for i, l in enumerate(lines)
                    if l.startswith("|") and i + 1 < len(lines)
                    and re.fullmatch(r"\|[\s:|-]+\|", lines[i + 1].strip())), None)
    if head_at is None:
        return markdown
    body_at = head_at + 2
    docs: list[str] = []
    for line in lines[body_at:]:
        if not line.startswith("|"):
            break
        first = line.strip().strip("|").split("|")[0].strip()
        match = _DOC_ID_RE.search(first)
        docs.append(match.group(1) if match else "")
    if not any(docs):
        return markdown

    from app.services.deposit_match import _money_sync  # noqa: PLC0415

    money = await asyncio.to_thread(_money_sync, [d for d in docs if d])
    if not money:
        return markdown

    def won(value: Any) -> str:
        return "-" if value is None else format(float(value or 0), ",.0f")

    lines[head_at] = lines[head_at].rstrip() + " 매출총액 | 미수금 |"
    lines[head_at + 1] = lines[head_at + 1].rstrip() + "---|---|"
    for offset, doc in enumerate(docs):
        index = body_at + offset
        info = money.get(doc) or {}
        # 소재지가 통째로 든 '제목' 칸이 표를 좌우로 늘린다 — 앞부분만 남긴다.
        cells = lines[index].strip().strip("|").split("|")
        if len(cells) > 1 and len(cells[1]) > 34:
            cells[1] = " " + cells[1].strip()[:32] + "… "
            lines[index] = "|" + "|".join(cells) + "|"
        lines[index] = "%s %s | %s |" % (
            lines[index].rstrip(), won(info.get("billed_amount")),
            won(info.get("outstanding_amount")))
    return "\n".join(lines)


async def _money_summary(vendor, spec: dict[str, Any], limit: int = 1500) -> str:
    """이 조건에 걸린 감정서들의 회계 합계 한 줄.

    집계 답변이 건수·평가액만 말하면 회계 쪽 사람에겐 반쪽이다 (2026-08-05 요청).
    같은 조건으로 감정서번호를 모아 입금현황 요약에서 합친다 — 화면과 같은 숫자다.
    """
    try:
        wide = {k: v for k, v in spec.items()
                if k not in ("want_agg", "group_by", "sort", "limit")}
        sql, params = vendor.build_search_sql(wide, use_fts=False)
        # 벤더는 목록용이라 TOP 50 으로 자른다. 합계를 내려면 그 상한을 풀어야 하는데,
        # 안 풀면 '50건만 더한 값'을 전체 합계인 척 보여주게 된다 (2026-08-05).
        sql = re.sub(r"^SELECT TOP \d+ ", f"SELECT TOP {limit + 1} ", sql, count=1)
        if await _office_snapshot_ready() and wide.get("office"):
            sql, params = _swap_office_sql(sql, params, str(wide["office"]))
        rows = await vendor.run_query(sql, params)
        docs = [str(r["doc_id"]).strip() for r in rows if r.get("doc_id")]
        if not docs:
            return ""
        if len(docs) > limit:
            # 조건이 너무 넓다 — 반쪽 합계를 전체인 척 보여주느니 말을 안 한다.
            return ("\n\n> 조건에 걸린 감정서가 %s건을 넘어 회계 합계는 생략했습니다. "
                    "기간이나 지역을 좁히면 매출총액·미수금까지 함께 보여드립니다."
                    % format(limit, ","))
        from app.services.deposit_match import _money_sync  # noqa: PLC0415

        money: dict[str, Any] = {}
        for start in range(0, len(docs), 500):  # IN 절이 너무 길어지지 않게 나눠 조회
            money.update(await asyncio.to_thread(_money_sync, docs[start:start + 500]))
        if not money:
            return ""
        billed = sum(float(v.get("billed_amount") or 0) for v in money.values())
        received = sum(float(v.get("received_amount") or 0) for v in money.values())
        outstanding = sum(float(v.get("outstanding_amount") or 0) for v in money.values())
        if not billed and not outstanding:
            return ""
        return ("\n\n**회계 합계** (입금현황 기준 · 감정서 %s건 중 전표 있는 %s건)\n\n"
                "| 구분 | 금액 |\n|---|---|\n"
                "| 매출총액 | %s원 |\n| 입금액 | %s원 |\n| **미수금** | %s원 |"
                % (format(len(docs), ","), format(len(money), ","),
                   format(billed, ",.0f"), format(received, ",.0f"),
                   format(outstanding, ",.0f")))
    except Exception:
        # 곁들이라 본 답은 그대로 나가지만, 조용히 삼키면 버그를 못 본다
        # (실제로 NameError 하나가 여기 숨어 합계가 통째로 안 나왔다).
        logging.getLogger(__name__).exception("[gamjun-chat] 회계 합계 실패")
        return ""


def _trim_card(markdown: str) -> str:
    """상세 카드의 안내 문구와 '문서 구성' 절을 걷어낸다."""
    out: list[str] = []
    skipping = False
    for line in markdown.split("\n"):
        heading = line.lstrip("#").strip() if line.lstrip().startswith("#") else ""
        if heading:
            skipping = (any(heading.startswith(s) for s in _CARD_DROP_SECTIONS)
                        or bool(_CARD_EXCERPT_RE.search(heading)))
            if skipping:
                continue
        if skipping:
            # 그 절의 본문(표·목록·빈 줄)만 건너뛴다. '**회계 …**' 처럼 굵게 쓴 줄은
            # 다음 내용의 시작이라 여기서 멈춰야 한다 — '*' 로 시작한다고 목록으로
            # 보면 뒤따르는 회계 표까지 통째로 지워진다 (2026-08-05 실측).
            body = line.strip()
            is_section_body = (not body or body.startswith("|")
                               or re.match(r"^[-*]\s", body) is not None)
            if is_section_body:
                continue
            skipping = False
        if any(mark in line for mark in _CARD_NOISE):
            continue
        out.append(line)
    return "\n".join(out)


def _drop_broken_tables(markdown: str) -> str:
    """원문에서 뜬 물건내역 표가 셀이 거의 비어 있으면 통째로 뺀다.

    파싱이 어긋난 표는 '| - | - | - |' 만 잔뜩 늘어놓아 읽을 수가 없다.
    회계 항목을 보러 온 사람에게는 특히 방해가 된다 (2026-08-05 요청).
    """
    out: list[str] = []
    block: list[str] = []

    def meaningful(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")
                if c.strip() and not set(c.strip()) <= {"-", ":", " "}]

    def flush() -> None:
        if not block:
            return
        # 머리행에 이름이 하나도 없으면 열이 무엇인지 알 수 없는 표다 — 통째로 버린다.
        headless = not meaningful(block[0])
        cells = [c for line in block for c in line.strip().strip("|").split("|")]
        body = [c for line in block for c in meaningful(line)]
        # 뜻 있는 칸이 전체의 1/4 도 안 되는 표도 읽을 수 없다.
        if body and not headless and len(body) * 4 >= len(cells):
            out.extend(block)
        block.clear()

    for line in markdown.split("\n"):
        if line.lstrip().startswith("|"):
            block.append(line)
            continue
        flush()
        out.append(line)
    flush()
    # 표를 버리고 제목만 남은 자리(### 물건 내역 …)도 같이 지운다.
    cleaned: list[str] = []
    for index, line in enumerate(out):
        if line.startswith("###"):
            rest = [x for x in out[index + 1:] if x.strip()]
            if not rest or rest[0].startswith("###"):
                continue
        cleaned.append(line)
    # 빈 줄이 세 줄 넘게 이어지면 한 줄로 줄인다 — 지운 자리가 구멍으로 남지 않게.
    tidy: list[str] = []
    for line in cleaned:
        if not line.strip() and tidy and not tidy[-1].strip():
            continue
        tidy.append(line)
    return "\n".join(tidy)


def _has_doc(data: Any) -> bool:
    """벤더 fetch_doc_detail 이 실제로 감정서를 찾았나.

    못 찾아도 빈손이 아니라 `{"master": None, "tables": [], ...}` 를 돌려준다 —
    그냥 truthy 로 보면 폴백이 죽어 '찾지 못했어요'로 끝나 버린다 (2026-08-05 실측).
    """
    return bool(data) and bool(isinstance(data, dict) and data.get("master"))


def _ledger_lookup_sync(doc_id: str) -> "dict[str, Any] | None":
    """10번 서버 원장(apw_masterex)에서 한 건 — 파싱 전 감정서의 폴백 카드용."""
    from sqlalchemy import text  # noqa: PLC0415
    from app.database import get_session_factory  # noqa: PLC0415
    from app.services.appraisals import _source_view  # noqa: PLC0415

    db = get_session_factory()()
    try:
        row = db.execute(
            text(
                f"SELECT TOP 1 CONVERT(varchar(10), a.ReceiptDate, 120) AS receipt_date, "
                f"a.CustName AS client, a.Manager AS manager, a.LStatus AS status, "
                f"a.Address AS address FROM {_source_view()} a WHERE a.DocID = :doc"
            ),
            {"doc": doc_id},
        ).mappings().first()
        return dict(row) if row else None
    finally:
        db.close()


def _audit_sync(
    question: str, office_code: str, usr_seq: str, data: dict[str, Any], elapsed_ms: int
) -> None:
    """질문 로그(a10_api_log) — 무엇을 몇 초에 답했는지. 실패는 조용히 넘긴다."""
    try:
        from app.database import get_session_factory  # noqa: PLC0415
        from app.models.api_log import ApiLog  # noqa: PLC0415

        db = get_session_factory()()
        try:
            db.add(ApiLog(
                direction="chatbot", endpoint="/api/gamjun-chat", http_status=200,
                req_body=json.dumps(
                    {"q": question[:200], "office": office_code, "usr": usr_seq},
                    ensure_ascii=False),
                res_body=json.dumps(
                    {"rows": data.get("rows"), "cached": bool(data.get("cached")),
                     "note": bool(data.get("note"))},
                    ensure_ascii=False),
                elapsed_ms=elapsed_ms,
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


def _prepare_env() -> None:
    """벤더 모듈이 보는 환경변수를 우리 설정으로 채운다."""
    settings = get_settings()
    os.environ.setdefault("GAMJUN_DB_HOST", settings.gamjun_parse_server)
    os.environ.setdefault("GAMJUN_DB_PORT", str(settings.mssql_port))
    os.environ.setdefault("GAMJUN_DB_NAME", settings.gamjun_parse_db)
    os.environ.setdefault("GAMJUN_DB_USER", settings.mssql_user)
    os.environ.setdefault(
        "GAMJUN_DB_PASSWORD", settings.mssql_password.get_secret_value()
    )
    key = settings.gemini_api_key.get_secret_value()
    if key:
        os.environ.setdefault("GEMINI_API_KEY", key)
    # 오래 걸리는 조회가 서버 CPU를 물고 늘어지지 않게 짧게 끊는다.
    os.environ.setdefault("GAMJUN_QUERY_TIMEOUT", "25")


def _vendor():
    """벤더 모듈을 늦게 불러온다 — 서버 기동을 DB·키에 묶지 않는다."""
    global _READY
    if not _READY:
        _prepare_env()
        vendor_dir = str(Path(__file__).resolve().parent.parent / "vendor")
        if vendor_dir not in sys.path:
            sys.path.insert(0, vendor_dir)
        _READY = True
    import gamjun_search  # noqa: PLC0415  (늦은 import 가 의도다)

    return gamjun_search


def available() -> bool:
    """DB와 API 키가 준비됐나. 화면이 안내 문구를 고르는 데 쓴다."""
    try:
        _prepare_env()
        if not os.getenv("GEMINI_API_KEY"):
            return False
        return bool(_vendor().gamjun_available())
    except Exception:
        return False


async def warmup() -> None:
    """어휘 캐시(지역·종별·평가사 목록)와 원문 전문검색 인덱스를 미리 데운다.

    화면이 열릴 때(health) 백그라운드로 불러, 첫 질문이 예열비를 물지 않게 한다.
    """
    try:
        await _vendor()._ensure_vocab()
    except Exception:
        pass  # 예열 실패는 치명적이지 않다 — 첫 질문이 대신 데운다
    await asyncio.to_thread(_warm_fulltext_sync)


def _warm_fulltext_sync() -> None:
    """원문 전문검색(jun.chunk FULLTEXT) 인덱스 페이지를 데운다.

    실측: 커넥션을 새로 연 뒤 처음 도는 CONTAINS 는 8~12초까지 튀는데, 같은
    쿼리를 데워진 상태로 다시 돌리면 0.02초다. 느림의 원인이 결과 크기가 아니라
    인덱스 페이지 콜드 리드라, 아무 말이나 한 번 던져 두면 그걸로 끝난다.
    입금 대사에서 줄을 눌렀을 때 11초를 기다리던 게 이 비용이었다.

    'SELECT COUNT(*) FROM jun.chunk' 류는 절대 쓰지 마라 — 풀스캔이라 10초다.
    """
    try:
        _vendor()._run_query(
            "SELECT TOP 1 ch.master_id FROM jun.chunk ch "
            "WHERE ch.is_active = 1 AND CONTAINS(ch.content, %s)",
            ('"감정평가"',))
    except Exception:
        logger.debug("[gamjun-chat] 원문 인덱스 예열 실패 — 첫 조회가 대신 데운다")


def _cache_get(key: tuple[str, str]) -> "dict[str, Any] | None":
    item = _CACHE.get(key)
    if not item:
        return None
    stamp, ttl, value = item
    if time.time() - stamp > ttl:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: tuple[str, str], value: dict[str, Any], ttl: float = _CACHE_TTL) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        oldest = min(_CACHE, key=lambda k: _CACHE[k][0])
        _CACHE.pop(oldest, None)
    _CACHE[key] = (time.time(), ttl, value)


# 카드가 스스로 '요약해줘'를 안내한다 — 그 질문은 카드가 아니라 요약으로 가야 한다.
_SUMMARY_RE = re.compile(r"요약|의견\s*(내용|정리|알려|설명)?")


def _doc_summary_intent(question: str) -> bool:
    return bool(_SUMMARY_RE.search(question))


def _doc_only(question: str) -> "str | None":
    """질문이 사실상 감정서번호 하나면 그 번호를 준다 — Gemini 를 건너뛰는 지름길.

    '01-2607-3-2235 의뢰인이 누구야?' 처럼 번호 뒤에 짧은 물음만 붙는 게 대부분이고,
    답은 어차피 그 감정서 카드다. 번호를 뺀 나머지가 길면(다른 조건이 섞이면) 정상 경로로.
    """
    match = _DOC_ID_RE.search(question)
    if not match:
        return None
    rest = _DOC_ID_RE.sub("", question).strip()
    return match.group(1) if len(rest) <= 14 else None


def _strip_content(spec: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """본문 검색 조건을 떼어낸다. 뗐으면 True 를 같이 준다."""
    trimmed = dict(spec)
    dropped = False
    for key in CONTENT_FILTERS:
        if trimmed.get(key):
            trimmed.pop(key, None)
            dropped = True
    return trimmed, dropped


def _has_any_filter(spec: dict[str, Any]) -> bool:
    # office 는 우리가 항상 강제 주입하므로 '조건'으로 안 친다 — 이걸 세면
    # 조건 없는 질문 안내("무엇을 찾을지…")가 영영 안 나간다.
    for key in SUPPORTED_FILTERS:
        if key in ("limit", "office"):
            continue
        value = spec.get(key)
        if isinstance(value, (int, float)):
            if value:
                return True
        elif str(value or "").strip():
            return True
    return False


def _strip_copula(spec: dict[str, Any]) -> "dict[str, Any] | None":
    """'채무자가 곽한성인 건' → 이름에 서술격 조사가 붙어(곽한성인) 0건이 되는 걸 보정.

    이름류 필터가 '인'으로 끝나면 떼고 한 번 더 찾아본다. '김성인' 같은 진짜 이름은
    원래 검색이 결과를 냈을 것이므로(0건일 때만 재시도) 안전하다.
    """
    trimmed = None
    for key in ("debtor", "owner", "person", "client"):
        value = str(spec.get(key) or "")
        if len(value) >= 3 and value.endswith("인"):
            trimmed = dict(trimmed or spec)
            trimmed[key] = value[:-1]
    return trimmed


async def _answer(vendor, spec: dict[str, Any], note: str) -> dict[str, Any]:
    """필터 → SQL → 마크다운. 집계·분해는 본서버와 같은 빌더·렌더러를 그대로 쓴다."""
    # 오피스 서브쿼리 가속 — 스냅샷이 준비됐을 때만 바꿔치기 (없으면 원본 그대로).
    fast = await _office_snapshot_ready()
    label = str(spec.get("office") or "").strip()

    def _swap(s: str, p: tuple) -> tuple[str, tuple]:
        return _swap_office_sql(s, p, label) if fast and label else (s, p)

    if spec.get("group_by") and not spec.get("doc_id"):
        sql, params, dim_label = vendor.build_group_sql(spec)
        sql, params = _swap(sql, params)
        rows = await vendor.run_query(sql, params)
        answer = vendor.render_group_results(rows, spec, dim_label)
        return {"answer": answer + await _money_summary(vendor, spec),
                "note": note, "spec": spec, "rows": len(rows)}

    if spec.get("want_agg") and not spec.get("doc_id"):
        stats_sql, median_sql, params = vendor.build_agg_sql(spec)
        s_sql, s_params = _swap(stats_sql, params)
        median = None
        if median_sql:
            m_sql, m_params = _swap(median_sql, params)

            async def _med():
                try:
                    r = await vendor.run_query(m_sql, m_params)
                    return float(r[0]["v_med"]) if r and r[0].get("v_med") else None
                except Exception:
                    return None  # 중앙값은 곁들이 — 실패해도 본 답은 나간다
            stats_rows, median = await asyncio.gather(
                vendor.run_query(s_sql, s_params), _med()
            )
        else:
            stats_rows = await vendor.run_query(s_sql, s_params)
        stats = stats_rows[0] if stats_rows else {}
        answer = vendor.render_agg_results(stats, median, spec)
        return {"answer": answer + await _money_summary(vendor, spec),
                "note": note, "spec": spec, "rows": int(stats.get("n_docs") or 0)}

    sql, params = vendor.build_search_sql(spec, use_fts=False)
    sql, params = _swap(sql, params)
    rows = await vendor.run_query(sql, params)
    if not rows:
        retried = _strip_copula(spec)
        if retried is not None:
            sql, params = vendor.build_search_sql(retried, use_fts=False)
            sql, params = _swap(sql, params)
            rows = await vendor.run_query(sql, params)
            if rows:
                spec = retried
    return {"answer": await _add_money_columns(vendor.render_search_results(rows, spec)),
            "note": note, "spec": spec, "rows": len(rows)}


async def _extract_cached(vendor, question: str, prev_question: str) -> dict[str, Any]:
    """필터 추출 — 같은 날 같은 질문이면 Gemini 왕복(~1초)을 건너뛴다."""
    key = (question, prev_question or "", dt.date.today().isoformat())
    hit = _XCACHE.get(key)
    if hit and time.time() - hit[0] < _XCACHE_TTL:
        return dict(hit[1])
    spec = await vendor.extract_filters(question, prev_question)
    if len(_XCACHE) >= _XCACHE_MAX:
        _XCACHE.clear()  # 단순 초기화 — 상한을 넘을 만큼 쌓이는 일 자체가 드물다
    _XCACHE[key] = (time.time(), dict(spec))
    return dict(spec)


async def ask(
    question: str, prev_question: str = "", office_code: str = "10",
    usr_seq: str = "",
) -> dict[str, Any]:
    """질문 하나에 답한다 → {"answer": 마크다운, "note": 안내, "spec": 쓰인 조건}.

    조회 범위는 사용자 소속(office_code)으로 좁힌다 — 본사 사용자는 본사(01-) 건만
    (2026-08-05 사용자 확정: 우선 소속 데이터만 보여준다).
    office_code 는 라우터가 usr_seq 로 서버측에서 푼 값이다 — 화면 값을 믿지 않는다.
    """
    question = (question or "").strip()
    if not question:
        return {"answer": "", "note": "질문을 입력해 주세요.", "spec": {}}

    started = time.time()

    def _done(result: dict[str, Any]) -> dict[str, Any]:
        # 질문 로그 — 사용 패턴·느린 질문을 데이터로 보기 위해. 응답을 막지 않는다.
        elapsed = int((time.time() - started) * 1000)
        try:
            asyncio.get_running_loop().create_task(
                asyncio.to_thread(_audit_sync, question, office_code, usr_seq,
                                  result, elapsed))
        except Exception:
            pass
        return result

    label, prefix = office_scope(office_code)
    # 소속이 다르면 답도 달라야 하므로 캐시 키에 소속을 넣는다.
    key = (f"{office_code}|{question}", (prev_question or "").strip())
    hit = _cache_get(key)
    if hit is not None:
        return _done({**hit, "cached": True})

    # 통장 적요를 붙여넣은 경우 — 재무팀이 손으로 하던 감정서 찾기를 대신한다.
    deposit = _deposit_intent(question)
    if deposit:
        from app.services import deposit_match  # noqa: PLC0415

        jeokyo, money, day = deposit
        # 표를 통째로 붙여넣었으면 UNIQUE_FIELD 도 들어 있다 — 사이버브랜치 매핑표를
        # 바로 두드릴 수 있는 열쇠라 함께 넘긴다.
        uf = deposit_match._UNIQUE_RE.search(question or "")
        data = await deposit_match.find(
            jeokyo, money, day or dt.date.today().isoformat(),
            uf.group(1) if uf else "")
        result = {"answer": deposit_match.render(data, jeokyo, money),
                  "note": "", "spec": {"deposit": jeokyo}, "rows": len(data.get("items") or [])}
        _cache_put(key, result)
        return _done(result)

    # 돈 질문(미수·입금·선수금…)은 회계 경로로 — 입금현황 화면과 같은 계산식을 쓴다.
    # 감정서번호 지름길보다 먼저 봐야 '01-xxx 입금됐어?'가 감정서 카드로 새지 않는다.
    from app.services import money_chat  # noqa: PLC0415 (돈 질문이 없으면 안 불러온다)
    if money_chat.is_money_question(question):
        result = await money_chat.ask(question, office_code)
        _cache_put(key, result, ttl=_MONEY_CACHE_TTL)
        return _done(result)

    # 감정서번호만 묻는 질문은 곧장 카드로 (Gemini 왕복 ~1초 절약).
    # '요약해줘'는 카드가 아니라 감정평가 의견 요약으로 (카드 스스로 안내하는 경로다).
    doc_id = _doc_only(question)
    if doc_id:
        if _doc_summary_intent(question):
            result = await doc_summary(doc_id, question, office_code)
        else:
            result = await doc_detail(doc_id, office_code)
        result["spec"] = {"doc_id": doc_id}
        _cache_put(key, result)
        return _done(result)

    vendor = _vendor()
    spec = await _extract_cached(vendor, question, prev_question)
    spec, dropped = _strip_content(spec)
    note = _UNSUPPORTED_NOTE if dropped else ""
    # 소속 범위 강제. 다른 지사를 물었으면 그 사실을 알린다.
    asked_office = str(spec.get("office") or "").strip()
    if label and asked_office and asked_office != label:
        note = (note + " " if note else "") +             f"조회 범위가 소속({label})으로 제한되어 {asked_office} 데이터는 볼 수 없습니다."
    if label:
        spec["office"] = label
    else:
        spec.pop("office", None)  # 전체 — 지사로 좁히지 않는다

    # 축을 안 밝힌 이름("신한은행")을 살려낸다 — 본문 키워드로 떨어져 사라지던 것.
    spec, name_note = await _resolve_names(vendor, question, spec, prefix)
    if name_note:
        # 이름을 살렸으면 '본문 검색은 준비 중' 안내는 오히려 헷갈린다.
        note = name_note if note == _UNSUPPORTED_NOTE else (
            (note + " " if note else "") + name_note)

    if not _has_any_filter(spec):
        result = {
            "answer": "",
            "note": note or (
                "무엇을 찾을지 못 알아들었습니다. 소재지·물건종류·목적·기간·평가액·"
                "평가사·감정서번호로 물어봐 주세요."
            ),
            "spec": spec,
        }
        _cache_put(key, result)
        return _done(result)

    result = await _answer(vendor, spec, note)
    # 적재 지연 안내는 뺐다 (2026-08-05 요청). 번호로 물으면 원장 폴백이
    # 그 사실을 그 자리에서 말해 주므로 매 답변에 붙일 이유가 없다.
    _cache_put(key, result)
    return _done(result)


async def requery(spec: dict[str, Any], office_code: str = "10") -> dict[str, Any]:
    """조건 칩 편집 재조회 — 화면이 돌려준 spec 에서 칩 하나를 뺀 그대로 다시 찾는다.

    Gemini 를 안 거치므로 빠르고(SQL만), 칩과 결과가 정확히 1:1 이다.
    spec 은 클라이언트발이라 화이트리스트로 거르고 소속을 다시 강제한다.
    """
    vendor = _vendor()
    label, _prefix = office_scope(office_code)
    clean = {k: v for k, v in dict(spec or {}).items() if k in SUPPORTED_FILTERS}
    clean, _ = _strip_content(clean)
    if label:
        clean["office"] = label
    if not _has_any_filter(clean):
        return {"answer": "", "spec": clean,
                "note": "조건이 모두 지워졌습니다. 새 질문을 입력해 주세요."}
    return await _answer(vendor, clean, "")


async def suggest(q: str, office_code: str = "10") -> "list[dict[str, str]]":
    """입력 자동완성 — 벤더가 예열해 둔 사전(지역·종별·목적·평가사) + 거래처 라이브.

    전문 검색창의 기본기다: 이름을 정확히 몰라 검색이 빗나가는 걸 입력 단계에서 줄인다.
    거래처만 사전에 없어 소속 접두사 범위로 TOP 5 라이브 조회한다 (LIKE 앞고정이라 싸다).
    """
    q = (q or "").strip()
    if not q:
        return []
    vendor = _vendor()
    try:
        await vendor._ensure_vocab()
    except Exception:
        pass
    vocab = getattr(vendor, "_vocab", {}) or {}
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(kind: str, values, limit: int) -> None:
        # 앞부분 일치를 먼저, 포함 일치를 뒤에 — 짧은 입력에도 쓸 만한 순서가 나온다.
        starts = [v for v in values if v.startswith(q)]
        contains = [v for v in values if q in v and not v.startswith(q)]
        for value in (starts + contains)[:limit]:
            if value not in seen:
                seen.add(value)
                out.append({"kind": kind, "value": value})

    _label, prefix = office_scope(office_code)
    try:
        rows = await vendor.run_query(
            "SELECT DISTINCT TOP 5 client_name FROM jun.apw_case "
            "WHERE doc_id_raw LIKE %s AND client_name LIKE %s ORDER BY client_name",
            (prefix + "-%", q + "%"),
        )
        add("거래처", [str(r["client_name"]).strip() for r in rows if r.get("client_name")], 4)
    except Exception:
        pass  # 자동완성은 곁들이 — 실패해도 입력을 막지 않는다
    add("평가사·담당", sorted(vocab.get("persons") or ()), 3)
    add("지역", vocab.get("regions") or (), 3)
    add("물건종별", vocab.get("categories") or (), 3)
    add("목적", vocab.get("purposes") or (), 2)
    return out[:8]


async def search_page(
    spec: dict[str, Any], offset: int, office_code: str = "10"
) -> dict[str, Any]:
    """목록 '더보기' — 같은 조건으로 다음 10건.

    벤더의 fetch_search_page 를 안 쓰고 직접 만든다. 그 함수의 재위생 화이트리스트
    (_PAGE_STR_FIELDS)에 owner·debtor 가 빠져 있어서, 채무자로 찾은 목록의 2페이지가
    조건을 잃고 **전체 목록**을 붙여 버린다 (2026-08-05 실측: {'debtor':'곽한성'} →
    {} 로 위생됨). 우리도 클라이언트발 spec 은 화이트리스트로 거르므로 안전은 같다.
    """
    vendor = _vendor()
    size = 10
    clean = {k: v for k, v in dict(spec or {}).items() if k in SUPPORTED_FILTERS}
    clean, _ = _strip_content(clean)
    label, _prefix = office_scope(office_code)
    if label:
        clean["office"] = label
    clean["limit"] = size + 1  # has_more 판정용 한 건 더

    sql, params = vendor.build_search_sql(clean, offset=max(0, int(offset or 0)))
    if await _office_snapshot_ready():
        sql, params = _swap_office_sql(sql, params, label)
    rows = await vendor.run_query(sql, params)
    has_more = len(rows) > size

    # 셀 서식은 벤더 것을 그대로 쓴다 — 1페이지와 글자 한 자도 달라지면 안 된다.
    cell = getattr(vendor, "_sanitize_cell", lambda v: "" if v is None else str(v))
    amount = getattr(vendor, "_fmt_amount", lambda v: "" if v is None else str(v))
    date = getattr(vendor, "_fmt_date", lambda v: "" if v is None else str(v))
    out = [[cell(r.get("doc_id")), cell(r.get("title")), cell(r.get("client")),
            cell(r.get("purpose")), amount(r.get("appraisal_value")),
            date(r.get("write_dt"))] for r in rows[:size]]
    return {"rows": out, "has_more": bool(has_more)}


async def doc_detail(doc_id: str, office_code: str = "10") -> dict[str, Any]:
    """감정서 한 건 카드. 소속 감정서가 아니면 열지 않는다 (접두사 또는 원장 LOffice)."""
    label, prefix = office_scope(office_code)
    vendor = _vendor()
    if not await _office_gate(vendor, doc_id, label, prefix):
        return {"answer": "",
                "note": f"소속({label}) 감정서만 조회할 수 있습니다 — {doc_id.strip()} 는 다른 지사 번호입니다."}
    data = await vendor.fetch_doc_detail(doc_id.strip())
    if not _has_doc(data):
        # 원문 DB에 아직 없어도 원장에는 있다 — '못 찾음'으로 끝내면 사용자가
        # 챗봇을 의심한다. 원장 기본 정보로 대신 답하고 사유를 밝힌다.
        ledger = await asyncio.to_thread(_ledger_lookup_sync, doc_id.strip())
        if ledger:
            lines = [
                f"## {doc_id.strip()}", "",
                f"- **접수일**: {ledger.get('receipt_date') or '-'}",
                f"- **의뢰인**: {(ledger.get('client') or '-').strip() or '-'}",
                f"- **담당**: {(ledger.get('manager') or '-').strip() or '-'}",
                f"- **진행상태**: {(ledger.get('status') or '-').strip() or '-'}",
                f"- **소재지**: {(ledger.get('address') or '-').strip() or '-'}",
            ]
            from app.services.money_chat import doc_money_brief  # noqa: PLC0415
            brief = await doc_money_brief(doc_id.strip(), office_code)
            if brief:
                lines.append(brief)
            day = await _jun_coverage()
            lines += ["", "> 원장(감정서 LIST)에는 접수돼 있으나 감정서 원문은 아직 "
                          "정리 전입니다"
                          + (f" — 원문 DB는 {day} 접수분까지 들어와 있습니다." if day else ".")]
            return {"answer": "\n".join(lines), "note": ""}
        return {"answer": "", "note": "그 번호의 감정서를 찾지 못했습니다."}
    answer = _trim_card(_drop_broken_tables(vendor.render_doc_detail(data)))
    # 회계 항목을 끼운다 — 카드만 보고 돈은 또 묻지 않게 (입금현황과 같은 숫자).
    from app.services.money_chat import doc_money_brief  # noqa: PLC0415
    brief = await doc_money_brief(doc_id.strip(), office_code)
    if brief:
        marker = "\n\n>"
        if marker in answer:
            index = answer.index(marker)
            answer = answer[:index] + "\n" + brief + answer[index:]
        else:
            answer += "\n" + brief
    return {"answer": answer, "note": ""}


async def doc_summary(doc_id: str, question: str, office_code: str = "10") -> dict[str, Any]:
    """감정평가 의견 요약 — 벤더 summarize_doc (숫자 가드 포함). 원문 없으면 카드로."""
    label, prefix = office_scope(office_code)
    vendor = _vendor()
    if not await _office_gate(vendor, doc_id, label, prefix):
        return {"answer": "",
                "note": f"소속({label}) 감정서만 조회할 수 있습니다 — {doc_id.strip()} 는 다른 지사 번호입니다."}
    data = await vendor.fetch_doc_detail(doc_id.strip())
    if not _has_doc(data):
        # 원문이 아직 없으면 카드 경로가 원장 폴백까지 처리한다.
        return await doc_detail(doc_id, office_code)
    try:
        summary = await vendor.summarize_doc(doc_id.strip(), question, data)
    except Exception:
        summary = None
    if summary:
        return {"answer": f"## {doc_id.strip()} 감정평가 의견 요약\n\n{summary}", "note": ""}
    # 원문(의견)이 아직 정리되지 않은 건 — 카드로 대신하고 사유를 밝힌다.
    result = await doc_detail(doc_id, office_code)
    result["note"] = "이 감정서는 의견 원문이 아직 정리되지 않아 요약 대신 기본 정보를 보여드립니다."
    return result
