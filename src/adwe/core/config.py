import re

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    api_operator_id: str = Field(
        default="operator", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
    )
    api_token_sha256: SecretStr | None = None

    @field_validator("api_token_sha256")
    @classmethod
    def validate_token_digest(cls, value: SecretStr | None) -> SecretStr | None:
        if (
            value is not None
            and re.fullmatch(r"[0-9a-f]{64}", value.get_secret_value()) is None
        ):
            raise ValueError("API_TOKEN_SHA256 must be a lowercase SHA-256 hex digest")
        return value

    database_url: str = "postgresql+asyncpg://adwe:adwe@localhost:5432/adwe"
    redis_url: str = "redis://localhost:6379/0"
    github_token: str | None = None

    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_enabled: bool = False


settings = Settings()
