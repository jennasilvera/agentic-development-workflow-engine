import json
from dataclasses import replace

import httpx
import pytest
from pydantic import SecretStr

from adwe.domain.proposal import ProposalInput
from adwe.services.model_gateway import ProviderFailure, ProviderRequest
from adwe.services.openai_chat_provider import ENDPOINT, PROVIDER, OpenAIChatProvider


def request():
    source = ProposalInput.model_validate(
        {
            "run_input": {
                "repository_id": "00000000-0000-4000-8000-000000000001",
                "repository_url": "https://github.com/example/repo",
                "base_commit_sha": "a" * 40,
                "policy_version": "test-v1",
                "task": {"objective": "Fix", "acceptance_criteria": ["Pass"]},
            },
            "files": [{"path": "a.py", "content": "old"}],
        }
    )
    return ProviderRequest(
        PROVIDER, "pinned-model", source.canonical_bytes(), source.digest(), 100, 4096
    )


def envelope():
    return {
        "model": "pinned-model",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "{}", "refusal": None},
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 30},
    }


@pytest.mark.asyncio
async def test_fixed_origin_bounded_request_and_provenance(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://invalid-proxy.example")
    calls = []

    def handler(req):
        calls.append(req)
        assert str(req.url) == ENDPOINT
        assert req.headers["authorization"] == "Bearer fixture-secret"
        assert req.headers["accept-encoding"] == "identity"
        assert "cookie" not in req.headers
        payload = json.loads(req.content)
        assert payload["store"] is False and payload["stream"] is False
        assert payload["max_completion_tokens"] == 100
        assert "tools" not in payload
        context = json.loads(payload["messages"][1]["content"])
        assert context["input_digest"] == request().input_digest
        assert len(context["source_sha256"]["a.py"]) == 64
        return httpx.Response(200, json=envelope())

    provider = OpenAIChatProvider(
        SecretStr("fixture-secret"), transport=httpx.MockTransport(handler)
    )
    result = await provider.propose(request())
    assert result.body == b"{}" and result.usage.output_tokens == 30
    assert len(calls) == 1
    assert "fixture-secret" not in repr(provider)


@pytest.mark.parametrize(
    "status,code",
    [
        (301, "invalid_provider_reply"),
        (401, "provider_refused"),
        (403, "provider_refused"),
        (429, "rate_limited"),
        (500, "provider_unavailable"),
    ],
)
@pytest.mark.asyncio
async def test_status_failure_no_retry_or_redirect(status, code):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(
            status,
            text="sensitive server message",
            headers={"location": "https://evil.example"},
        )

    with pytest.raises(ProviderFailure, match="^" + code + "$"):
        await OpenAIChatProvider(
            SecretStr("key"), transport=httpx.MockTransport(handler)
        ).propose(request())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "model",
        "length",
        "tool",
        "refusal",
        "usage",
        "oversize",
        "bad_message",
        "choices",
    ],
)
@pytest.mark.asyncio
async def test_invalid_envelopes_and_refusal(mutation):
    data = envelope()
    if mutation == "model":
        data["model"] = "other"
    if mutation == "length":
        data["choices"][0]["finish_reason"] = "length"
    if mutation == "tool":
        data["choices"][0]["message"]["tool_calls"] = [{"name": "execute"}]
    if mutation == "refusal":
        data["choices"][0]["message"]["refusal"] = "sensitive refusal"
    if mutation == "usage":
        data["usage"]["completion_tokens"] = True
    if mutation == "oversize":
        data["choices"][0]["message"]["content"] = "x" * 4097
    if mutation == "bad_message":
        data["choices"][0]["message"] = []
    if mutation == "choices":
        data["choices"] = []
    provider = OpenAIChatProvider(
        SecretStr("key"),
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=data)),
    )
    with pytest.raises(ProviderFailure):
        await provider.propose(request())


@pytest.mark.parametrize(
    "body,headers",
    [
        (b'{"model":"a","model":"b"}', {"content-type": "application/json"}),
        (b"{}", {"content-type": "text/html"}),
        (b"{}", {"content-type": "application/json", "content-length": "999999999"}),
        (b"{}", {"content-type": "application/json", "content-encoding": "br"}),
        (b"\xff", {"content-type": "application/json"}),
    ],
)
@pytest.mark.asyncio
async def test_transport_body_validation(body, headers):
    provider = OpenAIChatProvider(
        SecretStr("key"),
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=body, headers=headers)
        ),
    )
    with pytest.raises(ProviderFailure):
        await provider.propose(request())


@pytest.mark.asyncio
async def test_input_mismatch_fails_before_network():
    def forbidden(req):
        pytest.fail("Network should not be reached")

    provider = OpenAIChatProvider(
        SecretStr("key"), transport=httpx.MockTransport(forbidden)
    )
    with pytest.raises(ProviderFailure, match="invalid_gateway_input"):
        await provider.propose(replace(request(), input_digest="0" * 64))


@pytest.mark.parametrize(
    "error,code",
    [
        (httpx.ReadTimeout("secret"), "provider_timeout"),
        (httpx.ConnectError("secret"), "provider_unavailable"),
    ],
)
@pytest.mark.asyncio
async def test_transport_errors_are_sanitized(error, code):
    def handler(req):
        raise error

    provider = OpenAIChatProvider(
        SecretStr("key"), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ProviderFailure, match="^" + code + "$"):
        await provider.propose(request())


@pytest.mark.asyncio
async def test_streamed_body_limit_without_content_length():
    class Flood(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                yield b"x" * 4096

    provider = OpenAIChatProvider(
        SecretStr("key"),
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200, stream=Flood(), headers={"content-type": "application/json"}
            )
        ),
    )
    with pytest.raises(ProviderFailure, match="invalid_provider_reply"):
        await provider.propose(request())
