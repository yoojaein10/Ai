def _create_round(client, auth_headers) -> int:
    resp = client.post(
        "/api/v1/eval/rounds",
        json={"year": 2026, "name": "2026"},
        headers=auth_headers,
    )
    return resp.json()["id"]


def _create_employee(client, auth_headers, emp_no: str, name: str) -> int:
    resp = client.post(
        "/api/v1/employees",
        json={"emp_no": emp_no, "name_ko": name, "hire_date": "2021-01-01"},
        headers=auth_headers,
    )
    return resp.json()["id"]


def _create_target(client, auth_headers, emp_id: int, round_id: int) -> int:
    resp = client.post(
        "/api/v1/eval/perf/targets",
        json={"emp_id": emp_id, "round_id": round_id, "target_value": "T", "weight_percent": "30"},
        headers=auth_headers,
    )
    return resp.json()["id"]


def test_midterm_upsert_creates(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    emp_id = _create_employee(client, auth_headers, "40000001", "M1")
    target_id = _create_target(client, auth_headers, emp_id, round_id)

    resp = client.post(
        "/api/v1/eval/perf/midterm",
        json={"target_id": target_id, "progress_rate": "55.50", "description": "진행중", "expected_rate": "80.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["target_id"] == target_id
    assert float(data["progress_rate"]) == 55.5


def test_midterm_upsert_updates_existing(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    emp_id = _create_employee(client, auth_headers, "40000002", "M2")
    target_id = _create_target(client, auth_headers, emp_id, round_id)

    client.post(
        "/api/v1/eval/perf/midterm",
        json={"target_id": target_id, "progress_rate": "30.00"},
        headers=auth_headers,
    )
    resp = client.post(
        "/api/v1/eval/perf/midterm",
        json={"target_id": target_id, "progress_rate": "75.00", "description": "업데이트"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert float(resp.json()["progress_rate"]) == 75.0

    # Should still be a single record
    got = client.get(f"/api/v1/eval/perf/midterm?target_id={target_id}", headers=auth_headers)
    assert got.status_code == 200
    assert float(got.json()["progress_rate"]) == 75.0


def test_midterm_get_returns_null_when_missing(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    emp_id = _create_employee(client, auth_headers, "40000003", "M3")
    target_id = _create_target(client, auth_headers, emp_id, round_id)

    resp = client.get(f"/api/v1/eval/perf/midterm?target_id={target_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() is None


def test_final_upsert(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    emp_id = _create_employee(client, auth_headers, "40000004", "F1")
    target_id = _create_target(client, auth_headers, emp_id, round_id)

    resp = client.post(
        "/api/v1/eval/perf/final",
        json={"target_id": target_id, "achievement_rate": "92.00", "self_score": "85.50"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert float(resp.json()["achievement_rate"]) == 92.0


def test_midterm_target_not_found(client, auth_headers):
    resp = client.post(
        "/api/v1/eval/perf/midterm",
        json={"target_id": 99999, "progress_rate": "10.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_final_target_not_found(client, auth_headers):
    resp = client.post(
        "/api/v1/eval/perf/final",
        json={"target_id": 99999, "achievement_rate": "10.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
