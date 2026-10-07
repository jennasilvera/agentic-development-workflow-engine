"""Independent metadata policy and transactional observation recording."""

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from adwe.domain.run_input import RunInput
from adwe.models.repository import Repository
from adwe.models.run_submission import RunSubmission
from adwe.services.audit import record_audit_event
from adwe.services.github_revision import observe_public_revision

POLICY_VERSION = "public-metadata-v1"


class VerificationConflict(ValueError):
    pass


async def pin_repository_identity(session, repository_id, github_id, actor_id):
    if type(github_id) is not int or not 0 < github_id <= 2**63 - 1:
        raise VerificationConflict("Invalid provider identity")
    repo = (
        await session.execute(
            select(Repository)
            .where(Repository.id == repository_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if repo is None or not repo.enabled:
        raise VerificationConflict("Repository is missing or disabled")
    if repo.github_repository_id is not None:
        if repo.github_repository_id != github_id:
            raise VerificationConflict(
                "Repository is already pinned to a different identity"
            )
        return repo
    repo.github_repository_id = github_id
    await record_audit_event(
        session,
        "repository.identity_pinned",
        payload={
            "repository_id": repo.id,
            "github_repository_id": github_id,
            "actor_id": actor_id,
        },
    )
    await session.flush()
    return repo


async def _load(session, submission_id, *, lock=False):
    submission = await session.get(RunSubmission, submission_id)
    if submission is None:
        raise VerificationConflict("Unknown submission")
    if not await session.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM verification_inbox WHERE submission_id=:id)"
        ),
        {"id": submission_id},
    ):
        raise VerificationConflict("Submission has not reached the durable inbox")
    query = select(Repository).where(Repository.id == submission.repository_id)
    if lock:
        query = query.with_for_update()
    repo = (
        await session.execute(query.execution_options(populate_existing=True))
    ).scalar_one()
    value = RunInput.model_validate_json(submission.canonical_input)
    if (
        not repo.enabled
        or repo.github_repository_id is None
        or repo.canonical_url != value.repository_url
        or repo.id != value.repository_id
    ):
        raise VerificationConflict("Repository is disabled, unpinned or mismatched")
    if value.policy_version != POLICY_VERSION:
        raise VerificationConflict("Requested policy is not enabled")
    if (
        value.digest() != submission.input_digest
        or value.canonical_bytes().decode("ascii") != submission.canonical_input
    ):
        raise VerificationConflict("Stored input integrity mismatch")
    return value, repo.github_repository_id


async def verify_submission(
    sessions, submission_id, actor_id, *, observer=observe_public_revision
):
    # No transaction or row lock is held across the provider request.
    async with sessions() as session:
        value, github_id = await _load(session, submission_id)
        existing = (
            (
                await session.execute(
                    text("SELECT * FROM revision_observations WHERE submission_id=:id"),
                    {"id": submission_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            if datetime.now(UTC) - existing["observed_at"] > timedelta(minutes=5):
                raise VerificationConflict(
                    "Observation expired; create a new submission"
                )
            return dict(existing)
    observation = await observer(value.model_dump(mode="json"))
    now = datetime.now(UTC)
    if (
        observation.input_digest != value.digest()
        or observation.repository_id != value.repository_id
        or observation.canonical_url != value.repository_url
        or observation.github_repository_id != github_id
        or observation.commit_sha != value.base_commit_sha
        or observation.provider != "github-public-rest-v1"
        or not re.fullmatch(r"[0-9a-f]{40}", observation.tree_sha)
        or observation.observed_at.tzinfo is None
        or not now - timedelta(seconds=60) <= observation.observed_at <= now
    ):
        raise VerificationConflict(
            "Observation is stale or does not match authorized input"
        )
    async with sessions() as session, session.begin():
        current, current_id = await _load(session, submission_id, lock=True)
        if datetime.now(UTC) - observation.observed_at > timedelta(seconds=60):
            raise VerificationConflict("Observation expired before recording")
        if current != value or current_id != github_id:
            raise VerificationConflict("Repository or input changed during observation")
        params = {
            "id": submission_id,
            "digest": observation.input_digest,
            "github_id": github_id,
            "commit": observation.commit_sha,
            "tree": observation.tree_sha,
            "policy": POLICY_VERSION,
            "observed": observation.observed_at,
            "actor": actor_id,
        }
        inserted = await session.scalar(
            text("""INSERT INTO revision_observations
            (submission_id,input_digest,github_repository_id,commit_sha,tree_sha,policy_version,observed_at,recorded_by)
            VALUES (:id,:digest,:github_id,:commit,:tree,:policy,:observed,:actor)
            ON CONFLICT (submission_id) DO NOTHING RETURNING submission_id"""),
            params,
        )
        result = dict(
            (
                await session.execute(
                    text("SELECT * FROM revision_observations WHERE submission_id=:id"),
                    {"id": submission_id},
                )
            )
            .mappings()
            .one()
        )
        if result["tree_sha"] != observation.tree_sha:
            raise VerificationConflict("Conflicting provider observation")
        if inserted:
            await record_audit_event(
                session,
                "revision.metadata_observed",
                payload={
                    "submission_id": submission_id,
                    "input_digest": observation.input_digest,
                    "actor_id": actor_id,
                    "policy_version": POLICY_VERSION,
                    "execution_admitted": False,
                },
            )
            await session.flush()
        return result
