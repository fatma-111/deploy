"""HTTP contract."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_investigate_returns_report(langchain_bug):
    response = client.post("/api/investigate", json=langchain_bug)
    assert response.status_code == 200
    body = response.json()
    assert body["error_type"] == "ModuleNotFoundError"
    assert body["final_response"]
    assert "investigation_id" in body


def test_investigate_rejects_empty_body():
    assert client.post("/api/investigate", json={"error_message": ""}).status_code == 422


def test_samples_endpoint():
    body = client.get("/api/samples").json()
    assert len(body["samples"]) >= 4


def test_metrics_endpoint(langchain_bug):
    client.post("/api/investigate", json=langchain_bug)
    body = client.get("/api/dashboard/metrics").json()
    assert body["total"] >= 1
    assert body["feed"]
    assert "confidence_threshold" in body["config"]
