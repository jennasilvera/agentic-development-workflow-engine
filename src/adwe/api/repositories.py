from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from adwe.api.auth import Operator, require_operator
from adwe.db.session import AsyncSessionLocal
from adwe.models.repository import Repository
from adwe.models.repository_schema import (
    RepositoryCreate,
    RepositoryPage,
    RepositoryRead,
    RepositoryUpdate,
)
from adwe.services.repositories import register_repository, set_repository_enabled

router = APIRouter(prefix="/v1/repositories", tags=["repositories"])


async def repository_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


Session = Annotated[AsyncSession, Depends(repository_session)]
Actor = Annotated[Operator, Depends(require_operator)]


def missing_repository() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "repository_not_found", "message": "Repository not found"},
    )


@router.post("", response_model=RepositoryRead, status_code=201)
async def create_repository(
    payload: RepositoryCreate, response: Response, session: Session, actor: Actor
) -> RepositoryRead:
    async with session.begin():
        repository, created = await register_repository(
            session, payload.repository_url, actor.actor_id
        )
        result = RepositoryRead.model_validate(repository)
    response.status_code = 201 if created else 200
    return result


@router.get("", response_model=RepositoryPage)
async def list_repositories(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> RepositoryPage:
    rows = (
        (
            await session.execute(
                select(Repository)
                .order_by(Repository.created_at, Repository.id)
                .offset(offset)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    return RepositoryPage(
        items=[RepositoryRead.model_validate(row) for row in rows[:limit]],
        next_offset=offset + limit if len(rows) > limit else None,
    )


@router.get("/{repository_id}", response_model=RepositoryRead)
async def get_repository(repository_id: UUID, session: Session) -> RepositoryRead:
    repository = await session.get(Repository, str(repository_id))
    if repository is None:
        raise missing_repository()
    return RepositoryRead.model_validate(repository)


@router.patch("/{repository_id}", response_model=RepositoryRead)
async def update_repository(
    repository_id: UUID, payload: RepositoryUpdate, session: Session, actor: Actor
) -> RepositoryRead:
    async with session.begin():
        repository = await set_repository_enabled(
            session, str(repository_id), payload.enabled, actor.actor_id
        )
        if repository is None:
            raise missing_repository()
        return RepositoryRead.model_validate(repository)
