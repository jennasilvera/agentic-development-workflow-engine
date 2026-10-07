# Authenticated metadata intake

This is a working metadata-only control-plane flow. It does not admit an execution run.
The only enabled policy is `public-metadata-v1`, selected by application code. Task text
cannot extend it. Legacy execution routes continue returning containment errors.

1. Register a canonical public GitHub repository using `POST /v1/repositories`.
2. Pin its numeric GitHub repository ID with `POST /v1/repositories/{id}/identity` and
   `{"github_repository_id": 123}`. The operator must obtain the ID independently from
   GitHub repository metadata. This is an explicit administrative trust decision, not a
   task-supplied identity. A different subsequent pin or URL change is rejected. Renames,
   transfers and mistaken pins require a reviewed migration, not silent reassignment.
3. Submit a RunInput to `POST /v1/submissions` with an `Idempotency-Key` header. Use the
   registered UUID and URL, full commit SHA, task and `policy_version: public-metadata-v1`.
   New requests return 201; identical retries 200; reuse with changed content 409.
4. Run `PYTHONPATH=src uv run --frozen python -m adwe.workers.verification_dispatcher` to
   deliver one request to its durable inbox. Scheduling remains explicitly operator-managed.
5. Call `POST /v1/submissions/{id}/observe`. The server checks the inbox, input integrity,
   enabled registration, pinned provider ID and trusted policy before calling GitHub.
   It closes the read transaction before network I/O. It then locks and rechecks registry
   state and records the exact observation and audit in one transaction.
6. Read `GET /v1/submissions/{id}/status` for delivery, receipt and observation evidence.
   `execution_admitted` is always false. List requests with bounded limit/offset.

All endpoints require the operator bearer. They are single-operator, not tenant-isolated.
Inputs and task text are persisted in plaintext and returned only through authenticated APIs;
retention/encryption must be qualified for production before collecting confidential tasks.

Observation recording accepts only an exact matching result no older than 60 seconds. It
requires the pinned GitHub numeric identity to match the provider response. Existing results
can be reused for five minutes, after which a new submission is required. These durations
are conservative development policy values, not workload-backed SLOs. Concurrent observations
produce one evidence row/event; contradictory tree results are rejected. Disable during network
I/O blocks recording. No database lock spans the network request.

Database guards preserve identity pins, immutable observations, submission/digest/commit/policy
association and protected downgrades. Schema version `c264b8da5eb7` is additive; existing
registrations start unpinned and are not implicitly trusted. Stop old writers while migrating.
The operator and database administrator remain trusted; these are not cryptographically signed
attestations. An API observation does not establish branch ancestry, signature trust or safe code.

Verification errors are classified: 409 for local policy/identity/state conflicts; 422 for
non-retryable provider lookup failure; 503 for retryable provider failures. Unknown submissions
on read return 404. No error enables fallback execution. No model provider is called.
