import subprocess
import sys
from unittest.mock import Mock

import pytest

from adwe.services.execution_policy import OperationUnavailable
from adwe.services.test_runner import run_tests


@pytest.mark.parametrize(
    "command",
    [
        [sys.executable, "-c", "print('ok')"],
        ["python", "-m", "pytest"],
        ["sh", "-c", "env"],
        [],
    ],
)
def test_host_commands_never_execute(tmp_path, monkeypatch, command):
    forbidden = Mock(side_effect=AssertionError("Host process spawned"))
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    with pytest.raises(OperationUnavailable):
        run_tests(tmp_path, command)
    forbidden.assert_not_called()
