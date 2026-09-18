from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "A10-Bridge"
    assert body["version"] == "0.1.0"
    settings = get_settings()
    assert body["database_configured"] is settings.is_database_configured
    assert body["amaranth_configured"] is settings.is_amaranth_configured
