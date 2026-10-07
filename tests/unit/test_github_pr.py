import pytest

from adwe.services.execution_policy import OperationUnavailable
from adwe.services.github_pr import create_pull_request, parse_github_repo


def test_parse_github_repo_https_url():
    owner, repo = parse_github_repo("https://github.com/pallets/flask")

    assert owner == "pallets"
    assert repo == "flask"


def test_parse_github_repo_git_suffix():
    owner, repo = parse_github_repo("https://github.com/pallets/flask.git")

    assert owner == "pallets"
    assert repo == "flask"


def test_create_pull_request_is_unavailable_without_validation_authority():
    with pytest.raises(OperationUnavailable):
        create_pull_request(
            repository_url="https://github.com/pallets/flask",
            branch_name="adwe/test",
            title="Test PR",
            body="Test body",
        )
