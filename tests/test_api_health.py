from fastapi.testclient import TestClient

from api.main import app


def test_health_reports_persistence_backend():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["persistence"] in {"memory", "supabase"}