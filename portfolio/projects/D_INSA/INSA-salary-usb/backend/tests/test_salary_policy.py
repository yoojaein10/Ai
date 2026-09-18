"""연봉 금고 IP 접근 정책 — 스펙 §9.2."""


def test_policy_table_name_and_columns():
    from app.db.models import SalaryVaultPolicy

    assert SalaryVaultPolicy.__tablename__ == "insa_salary_vault_policy"
    columns = {c.name for c in SalaryVaultPolicy.__table__.columns}
    assert {"owner_user_id", "allowed_ip", "is_active", "updated_by", "updated_at"} <= columns


def test_check_denies_when_no_seat_and_no_policy(client, auth_headers, db_session):
    """좌석 매핑도 수동 정책도 없으면 거부한다(fail-closed). 정책 등록은
    SYSTEM_ADMIN의 별도 API라 check가 거부돼도 최초 설정은 가능하다."""
    from app.db.models import SalaryAccessLog

    res = client.get("/api/v1/salary/policy/check", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["allowed"] is False
    assert body["configured"] is False
    assert body["via"] is None
    assert body["login_id"] == "admin"
    assert "admin" in body["reason"] and "권한이 없습니다" in body["reason"]
    assert db_session.query(SalaryAccessLog).filter_by(action="IP_DENIED").count() == 1


def test_check_allows_when_seat_ip_matches(client, auth_headers, monkeypatch):
    """SEAT_USERINFO의 UID로 만든 기대 IP가 접속 IP와 같으면 좌석 규칙으로 허용."""
    from app.services import salary_seat

    current = client.get("/api/v1/salary/policy/check", headers=auth_headers).json()["current_ip"]
    monkeypatch.setattr(salary_seat, "lookup_seat_uid", lambda apw_db, login_id: 187)
    monkeypatch.setattr(salary_seat, "expected_ip_for_uid", lambda uid: current if uid == 187 else "x")

    res = client.get("/api/v1/salary/policy/check", headers=auth_headers)
    body = res.json()
    assert body["allowed"] is True
    assert body["via"] == "seat"
    assert body["seat_expected_ip"] == current


def test_check_denies_when_seat_ip_differs(client, auth_headers, monkeypatch):
    from app.services import salary_seat

    monkeypatch.setattr(salary_seat, "lookup_seat_uid", lambda apw_db, login_id: 187)
    monkeypatch.setattr(salary_seat, "expected_ip_for_uid", lambda uid: '192.0.2.10')

    body = client.get("/api/v1/salary/policy/check", headers=auth_headers).json()
    assert body["allowed"] is False
    assert body["seat_expected_ip"] == '192.0.2.10'


def test_check_denies_when_seat_lookup_fails(client, auth_headers, monkeypatch):
    """APW 장애는 허용이 아니라 거부다."""
    from app.services import salary_seat

    def boom(apw_db, login_id):
        raise RuntimeError("apw down")

    monkeypatch.setattr(salary_seat, "lookup_seat_uid", boom)
    body = client.get("/api/v1/salary/policy/check", headers=auth_headers).json()
    assert body["allowed"] is False


def test_manual_policy_only_applies_to_its_owner(
    client, system_admin_headers, auth_headers, admin_user, system_admin_user
):
    """다른 사용자 소유의 수동 정책은 나를 허용하지 않는다."""
    current = client.get("/api/v1/salary/policy/check", headers=auth_headers).json()["current_ip"]
    client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": system_admin_user.id, "allowed_ip": current},
        headers=system_admin_headers,
    )
    body = client.get("/api/v1/salary/policy/check", headers=auth_headers).json()
    assert body["allowed"] is False
    assert body["configured"] is False


def test_expected_ip_uses_prefix_setting():
    from app.core.config import settings
    from app.services.salary_seat import expected_ip_for_uid

    assert expected_ip_for_uid(187) == f"{settings.SALARY_SEAT_IP_PREFIX}187"


def test_lookup_seat_uid_returns_none_without_apw_db():
    from app.services.salary_seat import lookup_seat_uid

    assert lookup_seat_uid(None, "4317") is None


def test_hr_admin_cannot_write_policy(client, auth_headers, admin_user):
    res = client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": '192.0.2.10'},
        headers=auth_headers,
    )
    assert res.status_code == 403


def test_system_admin_can_write_policy(client, system_admin_headers, admin_user):
    res = client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": '192.0.2.10'},
        headers=system_admin_headers,
    )
    assert res.status_code == 200
    assert res.json()["allowed_ip"] == '192.0.2.10'


def test_policy_write_leaves_policy_change_log(
    client, system_admin_headers, admin_user, db_session
):
    from app.db.models import SalaryAccessLog

    client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": '192.0.2.10'},
        headers=system_admin_headers,
    )
    logs = (
        db_session.query(SalaryAccessLog)
        .filter(SalaryAccessLog.action == "POLICY_CHANGE")
        .all()
    )
    assert len(logs) == 1


def test_invalid_ip_rejected(client, system_admin_headers, admin_user):
    res = client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": "not-an-ip"},
        headers=system_admin_headers,
    )
    assert res.status_code == 422


