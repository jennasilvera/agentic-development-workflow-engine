"""Receipt only: immutable evidence of input delivery, not verification success."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from adwe.db.base import Base


class VerificationReceipt(Base):
    __tablename__ = "verification_inbox"
    submission_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("run_submissions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
