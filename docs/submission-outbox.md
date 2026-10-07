# Submission verification outbox

This increment records and leases delivery intents for **verification requests**, not execution
jobs. No dispatcher, queue consumer, Git acquisition, policy authorization or execution is
installed. The existing containment policy remains in force.

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
cannot retract a request already delivered to an external service. The future consumer must
persist its own idempotent receipt before processing and independently check repository,
revision and policy authority. Never connect these intents directly to legacy run_workflow.

## Operations and recovery still required

There is no background lease renewal, dispatcher, dead-letter replay API or consumer yet.
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
