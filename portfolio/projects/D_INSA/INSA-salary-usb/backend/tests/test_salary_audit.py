"""연봉 감사 로그 — 스펙 §10."""

FORBIDDEN_COLUMNS = {
    "emp_id",
    "emp_no",
    "emp_name",
    "employee_id",
    "annual_salary",
    "raise_rate",
    "note",
    "password",
    "file_path",
    "salt",
    "iv",
}


def test_access_log_has_no_salary_columns():
    """연봉 데이터는 서버 스키마에 존재조차 하지 않아야 한다."""
    from app.db.models import SalaryAccessLog

    columns = {c.name for c in SalaryAccessLog.__table__.columns}
    assert columns & FORBIDDEN_COLUMNS == set()


def test_access_log_table_name():
    from app.db.models import SalaryAccessLog

    assert SalaryAccessLog.__tablename__ == "insa_salary_access_log"


def test_employee_cannot_post_log(client, plain_headers):
    res = client.post(
        "/api/v1/salary/access-logs",
        json={"action": "OPEN", "record_count": 3},
        headers=plain_headers,
    )
    assert res.status_code == 403


def test_hr_admin_can_post_log(client, auth_headers):
    res = client.post(
        "/api/v1/salary/access-logs",
        json={"action": "OPEN", "record_count": 3},
        headers=auth_headers,
    )
    assert res.status_code == 201


def test_server_fills_user_and_time_ignoring_client(client, auth_headers, admin_user):
    """클라이언트가 보낸 user_id·occurred_at은 무시하고 서버 값을 쓴다."""
    res = client.post(
        "/api/v1/salary/access-logs",
        json={
            "action": "SAVE",
            "record_count": 5,
            "user_id": 99999,
            "occurred_at": "1999-01-01T00:00:00",
        },
        headers=auth_headers,
    )
    assert res.status_code == 201
    body = res.json()
    assert body["user_id"] == admin_user.id
    assert not body["occurred_at"].startswith("1999")


def test_delegate_stores_target_user(client, auth_headers, system_admin_user):
    res = client.post(
        "/api/v1/salary/access-logs",
        json={"action": "DELEGATE", "target_user_id": system_admin_user.id},
        headers=auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["target_user_id"] == system_admin_user.id


def test_target_user_id_rejected_for_non_delegate(client, auth_headers, system_admin_user):
    res = client.post(
        "/api/v1/salary/access-logs",
        json={"action": "OPEN", "target_user_id": system_admin_user.id},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_unknown_target_user_rejected(client, auth_headers):
    res = client.post(
        "/api/v1/salary/access-logs",
        json={"action": "DELEGATE", "target_user_id": 987654},
        headers=auth_headers,
    )
    assert res.status_code == 400


def test_invalid_action_rejected(client, auth_headers):
    res = client.post(
        "/api/v1/salary/access-logs",
        json={"action": "NOT_A_REAL_ACTION"},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_hr_admin_cannot_read_logs(client, auth_headers):
    """본인이 본인 감사 기록을 관리하면 감사가 아니다."""
    res = client.get("/api/v1/salary/access-logs", headers=auth_headers)
    assert res.status_code == 403


def test_system_admin_can_read_logs(client, auth_headers, system_admin_headers):
    client.post(
        "/api/v1/salary/access-logs",
        json={"action": "OPEN", "record_count": 1},
        headers=auth_headers,
    )
    res = client.get("/api/v1/salary/access-logs", headers=system_admin_headers)
    assert res.status_code == 200
    assert res.json()["total"] >= 1


def test_log_response_has_no_forbidden_fields(client, auth_headers, system_admin_headers):
    client.post(
        "/api/v1/salary/access-logs",
        json={"action": "OPEN", "record_count": 1},
        headers=auth_headers,
    )
    res = client.get("/api/v1/salary/access-logs", headers=system_admin_headers)
    for row in res.json()["items"]:
        assert set(row.keys()) & FORBIDDEN_COLUMNS == set()


def test_normalize_ip_maps_ipv6_forms_to_ipv4():
    from app.api.v1.salary_audit import normalize_ip

    assert normalize_ip('::ffff:192.0.2.10') == '192.0.2.10'
    assert normalize_ip("::1") == "127.0.0.1"
    assert normalize_ip('192.0.2.10') == '192.0.2.10'
    assert normalize_ip("testclient") == "testclient"
    assert normalize_ip(None) is None


def test_client_ip_maps_loopback_to_server_lan_ip(monkeypatch):
    from types import SimpleNamespace

    import app.api.v1.salary_audit as mod

    monkeypatch.setattr(mod, "local_lan_ip", lambda: '192.0.2.10')
    req = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    assert mod.client_ip(req) == '192.0.2.10'
    req6 = SimpleNamespace(client=SimpleNamespace(host="::1"))
    assert mod.client_ip(req6) == '192.0.2.10'
    other = SimpleNamespace(client=SimpleNamespace(host='192.0.2.10'))
    assert mod.client_ip(other) == '192.0.2.10'
