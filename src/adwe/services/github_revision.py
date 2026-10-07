"""Bounded public GitHub commit lookup, not checkout or execution authorization."""

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from adwe.domain.run_input import RunInput

MAX_RESPONSE_BYTES = 65536
_SHA1 = re.compile(r"[0-9a-f]{40}")


class RevisionLookupError(ValueError):
    def __init__(self, code: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(code)  # Never include bodies, URLs, headers or credentials.


@dataclass(frozen=True)
class RevisionObservation:
    input_digest: str
    repository_id: str
    canonical_url: str
    github_repository_id: int
    commit_sha: str
    tree_sha: str
    observed_at: datetime
    provider: str = "github-public-rest-v1"


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise RevisionLookupError("ambiguous_response")
        value[key] = item
    return value


def _reject_constant(value: str):
    raise ValueError("Non-finite JSON numbers are forbidden")


async def _get_json(client: httpx.AsyncClient, path: str) -> dict:
    client.cookies.clear()
    async with client.stream("GET", "https://api.github.com" + path) as response:
        status = response.status_code
        if status != 200:
            if status == 429 or (
                status == 403 and response.headers.get("x-ratelimit-remaining") == "0"
            ):
                raise RevisionLookupError("rate_limited", retryable=True)
            if 500 <= status <= 599:
                raise RevisionLookupError("provider_unavailable", retryable=True)
            raise RevisionLookupError(
                {404: "not_found", 401: "access_denied", 403: "access_denied"}.get(
                    status, "unexpected_status"
                )
            )
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise RevisionLookupError("encoded_response_rejected")
        if response.headers.get("content-type", "").split(";", 1)[
            0
        ].strip().lower() not in {"application/json", "application/vnd.github+json"}:
            raise RevisionLookupError("invalid_content_type")
        size = response.headers.get("content-length")
        if size is not None and (
            len(size) > 10 or not size.isdecimal() or int(size) > MAX_RESPONSE_BYTES
        ):
            raise RevisionLookupError("response_too_large")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                raise RevisionLookupError("response_too_large")
            body.extend(chunk)
        try:
            result = json.loads(
                body,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except (ValueError, UnicodeError, RecursionError):
            raise RevisionLookupError("invalid_json") from None
        if not isinstance(result, dict):
            raise RevisionLookupError("invalid_response")
        return result


def _repository_identity(metadata: dict, expected_name: str) -> int:
    repository_id = metadata.get("id")
    name = metadata.get("full_name")
    if type(repository_id) is not int or repository_id <= 0:
        raise RevisionLookupError("repository_identity_mismatch")
    if not isinstance(name, str) or name.lower() != expected_name:
        raise RevisionLookupError("repository_identity_mismatch")
    if metadata.get("private") is not False:
        raise RevisionLookupError("public_repository_required")
    if metadata.get("archived") is not False or metadata.get("disabled") is not False:
        raise RevisionLookupError("repository_unavailable")
    return repository_id


async def observe_public_revision(
    serialized_input: dict, *, transport: httpx.AsyncBaseTransport | None = None
) -> RevisionObservation:
    """Look up exact GitHub SHA-1 commit metadata with no credentials or redirects.

    The optional transport is a trusted test seam, never an API input. Caller must
    check registry/policy authority before invocation and recheck before admission.
    """
    value = RunInput.model_validate(serialized_input)
    if _SHA1.fullmatch(value.base_commit_sha) is None:
        raise RevisionLookupError("unsupported_object_format")
    full_name = value.repository_url.removeprefix("https://github.com/")
    path = "/repos/" + full_name
    try:
        async with (
            asyncio.timeout(10),
            httpx.AsyncClient(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(3),
                limits=httpx.Limits(max_connections=1),
                headers={
                    "Accept": "application/vnd.github+json",
                    "Accept-Encoding": "identity",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "adwe-revision-observer",
                },
            ) as client,
        ):
            first_id = _repository_identity(await _get_json(client, path), full_name)
            commit = await _get_json(
                client, path + "/git/commits/" + value.base_commit_sha
            )
            if commit.get("sha") != value.base_commit_sha:
                raise RevisionLookupError("commit_identity_mismatch")
            tree = commit.get("tree")
            tree_sha = tree.get("sha") if isinstance(tree, dict) else None
            if not isinstance(tree_sha, str) or _SHA1.fullmatch(tree_sha) is None:
                raise RevisionLookupError("invalid_tree_identity")
            last_id = _repository_identity(await _get_json(client, path), full_name)
            if first_id != last_id:
                raise RevisionLookupError("repository_changed")
    except (TimeoutError, httpx.TimeoutException):
        raise RevisionLookupError("provider_timeout", retryable=True) from None
    except httpx.RequestError:
        raise RevisionLookupError("provider_transport_error", retryable=True) from None
    return RevisionObservation(
        input_digest=value.digest(),
        repository_id=value.repository_id,
        canonical_url=value.repository_url,
        github_repository_id=first_id,
        commit_sha=value.base_commit_sha,
        tree_sha=tree_sha,
        observed_at=datetime.now(UTC),
    )
