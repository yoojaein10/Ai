"""배치가 담당자 입력을 되돌리지 못하게 하는 규칙을 고정한다.

요구: "배치 돌리고 난 후 직접 수정한 데이터, 의견저장한 데이터는 매일 배치가 돌아도
변하지 않게." 적대적 검증에서 되돌려지는 경로 세 개가 실제로 재현됐다.
"""

import json

import pytest

from app.services import fee_basis


def _item(doc_id: str, suggested: str = "확인필요") -> "dict[str, object]":
    return {"doc_id": doc_id, "suggested_opinion": suggested}


# ---------- 1) 비운 의견이 자동 제안으로 되살아나면 안 된다 ----------

def test_cleared_opinion_does_not_fall_back_to_the_auto_suggestion():
    """검토를 끝내고 칸을 비우면 그대로 공란이어야 한다.

    예전에는 `saved.get(doc) or 제안` 이라 빈 문자열이 falsy 로 밀려 '확인필요'가
    되살아났다. 그 제안 문구는 배치가 규칙을 고칠 때마다 바뀌고 엑셀에도 나간다.
    """
    view = fee_basis.select_view(
        {"items": [_item("01-2603-3-1000")]}, opinions={"01-2603-3-1000": ""}
    )
    row = view["items"][0]

    assert row["effective_opinion"] == ""
    assert row["saved_opinion"] == ""
    assert row["opinion_cleared"] is True


def test_never_saved_row_still_shows_the_auto_suggestion():
    """'저장한 적 없음'과 '일부러 비움'은 다르다."""
    view = fee_basis.select_view({"items": [_item("01-2603-3-1000")]}, opinions={})
    row = view["items"][0]

    assert row["effective_opinion"] == "확인필요"
    assert row["opinion_cleared"] is False


def test_saved_opinion_wins_over_the_auto_suggestion():
    view = fee_basis.select_view(
        {"items": [_item("01-2603-3-1000")]},
        opinions={"01-2603-3-1000": "법원감정"},
    )

    assert view["items"][0]["effective_opinion"] == "법원감정"


def test_apply_to_items_follows_the_same_rule_as_select_view():
    """엑셀 내보내기가 화면과 다른 문구를 쓰면 재무팀이 받는 파일이 어긋난다."""
    items = [_item("A"), _item("B"), _item("C")]

    fee_basis.apply_to_items(items, {"A": "", "B": "확정 의견"})

    assert [i["effective_opinion"] for i in items] == ["", "확정 의견", "확인필요"]


def test_stored_blank_opinion_survives_a_reload():
    """load_with_source 가 빈 값을 버리면 '비움'이 저장되지 않는다."""
    stored = {"opinions": {"01-2603-3-1000": "", " 01-2604-3-1086 ": "확정"}}

    class _Run:
        data = stored

    opinions, _sha = fee_basis._opinions_from_run(_Run())

    assert opinions == {"01-2603-3-1000": "", "01-2604-3-1086": "확정"}


# ---------- 2) 배치가 사람 입력(decisions_json)을 지우면 안 된다 ----------

def test_batch_rerun_keeps_human_decisions(monkeypatch):
    """save_prepared_run 이 decisions_json 을 빈 값으로 덮으면 사람 값이 사라진다."""
    payload = fee_basis._decisions_payload(
        opinions={1: "사람이 남긴 결정 의견"},
        skipped={2: "보류"},
        accepted={1},
    )
    kept, skipped, accepted, _meta = fee_basis._parse_decisions(json.dumps(payload))

    assert kept == {1: "사람이 남긴 결정 의견"}
    assert skipped == {2: "보류"}
    assert accepted == {1}


# ---------- 3) 의견 행이 TTL 로 조용히 사라지면 안 된다 ----------

def test_opinion_profile_always_gets_the_record_ttl():
    """호출부가 TTL 을 빠뜨려도 90일로 저장되면 만료 후 첫 저장이 영구 소실시킨다."""
    assert fee_basis.OPINION_TTL_SECONDS > 50 * 365 * 24 * 60 * 60
    assert fee_basis.OPINION_TTL_SECONDS > fee_basis.PERSISTED_TTL_SECONDS


def test_shared_lookup_requires_a_profile():
    """공용 소유자 범위에서 profile 을 빼면 스냅숏 행이 잡혀 의견이 빈 것으로 보인다."""
    with pytest.raises(fee_basis.RunValidationError):
        fee_basis.find_latest_run(
            owner_usr_seq=fee_basis.PREPARED_OWNER_USR_SEQ,
            office_code="10", year=2026, month=7, half="상반", basis="매출",
            profile=None, db=None,
        )
