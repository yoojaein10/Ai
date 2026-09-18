"""감정서 조회 챗봇 API.

조회 범위(본·지사)는 화면 값을 그대로 믿지 않는다 — usr_seq 로 소속을 풀고,
화면이 고른 지사는 **전체조회 권한이 있을 때만** 받아들인다 — 개발자도구로 office_code 를 바꿔 다른 지사를 보는 구멍을 막는다
(2026-08-05). usr_seq 가 없거나 무효(퇴사·미등록)면 조회를 거부한다.

TODO(권한): 메뉴권한 배선은 아직 없다 — 권한 브랜치가 main 에 합쳐지면
이 라우터도 메뉴권한 검사에 넣어야 한다.
"""

import asyncio
import json
import logging
import re
from typing import Annotated

from fastapi import APIRouter, Body, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.schemas.common import ApiResponse
from app.services import gamjun_chat

router = APIRouter(prefix="/api/gamjun-chat", tags=["gamjun-chat"])
logger = logging.getLogger(__name__)

_AUTH_NOTE = (
    "사용자 확인이 안 되어 조회할 수 없습니다. APWorks에서 화면을 다시 열어 주세요."
)


class AskBody(BaseModel):
    question: Annotated[str, Field(min_length=1, max_length=300)]
    # 직전 질문. "그중 담보만" 처럼 이어 묻는 걸 벤더 모듈이 처리한다.
    prev_question: Annotated[str, Field(max_length=300)] = ""
    # 사용자 식별자(context.js A10_USR). 소속 지사는 이걸로 서버가 푼다.
    usr_seq: Annotated[str, Field(pattern=r"^[0-9]{0,10}$")] = ""
    # 화면에서 고른 본·지사('all'=전체). 권한 밖이면 서버가 소속으로 되돌린다.
    office_code: Annotated[str, Field(pattern=r"^[0-9A-Za-z]{0,10}$")] = ""


def _failed(message: str, code: str = "GAMJUN_ERROR") -> JSONResponse:
    response = ApiResponse(success=False, code=code, message=message, data=None)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=response.model_dump(mode="json"),
    )


# 이 화면의 메뉴 키. 화면(context.js menuKeyForUrl)과 같은 값이어야 한다.
MENU_KEY = "depositMatch"


async def _office_of(usr_seq: str, requested: str = "") -> "str | None":
    """usr_seq → 조회할 지사 코드. 무효 사용자나 권한 없는 사용자는 None.

    화면이 고른 지사(requested)는 전체조회 권한이 있을 때만 받아들인다 —
    다른 조회 화면과 같은 규칙이고, 판정은 서버가 다시 한다.

    메뉴 권한도 여기서 본다. 데이터를 내려주는 엔드포인트가 모두 이 함수를
    거치므로 한 곳만 막으면 된다(/health 는 안 거친다 — 준비 상태만 알려준다).
    화면은 메뉴를 숨기지만 주소를 아는 사람은 API 를 그냥 부를 수 있었다.
    """
    if not await gamjun_chat.can_menu(usr_seq, MENU_KEY):
        return None
    return await gamjun_chat.resolve_office(usr_seq, requested)


@router.get("/health", response_model=ApiResponse)
async def health() -> ApiResponse:
    """감정서 DB·API 키가 준비됐는지. 화면이 안내 문구를 고르는 데 쓴다.

    겸사겸사 어휘 캐시를 백그라운드로 예열한다 — 화면을 연 사람의 첫 질문이
    예열비(~1초)를 물지 않게 한다.
    """
    ok = await asyncio.to_thread(gamjun_chat.available)
    if ok:
        asyncio.get_running_loop().create_task(gamjun_chat.warmup())
    return ApiResponse(
        success=True, code="0000", message="조회 완료",
        data={"available": ok},
    )


