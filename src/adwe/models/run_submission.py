"""Append-only requested inputs. A submission is not an admitted execution."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from adwe.db.base import Base


class RunSubmission(Base):
    __tablename__ = "run_submissions"
    __table_args__ = (
        UniqueConstraint("actor_id", "request_key", name="uq_run_submission_request"),
        CheckConstraint(
            "actor_id ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'", name="ck_submission_actor"
        ),
        CheckConstraint(
            "request_key ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$'",
            name="ck_submission_key",
        ),
        CheckConstraint(
            "input_digest = encode(sha256(convert_to('adwe.run-input.v1', 'UTF8') || "
            "decode('00', 'hex') || convert_to(canonical_input, 'UTF8')), 'hex')",
            name="ck_submission_digest",
        ),
        CheckConstraint(
            "(canonical_input::jsonb ->> 'repository_id') IS NOT NULL AND "
            "canonical_input::jsonb ->> 'repository_id' = repository_id",
            name="ck_submission_repository",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    repository_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_input: Mapped[str] = mapped_column(Text, nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
