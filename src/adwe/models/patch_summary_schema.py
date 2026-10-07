from pydantic import BaseModel


class PatchSummaryRead(BaseModel):
    workflow_id: str
    total: int
    proposed: int
    applied: int
    rejected: int
    approved: int = 0
    applying: int = 0
    failed: int = 0
    requires_review: int = 0
