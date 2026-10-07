from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from adwe.domain.patch_decision import (
    PatchDecisionConflict,
    diff_digest,
    validate_decision,
)
from adwe.models.patch import Patch
from adwe.models.patch_status import PatchStatus
from adwe.models.workflow import Workflow
from adwe.services.audit import record_audit_event


async def decide_patch(
    session: AsyncSession,
    workflow_id: str,
    patch_id: str,
    target: PatchStatus,
    expected_diff_sha256: str,
    actor_id: str,
) -> Patch | None:
    patch = (
        await session.execute(
            select(Patch)
            .where(Patch.id == patch_id, Patch.workflow_id == workflow_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if patch is None:
        return None
    # Legacy patch rows have no FK. Orphaned records cannot receive new approvals.
    workflow = await session.get(Workflow, workflow_id)
    if workflow is None:
        raise PatchDecisionConflict(
            "orphaned_patch", "Patch has no workflow; reconciliation is required"
        )
    actual_digest = diff_digest(patch.diff)
    if expected_diff_sha256 != actual_digest:
        raise PatchDecisionConflict(
            "patch_changed", "Patch content differs from the reviewed digest"
        )
    changed = validate_decision(patch.status, target)
    if not changed:
        if (
            target == PatchStatus.APPROVED
            and patch.approved_diff_sha256 != actual_digest
        ):
            raise PatchDecisionConflict(
                "stale_approval", "Stored approval does not match current content"
            )
        return patch
    previous_status = patch.status
    patch.status = target
    if target == PatchStatus.APPROVED:
        patch.approved_by = actor_id
        patch.approved_at = datetime.now(UTC)
        patch.approved_diff_sha256 = actual_digest
    else:
        patch.approved_by = None
        patch.approved_at = None
        patch.approved_diff_sha256 = None
    await record_audit_event(
        session,
        "patch.approved" if target == PatchStatus.APPROVED else "patch.rejected",
        workflow_id=workflow_id,
        payload={
            "patch_id": patch.id,
            "actor_id": actor_id,
            "diff_sha256": actual_digest,
            "previous_status": previous_status,
            "status": target.value,
            "repository_url": workflow.repository_url,
        },
    )
    await session.flush()
    return patch
