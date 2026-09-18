"""다른 반월에 이미 협회로 보고한 건 잡아내기.

협회 조회는 (APPCODE, BUNGI, MON) 한 칸씩만 준다. 그래서 8월 반월을 보면 4월에
보고해 둔 건이 '미등록'으로 되살아나 또 대상이 된다.

실측(2026-09-04, 본사): 01-2601-1-0001 은 협회에 2026-04 로 등록돼 있는데
2026-08 하반 377행에 그대로 떴다 — 재무팀이 "중복돼서 나왔다"고 한 그 건이다.
범위를 최근 6개월로 넓히면 그 1건만 더 잡히고, 2026-08 상반·2026-07 하반은
추가 0건이었다(오탐 없음).
"""

import re
from pathlib import Path

import pytest

import app.services.kapa_submit as ks

JS = Path(__file__).parents[1] / "desktop" / "ui" / "work-report.js"

# 협회 서버가 월별로 내주는 등록분 — 01-2601-1-0001 은 4월에 보고돼 있다.
REGISTERED = {
    (2026, 4): {"01-2601-1-0001", "01-2604-9-0009"},
    (2026, 8): {"01-2608-3-2592"},
}


@pytest.fixture
def fake_kapa(monkeypatch):
    calls = []

    def fake_fetch(appcode, bungi, mon, **kw):
        calls.append((bungi, mon))
        # bungi 는 '20262' 꼴이라 앞 4자리가 연도다.
        year = int(str(bungi)[:4])
        return set(REGISTERED.get((year, mon), set()))

    monkeypatch.setattr(ks, "fetch_registered_doc_ids", fake_fetch)
    monkeypatch.setattr(ks, "_cache", {})          # 테스트 간 캐시 격리
    return calls


def test_finds_a_doc_reported_in_another_month(fake_kapa):
    found = ks.fetch_registered_months("300611", 2026, 8)
    assert found["checked"] is True
    assert found["failed"] == []
    # 8월(그 달)에 등록된 건은 current 로 분리된다 — 같은 반월 재전송은 중복이 아니다.
    assert found["current"] == {"01-2608-3-2592"}
    # 4월 등록분은 by_doc 에 언제 등록됐는지까지 남는다.
    assert found["by_doc"]["01-2601-1-0001"] == "2026-04"
    assert found["by_doc"]["01-2608-3-2592"] == "2026-08"


def test_lookback_covers_six_months_back_to_the_previous_year(fake_kapa):
    ks.fetch_registered_months("300611", 2026, 2, lookback=6)
    months = [mon for _, mon in fake_kapa]
    # 2026-02 에서 6개월 되짚으면 2025-09 까지 간다 — 연을 넘어가도 끊기면 안 된다.
    assert months == [2, 1, 12, 11, 10, 9]
    years = {str(bungi)[:4] for bungi, _ in fake_kapa}
    assert years == {"2026", "2025"}


def test_by_doc_keeps_the_latest_month_when_reported_twice(monkeypatch):
    """두 번 보고된 건은 가장 최근 등록 월을 남긴다 — 담당자가 볼 값은 최신이다."""
    monkeypatch.setattr(ks, "_cache", {})
    monkeypatch.setattr(
        ks, "fetch_registered_doc_ids",
        lambda appcode, bungi, mon, **kw: {"01-2601-1-0001"} if mon in (4, 6) else set(),
    )
    found = ks.fetch_registered_months("300611", 2026, 8)
    assert found["by_doc"]["01-2601-1-0001"] == "2026-06"


def test_one_failed_month_does_not_kill_the_whole_check(monkeypatch):
    """한 달치가 실패해도 나머지로 판정한다. 대신 어느 달이 실패했는지 남긴다."""
    monkeypatch.setattr(ks, "_cache", {})

    def flaky(appcode, bungi, mon, **kw):
        if mon == 6:
            raise ks.KapaQueryError("협회 조회 실패: 일시 오류")
        return set(REGISTERED.get((int(str(bungi)[:4]), mon), set()))

    monkeypatch.setattr(ks, "fetch_registered_doc_ids", flaky)
    found = ks.fetch_registered_months("300611", 2026, 8)
    assert found["failed"] == ["2026-06"]
    assert found["checked"] is True                      # 8월 자체는 확인됐다
    assert found["by_doc"]["01-2601-1-0001"] == "2026-04"


def test_current_month_failure_marks_the_check_untrustworthy(monkeypatch):
    """조회 중인 그 달이 실패하면 판정을 믿을 수 없다 — checked 가 False 여야 한다."""
    monkeypatch.setattr(ks, "_cache", {})

    def flaky(appcode, bungi, mon, **kw):
        if mon == 8:
            raise ks.KapaQueryError("협회 조회 실패")
        return set()

    monkeypatch.setattr(ks, "fetch_registered_doc_ids", flaky)
    found = ks.fetch_registered_months("300611", 2026, 8)
    assert found["checked"] is False
    assert "2026-08" in found["failed"]


def test_cache_avoids_hammering_the_association(fake_kapa):
    """같은 반월을 두 번 조회해도 협회를 두 번 부르지 않는다(TTL 안)."""
    ks.fetch_registered_months("300611", 2026, 8)
    first = len(fake_kapa)
    ks.fetch_registered_months("300611", 2026, 8)
    assert len(fake_kapa) == first, "캐시가 안 먹어 협회를 또 부른다"


def test_screen_unchecks_only_other_month_registrations():
    """이미 보고한 건은 기본 체크 해제. 단 같은 달 등록분은 건드리지 않는다.

    같은 달 등록분까지 해제하면 이미 보고를 마친 반월이 통째로 체크 해제된다
    (실측: 2026-08 상반은 117행 중 116행이 그 달 등록분이다).
    """
    js = JS.read_text(encoding="utf-8")
    body = js.split("function autoExcluded(row){", 1)[1].split("}", 1)[0]
    # 주석은 뺀다 — 설명 문구에 이름이 나온다고 코드가 그렇게 도는 건 아니다.
    code = re.sub(r"//.*", "", body)
    assert "KAPA_DUPLICATE" in code, "이미 보고한 건이 기본 체크로 남는다"
    assert "KAPA_REGISTERED" not in code.replace("KAPA_DUPLICATE", ""), (
        "같은 달 등록분까지 해제하면 재전송이 막힌다"
    )
    # 언제 보고했는지 배지에 적어야 담당자가 판단할 수 있다
    assert "KAPA_REGISTERED_AT" in js
    assert "이미 보고" in js
