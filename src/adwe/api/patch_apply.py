from fastapi import APIRouter, Depends, HTTPException

from adwe.api.execution_policy import require_live_operations
from adwe.models.patch_apply_schema import PatchApplyRequest, PatchApplyResponse
from adwe.services.errors import ADWEError
from adwe.services.patch_workflow import apply_patch_workflow

router = APIRouter(prefix="/v1/patch-workflows", tags=["patch-workflows"])


@router.post(
    "/apply",
    response_model=PatchApplyResponse,
    dependencies=[Depends(require_live_operations)],
)
async def apply_patch(payload: PatchApplyRequest):
    try:
        return apply_patch_workflow(
            repository_url=payload.repository_url,
            branch_name=payload.branch_name,
            diff=payload.diff,
            commit_message=payload.commit_message,
            test_command=payload.test_command,
            dry_run=payload.dry_run,
            push=payload.push,
            open_pr=payload.open_pr,
            pr_title=payload.pr_title,
            pr_body=payload.pr_body,
        )
    except ADWEError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
