"""Content-bound operator decisions, not execution/publication authorization."""

import hashlib

from adwe.models.patch_status import PatchStatus


class PatchDecisionConflict(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def diff_digest(diff: str) -> str:
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


def validate_decision(current: str, target: PatchStatus) -> bool:
    """Return whether a legal operator decision changes state; reject other transitions."""
    if target not in {PatchStatus.APPROVED, PatchStatus.REJECTED}:
        raise PatchDecisionConflict(
            "invalid_patch_decision",
            "Only approval or rejection is an operator decision",
        )
    if current == target:
        return False
    allowed = {
        PatchStatus.PROPOSED: {PatchStatus.APPROVED, PatchStatus.REJECTED},
        PatchStatus.APPROVED: {PatchStatus.REJECTED},
    }
    if target not in allowed.get(current, set()):
        raise PatchDecisionConflict(
            "invalid_patch_transition",
            f"Cannot change patch from {current} to {target}",
        )
    return True
