"""Authenticated metadata intake; no endpoint admits execution."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select, text

from adwe.api.repositories import Actor, Session
from adwe.db.session import AsyncSessionLocal
from adwe.domain.run_input import RunInput
from adwe.models.run_submission import RunSubmission
from adwe.services.github_revision import RevisionLookupError
from adwe.services.revision_verification import VerificationConflict, verify_submission
from adwe.services.run_submissions import SubmissionConflict, record_run_submission

router = APIRouter(prefix="/v1/submissions", tags=["submissions"])


class SubmissionRead(BaseModel):
    id: str
    actor_id: str
    input_digest: str
    created_at: datetime
    input: RunInput
    execution_admitted: bool = False


def render(row):
    return SubmissionRead(
        id=row.id,
        actor_id=row.actor_id,
        input_digest=row.input_digest,
        created_at=row.created_at,
        input=RunInput.model_validate_json(row.canonical_input),
    )


@router.post("", response_model=SubmissionRead, status_code=201)
async def submit_input(
    payload: RunInput,
    response: Response,
    session: Session,
    actor: Actor,
    request_key: Annotated[
        str,
        Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"),
    ],
):
    try:
        async with session.begin():
            row, created = await record_run_submission(
                session, payload.model_dump(mode="json"), actor.actor_id, request_key
            )
            result = render(row)
    except SubmissionConflict as exc:
        raise HTTPException(
            409, detail={"code": "submission_conflict", "message": str(exc)}
        ) from None
    response.status_code = 201 if created else 200
    return result


@router.get("", response_model=list[SubmissionRead])
async def list_submissions(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
):
    rows = (
        await session.scalars(
            select(RunSubmission)
            .order_by(RunSubmission.created_at, RunSubmission.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [render(row) for row in rows]


@router.get("/{submission_id}", response_model=SubmissionRead)
async def get_submission(submission_id: UUID, session: Session):
    row = await session.get(RunSubmission, str(submission_id))
    if row is None:
        raise HTTPException(404, detail={"code": "submission_not_found"})
    return render(row)


@router.get("/{submission_id}/status")
async def submission_status(submission_id: UUID, session: Session):
    sid = str(submission_id)
    if await session.get(RunSubmission, sid) is None:
        raise HTTPException(404, detail={"code": "submission_not_found"})
    delivery = (
        (
            await session.execute(
                text(
                    "SELECT status, attempts FROM submission_outbox WHERE submission_id=:id"
                ),
                {"id": sid},
            )
        )
        .mappings()
        .one()
    )
    received = await session.scalar(
        text("SELECT EXISTS(SELECT 1 FROM verification_inbox WHERE submission_id=:id)"),
        {"id": sid},
    )
    observed = (
        (
            await session.execute(
                text(
                    "SELECT commit_sha,tree_sha,observed_at,policy_version FROM revision_observations WHERE submission_id=:id"
                ),
                {"id": sid},
            )
        )
        .mappings()
        .one_or_none()
    )
    return {
        "submission_id": sid,
        "delivery": dict(delivery),
        "received": received,
        "observation": dict(observed) if observed else None,
        "execution_admitted": False,
    }


@router.post("/{submission_id}/observe")
async def observe_submission(submission_id: UUID, actor: Actor):
    try:
        result = await verify_submission(
            AsyncSessionLocal, str(submission_id), actor.actor_id
        )
    except VerificationConflict as exc:
        raise HTTPException(
            409, detail={"code": "verification_conflict", "message": str(exc)}
        ) from None
    except RevisionLookupError as exc:
        raise HTTPException(
            503 if exc.retryable else 422,
            detail={"code": exc.code, "retryable": exc.retryable},
        ) from None
    return {"observation": result, "execution_admitted": False}
