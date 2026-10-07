from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from adwe.domain.repository import canonical_repository_url


class RepositoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository_url: str = Field(max_length=200)

    @field_validator("repository_url")
    @classmethod
    def canonicalize_url(cls, value: str) -> str:
        return canonical_repository_url(value)


class RepositoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


class RepositoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    github_repository_id: int | None = None
    canonical_url: str
    registered_by: str
    enabled: bool
    created_at: datetime


class RepositoryPage(BaseModel):
    items: list[RepositoryRead]
    next_offset: int | None
