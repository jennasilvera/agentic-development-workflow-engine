from pathlib import Path

from git import Repo

from adwe.services.errors import RepositoryCloneError
from adwe.services.execution_policy import Operation, require_operation


def build_clone_url(repository_url: str) -> str:
    """Preserve the URL without attaching platform credentials."""
    return repository_url


def clone_repository(repository_url: str, destination: Path) -> Path:
    require_operation(Operation.REPOSITORY_ACQUISITION)
    try:
        clone_url = build_clone_url(repository_url)
        Repo.clone_from(clone_url, destination)
        return destination
    except Exception as exc:
        raise RepositoryCloneError(str(exc)) from exc
