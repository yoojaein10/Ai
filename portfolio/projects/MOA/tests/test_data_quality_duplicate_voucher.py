"""데이터 품질 점검 E — 입금 전표 중복 (2026-08-21 사용자 요청).

자동 전표 배치의 이중계상 가드는 10분 주기 캐시를 본다. 그래서 두 방향으로 샌다.
- 재무팀이 방금 넣은 전표를 배치가 못 보고 또 만든다 (01-2607-3-2258, 08-06).
- 배치가 먼저 만든 뒤 재무팀이 또 넣는다 (01-2607-4-0258, 08-20).

둘 다 전표가 두 장으로 남고, 요약 집계에서 입금이 두 배가 된다. 그 순간을 10분
배치가 사진 찍어 알림 큐에 박아 두는 것이 '큐 누적입금 과다' 21건의 주된 원인이었다.
막을 수는 없으니 **사람이 지우도록 목록으로 띄운다**.
"""

from datetime import date
from pathlib import Path

import pytest

SERVICE = (
    Path(__file__).resolve().parent.parent / "app" / "services" / "data_quality.py"
).read_text(encoding="utf-8")


def test_점검_항목이_등록돼_있다():
    assert '"key": "duplicate_payment_voucher"' in SERVICE
    assert '"title": "입금 전표 중복"' in SERVICE


def test_전표_장수로_센다():
    """반제 전표는 (차)보통예금/(대)외상매출금 한 장이다.

    계정별로 따로 세어 더하면 한 장을 두 번 세어 발행 건 전부가 중복으로 보인다
    (실측: 이렇게 셌더니 18건 중 15건이 오탐이었다).
    """
    block = SERVICE[SERVICE.index("e_rows = db.execute"):]
    block = block[:block.index("\n    checks = [")]

    assert "UNION" in block, "합집합으로 전표 장수를 세야 한다"
    assert "COUNT(*) AS cnt" in block
    assert "v.cnt > 1" in block


def test_감정서_단위_전표만_본다():
    """지사 본지점(BRANCH)·약식 묶음(YAK)은 doc_id 가 감정서번호가 아니다.

    BRANCH 는 은행 참조번호(302214244 등)라 관리번호로 못 찾고, 넣어 두면 132건이
    '전표 없음'으로 잡혀 목록이 못 쓰게 된다.
    """
    block = SERVICE[SERVICE.index("e_rows = db.execute"):]
    block = block[:block.index("\n    checks = [")]

    assert "o.voucher_kind IN ('BANJE','GENERAL')" in block
    assert "o.status = 'S'" in block, "실제로 발행한 건만 대상이다"


def test_관리번호는_직접_비교한다():
    """E·F 의 관리번호 상관 조건에 LTRIM(RTRIM()) 을 되살리면 인덱스 탐색이 막힌다.

    계산식 조인은 캐시가 자라면 옵티마이저가 174만 행 전체 스풀 계획으로 뒤집는다
    (2026-08-28 실측: E 하나가 논리 읽기 529만·10초 → 직접 비교로 0.2초, 결과 동일).
    앞공백 관리번호는 0건(아래 실데이터 핀)이고 꼬리 공백은 SQL Server 가 비교 시
    무시하므로 직접 비교가 안전하다 — 입금전표 배치 _voucher_kind 도 같다.
    """
    block = SERVICE[SERVICE.index("e_rows = db.execute"):]
    block = block[:block.index("\n    checks = [")]

    assert "a.management_no = o.doc_id" in block
    assert "s.management_no = o.doc_id" in block
    assert "c.management_no = o.doc_id" in block
    assert "LTRIM(RTRIM(a.management_no)) = o.doc_id" not in block
    assert "LTRIM(RTRIM(s.management_no)) = o.doc_id" not in block
    assert "LTRIM(RTRIM(c.management_no)) = o.doc_id" not in block


@pytest.mark.integration
def test_실데이터에_앞공백_관리번호가_없다():
    """직접 비교의 전제 — 앞공백 붙은 관리번호가 캐시에 생기면 E·F 가 그 건을
    놓치므로, 전제가 깨지는 순간 이 핀이 먼저 울려야 한다."""
    from sqlalchemy import text

    from app.database import get_session_factory

    db = get_session_factory()()
    try:
        n = db.execute(text(
            "SELECT COUNT(*) FROM dbo.a10_voucher_cache "
            "WHERE management_no IS NOT NULL AND management_no <> '' "
            "  AND management_no LIKE ' %'"
        )).scalar()
    finally:
        db.close()
    assert n == 0, f"앞공백 관리번호 {n}건 — E·F 직접 비교의 전제가 깨졌다"


def test_기간과_지사_조건을_지킨다():
    """다른 점검과 같은 조건으로 걸러야 화면 기간이 의미를 갖는다."""
    block = SERVICE[SERVICE.index("e_rows = db.execute"):]
    block = block[:block.index("\n    checks = [")]

    assert "o.tx_day BETWEEN :f AND :t" in block
    assert "CAST(:div AS varchar(10))" in block


def test_고치는_방법을_알려_준다():
    """'중복입니다'만으로는 재무팀이 무엇을 할지 모른다."""
    assert "한 장을 삭제하세요" in SERVICE
    assert "배치 발행" in SERVICE


def test_화면은_항목을_저절로_그린다():
    """새 점검을 넣을 때 화면을 함께 고쳐야 하면 다음번에 빠뜨린다."""
    js = (
        Path(__file__).resolve().parent.parent / "desktop" / "ui" / "data-quality.js"
    ).read_text(encoding="utf-8")

    assert "data.checks.map((c, i)" in js, "항목 목록을 그대로 돈다"
    assert 'data-k="${c.key}"' in js, "엑셀 내보내기도 key 로 자동 연결된다"


