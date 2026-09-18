def test_create_appointment(client, auth_headers):
    emp_resp = client.post("/api/v1/employees", json={
        "emp_no": "20210070",
        "name_ko": "발령테스트",
        "hire_date": "2021-01-01",
        "job_rank": "사원",
    }, headers=auth_headers)
    emp_id = emp_resp.json()["id"]

    resp = client.post("/api/v1/appointments", json={
        "employee_id": emp_id,
        "appt_type": "승진",
        "appt_date": "2024-01-01",
        "new_rank": "대리",
    }, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["appt_type"] == "승진"
    assert data["old_rank"] == "사원"
    assert data["new_rank"] == "대리"

    emp_resp = client.get(f"/api/v1/employees/{emp_id}", headers=auth_headers)
    assert emp_resp.json()["job_rank"] == "대리"


def test_appointment_employee_not_found(client, auth_headers):
    resp = client.post("/api/v1/appointments", json={
        "employee_id": 99999,
        "appt_type": "전보",
        "appt_date": "2024-01-01",
    }, headers=auth_headers)
    assert resp.status_code == 404


def test_list_appointments(client, auth_headers):
    emp_resp = client.post("/api/v1/employees", json={
        "emp_no": "20210071",
        "name_ko": "발령목록테스트",
        "hire_date": "2021-01-01",
    }, headers=auth_headers)
    emp_id = emp_resp.json()["id"]

    client.post("/api/v1/appointments", json={
        "employee_id": emp_id,
        "appt_type": "신규",
        "appt_date": "2021-01-01",
    }, headers=auth_headers)

    resp = client.get(f"/api/v1/appointments/employee/{emp_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_retirement_appointment(client, auth_headers):
    emp_resp = client.post("/api/v1/employees", json={
        "emp_no": "20210072",
        "name_ko": "퇴직테스트",
        "hire_date": "2021-01-01",
        "emp_status": "재직",
    }, headers=auth_headers)
    emp_id = emp_resp.json()["id"]

    client.post("/api/v1/appointments", json={
        "employee_id": emp_id,
        "appt_type": "퇴직",
        "appt_date": "2024-12-31",
    }, headers=auth_headers)

    emp_resp = client.get(f"/api/v1/employees/{emp_id}", headers=auth_headers)
    assert emp_resp.json()["emp_status"] == "퇴직"
    assert emp_resp.json()["resign_date"] == "2024-12-31"
