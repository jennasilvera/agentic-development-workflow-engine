import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from adwe.api.app import app
from adwe.api.repositories import repository_session
from adwe.domain.run_input import RunInput
from adwe.services.github_revision import RevisionObservation
from adwe.services.repositories import register_repository, set_repository_enabled
from adwe.services.revision_verification import (
    VerificationConflict,
    pin_repository_identity,
    verify_submission,
)
from adwe.services.run_submissions import record_run_submission
from adwe.workers.verification_dispatcher import DatabaseInboxReceiver, dispatch_one


async def fake_observer(data):
    value = RunInput.model_validate(data)
    return RevisionObservation(
        value.digest(),
        value.repository_id,
        value.repository_url,
        42,
        value.base_commit_sha,
        "b" * 40,
        datetime.now(UTC),
    )


async def setup(sessions, policy="public-metadata-v1", pin=True):
    async with sessions() as session, session.begin():
        repo, _ = await register_repository(
            session, "https://github.com/example/repo", "operator"
        )
        if pin:
            await pin_repository_identity(session, repo.id, 42, "operator")
        data = {
            "repository_id": repo.id,
            "repository_url": repo.canonical_url,
            "base_commit_sha": "a" * 40,
            "policy_version": policy,
            "task": {"objective": "Fix", "acceptance_criteria": ["Pass"]},
        }
        row, _ = await record_run_submission(session, data, "operator", "one")
    await dispatch_one(sessions, DatabaseInboxReceiver(sessions))
    return row.id, repo.id


@pytest.mark.asyncio
async def test_observation_concurrent_idempotence_and_database_guards(
    registry_database,
):
    engine, sessions, config = registry_database
    sid, _ = await setup(sessions)

    async def observe():
        return await verify_submission(
            sessions, sid, "operator", observer=fake_observer
        )

    first, second = await asyncio.gather(observe(), observe())
    assert first == second
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM revision_observations")) == 1
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM audit_events WHERE event_type='revision.metadata_observed'"
                )
            )
            == 1
        )
    for sql in [
        "UPDATE repositories SET github_repository_id=43",
        "UPDATE repositories SET canonical_url='https://github.com/other/repo'",
        "DELETE FROM revision_observations",
    ]:
        with pytest.raises(DBAPIError, match="immutable"), engine.begin() as conn:
            conn.execute(text(sql))
    with (
        pytest.raises(DBAPIError, match="populated downgrade refused"),
        engine.begin() as conn,
    ):
        config.attributes["connection"] = conn
        command.downgrade(config, "b153a7c94da6")


@pytest.mark.parametrize(
    "policy,pin", [("evil-policy", True), ("public-metadata-v1", False)]
)
@pytest.mark.asyncio
async def test_untrusted_policy_or_unpinned_repository_denied_before_network(
    registry_database, policy, pin
):
    _, sessions, _ = registry_database
    sid, _ = await setup(sessions, policy, pin)

    async def forbidden(data):
        pytest.fail("Network must not be reached")

    with pytest.raises(VerificationConflict):
        await verify_submission(sessions, sid, "operator", observer=forbidden)


@pytest.mark.asyncio
async def test_disable_during_lookup_prevents_recording(registry_database):
    engine, sessions, _ = registry_database
    sid, rid = await setup(sessions)

    async def disabling(data):
        # Succeeds independently: no repository row lock spans the provider call.
        async with sessions() as session, session.begin():
            await set_repository_enabled(session, rid, False, "operator")
        return await fake_observer(data)

    with pytest.raises(VerificationConflict, match="disabled"):
        await asyncio.wait_for(
            verify_submission(sessions, sid, "operator", observer=disabling), 10
        )
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM revision_observations")) == 0


@pytest.mark.parametrize("change", ["wrong_provider", "stale", "wrong_digest"])
@pytest.mark.asyncio
async def test_mismatched_or_stale_observation_rejected(registry_database, change):
    _, sessions, _ = registry_database
    sid, _ = await setup(sessions)

    async def wrong(data):
        value = await fake_observer(data)
        return replace(
            value,
            **{
                "wrong_provider": {"github_repository_id": 43},
                "stale": {"observed_at": datetime.now(UTC) - timedelta(minutes=2)},
                "wrong_digest": {"input_digest": "0" * 64},
            }[change],
        )

    with pytest.raises(VerificationConflict):
        await verify_submission(sessions, sid, "operator", observer=wrong)


@pytest.mark.asyncio
async def test_observation_audit_rollback(registry_database, monkeypatch):
    engine, sessions, _ = registry_database
    sid, _ = await setup(sessions)

    async def fail(*args, **kwargs):
        raise RuntimeError("audit failed")

    monkeypatch.setattr("adwe.services.revision_verification.record_audit_event", fail)
    with pytest.raises(RuntimeError):
        await verify_submission(sessions, sid, "operator", observer=fake_observer)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM revision_observations")) == 0


def test_authenticated_intake_status_and_pin_api(registry_database, operator_headers):
    _, sessions, _ = registry_database

    async def override():
        async with sessions() as session:
            yield session

    app.dependency_overrides[repository_session] = override
    try:
        with TestClient(app, headers=operator_headers) as client:
            repo = client.post(
                "/v1/repositories",
                json={"repository_url": "https://github.com/example/repo"},
            ).json()
            path = f"/v1/repositories/{repo['id']}/identity"
            assert (
                client.post(path, json={"github_repository_id": True}).status_code
                == 422
            )
            assert (
                client.post(path, json={"github_repository_id": 42}).status_code == 200
            )
            assert (
                client.post(path, json={"github_repository_id": 42}).status_code == 200
            )
            assert (
                client.post(path, json={"github_repository_id": 43}).status_code == 409
            )
            data = {
                "repository_id": repo["id"],
                "repository_url": repo["canonical_url"],
                "base_commit_sha": "a" * 40,
                "policy_version": "public-metadata-v1",
                "task": {"objective": "Fix", "acceptance_criteria": ["Pass"]},
            }
            assert client.post("/v1/submissions", json=data).status_code == 422
            first = client.post(
                "/v1/submissions", json=data, headers={"Idempotency-Key": "one"}
            )
            assert first.status_code == 201
            assert first.json()["execution_admitted"] is False
            assert (
                client.post(
                    "/v1/submissions", json=data, headers={"Idempotency-Key": "one"}
                ).status_code
                == 200
            )
            data["base_commit_sha"] = "b" * 40
            assert (
                client.post(
                    "/v1/submissions", json=data, headers={"Idempotency-Key": "one"}
                ).status_code
                == 409
            )
            sid = first.json()["id"]
            assert client.get(f"/v1/submissions/{sid}").status_code == 200
            status = client.get(f"/v1/submissions/{sid}/status").json()
            assert status["delivery"]["status"] == "pending"
            assert status["observation"] is None
            assert client.get("/v1/submissions?limit=101").status_code == 422
            assert len(client.get("/v1/submissions?limit=1").json()) == 1
    finally:
        app.dependency_overrides.pop(repository_session, None)
