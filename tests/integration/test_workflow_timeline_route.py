from fastapi.testclient import TestClient

from adwe.api.app import app


def test_workflow_timeline_route_registered(operator_headers):
    client = TestClient(app)

    response = client.get(
        "/v1/workflows/nonexistent-workflow/timeline", headers=operator_headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Workflow not found"
