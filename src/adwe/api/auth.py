"""Single-operator authentication; no implicit anonymous or development bypass."""

import hashlib
import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from adwe.core.config import settings

bearer = HTTPBearer(auto_error=False, scheme_name="OperatorBearer")


@dataclass(frozen=True)
class Operator:
    actor_id: str


def require_operator(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Operator:
    digest = settings.api_token_sha256
    if digest is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "authentication_unconfigured",
                "message": "Operator authentication is not configured",
            },
        )
    if credentials is None or len(credentials.credentials) > 1024:
        raise _unauthorized()
    candidate = hashlib.sha256(credentials.credentials.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(candidate, digest.get_secret_value()):
        raise _unauthorized()
    return Operator(actor_id=settings.api_operator_id)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={
            "code": "unauthorized",
            "message": "Valid operator bearer token required",
        },
        headers={"WWW-Authenticate": "Bearer"},
    )
