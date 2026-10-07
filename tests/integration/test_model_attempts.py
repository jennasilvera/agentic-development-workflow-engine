import asyncio
import json

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from adwe.domain.proposal import ProposalInput
from adwe.services.model_attempts import (
    AttemptConflict,
    create_model_budget,
    propose_with_budget,
    reserve_model_attempt,
)
from adwe.services.model_gateway import (
    GatewayError,
    GatewayPolicy,
    ProviderReply,
    Usage,
)
from adwe.services.repositories import register_repository
from adwe.services.run_submissions import record_run_submission


async def setup(sessions, max_calls=2):
    policy = GatewayPolicy(
        provider="fixture",
        model="fixture-v1",
        version="test-v1",
        max_calls=max_calls,
        max_input_bytes=16000,
        max_output_bytes=16000,
        max_output_tokens=100,
        output_token_reservation=200,
        timeout_seconds=1.0,
    )
    async with sessions() as session, session.begin():
        repo, _ = await register_repository(
            session, "https://github.com/example/repo", "operator"
        )
        run = {
            "repository_id": repo.id,
            "repository_url": repo.canonical_url,
            "base_commit_sha": "a" * 40,
            "policy_version": "fixture-v1",
            "task": {"objective": "Fix", "acceptance_criteria": ["Pass"]},
        }
        submission, _ = await record_run_submission(session, run, "operator", "one")
        await create_model_budget(session, submission.id, policy, "operator")
    return (
        submission.id,
        {"run_input": run, "files": [{"path": "a.py", "content": "old"}]},
        policy,
    )


class Provider:
    def __init__(self):
        self.calls = 0

    async def propose(self, request):
        self.calls += 1
        source = ProposalInput.model_validate_json(request.payload)
        return ProviderReply(
            "fixture",
            "fixture-v1",
            json.dumps(
                {
                    "input_digest": request.input_digest,
                    "summary": "Fix",
                    "replacements": [
                        {
                            "path": "a.py",
                            "content": "new",
                            "expected_sha256": source.files[0].content_digest(),
                        }
                    ],
                }
            ).encode(),
            Usage(input_tokens=20, output_tokens=30),
        )


@pytest.mark.asyncio
async def test_budget_survives_new_gateway_and_concurrent_workers(registry_database):
    engine, sessions, _ = registry_database
    sid, data, _ = await setup(sessions, max_calls=1)
    provider = Provider()
    results = await asyncio.gather(
        *[
            propose_with_budget(sessions, sid, key, data, provider)
            for key in ("one", "two")
        ],
        return_exceptions=True,
    )
    assert provider.calls == 1
    assert sum(isinstance(x, GatewayError) for x in results) == 1
    with pytest.raises(GatewayError, match="budget_exhausted"):
        await propose_with_budget(sessions, sid, "three", data, Provider())
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM model_attempts")) == 1
        evidence = json.loads(
            conn.scalar(text("SELECT evidence FROM model_attempt_results"))
        )
        assert evidence["attempt_id"] == conn.scalar(
            text("SELECT id FROM model_attempts")
        )
        assert evidence["usage"]["output_tokens"] == 30
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM audit_events WHERE event_type='model_attempt.succeeded'"
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_same_key_race_and_changed_input_do_not_reinvoke(registry_database):
    _, sessions, _ = registry_database
    sid, data, _ = await setup(sessions)
    provider = Provider()
    results = await asyncio.gather(
        *[propose_with_budget(sessions, sid, "same", data, provider) for _ in range(2)],
        return_exceptions=True,
    )
    assert sum(isinstance(x, AttemptConflict) for x in results) == 1
    assert provider.calls == 1
    data["run_input"]["base_commit_sha"] = "b" * 40
    with pytest.raises(AttemptConflict, match="input differs"):
        await propose_with_budget(sessions, sid, "new", data, provider)
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_crash_after_reservation_never_refunds_or_replays(registry_database):
    engine, sessions, _ = registry_database
    sid, data, _ = await setup(sessions, max_calls=1)
    async with sessions() as session, session.begin():
        await reserve_model_attempt(session, sid, "lost", data)
    with pytest.raises(AttemptConflict):
        await propose_with_budget(sessions, sid, "lost", data, Provider())
    with pytest.raises(GatewayError, match="budget_exhausted"):
        await propose_with_budget(sessions, sid, "retry", data, Provider())
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM model_attempt_results")) == 0


