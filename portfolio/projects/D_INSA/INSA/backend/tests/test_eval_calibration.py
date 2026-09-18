def _create_employee(client, auth_headers, emp_no: str, name: str) -> int:
    resp = client.post(
        "/api/v1/employees",
        json={"emp_no": emp_no, "name_ko": name, "hire_date": "2021-01-01"},
        headers=auth_headers,
    )
    return resp.json()["id"]


def test_create_calibration_group(client, auth_headers):
    resp = client.post(
        "/api/v1/eval/calibration-groups",
        json={"year": 2026, "name": "과장급"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["year"] == 2026
    assert data["name"] == "과장급"
    assert data["member_count"] == 0


def test_add_and_remove_members(client, auth_headers):
    create = client.post(
        "/api/v1/eval/calibration-groups",
        json={"year": 2026, "name": "부장급"},
        headers=auth_headers,
    )
    group_id = create.json()["id"]

    e1 = _create_employee(client, auth_headers, "40000001", "M1")
    e2 = _create_employee(client, auth_headers, "40000002", "M2")

    resp = client.post(
        f"/api/v1/eval/calibration-groups/{group_id}/members",
        json={"emp_ids": [e1, e2]},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["added"] == 2

    detail = client.get(f"/api/v1/eval/calibration-groups/{group_id}", headers=auth_headers).json()
    assert detail["member_count"] == 2
    assert {m["emp_id"] for m in detail["members"]} == {e1, e2}

    # Re-add duplicates → added=0
    resp2 = client.post(
        f"/api/v1/eval/calibration-groups/{group_id}/members",
        json={"emp_ids": [e1]},
        headers=auth_headers,
    )
    assert resp2.json()["added"] == 0

    # Remove
    resp3 = client.delete(
        f"/api/v1/eval/calibration-groups/{group_id}/members/{e1}",
        headers=auth_headers,
    )
    assert resp3.status_code == 204

    detail2 = client.get(f"/api/v1/eval/calibration-groups/{group_id}", headers=auth_headers).json()
    assert detail2["member_count"] == 1


def test_update_group_name(client, auth_headers):
    create = client.post(
        "/api/v1/eval/calibration-groups",
        json={"year": 2026, "name": "A"},
        headers=auth_headers,
    )
    group_id = create.json()["id"]

    resp = client.put(
        f"/api/v1/eval/calibration-groups/{group_id}",
        json={"name": "B"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "B"


def test_list_groups_by_year(client, auth_headers):
    client.post(
        "/api/v1/eval/calibration-groups",
        json={"year": 2025, "name": "G25"},
        headers=auth_headers,
    )
    client.post(
        "/api/v1/eval/calibration-groups",
        json={"year": 2026, "name": "G26"},
        headers=auth_headers,
    )

    resp = client.get("/api/v1/eval/calibration-groups?year=2026", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "G26"


def test_group_not_found(client, auth_headers):
    resp = client.get("/api/v1/eval/calibration-groups/99999", headers=auth_headers)
    assert resp.status_code == 404


def test_remove_unknown_member_returns_404(client, auth_headers):
    create = client.post(
        "/api/v1/eval/calibration-groups",
        json={"year": 2026, "name": "X"},
        headers=auth_headers,
    )
    group_id = create.json()["id"]

    resp = client.delete(
        f"/api/v1/eval/calibration-groups/{group_id}/members/99999",
        headers=auth_headers,
    )
    assert resp.status_code == 404
