"""Durable internal model budgets; no execution admission or live provider wiring."""

import json
import re
from dataclasses import asdict, replace
from uuid import uuid4

from sqlalchemy import text

from adwe.domain.proposal import ProposalInput, canonical_bytes
from adwe.services.audit import record_audit_event
from adwe.services.model_gateway import (
    FailureCode,
    GatewayError,
    GatewayPolicy,
    ModelGateway,
)


class AttemptConflict(ValueError):
    pass


async def create_model_budget(
    session, submission_id: str, policy: GatewayPolicy, actor_id: str
):
    """Trusted operator configuration, once per submission. Caller commits."""
    policy = GatewayPolicy.model_validate(policy.model_dump())
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", actor_id):
        raise ValueError("Invalid actor")
    stored = canonical_bytes(policy).decode("ascii")
    created = await session.scalar(
        text("""
      INSERT INTO model_budgets(submission_id,policy,actor_id) VALUES (:id,:policy,:actor)
      ON CONFLICT (submission_id) DO NOTHING RETURNING submission_id
    """),
        {"id": submission_id, "policy": stored, "actor": actor_id},
    )
    if created is None:
        row = (
            await session.execute(
                text(
                    "SELECT policy,actor_id FROM model_budgets WHERE submission_id=:id"
                ),
                {"id": submission_id},
            )
        ).one()
        if row.policy != stored or row.actor_id != actor_id:
            raise AttemptConflict("Budget already fixed for this submission")
        return False
    await record_audit_event(
        session,
        "model_budget.created",
        payload={
            "submission_id": submission_id,
            "actor_id": actor_id,
            "policy_version": policy.version,
        },
    )
    await session.flush()
    return True


async def reserve_model_attempt(
    session, submission_id: str, request_key: str, data: dict
):
    """Return fresh reservation only; existing keys never authorize another call."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", request_key):
        raise ValueError("Invalid request key")
    source = ProposalInput.model_validate(data)
    budget = (
        await session.execute(
            text("""
      SELECT b.policy,s.canonical_input FROM model_budgets b
      JOIN run_submissions s ON s.id=b.submission_id
      JOIN repositories r ON r.id=s.repository_id
      WHERE b.submission_id=:id AND r.enabled FOR UPDATE OF b,r
    """),
            {"id": submission_id},
        )
    ).one_or_none()
    if budget is None:
        raise AttemptConflict("Model budget missing or repository disabled")
    policy = GatewayPolicy.model_validate_json(budget.policy)
    if source.run_input.canonical_bytes().decode("ascii") != budget.canonical_input:
        raise AttemptConflict("Submission input differs")
    if len(source.canonical_bytes()) > policy.max_input_bytes:
        raise GatewayError(FailureCode.INPUT)
    exists = await session.scalar(
        text(
            "SELECT id FROM model_attempts WHERE submission_id=:id AND request_key=:key"
        ),
        {"id": submission_id, "key": request_key},
    )
    if exists:
        raise AttemptConflict("Attempt key already reserved; inspect recorded outcome")
    calls, reserved = (
        await session.execute(
            text("""
      SELECT count(*),coalesce(sum(reserved_tokens),0) FROM model_attempts WHERE submission_id=:id
    """),
            {"id": submission_id},
        )
    ).one()
    if (
        calls >= policy.max_calls
        or reserved + policy.max_output_tokens > policy.output_token_reservation
    ):
        raise GatewayError(FailureCode.BUDGET)
    attempt_id = str(uuid4())
    await session.execute(
        text("""
      INSERT INTO model_attempts(id,submission_id,request_key,input_digest,reserved_tokens)
      VALUES (:attempt,:id,:key,:digest,:tokens)
    """),
        {
            "attempt": attempt_id,
            "id": submission_id,
            "key": request_key,
            "digest": source.digest(),
            "tokens": policy.max_output_tokens,
        },
    )
    await record_audit_event(
        session,
        "model_attempt.reserved",
        payload={
            "submission_id": submission_id,
            "attempt_id": attempt_id,
            "input_digest": source.digest(),
            "reserved_tokens": policy.max_output_tokens,
        },
    )
    await session.flush()
    return attempt_id, policy


async def _record_result(
    session, attempt_id, outcome, evidence=None, failure_code=None
):
    encoded = None
    if evidence is not None:
        document = asdict(evidence)
        document["proposal"] = evidence.proposal.model_dump(mode="json")
        document["usage"] = evidence.usage.model_dump(mode="json")
        encoded = json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
    # Only called with the gateway result for this reserved invocation. No public
    # outcome-write API; primary key rejects contradictory/duplicate completions.
    await session.execute(
        text("""
      INSERT INTO model_attempt_results(attempt_id,outcome,evidence,failure_code)
      VALUES (:id,:outcome,:evidence,:code)
    """),
        {
            "id": attempt_id,
            "outcome": outcome,
            "evidence": encoded,
            "code": failure_code,
        },
    )
    await record_audit_event(
        session,
        "model_attempt." + outcome,
        payload={
            "attempt_id": attempt_id,
            "failure_code": failure_code,
        },
    )
    await session.flush()


async def propose_with_budget(sessions, submission_id, request_key, data, provider):
    """Commit reservation before provider I/O. Missing result is an uncertain attempt.

    Cancellation, process loss and persistence failure leave the reservation spent.
    Never repeat a request key or infer that an absent outcome means no provider call.
    """
    data = ProposalInput.model_validate(data).model_dump(mode="json")
    async with sessions() as session, session.begin():
        attempt_id, policy = await reserve_model_attempt(
            session, submission_id, request_key, data
        )
    try:
        evidence = await ModelGateway(policy, provider).propose(data)
    except GatewayError as error:
        outcome = (
            "uncertain"
            if error.code
            in {
                FailureCode.TIMEOUT,
                FailureCode.UNAVAILABLE,
            }
            else "failed"
        )
        async with sessions() as session, session.begin():
            await _record_result(
                session, attempt_id, outcome, failure_code=error.code.value
            )
        raise
    evidence = replace(evidence, attempt_id=attempt_id)
    async with sessions() as session, session.begin():
        await _record_result(session, attempt_id, "succeeded", evidence=evidence)
    return evidence
