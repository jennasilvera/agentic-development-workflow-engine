from arq import create_pool
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from adwe.api.execution_policy import require_live_operations
from adwe.db.session import AsyncSessionLocal
from adwe.models.patch import Patch
from adwe.models.patch_schema import PatchRead
from adwe.models.patch_status import PatchStatus
from adwe.models.patch_summary_schema import PatchSummaryRead
from adwe.services.audit import record_audit_event
from adwe.workers.queue import get_redis_settings

router = APIRouter(prefix="/v1/workflows", tags=["patches"])


async def enqueue_patch_apply(patch_id: str) -> str:
    redis = await create_pool(get_redis_settings())
    job = await redis.enqueue_job("apply_patch_job", patch_id)
    return job.job_id


@router.get("/{workflow_id}/patches", response_model=list[PatchRead])
async def list_workflow_patches(workflow_id: str):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Patch).where(Patch.workflow_id == workflow_id)
        )
        return result.scalars().all()


@router.get("/{workflow_id}/patches/{patch_id}", response_model=PatchRead)
async def get_workflow_patch(workflow_id: str, patch_id: str):
    async with AsyncSessionLocal() as session:
        patch = await session.get(Patch, patch_id)

        if patch is None or patch.workflow_id != workflow_id:
            raise HTTPException(status_code=404, detail="Patch not found")

        return patch


@router.post(
    "/{workflow_id}/patches/{patch_id}/approve",
    response_model=PatchRead,
    dependencies=[Depends(require_live_operations)],
)
async def approve_patch(workflow_id: str, patch_id: str):
    async with AsyncSessionLocal() as session:
        patch = await session.get(Patch, patch_id)

        if patch is None or patch.workflow_id != workflow_id:
            raise HTTPException(status_code=404, detail="Patch not found")

        patch.status = PatchStatus.APPLIED

        await record_audit_event(
            session=session,
            workflow_id=workflow_id,
            event_type="patch.approved",
            payload={"patch_id": patch_id, "file_path": patch.file_path},
        )

        await session.commit()
        await session.refresh(patch)

        return patch


@router.post(
    "/{workflow_id}/patches/{patch_id}/reject",
    response_model=PatchRead,
    dependencies=[Depends(require_live_operations)],
)
async def reject_patch(workflow_id: str, patch_id: str):
    async with AsyncSessionLocal() as session:
        patch = await session.get(Patch, patch_id)

        if patch is None or patch.workflow_id != workflow_id:
            raise HTTPException(status_code=404, detail="Patch not found")

        patch.status = PatchStatus.REJECTED

        await record_audit_event(
            session=session,
            workflow_id=workflow_id,
            event_type="patch.rejected",
            payload={"patch_id": patch_id, "file_path": patch.file_path, "queue_job_id": job_id},
        )

        await session.commit()
        await session.refresh(patch)

        return patch


@router.get("/{workflow_id}/patches-summary", response_model=PatchSummaryRead)
async def get_workflow_patches_summary(workflow_id: str):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Patch).where(Patch.workflow_id == workflow_id)
        )
        patches = result.scalars().all()

        return {
            "workflow_id": workflow_id,
            "total": len(patches),
            "proposed": sum(1 for patch in patches if patch.status == PatchStatus.PROPOSED),
            "applied": sum(1 for patch in patches if patch.status == PatchStatus.APPLIED),
            "rejected": sum(1 for patch in patches if patch.status == PatchStatus.REJECTED),
        }


@router.post(
    "/{workflow_id}/patches/{patch_id}/apply",
    response_model=PatchRead,
    dependencies=[Depends(require_live_operations)],
)
async def apply_approved_patch(
    workflow_id: str,
    patch_id: str,
    push: bool = False,
    open_pr: bool = False,
):
    async with AsyncSessionLocal() as session:
        patch = await session.get(Patch, patch_id)

        if patch is None or patch.workflow_id != workflow_id:
            raise HTTPException(status_code=404, detail="Patch not found")

        if patch.status != PatchStatus.APPLIED:
            raise HTTPException(
                status_code=400,
                detail="Patch must be approved before it can be applied",
            )
        patch.push_requested = push
        patch.open_pr_requested = open_pr
        patch.status = PatchStatus.APPLYING

        job_id = await enqueue_patch_apply(patch_id)

        await record_audit_event(
            session=session,
            workflow_id=workflow_id,
            event_type="patch.apply_requested",
            payload={"patch_id": patch_id, "file_path": patch.file_path, "queue_job_id": job_id},
        )

        await session.commit()
        await session.refresh(patch)

        return patch
