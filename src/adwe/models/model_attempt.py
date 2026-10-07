"""Model accounting tables. Migration-owned triggers enforce append-only records."""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from adwe.db.base import Base


class ModelBudget(Base):
    __tablename__ = "model_budgets"
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("run_submissions.id"), primary_key=True
    )
    policy: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )


class ModelAttempt(Base):
    __tablename__ = "model_attempts"
    __table_args__ = (UniqueConstraint("submission_id", "request_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("model_budgets.submission_id"), nullable=False
    )
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    reserved_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )


class ModelAttemptResult(Base):
    __tablename__ = "model_attempt_results"
    attempt_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("model_attempts.id"), primary_key=True
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )
