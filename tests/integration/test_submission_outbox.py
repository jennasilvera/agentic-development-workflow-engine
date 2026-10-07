import asyncio
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text

from adwe.domain.run_input import RunInput
from adwe.services.repositories import register_repository
from adwe.services.run_submissions import record_run_submission
from adwe.services.submission_outbox import (
    StaleDeliveryLease,
    claim_verification_intent,
    finish_verification_delivery,
)


async def submit(sessions, key="one"):
    async with sessions() as session, session.begin():
        repo, _ = await register_repository(
            session, "https://github.com/example/repo", "operator"
        )
        data = {
            "repository_id": repo.id,
            "repository_url": repo.canonical_url,
            "base_commit_sha": "a" * 40,
            "policy_version": "1",
            "task": {"objective": "Fix", "acceptance_criteria": ["Pass"]},
        }
        row, _ = await record_run_submission(session, data, "operator", key)
        return row.id


async def claim(sessions):
    async with sessions() as session, session.begin():
        return await claim_verification_intent(session)


def expire(engine, submission_id):
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE submission_outbox SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE submission_id=:id"
            ),
            {"id": submission_id},
        )


@pytest.mark.asyncio
async def test_atomic_intent_and_idempotent_submission(registry_database, monkeypatch):
    engine, sessions, _ = registry_database
    first = await submit(sessions)
    assert await submit(sessions) == first
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM submission_outbox")) == 1

    async def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("adwe.services.run_submissions.record_audit_event", fail)
    with pytest.raises(RuntimeError):
        await submit(sessions, "two")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM submission_outbox")) == 1
        assert conn.scalar(text("SELECT count(*) FROM run_submissions")) == 1


@pytest.mark.asyncio
async def test_skip_locked_and_concurrent_claims(registry_database):
    _, sessions, _ = registry_database
    first = await submit(sessions)
    second = await submit(sessions, "two")
    async with sessions() as held, held.begin():
        lease = await claim_verification_intent(held)
        other = await asyncio.wait_for(claim(sessions), 10)
        assert {lease.submission_id, other.submission_id} == {first, second}
    assert await claim(sessions) is None
    async with sessions() as session, session.begin():
        await finish_verification_delivery(session, lease, delivered=True)
    with pytest.raises(StaleDeliveryLease):
        async with sessions() as session, session.begin():
            await finish_verification_delivery(session, lease, delivered=True)


@pytest.mark.asyncio
async def test_expiry_reclaim_fences_old_owner_and_exhausts(registry_database):
    engine, sessions, _ = registry_database
    row_id = await submit(sessions)
    old = await claim(sessions)
    expire(engine, row_id)
    # Expiry rejects completion even before a replacement owner has claimed it.
    with pytest.raises(StaleDeliveryLease):
        async with sessions() as session, session.begin():
            await finish_verification_delivery(session, old, delivered=True)
    for attempt in range(2, 6):
        lease = await claim(sessions)
        assert lease.attempt == attempt
        assert lease.token != old.token
        with pytest.raises(StaleDeliveryLease):
            async with sessions() as session, session.begin():
                await finish_verification_delivery(session, old, delivered=False)
        expire(engine, row_id)
    assert await claim(sessions) is None
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT status, attempts FROM submission_outbox")
        ).one() == ("dead", 5)
    assert await claim(sessions) is None


@pytest.mark.asyncio
async def test_known_failure_backoff_and_ack_rollback(registry_database, monkeypatch):
    engine, sessions, _ = registry_database
    await submit(sessions)
    lease = await claim(sessions)
    async with sessions() as session, session.begin():
        await finish_verification_delivery(session, lease, delivered=False)
    assert await claim(sessions) is None
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE submission_outbox SET available_at=clock_timestamp()-interval '1 second'"
            )
        )
    lease = await claim(sessions)

    async def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("adwe.services.submission_outbox.record_audit_event", fail)
    with pytest.raises(RuntimeError):
        async with sessions() as session, session.begin():
            await finish_verification_delivery(session, lease, delivered=True)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT status FROM submission_outbox")) == "leased"


@pytest.mark.asyncio
async def test_claim_rollback_does_not_consume_attempt(registry_database):
    engine, sessions, _ = registry_database
    await submit(sessions)
    with pytest.raises(RuntimeError):
        async with sessions() as session, session.begin():
            await claim_verification_intent(session)
            raise RuntimeError("crash before commit")
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT status, attempts FROM submission_outbox")
        ).one() == ("pending", 0)
    assert (await claim(sessions)).attempt == 1


@pytest.mark.asyncio
async def test_migration_backfills_existing_unverified_requests(registry_database):
    engine, _, config = registry_database
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "9d31e5f72a84")
    # Seed the historical schema without using current ORM columns/services.
    row_id, repository_id = str(uuid4()), str(uuid4())
    value = RunInput.model_validate(
        {
            "repository_id": repository_id,
            "repository_url": "https://github.com/example/repo",
            "base_commit_sha": "a" * 40,
            "policy_version": "1",
            "task": {"objective": "Fix", "acceptance_criteria": ["Pass"]},
        }
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO repositories (id,canonical_url,registered_by) VALUES (:id,:url,'operator')"
            ),
            {"id": repository_id, "url": value.repository_url},
        )
        conn.execute(
            text(
                "INSERT INTO run_submissions (id,repository_id,actor_id,request_key,canonical_input,input_digest) VALUES (:id,:repo,'operator','one',:input,:digest)"
            ),
            {
                "id": row_id,
                "repo": repository_id,
                "input": value.canonical_bytes().decode("ascii"),
                "digest": value.digest(),
            },
        )
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
        assert conn.execute(
            text("SELECT submission_id, status, attempts FROM submission_outbox")
        ).one() == (row_id, "pending", 0)
