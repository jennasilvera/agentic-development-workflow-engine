import asyncio

import pytest
from alembic import command
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from adwe.models.audit_event import AuditEvent
from adwe.models.run_submission import RunSubmission
from adwe.services.repositories import register_repository, set_repository_enabled
from adwe.services.run_submissions import SubmissionConflict, record_run_submission


async def setup_input(sessions):
    async with sessions() as session, session.begin():
        repo, _ = await register_repository(
            session, "https://github.com/example/project", "operator"
        )
        return {
            "repository_id": repo.id,
            "repository_url": repo.canonical_url,
            "base_commit_sha": "a" * 40,
            "policy_version": "requested-1",
            "task": {"objective": "Fix café", "acceptance_criteria": ["Tests pass"]},
        }


@pytest.mark.asyncio
async def test_concurrent_duplicates_and_changed_key_conflict(registry_database):
    _, sessions, _ = registry_database
    data = await setup_input(sessions)

    async def submit(key="request-1"):
        async with sessions() as session, session.begin():
            row, created = await record_run_submission(session, data, "operator", key)
            return row.id, created

    results = await asyncio.gather(submit(), submit())
    assert results[0][0] == results[1][0]
    assert sorted(r[1] for r in results) == [False, True]
    # A new explicit request may repeat the same input.
    assert (await submit("request-2"))[0] != results[0][0]
    data["base_commit_sha"] = "b" * 40
    with pytest.raises(SubmissionConflict):
        await submit()
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(RunSubmission)) == 2
        )
        events = (
            await session.scalars(
                select(AuditEvent).where(AuditEvent.event_type == "run_input.recorded")
            )
        ).all()
        assert len(events) == 2
        assert all(e.payload["execution_admitted"] is False for e in events)


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_submission(registry_database, monkeypatch):
    _, sessions, _ = registry_database
    data = await setup_input(sessions)

    async def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("adwe.services.run_submissions.record_audit_event", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        async with sessions() as session, session.begin():
            await record_run_submission(session, data, "operator", "request")
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(RunSubmission)) == 0
        )


@pytest.mark.asyncio
async def test_disable_serializes_before_submission(registry_database):
    _, sessions, _ = registry_database
    data = await setup_input(sessions)
    started = asyncio.Event()

    async def submit():
        async with sessions() as session, session.begin():
            started.set()
            return await record_run_submission(session, data, "operator", "request")

    async with sessions() as session:
        async with session.begin():
            await set_repository_enabled(
                session, data["repository_id"], False, "operator"
            )
            await session.flush()
            task = asyncio.create_task(submit())
            await started.wait()
        with pytest.raises(SubmissionConflict, match="disabled"):
            await asyncio.wait_for(task, timeout=10)
    async with sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(RunSubmission)) == 0
        )


@pytest.mark.asyncio
async def test_repository_url_mismatch_is_rejected(registry_database):
    _, sessions, _ = registry_database
    data = await setup_input(sessions)
    data["repository_url"] = "https://github.com/example/other"
    with pytest.raises(SubmissionConflict, match="identity"):
        async with sessions() as session, session.begin():
            await record_run_submission(session, data, "operator", "request")


@pytest.mark.asyncio
async def test_database_immutability_digest_and_downgrade(registry_database):
    engine, sessions, config = registry_database
    data = await setup_input(sessions)
    async with sessions() as session, session.begin():
        row, _ = await record_run_submission(session, data, "operator", "request")
        row_id = row.id
    for statement in [
        "UPDATE run_submissions SET actor_id = 'other' WHERE id = :id",
        "DELETE FROM run_submissions WHERE id = :id",
        "INSERT INTO run_submissions SELECT 'invalid', repository_id, actor_id, 'bad', canonical_input, repeat('0',64), created_at FROM run_submissions WHERE id = :id",
    ]:
        with pytest.raises(DBAPIError), engine.begin() as conn:
            conn.execute(text(statement), {"id": row_id})
    with (
        pytest.raises(DBAPIError, match="populated downgrade refused"),
        engine.begin() as conn,
    ):
        config.attributes["connection"] = conn
        command.downgrade(config, "8c20d4e61f73")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM run_submissions")) == 1


def test_empty_submission_migration_roundtrip(registry_database):
    engine, _, config = registry_database
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "8c20d4e61f73")
        command.upgrade(config, "head")
        assert conn.scalar(text("SELECT count(*) FROM run_submissions")) == 0
