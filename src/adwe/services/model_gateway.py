"""Bounded internal model contract. No provider transport or execution admission.

The provider is trusted application code, not an object constructed from model or
repository text. Instance-local reservations are not a durable or billing budget.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Protocol
from uuid import uuid4

from pydantic import Field, StrictInt, StrictStr

from adwe.domain.proposal import ChangeProposal, FrozenDocument, ProposalInput

Identifier = Annotated[
    StrictStr,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"),
]


class GatewayPolicy(FrozenDocument):
    provider: Identifier
    model: Identifier
    version: Identifier
    max_calls: StrictInt = Field(ge=1, le=20)
    max_input_bytes: StrictInt = Field(ge=1, le=256000)
    max_output_bytes: StrictInt = Field(ge=1, le=256000)
    max_output_tokens: StrictInt = Field(ge=1, le=32000)
    output_token_reservation: StrictInt = Field(ge=1, le=640000)
    timeout_seconds: float = Field(gt=0, le=60, allow_inf_nan=False, strict=True)


class Usage(FrozenDocument):
    input_tokens: StrictInt = Field(ge=0, le=10000000)
    output_tokens: StrictInt = Field(ge=0, le=10000000)


@dataclass(frozen=True)
class ProviderRequest:
    provider: str
    model: str
    payload: bytes
    input_digest: str
    max_output_tokens: int
    max_response_bytes: int


@dataclass(frozen=True)
class ProviderReply:
    provider: str
    model: str
    body: bytes
    usage: Usage


class FailureCode(StrEnum):
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "provider_unavailable"
    REFUSED = "provider_refused"
    TIMEOUT = "provider_timeout"
    INVALID = "invalid_provider_reply"
    BUDGET = "budget_exhausted"
    INPUT = "invalid_gateway_input"


class GatewayError(Exception):
    def __init__(self, code: FailureCode):
        # Never include provider response, prompt, task or exception text.
        self.code = FailureCode(code)
        super().__init__(self.code.value)


class ProviderFailure(Exception):
    """Adapters classify errors without passing response bodies to the gateway."""

    def __init__(self, code: FailureCode):
        self.code = FailureCode(code)
        super().__init__(self.code.value)


class ProposalProvider(Protocol):
    async def propose(self, request: ProviderRequest) -> ProviderReply:
        """Enforce transport/body bounds while receiving; no retries or fallback."""
        ...


@dataclass(frozen=True)
class ProposalEvidence:
    attempt_id: str
    provider: str
    model: str
    policy_version: str
    input_digest: str
    response_digest: str
    proposal_digest: str
    usage: Usage
    proposal: ChangeProposal


def _strict_json(body: bytes):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON key")
            value[key] = item
        return value

    def invalid_constant(value):
        raise ValueError("Non-finite JSON number")

    return json.loads(
        body.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid_constant
    )


class ModelGateway:
    def __init__(self, policy: GatewayPolicy, provider: ProposalProvider):
        self.policy = GatewayPolicy.model_validate(policy.model_dump())
        self.provider = provider
        self._lock = asyncio.Lock()
        self._calls = 0
        self._reserved = 0

    async def propose(self, serialized_input: dict) -> ProposalEvidence:
        try:
            source = ProposalInput.model_validate(serialized_input)
            payload = source.canonical_bytes()
            if len(payload) > self.policy.max_input_bytes:
                raise ValueError("Input exceeds policy bound")
        except (ValueError, TypeError, UnicodeError):
            raise GatewayError(FailureCode.INPUT) from None

        # Reserve before any external attempt. Never refund uncertain outcomes,
        # malformed replies or cancellation, and never silently swap providers.
        async with self._lock:
            if (
                self._calls >= self.policy.max_calls
                or self._reserved + self.policy.max_output_tokens
                > self.policy.output_token_reservation
            ):
                raise GatewayError(FailureCode.BUDGET)
            self._calls += 1
            self._reserved += self.policy.max_output_tokens
        attempt_id = str(uuid4())
        request = ProviderRequest(
            self.policy.provider,
            self.policy.model,
            payload,
            source.digest(),
            self.policy.max_output_tokens,
            self.policy.max_output_bytes,
        )
        try:
            async with asyncio.timeout(self.policy.timeout_seconds):
                reply = await self.provider.propose(request)
        except TimeoutError:
            raise GatewayError(FailureCode.TIMEOUT) from None
        except OSError:
            raise GatewayError(FailureCode.UNAVAILABLE) from None
        except ProviderFailure as error:
            raise GatewayError(error.code) from None
        # Cancellation and programming errors propagate, with reservation retained.
        try:
            if not isinstance(reply, ProviderReply) or type(reply.body) is not bytes:
                raise ValueError("Invalid provider envelope")
            if (
                reply.provider != self.policy.provider
                or reply.model != self.policy.model
            ):
                raise ValueError("Provider/model substitution")
            if len(reply.body) > self.policy.max_output_bytes:
                raise ValueError("Response exceeds policy bound")
            if not isinstance(reply.usage, Usage):
                raise TypeError("Usage required")
            usage = Usage.model_validate(reply.usage.model_dump())
            if usage.output_tokens > self.policy.max_output_tokens:
                raise ValueError("Reported output exceeds reservation")
            proposal = ChangeProposal.model_validate(_strict_json(reply.body))
            proposal.validate_against(source)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise GatewayError(FailureCode.INVALID) from None
        return ProposalEvidence(
            attempt_id,
            self.policy.provider,
            self.policy.model,
            self.policy.version,
            source.digest(),
            hashlib.sha256(reply.body).hexdigest(),
            proposal.digest(),
            usage,
            proposal,
        )
