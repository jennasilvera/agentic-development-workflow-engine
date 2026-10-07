# Submission verification outbox

This increment records and leases delivery intents for **verification requests**, not execution
jobs. An explicit one-pass dispatcher now hands off to a durable PostgreSQL inbox.
Git acquisition, revision verification, policy authorization and execution remain unimplemented. The existing containment policy remains in force.

## Atomic creation

Migration `a042f6b83c95` creates `submission_outbox` and an AFTER INSERT trigger on
`run_submissions`. Every newly inserted submission receives exactly one intent in the same
transaction, including inserts from an older application version. Submission/audit rollback
also rolls back the intent. The submission ID is both primary key and foreign key; it is the
future consumer's stable deduplication identity. No task text or credentials are copied into
queue payloads. The migration backfills existing unverified submissions as pending verification
requests. It does not declare any submission admitted. Stop old writers while migrating.

## Delivery protocol

The internal service claims one eligible row with `FOR UPDATE SKIP LOCKED`. Database time
sets a fixed 60-second lease and each claim receives a fresh token and increasing attempt
number. Claim and audit must commit before any external handoff. Do not keep the transaction
open across network calls. Other claimers skip held rows rather than waiting for them.

Acknowledge or fail the handoff in a new transaction using the original lease. The service
locks the row, then uses a fresh database-time comparison to reject expired or replaced tokens.
Acknowledgement means only `delivered`, never verified, approved or executed. A known failure
returns to pending with five-second backoff. There are at most five claims: an exhausted
failure becomes dead immediately; an expired fifth lease becomes dead on the next claim sweep.
A claim returning None can mean an exhausted row was retired, so a future dispatcher must
continue periodic polling. Terminal delivered/dead rows are not automatically reopened.
All service transitions and their audit events share a transaction.

This is **at-least-once delivery preparation**. A crash after remote acceptance but before
acknowledgement can cause redelivery. Lease tokens fence database acknowledgements only; they
cannot retract a request already delivered to an external service. The inbox consumer now
persists its own idempotent receipt; future processing must and independently check repository,
revision and policy authority. Never connect these intents directly to legacy run_workflow.

## Operations and recovery still required

There is no background polling, lease renewal, dead-letter replay API or revision verifier yet.
Delivery adapters must use timeouts below the lease and classify known versus uncertain
outcomes. Dead rows require reviewed recovery; do not mass-reset attempts. Polling fairness,
metrics, retention, backoff tuning, dispatch fault injection and downstream fencing remain
release requirements. SQL constraints check status/lease shape and attempt bounds; trusted
service code enforces legal transitions. Database owners can bypass application rules.

Downgrade succeeds only with an empty outbox, otherwise it refuses evidence loss. Preserve
records and use an explicitly reviewed recovery migration if removal becomes necessary.
Real PostgreSQL tests cover atomic intent rollback, duplicate submissions, skip-locked claims,
expiry and stale tokens, bounded attempts, retry delay, acknowledgement/claim rollback, and
backfill from the prior schema. Database time is advanced in fixtures without sleeping.

## Explicit dispatcher and durable inbox

Run one handoff with:

```bash
PYTHONPATH=src uv run --frozen python -m adwe.workers.verification_dispatcher
```

This is an operator-side command with database access, not a public endpoint. It uses the
configured DATABASE_URL. Apply migrations first. It claims and commits one outbox lease,
then invokes `DatabaseInboxReceiver` with only the submission UUID in a separate transaction,
then acknowledges in another transaction. No legacy ARQ execution function is called and no
Redis service is needed for this handoff. This direct database receiver is the implemented
transport; the receiver protocol allows a later adapter without claiming one exists today.

The receiver loads the immutable submission, revalidates its schema, canonical encoding and
digest, and inserts one immutable receipt plus audit. Duplicate receipt IDs return without
repeating audit. The database requires the receipt digest to match its submission. A receipt
means only that input is durably available for future verification. It does not re-enable a
disabled repository, verify commit membership or authorize the requested policy. Those checks
belong to the later admission service and must use current repository state.

Receiver timeout is 20 seconds, below the 60-second delivery lease. Timeout, transport I/O and
database failures return `uncertain` and retain the lease for eventual replay; programming or
input-integrity errors propagate. Cancellation propagates too. Database failure during final
acknowledgement propagates while preserving the committed receipt. Replaying after any of
these outcomes is safe for receipt creation. `stale` means the handoff completed but the
original lease can no longer acknowledge. `idle` may mean an exhausted row was retired.
Invoke again periodically through an explicitly configured operator scheduler; no automatic
poller is installed. Monitor non-delivered outcomes and dead rows. The receiver contract
requires durable acceptance before returning and cooperative async cancellation. A future
network adapter must enforce its own timeout and cannot claim receipt semantics merely from
an enqueue response.

Migration `b153a7c94da6` adds the inbox and immutable/digest-match guards. It does not backfill
receipts or fabricate verification. Populated downgrade refuses receipt loss. Tests exercise
concurrent intake, reply loss after commit followed by replay, acknowledgement failure,
receipt audit rollback, cancellation, unknown IDs, database guards and protected downgrade.
