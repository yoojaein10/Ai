from app.services import attendance as svc


# ── _hhmmss ───────────────────────────────────────────────


def test_hhmmss_none_returns_none():
    assert svc._hhmmss(None) is None


def test_hhmmss_empty_returns_none():
    assert svc._hhmmss("") is None


def test_hhmmss_too_short_returns_none():
    assert svc._hhmmss("12345") is None


def test_hhmmss_formats_six_digits():
    assert svc._hhmmss("093015") == "09:30:15"


def test_hhmmss_truncates_extra_digits():
    assert svc._hhmmss("0930159") == "09:30:15"


def test_hhmmss_zero_padded_value():
    assert svc._hhmmss("000005") == "00:00:05"


# ── _work_minutes ─────────────────────────────────────────


def test_work_minutes_none_inputs():
    assert svc._work_minutes(None, None) is None
    assert svc._work_minutes("090000", None) is None
    assert svc._work_minutes(None, "180000") is None


def test_work_minutes_empty_inputs():
    assert svc._work_minutes("", "180000") is None
    assert svc._work_minutes("090000", "") is None


def test_work_minutes_same_time_returns_none():
    assert svc._work_minutes("090000", "090000") is None


def test_work_minutes_normal_workday():
    assert svc._work_minutes("090000", "180000") == 540


def test_work_minutes_partial_minutes_truncated():
    assert svc._work_minutes("090000", "093045") == 30


def test_work_minutes_invalid_format_returns_none():
    assert svc._work_minutes("notatime", "180000") is None
    assert svc._work_minutes("090000", "99:99:99") is None


def test_work_minutes_negative_delta_returns_none():
    assert svc._work_minutes("180000", "090000") is None


# ── _half_day_multiplier ──────────────────────────────────


def test_half_day_multiplier_none_returns_full():
    assert svc._half_day_multiplier(None) == 1.0


def test_half_day_multiplier_empty_returns_full():
    assert svc._half_day_multiplier("") == 1.0


def test_half_day_multiplier_no_keyword_returns_full():
    assert svc._half_day_multiplier("연차") == 1.0


def test_half_day_multiplier_keyword_returns_half():
    assert svc._half_day_multiplier("오전 반차") == 0.5


def test_half_day_multiplier_handles_whitespace():
    assert svc._half_day_multiplier("반 차") == 0.5


# ── _minutes_between ──────────────────────────────────────


def test_minutes_between_none_returns_zero():
    assert svc._minutes_between(None, None) == 0
    assert svc._minutes_between(None, "180000") == 0
    assert svc._minutes_between("090000", None) == 0


def test_minutes_between_same_time_returns_zero():
    assert svc._minutes_between("090000", "090000") == 0


def test_minutes_between_normal_workday():
    assert svc._minutes_between("090000", "180000") == 540


def test_minutes_between_invalid_format_returns_zero():
    assert svc._minutes_between("xx", "180000") == 0


def test_minutes_between_negative_clamped_to_zero():
    assert svc._minutes_between("180000", "090000") == 0
