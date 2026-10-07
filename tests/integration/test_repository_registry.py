import asyncio
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from adwe.api.app import app
from adwe.api.repositories import repository_session
from adwe.models.audit_event import AuditEvent
from adwe.models.repository import Repository
from adwe.services.repositories import register_repository, set_repository_enabled


def test_repository_api_roundtrip_and_containment(registry_database, operator_headers):
    engine, sessions, _ = registry_database

    async def session_override():
        async with sessions() as session:
            yield session

    app.dependency_overrides[repository_session] = session_override
    try:
        with TestClient(app, headers=operator_headers) as client:
            created = client.post(
                "/v1/repositories",
                json={"repository_url": "https://github.com/Owner/Repo.git"},
            )
            assert created.status_code == 201
            row = created.json()
            assert row["registered_by"] == "test-operator"
            assert row["canonical_url"] == "https://github.com/owner/repo"
            assert row["enabled"] is True
            repeated = client.post(
                "/v1/repositories",
                json={"repository_url": "https://github.com/owner/repo/"},
            )
            assert repeated.status_code == 200
            assert repeated.json()["id"] == row["id"]
            path = f"/v1/repositories/{row['id']}"
            assert client.get(path).json() == row
            assert (
                client.patch(path, json={"enabled": False}).json()["enabled"] is False
            )
            assert client.patch(path, json={"enabled": False}).status_code == 200
            repeated = client.post(
                "/v1/repositories", json={"repository_url": row["canonical_url"]}
            )
            assert repeated.json()["enabled"] is False
            assert client.get(f"/v1/repositories/{uuid4()}").status_code == 404
            assert (
                client.patch(
                    f"/v1/repositories/{uuid4()}", json={"enabled": True}
                ).status_code
                == 404
            )
            assert client.get("/v1/repositories?limit=101").status_code == 422
            assert client.get("/v1/repositories?offset=-1").status_code == 422
            assert (
                client.post(
                    "/v1/workflows", json={"repository_url": row["canonical_url"]}
                ).status_code
                == 503
            )
            # Two rows exercise bounded list/pagination against the actual database.
            client.post(
                "/v1/repositories",
                json={"repository_url": "https://github.com/owner/other"},
            )
            first = client.get("/v1/repositories?limit=1").json()
            assert len(first["items"]) == 1
            assert first["next_offset"] == 1
            second = client.get("/v1/repositories?limit=1&offset=1").json()
            assert second["items"][0]["id"] != first["items"][0]["id"]
            assert second["next_offset"] is None
        with engine.connect() as conn:
            events = conn.execute(
                select(AuditEvent.event_type, AuditEvent.payload)
            ).all()
            assert [event[0] for event in events].count("repository.registered") == 2
            assert [event[0] for event in events].count("repository.disabled") == 1
            assert all(event[1]["actor_id"] == "test-operator" for event in events)
    finally:
        app.dependency_overrides.pop(repository_session, None)


@pytest.mark.asyncio
async def test_concurrent_registration_creates_one_identity_and_event(
    registry_database,
):
    _, sessions, _ = registry_database

    async def register(url):
        async with sessions() as session, session.begin():
            repository, created = await register_repository(session, url, "operator")
            return repository.id, created

    results = await asyncio.gather(
        register("https://github.com/Owner/Repo"),
        register("https://github.com/owner/repo.git/"),
    )
    assert results[0][0] == results[1][0]
    assert sum(created for _, created in results) == 1
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Repository)) == 1
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 1


@pytest.mark.asyncio
async def test_registration_and_audit_rollback_together(registry_database):
    _, sessions, _ = registry_database
    with pytest.raises(RuntimeError, match="injected"):
        async with sessions() as session, session.begin():
            await register_repository(session, "https://github.com/a/b", "operator")
            await session.flush()
            raise RuntimeError("injected failure before commit")
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Repository)) == 0
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 0


@pytest.mark.asyncio
async def test_concurrent_disable_records_single_transition(registry_database):
    _, sessions, _ = registry_database
    async with sessions() as session, session.begin():
        repository, _ = await register_repository(
            session, "https://github.com/a/b", "operator"
        )
        repository_id = repository.id

    async def disable():
        async with sessions() as session, session.begin():
            await set_repository_enabled(session, repository_id, False, "operator")

    await asyncio.gather(disable(), disable())
    async with sessions() as session:
        assert (await session.get(Repository, repository_id)).enabled is False
        count = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type == "repository.disabled")
        )
        assert count == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/a/b",
        "https://github.com/Owner/Repo",
        "https://github.com/a/..",
        "https://github.com/a/b.git",
    ],
)
def test_database_rejects_noncanonical_identity(registry_database, url):
    engine, _, _ = registry_database
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            Repository.__table__.insert().values(
                id=str(uuid4()), canonical_url=url, registered_by="operator"
            )
        )


def test_populated_downgrade_refuses_data_loss_then_empty_roundtrip(registry_database):
    engine, _, config = registry_database
    with engine.begin() as conn:
        conn.execute(
            Repository.__table__.insert().values(
                id=str(uuid4()),
                canonical_url="https://github.com/a/b",
                registered_by="operator",
            )
        )
    with (
        pytest.raises(DBAPIError, match="Export and explicitly remove"),
        engine.begin() as conn,
    ):
        config.attributes["connection"] = conn
        command.downgrade(config, "b4741e3f30d9")
    with engine.begin() as conn:
        assert (
            conn.scalar(text("SELECT version_num FROM alembic_version"))
            == "7b91e2c40a16"
        )
        assert conn.scalar(select(func.count()).select_from(Repository)) == 1
        conn.execute(Repository.__table__.delete())
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "b4741e3f30d9")
        assert conn.scalar(text("SELECT to_regclass('repositories')")) is None
        assert conn.scalar(text("SELECT to_regclass('workflows')")) is not None
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
        assert conn.scalar(select(func.count()).select_from(Repository)) == 0
