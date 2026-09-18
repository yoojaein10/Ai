"""Tests for employee sub-tab APIs (1:1 and 1:N)."""

import pytest


@pytest.fixture
def employee_id(client, auth_headers):
    resp = client.post("/api/v1/employees", json={
        "emp_no": "20210100",
        "name_ko": "탭테스트",
        "hire_date": "2021-01-01",
    }, headers=auth_headers)
    return resp.json()["id"]


# ── 1:1 tabs ──

class TestPersonal:
    def test_get_empty(self, client, auth_headers, employee_id):
        resp = client.get(f"/api/v1/employees/{employee_id}/personal", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() is None

    def test_upsert_create(self, client, auth_headers, employee_id):
        resp = client.put(f"/api/v1/employees/{employee_id}/personal", json={
            "address": "서울시 강남구",
            "phone": '010-0000-0000',
            "email": 'contact@example.com',
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["address"] == "서울시 강남구"

    def test_upsert_update(self, client, auth_headers, employee_id):
        client.put(f"/api/v1/employees/{employee_id}/personal", json={
            "address": "서울시 강남구",
        }, headers=auth_headers)
        resp = client.put(f"/api/v1/employees/{employee_id}/personal", json={
            "address": "서울시 서초구",
        }, headers=auth_headers)
        assert resp.json()["address"] == "서울시 서초구"


class TestMilitary:
    def test_upsert(self, client, auth_headers, employee_id):
        resp = client.put(f"/api/v1/employees/{employee_id}/military", json={
            "branch": "육군",
            "rank": "병장",
            "service_start": "2015-03-01",
            "service_end": "2016-12-01",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["branch"] == "육군"


class TestVeteran:
    def test_upsert(self, client, auth_headers, employee_id):
        resp = client.put(f"/api/v1/employees/{employee_id}/veteran", json={
            "veteran_type": "국가유공자",
            "veteran_grade": "6급",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["veteran_type"] == "국가유공자"


class TestDisability:
    def test_upsert(self, client, auth_headers, employee_id):
        resp = client.put(f"/api/v1/employees/{employee_id}/disability", json={
            "disability_type": "지체장애",
            "disability_grade": "3급",
            "registered_at": "2020-05-15",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["disability_type"] == "지체장애"


# ── 1:N tabs ──

class TestFamily:
    def test_create_and_list(self, client, auth_headers, employee_id):
        resp = client.post(f"/api/v1/employees/{employee_id}/families", json={
            "relation": "배우자",
            "name": "김철수",
            "birth_date": "1990-01-15",
        }, headers=auth_headers)
        assert resp.status_code == 201

        resp = client.get(f"/api/v1/employees/{employee_id}/families", headers=auth_headers)
        assert len(resp.json()) == 1

    def test_delete(self, client, auth_headers, employee_id):
        create_resp = client.post(f"/api/v1/employees/{employee_id}/families", json={
            "relation": "자녀",
            "name": "김영수",
        }, headers=auth_headers)
        record_id = create_resp.json()["id"]

        resp = client.delete(
            f"/api/v1/employees/{employee_id}/families/{record_id}", headers=auth_headers
        )
        assert resp.status_code == 200


class TestEducation:
    def test_create(self, client, auth_headers, employee_id):
        resp = client.post(f"/api/v1/employees/{employee_id}/educations", json={
            "school_name": "서울대학교",
            "degree": "학사",
            "major": "컴퓨터공학",
            "graduation_year": 2020,
        }, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["school_name"] == "서울대학교"


class TestCareer:
    def test_create(self, client, auth_headers, employee_id):
        resp = client.post(f"/api/v1/employees/{employee_id}/careers", json={
            "company_name": "삼성전자",
            "position": "대리",
            "start_date": "2018-03-01",
            "end_date": "2020-12-31",
        }, headers=auth_headers)
        assert resp.status_code == 201


class TestCertificate:
    def test_create(self, client, auth_headers, employee_id):
        resp = client.post(f"/api/v1/employees/{employee_id}/certificates", json={
            "cert_name": "정보처리기사",
            "issuer": "한국산업인력공단",
            "acquired_at": "2019-11-22",
        }, headers=auth_headers)
        assert resp.status_code == 201


class TestLanguage:
    def test_create(self, client, auth_headers, employee_id):
        resp = client.post(f"/api/v1/employees/{employee_id}/languages", json={
            "language": "영어",
            "test_name": "TOEIC",
            "score": "920",
            "acquired_at": "2023-06-15",
        }, headers=auth_headers)
        assert resp.status_code == 201


class TestAward:
    def test_create(self, client, auth_headers, employee_id):
        resp = client.post(f"/api/v1/employees/{employee_id}/awards", json={
            "award_name": "우수사원상",
            "award_date": "2023-12-20",
            "description": "연간 우수 업무 성과",
        }, headers=auth_headers)
        assert resp.status_code == 201


class TestDiscipline:
    def test_create(self, client, auth_headers, employee_id):
        resp = client.post(f"/api/v1/employees/{employee_id}/disciplines", json={
            "discipline_type": "경고",
            "discipline_date": "2024-02-01",
            "reason": "지각 3회",
        }, headers=auth_headers)
        assert resp.status_code == 201


class TestEvaluation:
    def test_list_empty(self, client, auth_headers, employee_id):
        resp = client.get(f"/api/v1/employees/{employee_id}/evaluations", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []


class TestNotFound:
    def test_nonexistent_employee(self, client, auth_headers):
        resp = client.get("/api/v1/employees/99999/personal", headers=auth_headers)
        assert resp.status_code == 404
