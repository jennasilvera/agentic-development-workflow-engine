"""One verification-delivery intent per immutable submission; no workload payload."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from adwe.db.base import Base


class SubmissionOutbox(Base):
    __tablename__ = "submission_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'leased', 'delivered', 'dead')",
            name="ck_outbox_status",
        ),
        CheckConstraint("attempts BETWEEN 0 AND 5", name="ck_outbox_attempts"),
        CheckConstraint(
            "(status = 'leased' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'leased' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_outbox_lease",
        ),
        Index("ix_outbox_ready", "status", "available_at", "created_at"),
    )
    submission_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("run_submissions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
