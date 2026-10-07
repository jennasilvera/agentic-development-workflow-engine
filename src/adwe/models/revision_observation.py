from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from adwe.db.base import Base


class StoredRevisionObservation(Base):
    __tablename__ = "revision_observations"
    __table_args__ = (
        CheckConstraint(
            "commit_sha ~ '^[0-9a-f]{40}$' AND tree_sha ~ '^[0-9a-f]{40}$'",
            name="ck_revision_object_ids",
        ),
        CheckConstraint("github_repository_id > 0", name="ck_revision_provider_id"),
        CheckConstraint(
            "policy_version = 'public-metadata-v1'", name="ck_revision_policy"
        ),
        CheckConstraint(
            "recorded_by ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'",
            name="ck_revision_actor",
        ),
    )
    submission_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("verification_inbox.submission_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    github_repository_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    tree_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    recorded_by: Mapped[str] = mapped_column(String(64), nullable=False)
