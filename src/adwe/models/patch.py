from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from adwe.db.base import Base
from adwe.models.patch_status import PatchStatus


class Patch(Base):
    __tablename__ = "patches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','approved','applying','applied','rejected','failed','requires_review')",
            name="ck_patches_status",
        ),
        CheckConstraint(
            "(status IN ('approved','applying','applied') AND approved_by IS NOT NULL "
            "AND approved_by ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$' AND approved_at IS NOT NULL "
            "AND approved_diff_sha256 IS NOT NULL "
            "AND approved_diff_sha256 = encode(sha256(convert_to(diff, 'UTF8')), 'hex')) "
            "OR (status NOT IN ('approved','applying','applied') AND approved_by IS NULL "
            "AND approved_at IS NULL AND approved_diff_sha256 IS NULL)",
            name="ck_patches_approval_evidence",
        ),
        CheckConstraint(
            "status <> 'applied' OR (commit_sha IS NOT NULL AND commit_sha ~ '^([0-9a-f]{40}|[0-9a-f]{64})$')",
            name="ck_patches_applied_commit",
        ),
    )
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_diff_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    legacy_status: Mapped[str | None] = mapped_column(String, nullable=True)

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    workflow_id: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    diff: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=PatchStatus.PROPOSED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    branch_name: Mapped[str | None] = mapped_column(String, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    apply_error: Mapped[str | None] = mapped_column(String, nullable=True)
    push_requested: Mapped[bool] = mapped_column(default=False)
    open_pr_requested: Mapped[bool] = mapped_column(default=False)
    pr_title: Mapped[str | None] = mapped_column(String, nullable=True)
    pr_body: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(String, nullable=True)
    files_changed: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(String, nullable=True)
    priority_score: Mapped[int | None] = mapped_column(nullable=True)
    priority_reason: Mapped[str | None] = mapped_column(String, nullable=True)
