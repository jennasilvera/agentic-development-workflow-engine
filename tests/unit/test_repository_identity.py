import pytest
from pydantic import ValidationError

from adwe.domain.repository import canonical_repository_url
from adwe.models.repository_schema import RepositoryCreate, RepositoryUpdate


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/Owner/Repo",
        "https://github.com/owner/repo.git",
        "https://github.com/OWNER/REPO.GIT/",
    ],
)
def test_equivalent_repository_urls_have_one_identity(url):
    assert canonical_repository_url(url) == "https://github.com/owner/repo"
    assert (
        RepositoryCreate(repository_url=url).repository_url
        == "https://github.com/owner/repo"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "https://github.com.evil/a/b",
        "https://user:secret@github.com/a/b",
        "git@github.com:a/b",
        "file:///etc/passwd",
        "https://127.0.0.1/a/b",
        "https://github.com/a/b?token=secret",
        "https://github.com/a/b#fragment",
        "https://github.com/a/..",
        "https://github.com/a/.",
        "https://github.com/a/.git",
        "https://github.com/a/b.git.git",
        "https://github.com/a/%2e%2e",
        "https://github.com/a/b/tree/main",
        "https://github.com/a/b\n",
        " https://github.com/a/b",
        "https://github.com/a/b\\evil",
        "https://github.com/a/b//",
        "https://github.com/a/рroject",
        "https://github.com/a/" + "b" * 101,
    ],
)
def test_ambiguous_or_non_github_urls_are_rejected(url):
    with pytest.raises(ValueError):
        canonical_repository_url(url)
    with pytest.raises(ValidationError):
        RepositoryCreate(repository_url=url)


def test_registration_cannot_set_identity_or_execution_permissions():
    with pytest.raises(ValidationError):
        RepositoryCreate(
            repository_url="https://github.com/a/b", registered_by="attacker"
        )
    with pytest.raises(ValidationError):
        RepositoryUpdate(enabled=True, execute=True)
    with pytest.raises(ValidationError):
        RepositoryUpdate(enabled="true")
