import asyncio

import httpx
import pytest
from pydantic import ValidationError

from adwe.services.github_revision import RevisionLookupError, observe_public_revision


def request_input():
    return {
        "repository_id": "73b5c995-81c1-4daa-a456-70bd4945aeec",
        "repository_url": "https://github.com/Example/Repo.git",
        "base_commit_sha": "a" * 40,
        "policy_version": "1",
        "task": {"objective": "Fix", "acceptance_criteria": ["Pass"]},
    }


def repository(**overrides):
    return {
        "id": 42,
        "full_name": "Example/Repo",
        "private": False,
        "archived": False,
        "disabled": False,
        **overrides,
    }


def commit(**overrides):
    return {"sha": "a" * 40, "tree": {"sha": "b" * 40}, **overrides}


def transport_for(responses, requests):
    def handler(request):
        requests.append(request)
        return responses.pop(0)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_exact_metadata_identity_and_no_credentials(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-be-used")
    monkeypatch.setenv("HTTPS_PROXY", "http://must-not-be-used.invalid")
    requests = []
    result = await observe_public_revision(
        request_input(),
        transport=transport_for(
            [
                httpx.Response(200, json=repository(), headers={"set-cookie": "ignored=value"}),
                httpx.Response(200, json=commit()),
                httpx.Response(200, json=repository()),
            ],
            requests,
        ),
    )
    assert result.github_repository_id == 42
    assert result.commit_sha == "a" * 40
    assert result.tree_sha == "b" * 40
    assert result.observed_at.tzinfo is not None
    assert [str(r.url) for r in requests] == [
        "https://api.github.com/repos/example/repo",
        "https://api.github.com/repos/example/repo/git/commits/" + "a" * 40,
        "https://api.github.com/repos/example/repo",
    ]
    assert all(r.method == "GET" for r in requests)
    assert all(
        "authorization" not in r.headers and "cookie" not in r.headers for r in requests
    )


@pytest.mark.parametrize(
    "status,headers,code,retryable",
    [
        (302, {"location": "https://attacker.invalid"}, "unexpected_status", False),
        (404, {}, "not_found", False),
        (401, {}, "access_denied", False),
        (403, {}, "access_denied", False),
        (403, {"x-ratelimit-remaining": "0"}, "rate_limited", True),
        (429, {}, "rate_limited", True),
        (503, {}, "provider_unavailable", True),
    ],
)
@pytest.mark.asyncio
async def test_http_failures_are_closed_and_do_not_expose_body(
    status, headers, code, retryable
):
    requests = []
    with pytest.raises(RevisionLookupError) as error:
        await observe_public_revision(
            request_input(),
            transport=transport_for(
                [httpx.Response(status, headers=headers, text="private provider body")],
                requests,
            ),
        )
    assert error.value.code == code
    assert error.value.retryable is retryable
    assert "private provider body" not in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "metadata,code",
    [
        (repository(id=True), "repository_identity_mismatch"),
        (repository(full_name="other/repo"), "repository_identity_mismatch"),
        (repository(private=True), "public_repository_required"),
        (repository(archived=True), "repository_unavailable"),
        (repository(disabled=True), "repository_unavailable"),
    ],
)
@pytest.mark.asyncio
async def test_reject_repository_identity_and_state(metadata, code):
    with pytest.raises(RevisionLookupError, match=code):
        await observe_public_revision(
            request_input(),
            transport=transport_for([httpx.Response(200, json=metadata)], []),
        )


@pytest.mark.parametrize(
    "metadata,code",
    [
        (commit(sha="c" * 40), "commit_identity_mismatch"),
        (commit(tree={"sha": "main"}), "invalid_tree_identity"),
        (commit(tree=None), "invalid_tree_identity"),
    ],
)
@pytest.mark.asyncio
async def test_exact_commit_and_tree_required(metadata, code):
    with pytest.raises(RevisionLookupError, match=code):
        await observe_public_revision(
            request_input(),
            transport=transport_for(
                [
                    httpx.Response(200, json=repository()),
                    httpx.Response(200, json=metadata),
                ],
                [],
            ),
        )


@pytest.mark.asyncio
async def test_repository_replacement_during_lookup_is_rejected():
    with pytest.raises(RevisionLookupError, match="repository_changed"):
        await observe_public_revision(
            request_input(),
            transport=transport_for(
                [
                    httpx.Response(200, json=repository()),
                    httpx.Response(200, json=commit()),
                    httpx.Response(200, json=repository(id=43)),
                ],
                [],
            ),
        )


class Chunks(httpx.AsyncByteStream):
    async def __aiter__(self):
        for _ in range(20):
            yield b"x" * 4096


@pytest.mark.parametrize(
    "response,code",
    [
        (httpx.Response(200, text="<html>bad</html>"), "invalid_content_type"),
        (
            httpx.Response(
                200, content=b"{invalid", headers={"content-type": "application/json"}
            ),
            "invalid_json",
        ),
        (
            httpx.Response(
                200,
                content=b'{"id":42,"id":43}',
                headers={"content-type": "application/json"},
            ),
            "invalid_json",
        ),
        (httpx.Response(200, json=[]), "invalid_response"),
        (
            httpx.Response(
                200,
                headers={
                    "content-type": "application/json",
                    "content-length": "100000",
                },
            ),
            "response_too_large",
        ),
        (
            httpx.Response(
                200, stream=Chunks(), headers={"content-type": "application/json"}
            ),
            "response_too_large",
        ),
        (
            httpx.Response(
                200,
                stream=Chunks(),
                headers={
                    "content-type": "application/json",
                    "content-encoding": "gzip",
                },
            ),
            "encoded_response_rejected",
        ),
    ],
)
@pytest.mark.asyncio
async def test_response_limits_and_malformed_data(response, code):
    with pytest.raises(RevisionLookupError, match=code):
        await observe_public_revision(
            request_input(), transport=transport_for([response], [])
        )


@pytest.mark.parametrize(
    "exc,code",
    [
        (httpx.ReadTimeout("sensitive"), "provider_timeout"),
        (httpx.ConnectError("sensitive"), "provider_transport_error"),
    ],
)
@pytest.mark.asyncio
async def test_transport_failure_classification(exc, code):
    def handler(request):
        raise exc

    with pytest.raises(RevisionLookupError) as error:
        await observe_public_revision(
            request_input(), transport=httpx.MockTransport(handler)
        )
    assert error.value.code == code
    assert error.value.retryable
    assert "sensitive" not in str(error.value)


@pytest.mark.asyncio
async def test_cancellation_propagates():
    async def handler(request):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await observe_public_revision(
            request_input(), transport=httpx.MockTransport(handler)
        )


@pytest.mark.asyncio
async def test_invalid_input_and_unsupported_sha_fail_before_network():
    def handler(request):
        pytest.fail("Network should not be reached")

    data = request_input()
    data["repository_url"] = "https://127.0.0.1/private"
    with pytest.raises(ValidationError):
        await observe_public_revision(data, transport=httpx.MockTransport(handler))
    data = request_input()
    data["base_commit_sha"] = "a" * 64
    with pytest.raises(RevisionLookupError, match="unsupported_object_format"):
        await observe_public_revision(data, transport=httpx.MockTransport(handler))