@router.post("/stream")
async def ask_stream(body: AskBody = Body(...)) -> StreamingResponse:
    """답변을 SSE 로 조각내 흘린다 (레퍼런스 server.py 와 같은 방식 — 타이핑 효과).

    답은 어차피 1~4초에 다 나오므로 계산을 먼저 끝내고 80자씩 흘린다.
    마지막에 meta 프레임(note·spec·rows·cached)을 보내고 [DONE] 으로 닫는다.
    """
    office = await _office_of(body.usr_seq, body.office_code)
    if office is None:
        data = {"answer": "", "note": _AUTH_NOTE, "spec": {}}
    else:
        try:
            data = await gamjun_chat.ask(
                body.question, body.prev_question, office, usr_seq=body.usr_seq
            )
        except Exception:
            logger.exception("[gamjun-chat] stream 실패: %s", body.question[:80])
            data = {"answer": "", "note": "조회 중 문제가 생겼습니다. 잠시 후 다시 물어봐 주세요.",
                    "spec": {}}

    async def gen():
        answer = data.get("answer") or ""
        for chunk in (re.findall(r".{1,80}", answer, re.S) or [""]):
            yield "data: " + json.dumps({"delta": chunk}, ensure_ascii=False) + "\n\n"
            await asyncio.sleep(0.004)
        meta = {k: v for k, v in data.items() if k != "answer"}
        yield "data: " + json.dumps({"meta": meta}, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("", response_model=ApiResponse)
async def ask(body: AskBody = Body(...)) -> ApiResponse | JSONResponse:
    office = await _office_of(body.usr_seq, body.office_code)
    if office is None:
        return _failed(_AUTH_NOTE, code="GAMJUN_AUTH")
    try:
        data = await gamjun_chat.ask(
            body.question, body.prev_question, office, usr_seq=body.usr_seq
        )
    except Exception:  # 벤더 모듈이 DB 혼잡 등을 예외로 올린다
        logger.exception("[gamjun-chat] ask 실패: %s", body.question[:80])
        return _failed("조회 중 문제가 생겼습니다. 잠시 후 다시 물어봐 주세요.")
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


class PageBody(BaseModel):
    # ask() 가 돌려준 spec 을 그대로 되받는다 — 벤더 _sanitize_page_spec 이 재위생한다.
    spec: dict = {}
    offset: Annotated[int, Field(ge=0, le=5000)] = 0
    usr_seq: Annotated[str, Field(pattern=r"^[0-9]{0,10}$")] = ""
    # 화면에서 고른 본·지사('all'=전체). 권한 밖이면 서버가 소속으로 되돌린다.
    office_code: Annotated[str, Field(pattern=r"^[0-9A-Za-z]{0,10}$")] = ""


@router.post("/page", response_model=ApiResponse)
async def page(body: PageBody = Body(...)) -> ApiResponse | JSONResponse:
    """목록 '더보기' — 같은 조건의 다음 10건."""
    office = await _office_of(body.usr_seq, body.office_code)
    if office is None:
        return _failed(_AUTH_NOTE, code="GAMJUN_AUTH")
    try:
        data = await gamjun_chat.search_page(body.spec, body.offset, office)
    except Exception:
        logger.exception("[gamjun-chat] page 실패")
        return _failed("조회 중 문제가 생겼습니다. 잠시 후 다시 물어봐 주세요.")
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.post("/requery", response_model=ApiResponse)
async def requery(body: PageBody = Body(...)) -> ApiResponse | JSONResponse:
    """조건 칩 편집 재조회 — 칩 하나를 뺀 spec 으로 목록을 다시 만든다 (Gemini 없이)."""
    office = await _office_of(body.usr_seq, body.office_code)
    if office is None:
        return _failed(_AUTH_NOTE, code="GAMJUN_AUTH")
    try:
        data = await gamjun_chat.requery(body.spec, office)
    except Exception:
        logger.exception("[gamjun-chat] requery 실패")
        return _failed("조회 중 문제가 생겼습니다. 잠시 후 다시 물어봐 주세요.")
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


@router.get("/suggest", response_model=ApiResponse)
async def suggest(
    q: Annotated[str, Query(min_length=1, max_length=60)],
    usr_seq: Annotated[str, Query(pattern=r"^[0-9]{0,10}$")] = "",
    office_code: Annotated[str, Query(pattern=r"^[0-9A-Za-z]{0,10}$")] = "",
) -> ApiResponse | JSONResponse:
    """입력 자동완성 — 거래처·평가사·지역·물건종별·목적."""
    office = await _office_of(usr_seq, office_code)
    if office is None:
        return ApiResponse(success=True, code="0000", message="조회 완료", data={"items": []})
    try:
        items = await gamjun_chat.suggest(q, office)
    except Exception:
        logger.exception("[gamjun-chat] suggest 실패")
        items = []
    return ApiResponse(success=True, code="0000", message="조회 완료", data={"items": items})


@router.get("/doc", response_model=ApiResponse)
async def doc(
    doc_id: Annotated[str, Query(min_length=4, max_length=40)],
    usr_seq: Annotated[str, Query(pattern=r"^[0-9]{0,10}$")] = "",
    office_code: Annotated[str, Query(pattern=r"^[0-9A-Za-z]{0,10}$")] = "",
) -> ApiResponse | JSONResponse:
    """감정서 한 건 카드. 목록에서 번호를 눌렀을 때 — 소속 지사 건만 연다."""
    office = await _office_of(usr_seq, office_code)
    if office is None:
        return _failed(_AUTH_NOTE, code="GAMJUN_AUTH")
    try:
        data = await gamjun_chat.doc_detail(doc_id, office)
    except Exception:
        logger.exception("[gamjun-chat] doc 실패: %s", doc_id)
        return _failed("조회 중 문제가 생겼습니다. 잠시 후 다시 물어봐 주세요.")
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


class DepositListQuery(BaseModel):
    date_from: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    date_to: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    only_blank: bool = False
    # 적요 부분일치 — '세연스틸'·'부산은행'처럼 거래처 이름으로 기간 안을 좁힌다.
    keyword: Annotated[str, Field(max_length=60)] = ""
    usr_seq: Annotated[str, Field(pattern=r"^[0-9]{0,10}$")] = ""
    office_code: Annotated[str, Field(pattern=r"^[0-9A-Za-z]{0,10}$")] = ""


@router.post("/deposits", response_model=ApiResponse)
async def deposits(body: DepositListQuery = Body(...)) -> ApiResponse | JSONResponse:
    """기간 입금 목록 + 각 건의 감정서 후보 (통장 ACCT_TXDAY 기준).

    통장은 지사로 나눌 수 없다 — 한 계좌에 전 지사 수수료가 섞여 들어온다.
    그래서 조회 범위를 좁히는 대신 **전체조회 권한자만** 들여보낸다 (재무팀 업무).
    """
    office = await _office_of(body.usr_seq, body.office_code)
    if office is None:
        return _failed(_AUTH_NOTE, code="GAMJUN_AUTH")
    if not await gamjun_chat.can_view_all(body.usr_seq):
        return _failed(
            "통장 입금 목록은 본사(전체조회 권한)만 볼 수 있습니다.", code="GAMJUN_AUTH"
        )
    try:
        from app.services import deposit_list  # noqa: PLC0415

        data = await deposit_list.list_deposits(
            body.date_from, body.date_to, body.only_blank,
            keyword=body.keyword)
    except Exception:
        logger.exception("[gamjun-chat] 입금 목록 실패")
        return _failed("조회 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.")
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)


