def test_create_eval_round(client, auth_headers):
    resp = client.post(
        "/api/v1/eval/rounds",
        json={"year": 2026, "name": "2026 상반기 평가"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["year"] == 2026
    assert data["name"] == "2026 상반기 평가"
    assert data["status"] == "PLANNED"


def test_list_rounds_by_year(client, auth_headers):
    client.post(
        "/api/v1/eval/rounds",
        json={"year": 2025, "name": "2025"},
        headers=auth_headers,
    )
    client.post(
        "/api/v1/eval/rounds",
        json={"year": 2026, "name": "2026"},
        headers=auth_headers,
    )

    resp = client.get("/api/v1/eval/rounds?year=2026", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["year"] == 2026


def test_update_eval_round(client, auth_headers):
    create = client.post(
        "/api/v1/eval/rounds",
        json={"year": 2026, "name": "초안"},
        headers=auth_headers,
    )
    round_id = create.json()["id"]

    resp = client.put(
        f"/api/v1/eval/rounds/{round_id}",
        json={"name": "수정본", "status": "IN_PROGRESS"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "수정본"
    assert resp.json()["status"] == "IN_PROGRESS"


def test_close_eval_round(client, auth_headers):
    create = client.post(
        "/api/v1/eval/rounds",
        json={"year": 2026, "name": "마감대상"},
        headers=auth_headers,
    )
    round_id = create.json()["id"]

    resp = client.put(f"/api/v1/eval/rounds/{round_id}/close", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "CLOSED"

    # Re-close should fail
    resp2 = client.put(f"/api/v1/eval/rounds/{round_id}/close", headers=auth_headers)
    assert resp2.status_code == 400


def test_update_nonexistent_round_returns_404(client, auth_headers):
    resp = client.put(
        "/api/v1/eval/rounds/99999",
        json={"name": "ghost"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_schedules_bulk_upsert(client, auth_headers):
    create = client.post(
        "/api/v1/eval/rounds",
        json={"year": 2026, "name": "일정테스트"},
        headers=auth_headers,
    )
    round_id = create.json()["id"]

    resp = client.post(
        "/api/v1/eval/schedules",
        json={
            "round_id": round_id,
            "schedules": [
                {"stage": "TARGET", "start_date": "2026-01-01", "end_date": "2026-01-31"},
                {"stage": "MID", "start_date": "2026-06-01", "end_date": "2026-06-30"},
                {"stage": "FINAL", "start_date": "2026-12-01", "end_date": "2026-12-31"},
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert len(resp.json()) == 3

    # Bulk upsert replaces prior
    resp2 = client.post(
        "/api/v1/eval/schedules",
        json={
            "round_id": round_id,
            "schedules": [{"stage": "COMPREHENSIVE", "start_date": "2026-12-15", "end_date": "2026-12-31"}],
        },
        headers=auth_headers,
    )
    assert resp2.status_code == 201

    listed = client.get(f"/api/v1/eval/schedules?round_id={round_id}", headers=auth_headers)
    stages = [s["stage"] for s in listed.json()]
    assert stages == ["COMPREHENSIVE"]


def test_create_round_requires_admin(client):
    # No auth headers → 403 (FastAPI HTTPBearer returns 403 by default when missing)
    resp = client.post("/api/v1/eval/rounds", json={"year": 2026, "name": "X"})
    assert resp.status_code in (401, 403)
