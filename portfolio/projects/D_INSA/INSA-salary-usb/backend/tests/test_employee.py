import pytest


def test_create_employee(client, auth_headers):
    resp = client.post("/api/v1/employees", json={
        "emp_no": "20210001",
        "name_ko": "김영희",
        "hire_date": "2021-03-02",
        "emp_status": "재직",
        "emp_type": "정규직",
    }, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["emp_no"] == "20210001"
    assert data["name_ko"] == "김영희"


def test_create_duplicate_employee(client, auth_headers):
    client.post("/api/v1/employees", json={
        "emp_no": "20210099",
        "name_ko": "이철수",
        "hire_date": "2021-03-02",
    }, headers=auth_headers)

    resp = client.post("/api/v1/employees", json={
        "emp_no": "20210099",
        "name_ko": "박지민",
        "hire_date": "2021-03-02",
    }, headers=auth_headers)
    assert resp.status_code == 409


def test_list_employees(client, auth_headers):
    resp = client.get("/api/v1/employees", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data


def test_get_employee(client, auth_headers):
    create_resp = client.post("/api/v1/employees", json={
        "emp_no": "20210050",
        "name_ko": "정수진",
        "hire_date": "2020-01-15",
    }, headers=auth_headers)
    emp_id = create_resp.json()["id"]

    resp = client.get(f"/api/v1/employees/{emp_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name_ko"] == "정수진"


def test_get_employee_not_found(client, auth_headers):
    resp = client.get("/api/v1/employees/99999", headers=auth_headers)
    assert resp.status_code == 404


def test_update_employee(client, auth_headers):
    create_resp = client.post("/api/v1/employees", json={
        "emp_no": "20210060",
        "name_ko": "최동현",
        "hire_date": "2019-06-01",
    }, headers=auth_headers)
    emp_id = create_resp.json()["id"]

    resp = client.patch(f"/api/v1/employees/{emp_id}", json={
        "name_ko": "최동현(수정)",
        "workplace": "본사",
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name_ko"] == "최동현(수정)"
    assert resp.json()["workplace"] == "본사"
