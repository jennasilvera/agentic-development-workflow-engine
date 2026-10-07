import hashlib

import pytest
from pydantic import SecretStr

from adwe.core.config import settings


@pytest.fixture
def operator_headers(monkeypatch):
    # Synthetic test credential, never an operational token.
    token = "test-only-operator-token-that-is-not-a-production-secret"
    monkeypatch.setattr(
        settings,
        "api_token_sha256",
        SecretStr(hashlib.sha256(token.encode()).hexdigest()),
    )
    monkeypatch.setattr(settings, "api_operator_id", "test-operator")
    return {"Authorization": f"Bearer {token}"}
