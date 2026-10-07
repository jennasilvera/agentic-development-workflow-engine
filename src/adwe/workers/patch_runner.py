import logging

from adwe.db.session import AsyncSessionLocal
from adwe.models.patch import Patch
from adwe.models.patch_status import PatchStatus
from adwe.models.workflow import Workflow
from adwe.services.audit import record_audit_event
from adwe.services.execution_policy import Operation, require_operation
from adwe.services.patch_workflow import apply_patch_workflow
from adwe.services.pull_request_records import record_pull_request

logger = logging.getLogger(__name__)


async def apply_patch_job(ctx, patch_id: str):
    require_operation(Operation.PATCH_EXECUTION)
    async with AsyncSessionLocal() as session:
        patch = await session.get(Patch, patch_id)

        if patch is None:
            logger.warning("patch_not_found patch_id=%s", patch_id)
            return

        workflow = await session.get(Workflow, patch.workflow_id)

        if workflow is None:
            logger.warning("workflow_not_found workflow_id=%s", patch.workflow_id)
            return

        patch.status = PatchStatus.APPLYING

        await record_audit_event(
            session=session,
            workflow_id=patch.workflow_id,
            event_type="patch.applying",
            payload={"patch_id": patch.id, "file_path": patch.file_path},
        )

        await session.commit()

        try:
            result = apply_patch_workflow(
                repository_url=workflow.repository_url,
                branch_name=f"adwe/{workflow.id}",
                diff=patch.diff,
                commit_message=f"Apply ADWE patch for workflow {workflow.id}",
                test_command=["python", "-m", "pytest"],
                dry_run=False,
                push=patch.push_requested,
                open_pr=patch.open_pr_requested,
                pr_title=patch.pr_title,
                pr_body=patch.pr_body,
            )

            patch.branch_name = result.get("branch_name")
            patch.commit_sha = result.get("commit_sha")
            patch.status = PatchStatus.APPLIED

            pull_request = result.get("pull_request")

            if pull_request:
                record = await record_pull_request(
                    session=session,
                    repository_url=pull_request["repository_url"],
                    branch_name=pull_request["branch_name"],
                    title=pull_request["title"],
                    status=pull_request["status"],
                    url=pull_request.get("url"),
                    workflow_id=workflow.id,
                )

                await session.flush()
                workflow.pull_request_id = record.id

            await record_audit_event(
                session=session,
                workflow_id=patch.workflow_id,
                event_type="patch.applied",
                payload={
                    "patch_id": patch.id,
                    "file_path": patch.file_path,
                    "branch_name": patch.branch_name,
                    "commit_sha": patch.commit_sha,
                    "test_result": result.get("test_result"),
                    "pull_request": pull_request,
                },
            )

        except Exception as exc:
            logger.exception("patch_apply_failed patch_id=%s", patch.id)

            patch.status = PatchStatus.FAILED
            patch.apply_error = str(exc)

            await record_audit_event(
                session=session,
                workflow_id=patch.workflow_id,
                event_type="patch.apply_failed",
                payload={
                    "patch_id": patch.id,
                    "file_path": patch.file_path,
                    "error": str(exc),
                },
            )

        await session.commit()
