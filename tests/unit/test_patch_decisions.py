import hashlib

import pytest

from adwe.domain.patch_decision import (
    PatchDecisionConflict,
    diff_digest,
    validate_decision,
)
from adwe.models.patch_status import PatchStatus


@pytest.mark.parametrize("current", list(PatchStatus))
@pytest.mark.parametrize("target", [PatchStatus.APPROVED, PatchStatus.REJECTED])
def test_operator_transition_matrix(current, target):
    legal = {
        (PatchStatus.PROPOSED, PatchStatus.APPROVED),
        (PatchStatus.PROPOSED, PatchStatus.REJECTED),
        (PatchStatus.APPROVED, PatchStatus.REJECTED),
    }
    if current == target:
        assert validate_decision(current, target) is False
    elif (current, target) in legal:
        assert validate_decision(current, target) is True
    else:
        with pytest.raises(PatchDecisionConflict):
            validate_decision(current, target)


def test_operator_cannot_assert_execution_success():
    with pytest.raises(PatchDecisionConflict):
        validate_decision(PatchStatus.APPROVED, PatchStatus.APPLIED)


def test_digest_preserves_exact_utf8_content():
    assert diff_digest("+café\n") == hashlib.sha256("+café\n".encode()).hexdigest()
    assert diff_digest("+café\n") != diff_digest("+café\r\n")
