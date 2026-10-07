import logging

from arq import create_pool
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from adwe.api.execution_policy import require_live_operations
from adwe.db.session import AsyncSessionLocal
from adwe.models.pull_request_record_schema import PullRequestRecordRead
from adwe.models.workflow import Workflow
from adwe.models.workflow_artifacts_schema import WorkflowArtifactsRead
from adwe.models.workflow_schema import WorkflowCreate, WorkflowRead
from adwe.models.workflow_status import WorkflowStatus
from adwe.models.workflow_summary_schema import WorkflowSummaryRead
from adwe.services.audit import record_audit_event
from adwe.workers.queue import get_redis_settings

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])
logger = logging.getLogger(__name__)


async def enqueue_workflow_run(workflow_id: str) -> str:
    redis = await create_pool(get_redis_settings())

    job = await redis.enqueue_job(
        "run_workflow",
        workflow_id,
    )

    return job.job_id


@router.post(
    "",
    response_model=WorkflowRead,
    dependencies=[Depends(require_live_operations)],
)
async def create_workflow(payload: WorkflowCreate):
    async with AsyncSessionLocal() as session:
        workflow = Workflow(
            repository_url=payload.repository_url,
            status=WorkflowStatus.PENDING,
        )

        session.add(workflow)
        await session.flush()

        await record_audit_event(
            session=session,
            workflow_id=workflow.id,
            event_type="workflow.created",
            payload={"repository_url": payload.repository_url},
        )

        job_id = await enqueue_workflow_run(workflow.id)
        workflow.queue_job_id = job_id

        await session.commit()
        await session.refresh(workflow)

        return workflow


@router.get("", response_model=list[WorkflowRead])
async def list_workflows():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Workflow).order_by(Workflow.created_at.desc())
        )
        return result.scalars().all()


@router.get("/{workflow_id}", response_model=WorkflowRead)
async def get_workflow(workflow_id: str):
    async with AsyncSessionLocal() as session:
        workflow = await session.get(Workflow, workflow_id)

        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        return workflow


@router.post(
    "/{workflow_id}/run",
    response_model=WorkflowRead,
    dependencies=[Depends(require_live_operations)],
)
async def run_workflow_endpoint(workflow_id: str):
    async with AsyncSessionLocal() as session:
        workflow = await session.get(Workflow, workflow_id)

        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        workflow.status = WorkflowStatus.PENDING
        job_id = await enqueue_workflow_run(workflow_id)
        workflow.queue_job_id = job_id

        await session.commit()
        await session.refresh(workflow)

        return workflow


@router.get("/{workflow_id}/pull-request", response_model=PullRequestRecordRead)
async def get_workflow_pull_request(workflow_id: str):
    async with AsyncSessionLocal() as session:
        workflow = await session.get(Workflow, workflow_id)

        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        if workflow.pull_request_id is None:
            raise HTTPException(status_code=404, detail="Pull request not found")

        from adwe.models.pull_request import PullRequest

        pull_request = await session.get(PullRequest, workflow.pull_request_id)

        if pull_request is None:
            raise HTTPException(status_code=404, detail="Pull request not found")

        return pull_request


@router.get("/{workflow_id}/summary", response_model=WorkflowSummaryRead)
async def get_workflow_summary(workflow_id: str):
    async with AsyncSessionLocal() as session:
        workflow = await session.get(Workflow, workflow_id)

        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        analysis = workflow.repository_analysis or {}
        plan = workflow.implementation_plan or {}

        return {
            "id": workflow.id,
            "repository_url": workflow.repository_url,
            "status": workflow.status,
            "queue_job_id": workflow.queue_job_id,
            "pull_request_id": workflow.pull_request_id,
            "retry_count": workflow.retry_count,
            "last_error": workflow.last_error,
            "started_at": workflow.started_at,
            "completed_at": workflow.completed_at,
            "duration_seconds": workflow.duration_seconds,
            "file_count": analysis.get("file_count"),
            "detected_languages": analysis.get("languages"),
            "recommended_next_steps": plan.get("recommended_next_steps"),
            "planner": plan.get("planner"),
            "planner_fallback_reason": plan.get("planner_fallback_reason"),
        }


@router.get("/{workflow_id}/artifacts", response_model=WorkflowArtifactsRead)
async def get_workflow_artifacts(workflow_id: str):
    async with AsyncSessionLocal() as session:
        workflow = await session.get(Workflow, workflow_id)

        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        return {
            "workflow_id": workflow.id,
            "repository_analysis": workflow.repository_analysis,
            "implementation_plan": workflow.implementation_plan,
            "code_modification": workflow.code_modification,
            "pull_request_id": workflow.pull_request_id,
            "queue_job_id": workflow.queue_job_id,
        }