@pytest.mark.integration
def test_실데이터로_중복이_잡힌다():
    """2026-08-14 발행분 3건으로 검증했던 핀 — 재무팀이 정정을 마쳐(2026-08-28
    확인) 이제 0건이 정상 상태다. 건수는 못 박지 않고, 잡히는 건이 있다면
    목록 형식이 맞는지만 지킨다."""
    from app.database import get_session_factory
    from app.services.data_quality import run_checks

    db = get_session_factory()()
    try:
        data = run_checks(db, date(2026, 8, 1), date(2026, 8, 21), "10")
        check = next(
            c for c in data["checks"] if c["key"] == "duplicate_payment_voucher"
        )
        for item in check["items"]:
            assert item["lines"] >= 2, "전표가 2장 이상이어야 목록에 든다"
            assert "삭제" in item["reason"]
    finally:
        db.close()


# ── 속도 (2026-08-21) ────────────────────────────────────────────────────

def test_매출_유무는_한_번만_모아_맞댄다():
    """청구 건마다 NOT EXISTS 를 돌리면 인덱스를 못 써서 전량 스캔이 반복된다.

    LTRIM(RTRIM(management_no)) 이 인덱스를 무력화해, 연초~오늘 조회가 B 항목
    하나로 49초를 먹었다(전체 50.2초 중). 매출 관리번호를 한 번만 모아 맞대도록
    바꿔 0.2초가 됐고 결과는 같다(3건, 같은 감정서·금액).
    """
    block = SERVICE[SERVICE.index("# B. 외상매출금"):SERVICE.index("# C. 표준번호")]

    assert "WITH sales AS (" in block, "매출 번호를 한 번만 모아야 한다"
    assert "LEFT JOIN sales s ON s.mgmt = ar.mgmt" in block
    # 청구 건마다 도는 상관 서브쿼리를 되살리면 다시 50초가 된다.
    # (설명 주석의 'NOT EXISTS' 는 봐주고, 실제 그 형태만 막는다.)
    assert "LTRIM(RTRIM(v.management_no)) = ar.mgmt" not in block


@pytest.mark.integration
def test_실데이터_점검이_몇_초_안에_끝난다():
    """기본 기간(연초~오늘)에서 화면이 멈춘 것처럼 보이면 아무도 안 쓴다."""
    import time

    from app.database import get_session_factory
    from app.services.data_quality import run_checks

    db = get_session_factory()()
    try:
        started = time.time()
        run_checks(db, date(2026, 1, 1), date(2026, 8, 21), "10")
        elapsed = time.time() - started
    finally:
        db.close()

    assert elapsed < 10, f"기본 기간 점검이 {elapsed:.1f}초 걸린다 (고치기 전 50초)"


# ── F. 근거가 사라진 반제 전표 (2026-08-21) ──────────────────────────────

def test_근거가_사라진_반제를_잡는다():
    """배치는 발행 직전에 '같은 금액의 외상매출금 차변이 있나'를 다시 본다
    (deposit_vouchers._voucher_kind). 그런데 그 뒤 재무팀이 청구 전표를 지우고
    직접입금 전표로 바꾸면 반제만 남아 외상매출금이 음수가 된다.
    발행 시점 조건으로는 원리상 못 막으니 사후에 잡아 정리하게 한다.
    """
    assert '"key": "orphan_banje"' in SERVICE
    block = SERVICE[SERVICE.index("f_rows = db.execute"):SERVICE.index("\n    checks = [")]

    assert "o.voucher_kind = 'BANJE'" in block
    assert "o.status = 'S'" in block, "우리가 실제로 발행한 것만 본다"
    assert "ISNULL(v.bal, 0) < -0.5" in block


def test_잔액_음수만_보면_안_된다():
    """묶음 관리번호·지사·옛 데이터까지 2,750건 178억이 걸려 목록을 못 쓴다.

    우리가 발행한 반제(a10_deposit_outbox)로 좁혀야 문제 건만 남는다 — 실측 3건.
    """
    block = SERVICE[SERVICE.index("f_rows = db.execute"):SERVICE.index("\n    checks = [")]

    assert "FROM dbo.a10_deposit_outbox o" in block, "발행 기록에서 출발해야 한다"
    assert block.index("a10_deposit_outbox") < block.index("a10_voucher_cache"), (
        "전표에서 출발하면 2,750건이 걸린다"
    )


def test_F도_기간과_지사를_지킨다():
    block = SERVICE[SERVICE.index("f_rows = db.execute"):SERVICE.index("\n    checks = [")]

    assert "o.tx_day BETWEEN :f AND :t" in block
    assert "CAST(:div AS varchar(10))" in block


def test_F도_고치는_방법을_알려_준다():
    assert "반제 라인을 지우세요" in SERVICE
    assert "청구 없이 반제만 있음" in SERVICE


@pytest.mark.integration
def test_실데이터로_F가_잡은_건은_잔액이_음수다():
    """2026-08-14 발행 3건으로 검증했던 핀 — 재무팀이 정정을 마쳐(2026-08-28
    확인) 이제 0건이 정상 상태다. 잡히는 건이 있다면 형식만 지킨다."""
    from app.database import get_session_factory
    from app.services.data_quality import run_checks

    db = get_session_factory()()
    try:
        data = run_checks(db, date(2026, 8, 1), date(2026, 8, 21), "10")
        check = next(c for c in data["checks"] if c["key"] == "orphan_banje")
        for item in check["items"]:
            assert item["amount"] < 0, "외상매출금 잔액이 음수여야 한다"
    finally:
        db.close()
