from fastapi import APIRouter, Depends, HTTPException

from adwe.api.execution_policy import require_live_operations
from adwe.db.session import AsyncSessionLocal
from adwe.models.pull_request_schema import PullRequestCreate, PullRequestRead
from adwe.models.workflow import Workflow
from adwe.services.github_pr import create_pull_request
from adwe.services.pull_request_records import record_pull_request

router = APIRouter(prefix="/v1/pull-requests", tags=["pull-requests"])


@router.post(
    "",
    response_model=PullRequestRead,
    dependencies=[Depends(require_live_operations)],
)
async def open_pull_request(payload: PullRequestCreate):
    result = create_pull_request(
        repository_url=payload.repository_url,
        branch_name=payload.branch_name,
        title=payload.title,
        body=payload.body,
    )

    async with AsyncSessionLocal() as session:
        workflow = None

        if payload.workflow_id:
            workflow = await session.get(Workflow, payload.workflow_id)

            if workflow is None:
                raise HTTPException(status_code=404, detail="Workflow not found")

        record = await record_pull_request(
            session=session,
            repository_url=result["repository_url"],
            branch_name=result["branch_name"],
            title=result["title"],
            url=result.get("url"),
            status=result["status"],
            workflow_id=payload.workflow_id,
        )

        await session.flush()

        if workflow is not None:
            workflow.pull_request_id = record.id

        await session.commit()

    return result
