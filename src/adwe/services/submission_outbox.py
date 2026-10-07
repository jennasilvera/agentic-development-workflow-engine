"""Fenced delivery leases. No network calls, queue adapter or execution authority."""

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from adwe.services.audit import record_audit_event


@dataclass(frozen=True)
class DeliveryLease:
    submission_id: str
    token: str
    attempt: int


class StaleDeliveryLease(ValueError):
    pass


async def claim_verification_intent(session: AsyncSession) -> DeliveryLease | None:
    """Claim one ready row; commit before handing off outside this transaction.

    Database time governs the fixed 60-second lease. Expired fifth attempts become
    dead on the next claim sweep. A None result can mean an exhausted row was retired.
    """
    row = (
        (
            await session.execute(
                text("""
        SELECT submission_id, attempts FROM submission_outbox
        WHERE (status = 'pending' AND available_at <= clock_timestamp())
           OR (status = 'leased' AND lease_expires_at <= clock_timestamp())
        ORDER BY created_at, submission_id
        LIMIT 1 FOR UPDATE SKIP LOCKED
    """)
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    submission_id = row["submission_id"]
    if row["attempts"] >= 5:
        await session.execute(
            text("""UPDATE submission_outbox
            SET status='dead', lease_token=NULL, lease_expires_at=NULL
            WHERE submission_id=:id"""),
            {"id": submission_id},
        )
        await record_audit_event(
            session,
            "verification_delivery.exhausted",
            payload={"submission_id": submission_id, "attempts": 5},
        )
        await session.flush()
        return None
    token = str(uuid4())
    attempt = row["attempts"] + 1
    await session.execute(
        text("""UPDATE submission_outbox SET status='leased',
        attempts=attempts+1, lease_token=:token,
        lease_expires_at=clock_timestamp() + interval '60 seconds'
        WHERE submission_id=:id"""),
        {"id": submission_id, "token": token},
    )
    await record_audit_event(
        session,
        "verification_delivery.claimed",
        payload={"submission_id": submission_id, "attempt": attempt},
    )
    await session.flush()
    return DeliveryLease(submission_id, token, attempt)


async def finish_verification_delivery(
    session: AsyncSession, lease: DeliveryLease, *, delivered: bool
) -> None:
    """Acknowledge handoff, not verification success; stale owners cannot change state.

    On known handoff failure, retry after five seconds, at most five claims total.
    Unknown remote outcomes must eventually be deduplicated by the future consumer.
    """
    if type(delivered) is not bool:
        raise ValueError("delivered must be a boolean")
    # Lock first, then test expiry using a fresh statement after any lock wait.
    await session.execute(
        text("""SELECT submission_id FROM submission_outbox
        WHERE submission_id=:id FOR UPDATE"""),
        {"id": lease.submission_id},
    )
    status = (
        await session.execute(
            text("""UPDATE submission_outbox SET
        status=CASE WHEN :delivered THEN 'delivered'
                    WHEN attempts >= 5 THEN 'dead' ELSE 'pending' END,
        lease_token=NULL, lease_expires_at=NULL,
        available_at=clock_timestamp() + interval '5 seconds'
        WHERE submission_id=:id AND status='leased' AND lease_token=:token
          AND attempts=:attempt AND lease_expires_at > clock_timestamp()
        RETURNING status"""),
            {
                "id": lease.submission_id,
                "token": lease.token,
                "attempt": lease.attempt,
                "delivered": delivered,
            },
        )
    ).scalar_one_or_none()
    if status is None:
        raise StaleDeliveryLease(
            "Delivery lease is expired, superseded or already completed"
        )
    await record_audit_event(
        session,
        "verification_delivery." + status,
        payload={"submission_id": lease.submission_id, "attempt": lease.attempt},
    )
    await session.flush()
