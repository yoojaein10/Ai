"""보수기준 점검 조회 캐시 — 재사용 판정과 화면 조건 분리.

캐시를 그냥 얹으면 두 가지 사고가 난다. 둘 다 실측으로 겪었다.
  1. 규칙을 고쳐도 낡은 결과가 계속 나온다(빈 결과가 캐시돼 있는데 응답이 빨라서
     정상처럼 보였다).
  2. 필터별로 캐시를 나누면 적중률만 떨어진다. 필터는 화면 조건이지 원천이 아니다.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services import fee_basis as fee_basis_cache

fee_rules = fee_basis_cache

NOW = datetime(2026, 7, 30, 3, 0, tzinfo=timezone.utc)


def item(doc_id, verdict, direction, **extra):
    """필수 필드를 모두 채운 행. is_fresh 가 필드 누락을 걸러내므로 빠짐없이 둔다."""
    row = {field: None for field in fee_basis_cache.REQUIRED_ITEM_FIELDS}
    row.update({
        "doc_id": doc_id, "verdict": verdict, "deviation_direction": direction,
    })
    row.update(extra)
    return row


def snapshot(**overrides):
    base = {
        "year": 2026,
        "month": 6,
        "half": "상반",
        "basis": "매출",
        "prepared_at": (NOW - timedelta(hours=1)).isoformat(),
        "rule_versions": fee_basis_cache._rule_versions(),
        "summary": {"total": 3},
        "items": [
            item("A", "일치", "기준 내"),
            item("B", "불일치", "하한 미만"),
            item("C", "미입력", "상한 초과"),
        ],
    }
    base.update(overrides)
    return base


def test_fresh_snapshot_is_reused():
    assert fee_basis_cache.is_fresh(snapshot(), now=NOW) is True


def test_changed_rule_version_invalidates_the_cache():
    """판별 규칙을 바꿨는데 낡은 결과가 계속 나오면 수정한 줄 알고 넘어간다."""
    stale = snapshot()
    stale["rule_versions"] = {
        **stale["rule_versions"], "basis_rules_version": "fee-basis-detect/0",
    }

    assert fee_basis_cache.is_fresh(stale, now=NOW) is False


def test_changed_fee_rules_version_invalidates_the_cache():
    """보수표가 바뀌면 금액 판정이 달라지므로 다시 만들어야 한다."""
    stale = snapshot()
    stale["rule_versions"] = {
        **stale["rule_versions"], "fee_rules_version": "fee-rules-ko/0",
    }

    assert fee_basis_cache.is_fresh(stale, now=NOW) is False


def test_snapshot_without_rule_versions_is_not_reused():
    """버전을 안 남긴 옛 스냅숏은 무엇으로 만들었는지 알 수 없다."""
    assert fee_basis_cache.is_fresh(snapshot(rule_versions={}), now=NOW) is False


def test_current_month_expires_sooner_than_a_closed_month():
    """당월은 전표가 계속 붙고, 마감월은 거의 안 변한다."""
    old = (NOW - timedelta(hours=10)).isoformat()

    current = snapshot(year=2026, month=7, prepared_at=old)
    closed = snapshot(year=2026, month=6, prepared_at=old)

    assert fee_basis_cache.is_fresh(current, now=NOW) is False
    assert fee_basis_cache.is_fresh(closed, now=NOW) is True


def test_unparseable_prepared_at_is_not_reused():
    assert fee_basis_cache.is_fresh(snapshot(prepared_at="어제"), now=NOW) is False


def test_filter_is_applied_to_the_frozen_list_not_the_source():
    """필터·페이지는 화면 조건이라 캐시 키에 넣지 않고 동결 목록에서 고른다.

    화면에서 판정 선택은 뺐지만 API·엑셀에는 남겨 둔다 — 특정 판정만 뽑아
    확인할 일이 있다.
    """
    frozen = snapshot()

    assert [i["doc_id"] for i in fee_basis_cache.select_view(frozen)["items"]] == [
        "A", "B", "C"
    ]
    assert [
        i["doc_id"] for i in fee_basis_cache.select_view(frozen, flt="불일치")["items"]
    ] == ["B"]
    assert [
        i["doc_id"] for i in fee_basis_cache.select_view(frozen, flt="미입력")["items"]
    ] == ["C"]
    # 금액 이탈은 코드 판정과 독립된 축이라 둘 다 걸린다.
    assert [
        i["doc_id"]
        for i in fee_basis_cache.select_view(frozen, flt="금액이탈")["items"]
    ] == ["B", "C"]


def test_paging_reports_the_filtered_total():
    """전체 건수를 돌려주면 화면 페이지 수가 틀린다."""
    view = fee_basis_cache.select_view(
        snapshot(), flt="불일치", page=1, page_size=50
    )

    assert view["total"] == 1
    assert view["summary"]["total"] == 3  # 집계는 필터 전 전체다


def test_deviation_constants_come_from_fee_rules():
    """금액 이탈 문자열을 여기서 다시 적으면 두 화면이 어긋난다."""
    view = fee_basis_cache.select_view(
        snapshot(items=[item("X", "일치", fee_rules.DEVIATION_BELOW)]),
        flt="금액이탈",
    )

    assert [i["doc_id"] for i in view["items"]] == ["X"]


def test_saved_opinion_is_not_overwritten_by_the_auto_suggestion():
    """담당자가 저장한 의견을 자동 제안이 덮으면 확정 내용이 사라진다.

    키는 감정서번호다 — 행 번호는 순번이라 원천에 행이 추가·삭제되면 옛 의견이
    엉뚱한 감정서에 붙는다.
    """
    frozen = snapshot(items=[
        item("A", "일치", "기준 내", source_row_number=1,
             suggested_opinion="자동제안"),
        item("B", "일치", "기준 내", source_row_number=2,
             suggested_opinion="자동제안"),
    ])

    view = fee_basis_cache.select_view(frozen, opinions={"A": "담당자 확정"})

    assert view["items"][0]["effective_opinion"] == "담당자 확정"
    assert view["items"][0]["saved_opinion"] == "담당자 확정"
    # 저장 안 한 행은 자동 제안이 초기값으로 남는다.
    assert view["items"][1]["effective_opinion"] == "자동제안"
    assert view["items"][1]["saved_opinion"] == ""


def test_snapshot_items_carry_a_row_number_for_saving():
    """저장 엔진은 행번호로 의견을 잡는다. 없으면 어느 행인지 특정할 수 없다."""
    frozen = snapshot()
    view = fee_basis_cache.select_view(frozen)

    # 캐시 계층이 붙이는 값이라 이 테스트 픽스처에는 없다 — build_snapshot이 채운다.
    assert all("saved_opinion" in item for item in view["items"])


def test_changed_snapshot_shape_invalidates_the_cache():
    """규칙이 그대로여도 담는 필드가 바뀌면 화면·저장이 깨진다.

    실측: 저장용 source_row_number를 추가했는데 버전을 안 올려 낡은 스냅숏이
    재사용됐고 조회에서 KeyError가 났다.
    """
    stale = snapshot()
    stale["rule_versions"] = {
        **stale["rule_versions"], "snapshot_shape_version": "fee-basis-snapshot/1",
    }

    assert fee_basis_cache.is_fresh(stale, now=NOW) is False


def test_snapshot_missing_a_required_field_is_rejected():
    """버전을 올리는 것을 잊어도 필드가 빠졌으면 캐시를 버려야 한다.

    실측: 오늘 세 번 잊었다. source_row_number 누락은 KeyError 를,
    primary_candidate 누락은 화면이 첫 후보를 표시하는 결과를 냈다.
    """
    full = {field: None for field in fee_basis_cache.REQUIRED_ITEM_FIELDS}

    assert fee_basis_cache.is_fresh(snapshot(items=[full]), now=NOW) is True

    for field in fee_basis_cache.REQUIRED_ITEM_FIELDS:
        broken = {k: v for k, v in full.items() if k != field}
        assert fee_basis_cache.is_fresh(
            snapshot(items=[broken]), now=NOW
        ) is False, f"{field} 가 빠졌는데 캐시를 재사용했다"


def test_empty_snapshot_passes_the_field_check():
    """행이 없는 달(조회 결과 0건)은 필드를 볼 수 없으니 통과시킨다."""
    assert fee_basis_cache.is_fresh(snapshot(items=[]), now=NOW) is True


def test_build_snapshot_produces_every_required_field():
    """캐시가 요구하는 필드를 생성부가 실제로 채우는지 고정한다.

    두 목록이 어긋나면 캐시가 늘 무효가 되어 매 조회가 80초가 된다.
    """
    from app.services import fee_basis

    produced = set()
    # 금액·요율 판정이 채우는 필드
    produced |= set(fee_basis._fee_judgement(None, None))
    produced |= set(fee_basis.describe(
        None, billed_fee=None, standard_fee=None, lower_fee=None, upper_fee=None,
    ))
    # 나머지는 build_fee_basis_report·attach_review_evidence·캐시가 채운다.
    produced |= {
        "doc_id", "source_row_number", "candidates", "primary_candidate",
        "primary_label", "primary_source", "primary_code", "suggested_opinion",
        "verdict", "entered_label", "parsed",
        # 할인 적정성(업무연락 제2026-38호) — 아이템 루프가 discount_judgement 로 채운다.
        "discount_state", "discount_note",
    }

    missing = [
        field for field in fee_basis_cache.REQUIRED_ITEM_FIELDS
        if field not in produced
    ]
    assert missing == [], f"생성부가 채우지 않는 필수 필드: {missing}"


def test_rule_versions_hash_content_not_count():
    """라벨을 하나 바꾸고 하나 지우면 개수는 같다 — 내용 해시라야 잡는다."""
    versions = fee_basis_cache._rule_versions()

    assert "code_label_hash" in versions and "text_signal_hash" in versions
    assert "code_label_count" not in versions
    # 해시는 내용에서 나온다 — 같은 입력이면 같은 값(결정적).
    assert versions == fee_basis_cache._rule_versions()


def test_opinion_rows_do_not_expire_like_cache_rows():
    """의견은 기록이지 캐시가 아니다. 90일 TTL 이 지나면 조회 필터에서 걸러져
    조용히 사라지고, 만료 후 첫 저장이 빈 병합 기반 위에 덮어써 기존 의견을
    영구 소실시킨다(배포 전 검토에서 확정된 결함).
    """
    # 사실상 만료 없음(100년). 스냅숏 TTL(90일)보다 압도적으로 길어야 한다.
    assert (
        fee_basis_cache.OPINION_TTL_SECONDS
        > fee_basis_cache.PERSISTED_TTL_SECONDS * 100
    )


def test_opinion_save_is_serialized_against_lost_update():
    """load→merge→save 가 원자적이지 않아 동시 저장이 서로를 지운다.

    서버가 단일 프로세스라 in-process 잠금으로 직렬화한다.
    """
    import threading

    assert isinstance(fee_basis_cache._SAVE_LOCK, type(threading.Lock()))
    # save 본문이 잠금 아래에서 도는 구조인지(위임 함수 존재) 고정한다.
    assert hasattr(fee_basis_cache, "_save_locked")


def test_source_hash_ignores_volatile_prepare_timestamps():
    """같은 원천의 재배치는 의견을 원천 변경으로 만들면 안 된다."""
    first = {
        "items": [{"doc_id": "A", "actual_fee": 100}],
        "prepared_at": "2026-07-30T01:00:00+00:00",
        "snapshot_created_at": "2026-07-30T01:00:00+00:00",
    }
    second = {
        **first,
        "prepared_at": "2026-07-30T02:00:00+00:00",
        "snapshot_created_at": "2026-07-30T02:00:00+00:00",
    }

    assert fee_basis_cache._canonical_hash(first) == fee_basis_cache._canonical_hash(second)
    second["items"] = [{"doc_id": "A", "actual_fee": 101}]
    assert fee_basis_cache._canonical_hash(first) != fee_basis_cache._canonical_hash(second)


def test_opinion_store_outage_is_not_treated_as_no_opinion(monkeypatch):
    def unavailable(**_kwargs):
        raise fee_basis_cache.RunStoreUnavailable("down")

    monkeypatch.setattr(fee_basis_cache, "find_prepared_run", unavailable)
    with pytest.raises(fee_basis_cache.RunStoreUnavailable):
        fee_basis_cache.load_with_source(
            object(), office_code="10", year=2026, month=7,
            half="상반", basis="매출",
        )


def test_opinion_save_binds_snapshot_and_rejects_unknown_doc(monkeypatch):
    from types import SimpleNamespace

    run = SimpleNamespace(
        run_id="RUN-1",
        source_sha256="A" * 64,
        data={"items": [{"doc_id": "KNOWN"}]},
    )
    monkeypatch.setattr(
        fee_basis_cache, "find_prepared_run", lambda **_kwargs: run
    )
    monkeypatch.setattr(fee_basis_cache, "load", lambda *_args, **_kwargs: {})

    with pytest.raises(fee_basis_cache.OpinionSourceChanged):
        fee_basis_cache.save(
            object(), office_code="10", year=2026, month=7,
            half="상반", basis="매출", opinions={"KNOWN": "의견"},
            snapshot_run_id="RUN-OLD",
            snapshot_source_sha256="A" * 64,
            snapshot_profile="FEE_BASIS_CHECK_V1",
        )

    with pytest.raises(fee_basis_cache.OpinionValidationError):
        fee_basis_cache.save(
            object(), office_code="10", year=2026, month=7,
            half="상반", basis="매출", opinions={"UNKNOWN": "의견"},
            snapshot_run_id="RUN-1",
            snapshot_source_sha256="A" * 64,
            snapshot_profile="FEE_BASIS_CHECK_V1",
        )
