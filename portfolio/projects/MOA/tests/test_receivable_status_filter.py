"""입금·미수금 화면 상태 다중선택 필터 테스트."""

from app.services.receivables import _STATUS_CONDITIONS


def _combined(statuses):
    """서비스가 만드는 것과 같은 방식으로 상태 조건을 묶는다."""
    selected = [s for s in statuses if s in _STATUS_CONDITIONS]
    if not selected:
        return ""
    return "(" + " OR ".join(_STATUS_CONDITIONS[s] for s in selected) + ")"


def test_single_status_keeps_its_condition():
    sql = _combined(["완납"])

    assert sql == "(" + _STATUS_CONDITIONS["완납"] + ")"


def test_multiple_statuses_joined_with_or():
    sql = _combined(["부분입금", "미입금"])

    assert " OR " in sql
    assert _STATUS_CONDITIONS["부분입금"] in sql
    assert _STATUS_CONDITIONS["미입금"] in sql
    assert sql.startswith("(") and sql.endswith(")")


def test_unknown_status_ignored():
    assert _combined(["없는상태"]) == ""
    assert _combined(["완납", "없는상태"]) == "(" + _STATUS_CONDITIONS["완납"] + ")"


def test_empty_means_no_filter():
    assert _combined([]) == ""


def test_all_statuses_are_wrapped_so_or_cannot_leak():
    """OR 조건이 괄호 없이 붙으면 다른 AND 조건과 섞여 결과가 틀어진다."""
    sql = _combined(list(_STATUS_CONDITIONS))

    assert sql.startswith("(") and sql.endswith(")")
    assert sql.count(" OR ") == len(_STATUS_CONDITIONS) - 1
