import subprocess
from pathlib import Path

from adwe.core.config import settings
from adwe.services.execution_policy import Operation, require_operation


class GitPushError(Exception):
    pass


def push_branch(repo_path: Path, branch_name: str) -> None:
    require_operation(Operation.PUBLICATION)
    if not settings.github_token:
        raise GitPushError("GITHUB_TOKEN is required to push branches")

    result = subprocess.run(
        ["git", "push", "-u", "origin", branch_name],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise GitPushError(result.stderr)
