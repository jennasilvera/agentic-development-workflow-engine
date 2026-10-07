import hashlib
import re
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from adwe.api import repositories
from adwe.api.app import app
from adwe.core.config import Settings, settings

# Every registered application operation must inherit the auth dependency,
# including future routes and /metrics. OpenAPI/docs contain schema metadata only.
OPERATIONS = [
    (method.upper(), re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000001", path))
    for path, methods in app.openapi()["paths"].items()
    for method in methods
    if method in {"get", "post", "patch", "put", "delete"}
]


@pytest.mark.parametrize("method,path", OPERATIONS)
@pytest.mark.parametrize(
    "authorization", [None, "Bearer incorrect", "Basic credentials"]
)
def test_all_application_operations_require_auth(
    method, path, authorization, operator_headers
):
    headers = {"Authorization": authorization} if authorization else {}
    with TestClient(app) as client:
        response = client.request(method, path, headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"


def test_missing_configuration_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "api_token_sha256", None)
    with TestClient(app) as client:
        response = client.get(
            "/v1/repositories", headers={"Authorization": "Bearer anything"}
        )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "authentication_unconfigured"


def test_authorized_metrics_and_public_schema(operator_headers):
    with TestClient(app) as client:
        assert client.get("/metrics", headers=operator_headers).status_code == 200
        schema = client.get("/openapi.json").json()
        assert (
            schema["components"]["securitySchemes"]["OperatorBearer"]["scheme"]
            == "bearer"
        )
        for path in schema["paths"].values():
            for operation in path.values():
                assert operation["security"] == [{"OperatorBearer": []}]


def test_token_rotation_revokes_previous_token(monkeypatch, operator_headers):
    new_token = "synthetic-new-token-for-rotation-test"
    monkeypatch.setattr(
        settings,
        "api_token_sha256",
        SecretStr(hashlib.sha256(new_token.encode()).hexdigest()),
    )
    with TestClient(app) as client:
        assert client.get("/metrics", headers=operator_headers).status_code == 401
        assert (
            client.get(
                "/metrics", headers={"Authorization": f"Bearer {new_token}"}
            ).status_code
            == 200
        )


def test_unauthorized_registration_does_not_open_database(
    monkeypatch, operator_headers
):
    forbidden = Mock(side_effect=AssertionError("Unauthenticated database access"))
    monkeypatch.setattr(repositories, "AsyncSessionLocal", forbidden)
    with TestClient(app) as client:
        response = client.post(
            "/v1/repositories", json={"repository_url": "https://github.com/a/b"}
        )
    assert response.status_code == 401
    forbidden.assert_not_called()


def test_bad_token_not_returned_or_logged(operator_headers, caplog):
    token = "synthetic-token-must-not-appear-in-output"
    with TestClient(app) as client:
        response = client.get(
            "/v1/repositories", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 401
    assert token not in response.text
    assert token not in caplog.text


@pytest.mark.parametrize("digest", ["", "short", "Z" * 64, "A" * 64])
def test_invalid_digest_configuration_is_rejected(digest):
    with pytest.raises(ValidationError):
        Settings(api_token_sha256=digest)


@pytest.mark.parametrize("actor", ["", "../operator", "a" * 65, "operator\n"])
def test_invalid_operator_id_is_rejected(actor):
    with pytest.raises(ValidationError):
        Settings(api_operator_id=actor)
