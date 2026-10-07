"""Versioned input identity; validation does not authorize or admit execution."""

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from adwe.domain.repository import canonical_repository_url

Criterion = Annotated[StrictStr, Field(min_length=1, max_length=2000)]


class TaskSpecification(BaseModel):
    """Task text is data, never a source of tool or policy authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    objective: StrictStr = Field(min_length=1, max_length=8000)
    acceptance_criteria: tuple[Criterion, ...] = Field(min_length=1, max_length=20)

    @field_validator("objective")
    @classmethod
    def nonblank_objective(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Objective must contain non-whitespace text")
        return value

    @field_validator("acceptance_criteria")
    @classmethod
    def nonblank_criteria(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("Acceptance criteria must contain non-whitespace text")
        return values


class RunInput(BaseModel):
    """An immutable requested input, not proof of repository/revision verification.

    Admission must load the registration, check it is enabled and matches this URL,
    verify the commit belongs to it, and select an authorized policy independently.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = "1"
    repository_id: StrictStr
    repository_url: StrictStr = Field(max_length=200)
    base_commit_sha: StrictStr = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    task: TaskSpecification
    policy_version: StrictStr = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    )

    @field_validator("repository_id")
    @classmethod
    def canonical_id(cls, value: str) -> str:
        if str(UUID(value)) != value:
            raise ValueError("Repository ID must be a canonical UUID")
        return value

    @field_validator("repository_url")
    @classmethod
    def canonical_url(cls, value: str) -> str:
        return canonical_repository_url(value)

    def canonical_bytes(self) -> bytes:
        """v1 serialization: sorted keys, ASCII JSON, compact separators, no newline.

        Preserve task whitespace and criterion order. Defaults are always included.
        Changing this encoding requires a new version and digest domain.
        """
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")

    def digest(self) -> str:
        return hashlib.sha256(b"adwe.run-input.v1\x00" + self.canonical_bytes()).hexdigest()
