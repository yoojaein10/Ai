"""감정서 챗봇 골든셋 — 실DB·Gemini 를 실제로 태우는 회귀 검증 (옵트인).

벤더의 30문항 골든셋은 벤더 몫이고, 여기는 **우리가 얹은 것**만 본다:
돈 경로 라우팅·화면 숫자 일치·소속 범위·요약 라우팅·원장 폴백.

평소 pytest 에서는 건너뛴다 (외부 DB·API 의존이라 느리고 순단에 흔들린다).
챗봇 쪽을 고친 뒤에는 반드시 한 번 돌린다:

    GAMJUN_GOLDEN=1 pytest tests/test_gamjun_golden.py -v          (bash)
    $env:GAMJUN_GOLDEN='1'; pytest tests/test_gamjun_golden.py -v  (PowerShell)
"""

import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("GAMJUN_GOLDEN") != "1",
    reason="실DB·Gemini 를 태우는 골든셋 — GAMJUN_GOLDEN=1 로 옵트인",
)

OFFICE = "10"  # 본사


def _ask(question, prev=""):
    from app.services import gamjun_chat

    return asyncio.run(gamjun_chat.ask(question, prev, OFFICE))


def test_돈_질문은_입금현황과_같은_숫자다():
    """'이번 달 들어온 돈' == receivable_status_cte 직접 계산 (기간 입금분)."""
    import datetime as dt

    from app.services import money_chat

    today = dt.date.today()
    expected = money_chat._inflow_sync(today.replace(day=1), today, OFFICE)
    result = _ask("이번 달 들어온 돈 얼마야?")
    assert format(expected["inflow"], ",.0f") in result["answer"], (
        "챗봇 입금액이 화면 계산식과 다르다: %s" % result["answer"][:200]
    )


def test_미수금_질문은_돈_경로로_간다():
    result = _ask("미수금 얼마야?")
    assert "미수금 합계" in result["answer"]
    assert "본사" in result["answer"], "소속 라벨이 답에 밝혀져야 한다"
    assert "최근 입금일" in result["answer"], "기간 의미(화면과 동일)를 밝혀야 한다"


def test_지역_검색은_소속으로_좁혀진다():
    result = _ask("강남구 감정서 보여줘")
    assert result["spec"].get("office") == "본사"
    assert result.get("rows", 0) >= 1


def test_다른_지사를_물으면_제한을_밝힌다():
    result = _ask("동부지사 아파트 감정서 보여줘")
    assert "소속(본사)" in (result.get("note") or ""), result.get("note")


def test_집계_질문은_집계로_답한다():
    result = _ask("평가액 100억 넘는 감정서 몇 건이야?")
    assert result.get("rows", 0) >= 1
    assert "건" in result["answer"]


def test_그룹_질문은_그룹으로_답한다():
    result = _ask("목적별 감정서 건수 알려줘")
    assert "|" in result["answer"], "표가 나와야 한다"


def test_서술격_조사가_붙은_이름도_찾는다():
    result = _ask("채무자가 곽한성인 건 알려줘")
    assert result.get("rows", 0) >= 1, "copula 재시도가 죽었다"


def test_감정서_카드에는_입금_상태가_붙는다():
    """전표가 있는 건(미수 목록에서 뽑음)의 카드에는 입금현황과 같은 한 줄이 붙는다.

    전표가 아예 없는 신건(배정중 등)은 설계대로 조용히 생략되므로 여기서 안 본다.
    """
    import re

    from app.services import gamjun_chat

    top = _ask("미수금 큰 순 5건 보여줘")
    doc_ids = re.findall(r"\b(01-\d{4}-[0-9A-Z]-\d{4}(?:-\d+)?)\b", top["answer"])
    assert doc_ids, "미수 목록에서 번호를 못 찾았다"
    card = asyncio.run(gamjun_chat.doc_detail(doc_ids[0], OFFICE))
    assert "입금 상태" in card["answer"], (
        "돈 이력이 있는 건인데 입금 줄이 없다: %s" % card["answer"][:200]
    )


def test_다른_지사_감정서_카드는_거부된다():
    from app.services import gamjun_chat

    result = asyncio.run(gamjun_chat.doc_detail("13-2601-1-0001", OFFICE))
    assert result["answer"] == ""
    assert "소속(본사)" in result["note"]


def test_자동완성은_소속_거래처만_준다():
    from app.services import gamjun_chat

    items = asyncio.run(gamjun_chat.suggest("한국투자", OFFICE))
    assert items, "자동완성이 빈손이다"
    assert any(item["kind"] == "거래처" for item in items)


def test_칩_편집_재조회가_동작한다():
    from app.services import gamjun_chat

    narrow = asyncio.run(gamjun_chat.requery(
        {"region": "강남구", "category_use": "아파트"}, OFFICE))
    wide = asyncio.run(gamjun_chat.requery({"region": "강남구"}, OFFICE))
    assert narrow.get("rows", 0) >= 0 and wide.get("rows", 0) >= narrow.get("rows", 0) or (
        wide.get("rows", 0) == 10  # 둘 다 TOP 10 이면 같을 수 있다
    )
    assert wide["spec"]["office"] == "본사", "재조회도 소속 강제"


def test_파싱_전_감정서는_원장으로_답한다():
    """원장에는 있는데 원문 DB에 아직 없는 최신 건 — '못 찾음' 대신 원장 정보."""
    from sqlalchemy import text

    from app.database import get_session_factory
    from app.services import gamjun_chat
    from app.services.appraisals import _source_view

    db = get_session_factory()()
    try:
        # 어제~오늘 접수분은 원문 DB(전일 반영)에 없을 확률이 높다.
        rows = db.execute(text(
            f"SELECT TOP 5 a.DocID FROM {_source_view()} a "
            f"WHERE a.DocID LIKE '01-%' AND a.ReceiptDate >= CONVERT(date, GETDATE()-1) "
            f"ORDER BY a.ReceiptDate DESC"
        )).scalars().all()
    finally:
        db.close()
    if not rows:
        pytest.skip("어제 이후 접수 건이 없다")
    fresh = None
    for doc_id in rows:
        card = asyncio.run(gamjun_chat.doc_detail(str(doc_id).strip(), OFFICE))
        if "파싱 전" in card["answer"]:
            fresh = card
            break
    if fresh is None:
        pytest.skip("최신 건이 이미 전부 파싱돼 있다 (폴백 경로는 코드 테스트로 커버)")
    assert "접수일" in fresh["answer"]
