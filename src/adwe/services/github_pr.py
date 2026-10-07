import re

import httpx

from adwe.core.config import settings
from adwe.services.execution_policy import Operation, require_operation


class GitHubPRError(Exception):
    pass


def parse_github_repo(repository_url: str) -> tuple[str, str]:
    match = re.match(r"https://github.com/([^/]+)/([^/]+?)(?:\.git)?/?$", repository_url)

    if not match:
        raise GitHubPRError("Invalid GitHub repository URL")

    return match.group(1), match.group(2)


def create_pull_request(
    repository_url: str,
    branch_name: str,
    title: str,
    body: str,
) -> dict:
    require_operation(Operation.PUBLICATION)
    if not settings.github_token:
        return {
            "repository_url": repository_url,
            "branch_name": branch_name,
            "title": title,
            "body": body,
            "status": "skipped",
            "url": None,
        }

    owner, repo = parse_github_repo(repository_url)

    response = httpx.post(
        f"https://api.github.com/repos/{owner}/{repo}/pulls",
        headers={
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "title": title,
            "head": branch_name,
            "base": "master",
            "body": body,
        },
        timeout=30,
    )

    if response.status_code >= 400:
        raise GitHubPRError(response.text)

    data = response.json()

    return {
        "repository_url": repository_url,
        "branch_name": branch_name,
        "title": title,
        "body": body,
        "status": "opened",
        "url": data.get("html_url"),
    }
