from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

from adwe.core.config import settings
from adwe.db.base import Base
from adwe.models.audit_event import AuditEvent  # noqa: F401
from adwe.models.patch import Patch  # noqa: F401
from adwe.models.pull_request import PullRequest  # noqa: F401
from adwe.models.repository import Repository  # noqa: F401
from adwe.models.run_submission import RunSubmission  # noqa: F401
from adwe.models.workflow import Workflow  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
# The application and migrations use the same database identity. Alembic needs a
# synchronous driver; never interpolate credentials into logs or config strings.
database_url = make_url(settings.database_url).set(drivername="postgresql+psycopg")


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def migrate_connection(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tests and controlled callers may supply an already-scoped transaction.
    connection = config.attributes.get("connection")
    if connection is not None:
        migrate_connection(connection)
        return
    engine = create_engine(database_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            migrate_connection(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
