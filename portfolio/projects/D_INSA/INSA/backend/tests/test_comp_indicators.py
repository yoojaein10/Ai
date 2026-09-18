def test_create_indicator_admin(client, auth_headers):
    resp = client.post(
        "/api/v1/eval/comp/indicators",
        json={
            "year": 2026,
            "code": "C001",
            "name": "고객지향",
            "description": "고객 가치 우선",
            "weight": "20.00",
            "behaviors": [
                {"level": 1, "description": "기본"},
                {"level": 5, "description": "탁월"},
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["code"] == "C001"
    assert len(data["behaviors"]) == 2


def test_create_indicator_score_validation(client, auth_headers):
    resp = client.post(
        "/api/v1/eval/comp/indicators",
        json={
            "year": 2026,
            "code": "C002",
            "name": "도전",
            "behaviors": [{"level": 6, "description": "잘못된 레벨"}],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_list_indicators_by_year(client, auth_headers):
    client.post(
        "/api/v1/eval/comp/indicators",
        json={"year": 2025, "code": "C-OLD", "name": "구버전", "behaviors": []},
        headers=auth_headers,
    )
    client.post(
        "/api/v1/eval/comp/indicators",
        json={"year": 2026, "code": "C-NEW", "name": "신버전", "behaviors": []},
        headers=auth_headers,
    )
    resp = client.get("/api/v1/eval/comp/indicators?year=2026", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert all(r["year"] == 2026 for r in rows)
    assert any(r["code"] == "C-NEW" for r in rows)
