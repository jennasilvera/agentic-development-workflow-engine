# Immutable run input contract (v1)

`adwe.domain.run_input.RunInput` defines the input identity for future run admission.
An internal persistence service now records these inputs as unverified submissions.
No run API, dispatch or execution is enabled. Existing workflows are not retroactively bound to registrations.

The contract binds a canonical registry UUID and GitHub URL, a full lowercase 40- or
64-character commit object ID, a task specification, and a policy version. Branch names,
short SHAs, credential-bearing URLs, unknown versions and extra fields are rejected.
Tasks require an objective (1–8,000 characters) and 1–20 acceptance criteria (each
1–2,000 characters). Whitespace-only text and coercion from non-string values are rejected.
Both models are frozen and criteria are copied into an immutable tuple.

## Identity encoding

The digest is SHA-256 over `adwe.run-input.v1` followed by one NUL byte and the canonical
JSON bytes. JSON contains all defaults, sorted keys, ASCII Unicode escapes, compact comma
and colon separators, and no final newline. Repository URLs are canonicalized before
encoding. Task whitespace, Unicode code points and criterion order are preserved: changing
any of these changes identity. Changing the encoding requires a new schema/digest domain.
A committed golden-vector test pins this protocol across refactors.

The digest is an integrity identifier, not a signature, authorization, idempotency key,
proof of commit existence, or evidence that the requested task was performed. Do not use
an identical digest alone to suppress an explicitly requested subsequent run. Do not accept
model-generated actor identities, tools or budgets as authority. Frozen models prevent
accidental mutation; trusted Python code can bypass them and is not a security boundary.

## Admission still required

The future application service must validate serialized input at its boundary, load and lock
the registered repository, check enabled state and exact URL correspondence, resolve or
verify the full revision against that repository in the acquisition boundary, and select an
authorized policy independently of task text. A syntactically valid SHA does not establish
repository membership. Persist the exact input and digest with authenticated actor identity,
run state and audit in one transaction; durable dispatch must use the outbox. Concurrent
disabling, duplicate admission, crashes and rollback need real PostgreSQL acceptance tests.
None of those guarantees are claimed by this domain-only increment.

## Recorded submissions

`record_run_submission` validates a serialized input dictionary, takes a repository row
lock, checks enabled state and URL correspondence, then inserts `run_submissions` and
`run_input.recorded` audit evidence in the caller's transaction. The service does not commit.
Actor identity must come from the authenticated caller. Policy versions and revisions remain
unverified requests; recording them does not grant authority.

The unique `(actor_id, request_key)` constraint serializes duplicate submissions, including
cross-repository reuse of a key. Identical retries return the original record without a new
audit event; changed input conflicts. A new key may intentionally repeat the same input.
Retries after repository disable are rejected. Disable and recording serialize on the same
repository lock; a later disable does not erase a previously recorded request. Future execution
admission must recheck repository state.

PostgreSQL verifies the digest over the exact stored bytes, requires the embedded repository
ID to match the foreign key, and rejects updates/deletes through an append-only trigger. The
service validates the full schema and URL association; direct database writers can bypass
those application checks. Database owners can bypass triggers, so this is not tamper-proof
storage. No task text is copied into audit payloads. Input retention still needs an explicit
policy before API exposure; recorded task text is stored in plaintext.

Migration `9d31e5f72a84` is additive and leaves legacy workflows untouched. An empty table can
be downgraded; populated downgrade fails to preserve submission evidence. Export/recovery and
an explicitly reviewed migration are required for later removal. Never bypass this guard as
an automatic rollback. Real PostgreSQL tests cover concurrent duplicates, changed-key
conflicts, audit rollback, disable ordering, identity mismatch, immutability, digest rejection
and migration roundtrip. There is no SQLite substitute.
