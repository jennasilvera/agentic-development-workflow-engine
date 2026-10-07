from enum import StrEnum


class PatchStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    APPLIED = "applied"
    APPLYING = "applying"
    REJECTED = "rejected"
    FAILED = "failed"
    REQUIRES_REVIEW = "requires_review"
