"""Admission dependency for legacy mutating endpoints."""

from fastapi import HTTPException

from adwe.services.execution_policy import (
    Operation,
    OperationUnavailable,
    require_operation,
)


def require_live_operations() -> None:
    try:
        require_operation(Operation.LIVE_WORKFLOW)
    except OperationUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": exc.code,
                "message": str(exc),
                "policy_version": exc.decision.policy_version,
            },
        ) from exc