def test_check_denies_from_other_ip(client, system_admin_headers, auth_headers, admin_user):
    """TestClient의 요청 IP는 testclient이므로 다른 IP를 등록하면 거부된다."""
    client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": '192.0.2.10'},
        headers=system_admin_headers,
    )
    res = client.get("/api/v1/salary/policy/check", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["allowed"] is False


def test_denied_check_writes_ip_denied_log(
    client, system_admin_headers, auth_headers, admin_user, db_session
):
    from app.db.models import SalaryAccessLog

    client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": '192.0.2.10'},
        headers=system_admin_headers,
    )
    client.get("/api/v1/salary/policy/check", headers=auth_headers)

    logs = (
        db_session.query(SalaryAccessLog)
        .filter(SalaryAccessLog.action == "IP_DENIED")
        .all()
    )
    assert len(logs) == 1


def test_check_allows_from_matching_ip(
    client, system_admin_headers, auth_headers, admin_user, monkeypatch
):
    """접속 IP와 같은 수동 정책(내 소유)이 있으면 허용된다.

    TestClient의 접속 IP는 "testclient"라 IP 형식 검증에 걸리므로 유효한 IP로 흉내낸다.
    """
    import app.api.v1.salary_policy as mod

    monkeypatch.setattr(mod, "client_ip", lambda request: '192.0.2.10')
    put = client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": '192.0.2.10'},
        headers=system_admin_headers,
    )
    assert put.status_code == 200
    res = client.get("/api/v1/salary/policy/check", headers=auth_headers)
    assert res.json()["allowed"] is True
    assert res.json()["via"] == "manual"
    assert res.json()["configured"] is True


def test_upsert_deactivates_other_owners_active_policy(
    client, system_admin_headers, admin_user, system_admin_user, db_session
):
    """활성 정책은 항상 최대 1개 — 스키마가 아니라 upsert가 강제한다 (Task 5 리뷰 지적).

    A(admin_user)에게 활성 정책을 만든 뒤 B(system_admin_user)에게 upsert하면,
    A의 행은 비활성화되고 활성 행은 B의 것 하나만 남아야 한다.
    """
    from app.db.models import SalaryVaultPolicy

    client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": '192.0.2.10'},
        headers=system_admin_headers,
    )
    client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": system_admin_user.id, "allowed_ip": '192.0.2.10'},
        headers=system_admin_headers,
    )

    active_rows = (
        db_session.query(SalaryVaultPolicy)
        .filter(SalaryVaultPolicy.is_active == True)  # noqa: E712
        .all()
    )
    assert len(active_rows) == 1
    assert active_rows[0].owner_user_id == system_admin_user.id


def test_get_policy_when_not_configured(client, system_admin_headers):
    res = client.get("/api/v1/salary/policy", headers=system_admin_headers)
    assert res.status_code == 200
    assert res.json() is None


def test_get_policy_when_configured(client, system_admin_headers, admin_user):
    client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": '192.0.2.10'},
        headers=system_admin_headers,
    )
    res = client.get("/api/v1/salary/policy", headers=system_admin_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["owner_user_id"] == admin_user.id
    assert body["allowed_ip"] == '192.0.2.10'


def test_hr_admin_cannot_read_policy(client, auth_headers):
    res = client.get("/api/v1/salary/policy", headers=auth_headers)
    assert res.status_code == 403


def test_denied_check_actually_commits(
    client, system_admin_headers, auth_headers, admin_user, db_session, monkeypatch
):
    """db_session은 테스트와 요청이 공유하는 같은 세션 객체다. log_access는 flush만
    하고 커밋하지 않으므로, check_policy가 db.commit()을 아예 호출하지 않아도
    이 세션으로 조회하면 flush된 IP_DENIED 행이 그대로 보인다 — 즉 행의 '존재'만
    확인하는 test_denied_check_writes_ip_denied_log는 커밋 누락을 검출하지 못한다.
    그래서 여기서는 행이 아니라 session.commit() 호출 자체를 관찰한다.
    """
    client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": '192.0.2.10'},
        headers=system_admin_headers,
    )

    commit_calls = []
    original_commit = db_session.commit

    def counting_commit():
        commit_calls.append(1)
        return original_commit()

    monkeypatch.setattr(db_session, "commit", counting_commit)

    res = client.get("/api/v1/salary/policy/check", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["allowed"] is False
    assert len(commit_calls) >= 1


def test_upsert_policy_actually_commits(
    client, system_admin_headers, admin_user, db_session, monkeypatch
):
    """위 테스트와 같은 이유로, 행 존재가 아니라 commit() 호출 자체를 관찰한다 —
    db_session이 요청과 테스트에서 공유되는 한 flush만으로도 조회 결과는 커밋된
    경우와 구별되지 않는다.
    """
    commit_calls = []
    original_commit = db_session.commit

    def counting_commit():
        commit_calls.append(1)
        return original_commit()

    monkeypatch.setattr(db_session, "commit", counting_commit)

    res = client.put(
        "/api/v1/salary/policy",
        json={"owner_user_id": admin_user.id, "allowed_ip": '192.0.2.10'},
        headers=system_admin_headers,
    )
    assert res.status_code == 200
    assert len(commit_calls) >= 1
