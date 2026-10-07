"""Real PostgreSQL fixtures. Missing infrastructure is a failure, never a silent skip."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


@pytest.fixture
def registry_database():
    url = make_url(
        os.environ.get(
            "ADWE_TEST_DATABASE_URL",
            "postgresql+psycopg://adwe:adwe@127.0.0.1:5432/adwe",
        )
    )
    if url.get_backend_name() != "postgresql":
        pytest.fail("Registry integration tests require real PostgreSQL")
    schema = "adwe_test_" + uuid4().hex
    admin = create_engine(url.set(drivername="postgresql+psycopg"), poolclass=NullPool)
    with admin.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    sync_engine = create_engine(
        url.set(drivername="postgresql+psycopg"),
        poolclass=NullPool,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    async_engine = create_async_engine(
        url.set(drivername="postgresql+asyncpg"),
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    config = Config("alembic.ini")
    try:
        with sync_engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
        yield (
            sync_engine,
            async_sessionmaker(async_engine, expire_on_commit=False),
            config,
        )
    finally:
        sync_engine.dispose()
        # Only drop this fixture's newly generated schema, never public/shared tables.
        with admin.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()
