def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_login_success(client, admin_user):
    resp = client.post("/api/v1/auth/login", json={
        "login_id": "admin",
        "password": "password123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["login_id"] == "admin"
    assert "HR_ADMIN" in data["roles"]


def test_login_wrong_password(client, admin_user):
    resp = client.post("/api/v1/auth/login", json={
        "login_id": "admin",
        "password": "wrong",
    })
    assert resp.status_code == 401


def test_login_nonexistent_user(client):
    resp = client.post("/api/v1/auth/login", json={
        "login_id": "nobody",
        "password": "password123",
    })
    assert resp.status_code == 401


def test_protected_endpoint_no_token(client):
    resp = client.get("/api/v1/employees")
    assert resp.status_code == 403


def test_protected_endpoint_with_token(client, auth_headers):
    resp = client.get("/api/v1/employees", headers=auth_headers)
    assert resp.status_code == 200


def test_logout(client):
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
