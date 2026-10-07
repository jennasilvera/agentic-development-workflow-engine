"""Host execution is unavailable until an isolated execution backend exists."""

from pathlib import Path

from adwe.services.execution_policy import Operation, require_operation


def run_tests(repo_path: Path, command: list[str]) -> dict:
    # Even an allowlisted pytest command executes arbitrary repository code.
    # Keep the public signature for callers, but never spawn a host process.
    require_operation(Operation.HOST_TEST_EXECUTION)
    raise AssertionError("Host test execution has no authorized backend")
