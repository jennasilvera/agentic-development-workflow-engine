# Immutable run input contract (v1)

`adwe.domain.run_input.RunInput` defines the input identity for future run admission.
It is a domain contract only: no run API, persistence, dispatch or execution is enabled
by this increment. Existing workflows are not retroactively bound to registrations.

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
