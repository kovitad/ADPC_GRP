from fastapi.testclient import TestClient

from api.main import app


def test_healthz_is_detail_free() -> None:
    response = TestClient(app).get("/api/v1/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
