import pytest

from adwe.services.execution_policy import OperationUnavailable
from adwe.services.git_push import push_branch


def test_push_branch_is_unavailable(tmp_path):
    with pytest.raises(OperationUnavailable):
        push_branch(tmp_path, "adwe/test")
