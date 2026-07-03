"""PIN 인증 테스트: 형식, 중복 거부, 검증, 자료 격리, 첫 사용자 승계."""

import pytest

from app import pin_auth


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """users.json과 jobs 디렉토리를 테스트 전용 임시 경로로 격리."""
    monkeypatch.setattr(pin_auth, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(pin_auth.config, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(pin_auth, "WRONG_PIN_DELAY_SEC", 0)  # 테스트 속도
    yield tmp_path


def _make_job(tmp_path, job_id):
    d = tmp_path / "jobs" / job_id
    d.mkdir(parents=True)
    (d / "meta.json").write_text("{}", encoding="utf-8")


# --- 형식 -------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["123", "12345", "abcd", "12a4", "", None])
def test_format_rejected(bad):
    assert pin_auth.validate_pin_format(bad) is not None


def test_format_ok():
    assert pin_auth.validate_pin_format("0412") is None


# --- 등록·중복·검증 -----------------------------------------------------------

def test_register_and_verify():
    user_id, err = pin_auth.register_pin("1234")
    assert err is None
    assert pin_auth.verify_pin("1234") == user_id


def test_register_duplicate_rejected():
    pin_auth.register_pin("1234")
    user_id, err = pin_auth.register_pin("1234")
    assert user_id is None
    assert "이미 사용 중" in err


def test_verify_wrong_pin():
    pin_auth.register_pin("1234")
    assert pin_auth.verify_pin("9999") is None


def test_pin_stored_hashed(isolated_storage):
    pin_auth.register_pin("1234")
    raw = (isolated_storage / "users.json").read_text(encoding="utf-8")
    assert "1234" not in raw  # 평문 PIN이 파일에 없어야 한다


# --- 자료 격리 ----------------------------------------------------------------

def test_job_isolation_between_users():
    u1, _ = pin_auth.register_pin("1111")
    u2, _ = pin_auth.register_pin("2222")
    pin_auth.add_user_job(u1, "job-a")
    pin_auth.add_user_job(u2, "job-b")

    assert pin_auth.get_user_jobs(u1) == ["job-a"]
    assert pin_auth.get_user_jobs(u2) == ["job-b"]


def test_add_job_idempotent():
    u1, _ = pin_auth.register_pin("1111")
    pin_auth.add_user_job(u1, "job-a")
    pin_auth.add_user_job(u1, "job-a")
    assert pin_auth.get_user_jobs(u1) == ["job-a"]


def test_remove_user_job():
    u1, _ = pin_auth.register_pin("1111")
    pin_auth.add_user_job(u1, "job-a")
    pin_auth.remove_user_job(u1, "job-a")
    assert pin_auth.get_user_jobs(u1) == []


def test_delete_job_keeps_files_while_shared(isolated_storage):
    """두 사용자가 공유하는 job은 한 명이 지워도 파일이 남아야 한다."""
    _make_job(isolated_storage, "shared-job")
    u1, _ = pin_auth.register_pin("1111")  # 첫 사용자가 승계
    u2, _ = pin_auth.register_pin("2222")
    pin_auth.add_user_job(u2, "shared-job")

    purged = pin_auth.delete_job(u1, "shared-job")
    assert not purged  # u2가 아직 소유 — 파일 유지
    assert (isolated_storage / "jobs" / "shared-job").exists()
    assert pin_auth.get_user_jobs(u1) == []
    assert pin_auth.get_user_jobs(u2) == ["shared-job"]

    purged = pin_auth.delete_job(u2, "shared-job")
    assert purged  # 마지막 소유자 삭제 → 파일도 정리
    assert not (isolated_storage / "jobs" / "shared-job").exists()


def test_first_user_inherits_existing_jobs(isolated_storage):
    """PIN 도입 전 분석 자료는 첫 등록자(서비스 주인)가 승계한다."""
    _make_job(isolated_storage, "old-job-1")
    _make_job(isolated_storage, "old-job-2")

    u1, _ = pin_auth.register_pin("1111")
    assert sorted(pin_auth.get_user_jobs(u1)) == ["old-job-1", "old-job-2"]

    # 두 번째 사용자는 승계받지 않는다
    u2, _ = pin_auth.register_pin("2222")
    assert pin_auth.get_user_jobs(u2) == []
