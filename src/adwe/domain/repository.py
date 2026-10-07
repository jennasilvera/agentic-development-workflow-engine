"""Canonical identity for the initial public-GitHub repository registry."""

import re

_REPOSITORY_URL = re.compile(
    r"https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9_.-]{1,104})/?",
    re.ASCII,
)


def canonical_repository_url(value: str) -> str:
    """Reject ambiguous URLs; never resolve, redirect or contact the network."""
    match = _REPOSITORY_URL.fullmatch(value)
    if match is None:
        raise ValueError(
            "Use an HTTPS github.com owner/repository URL without credentials, query or fragment"
        )
    owner, name = match.groups()
    if name.lower().endswith(".git"):
        name = name[:-4]
    if (
        not name
        or name in {".", ".."}
        or len(name) > 100
        or name.lower().endswith(".git")
    ):
        raise ValueError("Invalid GitHub repository name")
    return f"https://github.com/{owner.lower()}/{name.lower()}"
