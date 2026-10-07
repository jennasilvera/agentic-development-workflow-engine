from pydantic import BaseModel, ConfigDict, Field


class PatchDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_diff_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
