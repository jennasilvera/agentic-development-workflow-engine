"""Registry mutations share the caller's transaction with their audit evidence."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from adwe.domain.repository import canonical_repository_url
from adwe.models.repository import Repository
from adwe.services.audit import record_audit_event


async def register_repository(
    session: AsyncSession,
    repository_url: str,
    actor_id: str,
) -> tuple[Repository, bool]:
    canonical_url = canonical_repository_url(repository_url)
    statement = (
        insert(Repository)
        .values(id=str(uuid4()), canonical_url=canonical_url, registered_by=actor_id)
        .on_conflict_do_nothing(constraint="uq_repositories_canonical_url")
        .returning(Repository)
    )
    repository = (await session.execute(statement)).scalar_one_or_none()
    created = repository is not None
    if repository is None:
        # Under READ COMMITTED, the next statement observes the winning committed insert.
        # Re-registration never changes ownership or re-enables a disabled repository.
        repository = (
            await session.execute(
                select(Repository).where(Repository.canonical_url == canonical_url)
            )
        ).scalar_one()
    else:
        await record_audit_event(
            session,
            "repository.registered",
            payload={
                "actor_id": actor_id,
                "repository_id": repository.id,
                "canonical_url": canonical_url,
            },
        )
    return repository, created


async def set_repository_enabled(
    session: AsyncSession,
    repository_id: str,
    enabled: bool,
    actor_id: str,
) -> Repository | None:
    repository = (
        await session.execute(
            select(Repository).where(Repository.id == repository_id).with_for_update()
        )
    ).scalar_one_or_none()
    if repository is not None and repository.enabled != enabled:
        repository.enabled = enabled
        await record_audit_event(
            session,
            "repository.enabled" if enabled else "repository.disabled",
            payload={"actor_id": actor_id, "repository_id": repository.id},
        )
    return repository
