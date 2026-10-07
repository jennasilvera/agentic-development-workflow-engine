import asyncio
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from adwe.services.repositories import register_repository
from adwe.services.run_submissions import record_run_submission
from adwe.services.verification_inbox import receive_verification_request
from adwe.workers.verification_dispatcher import (
    DatabaseInboxReceiver,
    DispatchResult,
    dispatch_one,
)


async def submit(sessions):
    async with sessions() as session, session.begin():
        repo, _ = await register_repository(
            session, "https://github.com/example/repo", "operator"
        )
        row, _ = await record_run_submission(
            session,
            {
                "repository_id": repo.id,
                "repository_url": repo.canonical_url,
                "base_commit_sha": "a" * 40,
                "policy_version": "unverified",
                "task": {"objective": "Fix", "acceptance_criteria": ["Pass"]},
            },
            "operator",
            "one",
        )
        return row.id


@pytest.mark.asyncio
async def test_concurrent_receive_is_idempotent(registry_database):
    engine, sessions, _ = registry_database
    row_id = await submit(sessions)

    async def receive():
        async with sessions() as session, session.begin():
            return await receive_verification_request(session, row_id)

    assert sorted(await asyncio.gather(receive(), receive())) == [False, True]
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM verification_inbox")) == 1
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM audit_events WHERE event_type='verification_request.received'"
                )
            )
            == 1
        )
        payload = conn.scalar(
            text(
                "SELECT payload FROM audit_events WHERE event_type='verification_request.received'"
            )
        )
        assert payload["revision_verified"] is False
        assert payload["execution_admitted"] is False


@pytest.mark.asyncio
async def test_durable_acceptance_then_timeout_replays_without_duplicate_receipt(
    registry_database,
):
    engine, sessions, _ = registry_database
    await submit(sessions)
    receiver = DatabaseInboxReceiver(sessions)

    class LostReply:
        async def receive(self, submission_id):
            await receiver.receive(submission_id)
            raise TimeoutError("reply lost after committed acceptance")

    assert await dispatch_one(sessions, LostReply()) == DispatchResult.UNCERTAIN
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT count(*) FROM verification_inbox")) == 1
        assert conn.scalar(text("SELECT status FROM submission_outbox")) == "leased"
        conn.execute(
            text(
                "UPDATE submission_outbox SET lease_expires_at=clock_timestamp()-interval '1 second'"
            )
        )
    assert await dispatch_one(sessions, receiver) == DispatchResult.DELIVERED
    assert await dispatch_one(sessions, receiver) == DispatchResult.IDLE
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM verification_inbox")) == 1
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM audit_events WHERE event_type='verification_request.received'"
                )
            )
            == 1
        )
        assert conn.scalar(text("SELECT attempts FROM submission_outbox")) == 2


@pytest.mark.asyncio
async def test_ack_commit_failure_preserves_receipt_for_replay(
    registry_database, monkeypatch
):
    engine, sessions, _ = registry_database
    await submit(sessions)

    async def fail(*args, **kwargs):
        raise RuntimeError("ack unavailable")

    monkeypatch.setattr(
        "adwe.workers.verification_dispatcher.finish_verification_delivery", fail
    )
    with pytest.raises(RuntimeError, match="ack unavailable"):
        await dispatch_one(sessions, DatabaseInboxReceiver(sessions))
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM verification_inbox")) == 1
        assert conn.scalar(text("SELECT status FROM submission_outbox")) == "leased"


@pytest.mark.asyncio
async def test_receipt_audit_failure_rolls_back_and_unknown_id_rejected(
    registry_database, monkeypatch
):
    engine, sessions, _ = registry_database
    row_id = await submit(sessions)
    with pytest.raises(ValueError, match="Unknown submission"):
        async with sessions() as session, session.begin():
            await receive_verification_request(session, str(uuid4()))

    async def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("adwe.services.verification_inbox.record_audit_event", fail)
    with pytest.raises(RuntimeError):
        async with sessions() as session, session.begin():
            await receive_verification_request(session, row_id)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM verification_inbox")) == 0


@pytest.mark.asyncio
async def test_cancellation_propagates_and_leaves_lease_recoverable(registry_database):
    engine, sessions, _ = registry_database
    await submit(sessions)

    class Cancelled:
        async def receive(self, submission_id):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await dispatch_one(sessions, Cancelled())
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT status FROM submission_outbox")) == "leased"
        assert conn.scalar(text("SELECT count(*) FROM verification_inbox")) == 0


@pytest.mark.asyncio
async def test_receipt_database_guards_and_downgrade(registry_database):
    engine, sessions, config = registry_database
    row_id = await submit(sessions)
    with pytest.raises(DBAPIError, match="input mismatch"), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO verification_inbox (submission_id,input_digest) VALUES (:id,repeat('0',64))"
            ),
            {"id": row_id},
        )
    await DatabaseInboxReceiver(sessions).receive(row_id)
    for query in [
        "DELETE FROM verification_inbox",
        "UPDATE verification_inbox SET input_digest=repeat('0',64)",
    ]:
        with pytest.raises(DBAPIError, match="immutable"), engine.begin() as conn:
            conn.execute(text(query))
    with (
        pytest.raises(DBAPIError, match="populated downgrade refused"),
        engine.begin() as conn,
    ):
        config.attributes["connection"] = conn
        command.downgrade(config, "a042f6b83c95")
