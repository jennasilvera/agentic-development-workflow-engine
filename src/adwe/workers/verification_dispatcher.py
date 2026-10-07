"""Explicit one-pass PostgreSQL outbox-to-inbox handoff; no execution worker."""

import asyncio
from enum import StrEnum
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from adwe.services.submission_outbox import (
    StaleDeliveryLease,
    claim_verification_intent,
    finish_verification_delivery,
)
from adwe.services.verification_inbox import receive_verification_request


class Receiver(Protocol):
    async def receive(self, submission_id: str) -> None: ...


class DispatchResult(StrEnum):
    IDLE = "idle"
    DELIVERED = "delivered"
    UNCERTAIN = "uncertain"
    STALE = "stale"


class DatabaseInboxReceiver:
    """Returns only after the receiving transaction has committed."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def receive(self, submission_id: str) -> None:
        async with self.sessions() as session, session.begin():
            await receive_verification_request(session, submission_id)


async def dispatch_one(
    sessions: async_sessionmaker[AsyncSession], receiver: Receiver
) -> DispatchResult:
    async with sessions() as session, session.begin():
        lease = await claim_verification_intent(session)
    if lease is None:
        return DispatchResult.IDLE
    try:
        # A receiver must return only after durable acceptance, not after scheduling
        # a coroutine. Timeout/cancellation may occur after acceptance; never guess.
        async with asyncio.timeout(20):
            await receiver.receive(lease.submission_id)
    except (TimeoutError, OSError, SQLAlchemyError):
        # Do not leak transport exception text. Retain the lease for expiry/replay.
        # CancelledError intentionally propagates for graceful process shutdown.
        return DispatchResult.UNCERTAIN
    try:
        async with sessions() as session, session.begin():
            await finish_verification_delivery(session, lease, delivered=True)
    except StaleDeliveryLease:
        return DispatchResult.STALE
    return DispatchResult.DELIVERED


async def main() -> None:
    from adwe.db.session import AsyncSessionLocal

    result = await dispatch_one(
        AsyncSessionLocal, DatabaseInboxReceiver(AsyncSessionLocal)
    )
    print(result.value)


if __name__ == "__main__":
    asyncio.run(main())
