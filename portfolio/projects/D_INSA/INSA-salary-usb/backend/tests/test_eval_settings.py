def test_upsert_setting_creates(client, auth_headers):
    resp = client.put(
        "/api/v1/eval/settings",
        json={
            "year": 2026,
            "weight_config": {"perf": 40, "comp": 30, "multi": 30},
            "grade_criteria": [
                {"grade": "S", "min": 90, "max": 100, "default_ratio": 10},
                {"grade": "A", "min": 80, "max": 90, "default_ratio": 20},
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["year"] == 2026
    assert data["weight_config"]["perf"] == 40
    assert len(data["grade_criteria"]) == 2
    assert data["grade_criteria"][0]["grade"] == "S"


def test_upsert_setting_updates_existing(client, auth_headers):
    client.put(
        "/api/v1/eval/settings",
        json={
            "year": 2026,
            "weight_config": {"perf": 50, "comp": 30, "multi": 20},
            "grade_criteria": [],
        },
        headers=auth_headers,
    )

    resp = client.put(
        "/api/v1/eval/settings",
        json={
            "year": 2026,
            "weight_config": {"perf": 40, "comp": 30, "multi": 30},
            "grade_criteria": [{"grade": "B", "min": 70, "max": 80, "default_ratio": 40}],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["weight_config"]["perf"] == 40

    fetched = client.get("/api/v1/eval/settings?year=2026", headers=auth_headers).json()
    assert fetched["weight_config"]["perf"] == 40
    assert len(fetched["grade_criteria"]) == 1


def test_get_setting_missing_returns_null(client, auth_headers):
    resp = client.get("/api/v1/eval/settings?year=2099", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() is None
