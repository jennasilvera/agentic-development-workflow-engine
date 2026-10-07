from datetime import datetime

from pydantic import BaseModel, computed_field

from adwe.domain.patch_decision import diff_digest


class PatchRead(BaseModel):
    id: str
    workflow_id: str
    file_path: str
    diff: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
    branch_name: str | None = None
    commit_sha: str | None = None
    apply_error: str | None = None
    push_requested: bool = False
    open_pr_requested: bool = False
    pr_title: str | None = None
    pr_body: str | None = None
    summary: str | None = None
    files_changed: list[str] | None = None
    reasoning: str | None = None
    priority_score: int | None = None
    priority_reason: str | None = None

    approved_by: str | None = None
    approved_at: datetime | None = None
    approved_diff_sha256: str | None = None
    legacy_status: str | None = None

    @computed_field
    @property
    def diff_sha256(self) -> str:
        return diff_digest(self.diff)
