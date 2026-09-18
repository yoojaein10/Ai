def _create_round(client, auth_headers) -> int:
    resp = client.post(
        "/api/v1/eval/rounds",
        json={"year": 2026, "name": "2026"},
        headers=auth_headers,
    )
    return resp.json()["id"]


def test_create_perf_kpi(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    resp = client.post(
        "/api/v1/eval/perf/kpis",
        json={
            "round_id": round_id,
            "code": "KPI-001",
            "name": "매출 목표",
            "measure_type": "정량",
            "weight": "30.00",
            "perspective": "재무",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["code"] == "KPI-001"
    assert data["perspective"] == "재무"


def test_list_perf_kpis_by_round(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    for code in ("K1", "K2", "K3"):
        client.post(
            "/api/v1/eval/perf/kpis",
            json={"round_id": round_id, "code": code, "name": code},
            headers=auth_headers,
        )

    resp = client.get(f"/api/v1/eval/perf/kpis?round_id={round_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_update_perf_kpi(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    created = client.post(
        "/api/v1/eval/perf/kpis",
        json={"round_id": round_id, "code": "K1", "name": "초안"},
        headers=auth_headers,
    )
    kpi_id = created.json()["id"]

    resp = client.put(
        f"/api/v1/eval/perf/kpis/{kpi_id}",
        json={"name": "수정본"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "수정본"


def test_delete_perf_kpi(client, auth_headers):
    round_id = _create_round(client, auth_headers)
    created = client.post(
        "/api/v1/eval/perf/kpis",
        json={"round_id": round_id, "code": "K1", "name": "삭제대상"},
        headers=auth_headers,
    )
    kpi_id = created.json()["id"]

    resp = client.delete(f"/api/v1/eval/perf/kpis/{kpi_id}", headers=auth_headers)
    assert resp.status_code == 204

    resp2 = client.get(f"/api/v1/eval/perf/kpis?round_id={round_id}", headers=auth_headers)
    assert len(resp2.json()) == 0


def test_create_kpi_requires_admin(client):
    resp = client.post(
        "/api/v1/eval/perf/kpis",
        json={"round_id": 1, "code": "K", "name": "N"},
    )
    assert resp.status_code in (401, 403)


def test_create_kpi_round_not_found(client, auth_headers):
    resp = client.post(
        "/api/v1/eval/perf/kpis",
        json={"round_id": 99999, "code": "K1", "name": "N"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