@pytest.mark.asyncio
async def test_result_audit_failure_leaves_uncertain_spent_attempt(
    registry_database, monkeypatch
):
    engine, sessions, _ = registry_database
    sid, data, _ = await setup(sessions, max_calls=1)
    from adwe.services import model_attempts

    real = model_attempts.record_audit_event

    async def fail(session, event_type, **kwargs):
        if event_type == "model_attempt.succeeded":
            raise RuntimeError("audit failed")
        return await real(session, event_type, **kwargs)

    monkeypatch.setattr(model_attempts, "record_audit_event", fail)
    provider = Provider()
    with pytest.raises(RuntimeError, match="audit failed"):
        await propose_with_budget(sessions, sid, "one", data, provider)
    assert provider.calls == 1
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM model_attempts")) == 1
        assert conn.scalar(text("SELECT count(*) FROM model_attempt_results")) == 0
    with pytest.raises(AttemptConflict):
        await propose_with_budget(sessions, sid, "one", data, provider)


@pytest.mark.asyncio
async def test_cancellation_and_transport_failure_remain_spent(registry_database):
    engine, sessions, _ = registry_database
    sid, data, _ = await setup(sessions)
    started = asyncio.Event()

    class Hanging:
        async def propose(self, request):
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(
        propose_with_budget(sessions, sid, "cancel", data, Hanging())
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    class Failed:
        async def propose(self, request):
            raise OSError("secret detail")

    with pytest.raises(GatewayError, match="provider_unavailable"):
        await propose_with_budget(sessions, sid, "error", data, Failed())
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM model_attempts")) == 2
        row = conn.execute(
            text("SELECT outcome,failure_code FROM model_attempt_results")
        ).one()
        assert tuple(row) == ("uncertain", "provider_unavailable")


@pytest.mark.asyncio
async def test_database_guards_budget_identity_and_populated_downgrade(
    registry_database,
):
    engine, sessions, config = registry_database
    sid, data, policy = await setup(sessions, max_calls=1)
    async with sessions() as session, session.begin():
        assert await create_model_budget(session, sid, policy, "operator") is False
    with pytest.raises(AttemptConflict):
        async with sessions() as session, session.begin():
            await create_model_budget(
                session, sid, policy.model_copy(update={"max_calls": 2}), "operator"
            )
    await propose_with_budget(sessions, sid, "one", data, Provider())
    for table in ("model_budgets", "model_attempts", "model_attempt_results"):
        with pytest.raises(DBAPIError, match="immutable"), engine.begin() as conn:
            conn.execute(text("DELETE FROM " + table))
    with pytest.raises(DBAPIError, match="exceeds budget"), engine.begin() as conn:
        conn.execute(
            text("""
          INSERT INTO model_attempts(id,submission_id,request_key,input_digest,reserved_tokens)
          VALUES ('other',:id,'extra',:digest,100)
        """),
            {"id": sid, "digest": "0" * 64},
        )
    with (
        pytest.raises(DBAPIError, match="populated downgrade refused"),
        engine.begin() as conn,
    ):
        config.attributes["connection"] = conn
        command.downgrade(config, "c264b8da5eb7")


def test_empty_migration_roundtrip(registry_database):
    engine, _, config = registry_database
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "c264b8da5eb7")
        command.upgrade(config, "head")
        assert conn.scalar(text("SELECT count(*) FROM model_budgets")) == 0


@pytest.mark.asyncio
async def test_reservation_audit_failure_prevents_provider_call(
    registry_database, monkeypatch
):
    engine, sessions, _ = registry_database
    sid, data, _ = await setup(sessions)

    async def fail(*args, **kwargs):
        raise RuntimeError("audit failed")

    monkeypatch.setattr("adwe.services.model_attempts.record_audit_event", fail)
    provider = Provider()
    with pytest.raises(RuntimeError):
        await propose_with_budget(sessions, sid, "one", data, provider)
    assert provider.calls == 0
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM model_attempts")) == 0
