from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from adwe.db.base import Base


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("canonical_url", name="uq_repositories_canonical_url"),
        CheckConstraint(
            "canonical_url ~ '^https://github[.]com/[a-z0-9][a-z0-9-]{0,38}/[a-z0-9_.-]{1,100}$' "
            "AND canonical_url NOT LIKE '%.git' "
            "AND split_part(canonical_url, '/', 5) NOT IN ('.', '..')",
            name="ck_repositories_canonical_url",
        ),
        CheckConstraint(
            "registered_by ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'",
            name="ck_repositories_actor",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    canonical_url: Mapped[str] = mapped_column(String(160), nullable=False)
    registered_by: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
