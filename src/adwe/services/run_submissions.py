"""Atomically record unverified inputs and audit; never enqueue a workload."""

import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from adwe.domain.run_input import RunInput
from adwe.models.repository import Repository
from adwe.models.run_submission import RunSubmission
from adwe.services.audit import record_audit_event


class SubmissionConflict(ValueError):
    pass


async def record_run_submission(
    session: AsyncSession, serialized_input: dict, actor_id: str, request_key: str
) -> tuple[RunSubmission, bool]:
    """Caller owns transaction and supplies authenticated actor, never task content.

    Retries require an enabled repository too. Policy/revision values are recorded
    requests only; future admission must independently verify and authorize them.
    """
    value = RunInput.model_validate(serialized_input)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", actor_id):
        raise ValueError("Invalid actor ID")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", request_key):
        raise ValueError("Invalid request key")
    repository = (
        await session.execute(
            select(Repository)
            .where(Repository.id == value.repository_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if repository is None or not repository.enabled:
        raise SubmissionConflict("Repository is missing or disabled")
    if repository.canonical_url != value.repository_url:
        raise SubmissionConflict("Repository identity does not match registration")
    canonical = value.canonical_bytes().decode("ascii")
    row = (
        await session.execute(
            insert(RunSubmission)
            .values(
                id=str(uuid4()),
                repository_id=repository.id,
                actor_id=actor_id,
                request_key=request_key,
                canonical_input=canonical,
                input_digest=value.digest(),
            )
            .on_conflict_do_nothing(constraint="uq_run_submission_request")
            .returning(RunSubmission)
        )
    ).scalar_one_or_none()
    if row is None:
        row = (
            await session.execute(
                select(RunSubmission).where(
                    RunSubmission.actor_id == actor_id,
                    RunSubmission.request_key == request_key,
                )
            )
        ).scalar_one()
        if row.canonical_input != canonical:
            raise SubmissionConflict("Request key was already used for different input")
        return row, False
    await record_audit_event(
        session,
        "run_input.recorded",
        payload={
            "actor_id": actor_id,
            "submission_id": row.id,
            "repository_id": repository.id,
            "input_digest": row.input_digest,
            "execution_admitted": False,
        },
    )
    await session.flush()
    return row, True
