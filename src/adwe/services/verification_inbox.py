"""Durable receipt of an unverified request; never authorizes acquisition/execution."""

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from adwe.domain.run_input import RunInput
from adwe.models.run_submission import RunSubmission
from adwe.services.audit import record_audit_event


async def receive_verification_request(
    session: AsyncSession, submission_id: str
) -> bool:
    """Return True once per submission. Caller commits receipt and audit together.

    The transport carries only a canonical UUID. All input comes from the immutable
    submission, not from a queue-supplied task, actor, policy or repository URL.
    """
    if not isinstance(submission_id, str) or str(UUID(submission_id)) != submission_id:
        raise ValueError("Expected a canonical submission UUID")
    submission = (
        await session.execute(
            select(RunSubmission).where(RunSubmission.id == submission_id)
        )
    ).scalar_one_or_none()
    if submission is None:
        raise ValueError("Unknown submission")
    value = RunInput.model_validate_json(submission.canonical_input)
    if (
        value.digest() != submission.input_digest
        or value.canonical_bytes().decode("ascii") != submission.canonical_input
        or value.repository_id != submission.repository_id
    ):
        raise ValueError("Submission integrity mismatch")
    created = (
        await session.execute(
            text("""INSERT INTO verification_inbox
        (submission_id, input_digest) VALUES (:id, :digest)
        ON CONFLICT (submission_id) DO NOTHING RETURNING submission_id"""),
            {"id": submission_id, "digest": submission.input_digest},
        )
    ).scalar_one_or_none()
    if created is None:
        return False
    await record_audit_event(
        session,
        "verification_request.received",
        payload={
            "submission_id": submission_id,
            "input_digest": submission.input_digest,
            "revision_verified": False,
            "execution_admitted": False,
        },
    )
    await session.flush()
    return True