class DepositMatchQuery(BaseModel):
    """목록에서 누른 한 줄. 통장에서 읽어 온 값을 그대로 되돌려 받는다."""

    jeokyo: Annotated[str, Field(min_length=1, max_length=200)]
    amount: Annotated[int, Field(ge=0, le=10**13)] = 0
    day: Annotated[str, Field(pattern=r"^(\d{4}-\d{2}-\d{2})?$")] = ""
    unique_field: Annotated[str, Field(max_length=80)] = ""
    usr_seq: Annotated[str, Field(pattern=r"^[0-9]{0,10}$")] = ""
    office_code: Annotated[str, Field(pattern=r"^[0-9A-Za-z]{0,10}$")] = ""


@router.post("/deposit-match", response_model=ApiResponse)
async def deposit_match_one(
    body: DepositMatchQuery = Body(...),
) -> ApiResponse | JSONResponse:
    """목록에서 누른 한 줄의 감정서 찾기.

    목록 조회와 갈라 둔 이유: 한 건마다 통장·원장·전표 세 DB 를 두드려 1초쯤
    걸리는데, 재무팀이 실제로 손대는 건 하루치 중 몇 줄뿐이다.
    """
    office = await _office_of(body.usr_seq, body.office_code)
    if office is None:
        return _failed(_AUTH_NOTE, code="GAMJUN_AUTH")
    if not await gamjun_chat.can_view_all(body.usr_seq):
        return _failed(
            "통장 입금 목록은 본사(전체조회 권한)만 볼 수 있습니다.", code="GAMJUN_AUTH"
        )
    try:
        from app.services import deposit_list  # noqa: PLC0415

        data = await deposit_list.match_one(
            body.jeokyo, body.amount, body.day, body.unique_field)
    except Exception:
        logger.exception("[gamjun-chat] 입금 매칭 실패: %s", body.jeokyo[:60])
        return _failed("찾는 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.")
    return ApiResponse(success=True, code="0000", message="조회 완료", data=data)
