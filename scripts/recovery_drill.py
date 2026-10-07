"""Disposable PostgreSQL backup/restore drill; never restores over an existing DB.

Run against a local/CI PostgreSQL container with CREATEDB authority. The container
supplies matching pg_dump/pg_restore binaries. No production credentials required.
"""

import asyncio
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from adwe.domain.run_input import RunInput
from adwe.services.github_revision import RevisionObservation
from adwe.services.repositories import register_repository
from adwe.services.revision_verification import (
    pin_repository_identity,
    verify_submission,
)
from adwe.services.run_submissions import record_run_submission
from adwe.services.submission_outbox import (
    StaleDeliveryLease,
    claim_verification_intent,
    finish_verification_delivery,
)
from adwe.services.verification_inbox import receive_verification_request
from adwe.workers.verification_dispatcher import DatabaseInboxReceiver, dispatch_one


async def seed(url):
    engine = create_async_engine(url.set(drivername="postgresql+asyncpg"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session, session.begin():
            repo, _ = await register_repository(
                session, "https://github.com/example/recovery-fixture", "operator"
            )
            await pin_repository_identity(session, repo.id, 42, "operator")
            data = RunInput(
                repository_id=repo.id,
                repository_url=repo.canonical_url,
                base_commit_sha="a" * 40,
                policy_version="public-metadata-v1",
                task={
                    "objective": "Recovery fixture",
                    "acceptance_criteria": ["Restore"],
                },
            ).model_dump(mode="json")
            first, _ = await record_run_submission(
                session, data, "operator", "delivered"
            )
        assert (
            await dispatch_one(sessions, DatabaseInboxReceiver(sessions)) == "delivered"
        )

        async def fixture_observer(value):
            run = RunInput.model_validate(value)
            return RevisionObservation(
                run.digest(),
                run.repository_id,
                run.repository_url,
                42,
                run.base_commit_sha,
                "b" * 40,
                datetime.now(UTC),
            )

        await verify_submission(
            sessions, first.id, "operator", observer=fixture_observer
        )
        async with sessions() as session, session.begin():
            await record_run_submission(session, data, "operator", "uncertain")
        async with sessions() as session, session.begin():
            lease = await claim_verification_intent(session)
            assert lease is not None
        # Simulate crash after receiver commit, before sender acknowledgement.
        async with sessions() as session, session.begin():
            await receive_verification_request(session, lease.submission_id)
        async with sessions() as session, session.begin():
            await record_run_submission(session, data, "operator", "pending")
        return lease
    finally:
        await engine.dispose()


def manifest(engine):
    """Compare all application data, including audit payloads and migration head."""
    with engine.connect() as conn:
        tables = (
            conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
                )
            )
            .scalars()
            .all()
        )
        return {
            table: sorted(
                conn.exec_driver_sql(
                    'SELECT row_to_json(t)::text FROM "'
                    + table.replace('"', '""')
                    + '" t'
                )
                .scalars()
                .all()
            )
            for table in tables
        }


async def recover(url, old_lease):
    engine = create_async_engine(url.set(drivername="postgresql+asyncpg"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        # Only the disposable fixture lease is aged; production recovery waits
        # for database-clock expiry and must not reset attempts or fencing tokens.
        async with sessions() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE submission_outbox SET lease_expires_at=clock_timestamp()-interval '1 second' "
                    "WHERE submission_id=:id"
                ),
                {"id": old_lease.submission_id},
            )
        for _ in range(2):
            assert (
                await dispatch_one(sessions, DatabaseInboxReceiver(sessions))
                == "delivered"
            )
        assert await dispatch_one(sessions, DatabaseInboxReceiver(sessions)) == "idle"
        try:
            async with sessions() as session, session.begin():
                await finish_verification_delivery(session, old_lease, delivered=True)
        except StaleDeliveryLease:
            pass
        else:
            raise AssertionError("Restored stale owner was accepted")
        async with sessions() as session:
            assert (
                await session.scalar(text("SELECT count(*) FROM verification_inbox"))
                == 3
            )
            assert (
                await session.scalar(text("SELECT count(*) FROM revision_observations"))
                == 1
            )
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM submission_outbox WHERE status='delivered'"
                    )
                )
                == 3
            )
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM audit_events WHERE event_type='verification_request.received'"
                    )
                )
                == 3
            )
    finally:
        await engine.dispose()


def main():
    container = os.environ["ADWE_DRILL_CONTAINER"]
    url = make_url(
        os.environ.get(
            "ADWE_TEST_DATABASE_URL",
            "postgresql+psycopg://adwe:adwe@127.0.0.1:5432/adwe",
        )
    ).set(drivername="postgresql+psycopg")
    if url.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL required")
    admin = psycopg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False),
        autocommit=True,
    )
    created = []
    engines = []
    try:
        names = ["adwe_drill_" + uuid4().hex for _ in range(2)]
        for name in names:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            created.append(name)
            engines.append(create_engine(url.set(database=name)))
        config = Config("alembic.ini")
        with engines[0].begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        lease = asyncio.run(seed(url.set(database=names[0])))
        expected = manifest(engines[0])
        with tempfile.TemporaryFile() as backup:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "pg_dump",
                    "-U",
                    url.username,
                    "-d",
                    names[0],
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                ],
                stdout=backup,
                check=True,
                timeout=60,
            )
            backup.seek(0)
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    container,
                    "pg_restore",
                    "-U",
                    url.username,
                    "-d",
                    names[1],
                    "--exit-on-error",
                    "--no-owner",
                    "--no-privileges",
                ],
                stdin=backup,
                check=True,
                timeout=60,
            )
        assert manifest(engines[1]) == expected, "Restored data differs"
        # Restoring data alone is insufficient: immutable evidence guards must survive.
        for table in ("run_submissions", "verification_inbox", "revision_observations"):
            try:
                with engines[1].begin() as conn:
                    conn.exec_driver_sql("DELETE FROM " + table)
                    raise AssertionError("Restored immutable evidence was deletable")
            except DBAPIError as error:
                if "immutable" not in str(error):
                    raise
        asyncio.run(recover(url.set(database=names[1]), lease))
        print(
            "Recovery drill passed: exact restore, immutable guards, deduplicated replay, stale-owner rejection"
        )
    finally:
        for engine in engines:
            engine.dispose()
        for name in created:
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
        admin.close()


if __name__ == "__main__":
    main()
