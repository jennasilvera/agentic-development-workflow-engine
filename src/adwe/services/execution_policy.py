"""Temporary release containment, not a sandbox or per-repository authorization.

These operations cannot be enabled by configuration. Replace each denial only after
its prerequisites in IMPLEMENTATION_ROADMAP.md have been implemented and verified.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum

from adwe.services.errors import ADWEError

logger = logging.getLogger(__name__)


class Operation(StrEnum):
    LIVE_WORKFLOW = "live_workflow"
    REPOSITORY_ACQUISITION = "repository_acquisition"
    PATCH_EXECUTION = "patch_execution"
    HOST_TEST_EXECUTION = "host_test_execution"
    PUBLICATION = "publication"


@dataclass(frozen=True)
class ContainmentDecision:
    operation: Operation
    code: str = "operation_unavailable"
    policy_version: str = "containment-v1"
    reason: str = (
        "Live repository operations are disabled until authorization, isolated "
        "execution and durable side-effect controls are implemented."
    )


class OperationUnavailable(ADWEError):
    code = "operation_unavailable"

    def __init__(self, decision: ContainmentDecision) -> None:
        self.decision = decision
        super().__init__(decision.reason)


def require_operation(operation: Operation) -> None:
    """Deny before any operational side effect; never log caller-controlled input."""
    decision = ContainmentDecision(operation=operation)
    logger.warning(
        "operation_denied operation=%s policy_version=%s code=%s",
        decision.operation.value,
        decision.policy_version,
        decision.code,
    )
    raise OperationUnavailable(decision)
