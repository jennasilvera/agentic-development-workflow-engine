# Internal model proposal contract

`ModelGateway` accepts a trusted application-selected provider and immutable policy. It is
not wired into an API, the legacy planner or an execution worker. An opt-in
[OpenAI adapter](openai-provider.md) implements its provider protocol but is not auto-enabled. No keys
or external calls are needed for its deterministic tests. The existing legacy text client
is not a production adapter for this gateway.

## Input and proposal identity

`ProposalInput` combines the versioned `RunInput` with at most 32 supplied text files.
Canonical sorted ASCII JSON and the `adwe.proposal-input.v1` digest domain bind all task,
revision, policy and source content. File content is capped at 16,000 characters; the gateway
also bounds the complete canonical payload in bytes before contacting a provider. Duplicate
or case-colliding paths are rejected. The source text is untrusted data, never policy.

The caller must supply curated context from a future verified acquisition path. This code
does not read a checkout, prove that supplied content belongs to the commit, discover or
redact secrets, or resolve filesystem symlinks. Do not pass credentials or sensitive files
to a provider merely because the schema accepts them.

`ChangeProposal` contains an input digest, summary and at most 16 complete-file replacements.
Each replacement must name an exactly supplied file and its SHA-256 content digest. Duplicate
targets, unchanged replacements and unsupplied targets fail validation. Creation, deletion,
rename, binary changes and executable tools are unsupported. Extra fields are rejected;
the schema cannot grant approval or report that tests ran. Relative path checks are lexical,
not an execution sandbox or a complete cross-platform filesystem validator.

The response must be strict UTF-8 JSON: duplicate keys, non-finite numbers, Markdown wrappers
and malformed/schema-invalid documents fail. Validated proposals remain untrusted content;
no file is written, imported, compiled, tested, approved or published.

## Limits and failure behavior

The immutable policy fixes provider, model, configuration version, input/output byte limits,
output token ceiling, call ceiling, cumulative output-token reservation and request deadline.
Concurrent calls reserve a call and the entire output-token ceiling under a lock before
contacting the provider. Reservations are never refunded, including on timeout, cancellation,
malformed responses and uncertain outcomes. Invalid input rejected before a provider attempt
does not consume a reservation. There is no implicit retry or provider fallback.

The typed provider request contains the chosen model, expected input digest and response limits.
Adapters must include that digest in the model request rather than ask the model to compute it. A production adapter
must enforce transport deadlines, streaming response-size bounds and provider output-token
limits. The gateway checks returned bytes, provider/model identity and strict reported usage
again. Its timeout requires a cooperative async adapter; blocking or cancellation-suppressing
provider code is unsupported and cannot be made safe by this wrapper.

These budgets belong to one gateway instance in one process. They reset on process restart,
do not coordinate multiple workers, and do not bound input-token charges or monetary cost.
Reported usage is provider evidence, not independently verified billing. Production requires
durable pre-call reservations, pricing/version policy and reconciliation of uncertain attempts.

Provider failures expose only classified codes. Response bodies and task text are never logged
by the gateway. Cancellation propagates; unexpected adapter programming exceptions propagate
for investigation. Callers must not expose arbitrary exception tracebacks to users. A successful
result includes attempt UUID, provider/model/policy version, input/response/proposal digests,
strict usage and the immutable proposal. The durable wrapper below persists outcomes and audit;
the standalone gateway itself remains stateless beyond its in-memory reservations.

## Verification and next boundary

Unit fixtures exercise invalid JSON and schemas, stale identities, unsupplied/traversal targets,
provider substitution, body/usage limits, concurrent reservations, provider failure, deadline,
cancellation and repository text that requests policy changes. The addition fixture verifies
proposal shape and content only; it does not execute code or measure model task correctness.

Before enabling a live path, implement a selected provider adapter with transport tests and
explicit credential handling, monetary/global budgets and billing reconciliation, verified curated context,
independent changeset validation, an isolated executor and task-level model evaluations.
The gateway does not remove any existing containment decision.

## Durable reservation path

`create_model_budget` stores one immutable operator-selected policy per submission. Identical
configuration is idempotent; changed limits or actor conflict. `propose_with_budget` snapshots
caller input, checks its exact run-input identity and repository enablement, locks the budget,
reserves one attempt, and commits its audit before provider I/O. The gateway then validates the
reply and commits immutable result evidence and audit in a separate transaction. No database
transaction spans the provider call. Disabling a repository prevents subsequent reservations;
it cannot revoke an already committed attempt or recall text sent to a provider.

Reservations are append-only. Their count and sum are the budget authority across workers and
restarts. Database triggers also reject attempts beyond the fixed limits and prevent record
updates/deletions. Result identity and reported output usage bind to the reserved attempt and
policy. Schema creation must use Alembic; ORM metadata alone does not install these database
checks and triggers. Populated downgrade is refused.

The submission/request-key pair can be reserved only once, even if input changes. A duplicate
raises `AttemptConflict` and never invokes the provider. Inspect existing records; do not treat
this conflict as permission to generate a fresh key automatically. A new key consumes another
reservation and is an explicit application decision. There is no automatic recovery retry.

A reservation without a result means **unknown outcome**: the process may have stopped before
the call, after remote completion, or during result persistence. Cancellation/programming errors
leave that state. Timeout/transport errors record `uncertain`; other classified gateway errors
record `failed`. None refunds budget. `failed` does not imply zero provider charges. A successful
result means validated proposal shape and identity only, not correct code or executed tests.

This internal path persists proposal text in PostgreSQL, so existing database access controls,
backup handling and eventual retention policy must cover source-derived model output. Error
records store only classified codes. No public endpoints or live provider adapters are enabled.
The original instance-only gateway remains a testable contract, not the durable entry point.

Durable **call and output-token reservations** are implemented. Monetary/input-token limits,
provider billing reconciliation, deployment-wide budgets spanning multiple submissions,
failed-attempt reconciliation and provider idempotency still require implementation. The fixed
per-submission budget is not a global spending cap.
