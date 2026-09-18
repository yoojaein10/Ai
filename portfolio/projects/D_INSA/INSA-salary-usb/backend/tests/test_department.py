def test_create_department(client, auth_headers):
    resp = client.post("/api/v1/departments", json={
        "code": "HR",
        "name": "인사팀",
    }, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["name"] == "인사팀"


def test_list_departments(client, auth_headers):
    resp = client.get("/api/v1/departments", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_department_tree(client, auth_headers):
    client.post("/api/v1/departments", json={"code": "ROOT", "name": "본사"}, headers=auth_headers)
    resp = client.get("/api/v1/departments/tree", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_update_department(client, auth_headers):
    create_resp = client.post("/api/v1/departments", json={
        "code": "DEV",
        "name": "개발팀",
    }, headers=auth_headers)
    dept_id = create_resp.json()["id"]

    resp = client.patch(f"/api/v1/departments/{dept_id}", json={
        "name": "개발1팀",
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "개발1팀"


def test_deactivate_department(client, auth_headers):
    create_resp = client.post("/api/v1/departments", json={
        "code": "OLD",
        "name": "폐지부서",
    }, headers=auth_headers)
    dept_id = create_resp.json()["id"]

    resp = client.patch(f"/api/v1/departments/{dept_id}", json={
        "is_active": False,
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
