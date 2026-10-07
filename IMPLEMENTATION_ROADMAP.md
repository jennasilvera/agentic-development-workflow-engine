# Implementation roadmap

Work in reviewable increments. Each phase may span multiple changes; no phase is complete
until its acceptance evidence exists. Preserve legacy data and public contracts explicitly.

## 0. Contain unsafe execution (implemented)

- Objective/rationale: stop externally reachable untrusted acquisition, host commands and
  publication while their trust boundaries are absent.
- Components: policy module; write API dependencies; workflow/patch workers; clone,
  analyzer, patch workflow, test runner, Git push and PR services; README/SECURITY/tests.
- Work: typed deny decisions with stable codes; deny before queue/database/external effects;
  remove host command execution from test runner; deny direct service and queued-job bypasses.
  No environment switch may silently restore the unsafe implementation.
- Tests: API denial before side effects, worker denial before DB/heartbeat, service denial
  before clone/subprocess/HTTP, credentialed requests still denied, preview still available.
- Acceptance: documented 503 contract; regression tests pass apart from independently
  identified baseline infrastructure failures; no assertion that containment supplies isolation.
- Risks: intentional unavailability of live workflow execution and publication.
- Recovery: drain/quarantine legacy jobs and terminate already-running old workers before
  rollout; guards cannot revoke an already running process. Do not roll back to unsafe
  execution on a network-exposed service; stop service instead. No schema migration.

## 1. Identity, repository registration and truthful lifecycle

- Objective/rationale: bind every request and approval to an authorized actor and exact input.
- Components: API auth/application services; repository/revision/task models; patch/run domain;
  Alembic; timeline/audit and error schemas.
- Work: actor identity and repository allowlist; versioned task specification; approved distinct
  from applied; legal transitions and optimistic/atomic updates; fix rejection handler; classify
  ambiguous legacy APPLIED rows using evidence, not assumptions. Read APIs need authorization.
- Tests: authorization matrix, repository mismatch, changed-diff approval invalidation,
  duplicate approve/reject/apply using real PostgreSQL connections; orphan/backfill fixtures.
- Acceptance: unauthorized reads/writes rejected; illegal transitions impossible through API
  and services; migration reconciles legacy ambiguity without claiming execution occurred.
- Risks: data quality and status contract compatibility.
- Recovery: additive migration first; backups; quarantined ambiguous records; refuse downgrade
  when it would merge semantically distinct states without an explicit export/recovery plan.

## 2. Durable scheduling and recovery

- Objective/rationale: remove lost-job races and duplicate execution before adding autonomy.
- Components: outbox dispatcher, ARQ adapters, runs/steps/attempts/checkpoints, worker lifecycle.
- Work: transactional outbox; leases with fencing; bounded/classified retries; cancellation,
  stale-run reconciliation; checkpoint/side-effect ordering ADR. Keep Redis until evidence
  supports changing it. Replace blocking worker call paths.
- Tests: kill before/after each transaction and dispatch; duplicate delivery; lease expiry and
  stale-worker writes; DB/Redis outage; restart between nodes; cancellation races.
- Acceptance: committed work eventually dispatches; effects cannot repeat through replay;
  terminal states stay terminal; recovery emits causal audit evidence.
- Risks: split state authority between graph and application; lease clock assumptions.
- Recovery: pause dispatch, inspect pending intents, resume via reconciler; preserve attempt
  history; never recover by blindly setting all rows back to pending.

## 3. Isolated acquisition and execution

- Objective/rationale: safely inspect and execute untrusted repositories.
- Components: WorkspaceManager/executor adapter, credential broker, typed tools, policy,
  repository inventory and artifact collection.
- Work: resolve immutable base SHA; bounded checkout without retained credentials; prohibit
  cross-run mounts, host socket and platform secrets; enforce egress/resource/path/symlink
  rules; signed/hashed action binding; bounded output and cleanup reconciliation.
- Tests: malicious README/AGENTS text, symlink/path traversal, secret reads, network
  exfiltration, hanging/forking/output-flooding tests, disk exhaustion and cleanup crash.
- Acceptance: boundary independently reviewed and exercised; denied actions never spawn;
  allowed fixture tasks execute in isolation; only then replace specific containment denials.
- Risks: kernel/runtime vulnerabilities, supply-chain inputs and residual side channels.
- Recovery: revoke executor credentials, stop admission, terminate workspaces, retain bounded
  evidence; cleanup failure consumes capacity and alerts rather than silently leaking resources.

## 4. Model gateway and task-based proposals

- Objective/rationale: implement requested tasks with typed, bounded model proposals.
- Components: provider-neutral gateway, analyzer/planner/implementer/reviewer, budgets, evals.
- Work: strict schemas, provider capabilities, explicit fallback, model/usage provenance,
  redaction, independently validated patches and evidence-based review; remove misleading
  Markdown-to-code/YAML generation and recruiter-oriented output.
- Tests: malformed outputs, provider timeouts/429/5xx, budget exhaustion, prompt injection,
  unnecessary changes and regression fixtures; deterministic provider doubles.
- Acceptance: reproducible fixture tasks measure correctness and cost; no model grants tool
  authority; policy changes cannot be induced by repository content.
- Risks: stochastic output, sensitive prompt retention and invalid evaluation conclusions.
- Recovery: disable a model/config version; resume only at compatible checkpoints with an
  explicit new attempt; never silently swap providers mid-run.

## 5. Validated changesets and reconciled publication

- Objective/rationale: create the intended remote change exactly once in operational terms.
- Components: GitHub App adapter, effect-intent table, changesets, approvals and PR records.
- Work: persist base/head/diff/validation identities; aggregate patches; gated push/PR;
  deterministic branch/effect keys, remote reconciliation, conflict/base-moved handling;
  signed webhooks with durable delivery IDs.
- Tests: HTTP timeout after remote success; DB failure before result persistence; duplicate
  webhook; conflicting existing branch; invalid approval; tests failed or stale evidence.
- Acceptance: uncertain effect is reconciled or requires human review, never blind repeat;
  PR references exact verified head and audit report. Remove publication guard only then.
- Risks: API eventual consistency and concurrent external changes.
- Recovery: pause publisher and reconcile intents against GitHub; preserve remote work;
  do not delete or force-push unfamiliar branches as an automatic repair.

## 6. Operational qualification and release

- Objective/rationale: prove repeatable deployment, investigation and recovery.
- Components: Docker/Compose, CI, config, telemetry, docs/runbooks, retention, benchmarks.
- Work: frozen builds, non-root runtime and migration job, static/security checks, image smoke
  tests; structured redacted logs/traces/metrics; secret rotation, backup/restore and rollback
  drills; bounded API pagination; release artifacts tied to commits.
- Tests: clean-clone bootstrap, real PostgreSQL migration up/down where safe, backup restore,
  graceful shutdown, provider/GitHub outages, sustained representative bounded workload.
- Acceptance: release evidence and documented residual risks; performance/SLO proposals derive
  from measured workload. No production-ready claim based solely on passing unit tests.
- Risks: environment drift, retention mistakes, observer data leakage.
- Recovery: immutable prior image plus schema-compatible rollback; feature admission stops
  before data repair; preserve audit/effect history through rollback.

Next after phase 0: implement phase 1's authenticated read/write admission and repository
registration in a separately tested increment, then lifecycle migration. Do not re-enable
host commands as a shortcut while the isolated executor is under development.

## Increment 1a: implemented operator and registry foundation

- All application reads/writes/metrics require the configured operator bearer token; metadata
  docs remain public. Missing config/invalid tokens fail closed, and credentials are not logged.
- Add canonical repository registration and enable/disable endpoints, database constraints,
  transactionally recorded actor attribution, duplicate-safe registration and row-locked updates.
- Add Alembic migration with populated-downgrade protection; share DATABASE_URL across app/migrations.
- Split real PostgreSQL integration tests from unit tests; test concurrent registrations,
  concurrent disables, rollback, canonical database constraints and migration roundtrips.
- Scope remains single-operator, no per-user RBAC or GitHub identity verification. Registrations
  do not enable live execution or automatically approve historical workflow repositories.

Next increment: truthful patch approval/application lifecycle, explicit legacy-state migration,
then immutable repository/revision/task bindings and atomic run admission.

## Increment 1b: content-bound patch review

Approve/reject now use an explicit content digest, operator attribution, legal transitions,
row locking and transactional audit. Approval is distinct from application. Legacy ambiguous
statuses migrate to requires_review with prior status/evidence preserved. Downgrade protects
those decisions from silent loss. The undefined rejection-handler job_id is removed.
Execution/worker admission remains contained; no completed execution can be asserted by the
operator-decision API. Next: immutable repository/revision/task bindings and atomic run admission.

## Increment 1c: immutable run-input domain contract

Implemented a bounded, versioned task specification and immutable repository/revision/task/
policy binding with canonical serialization and a domain-separated SHA-256 digest. Tests
cover changed inputs, nested immutability, invalid/coerced/oversized fields, full revisions,
URL normalization, criterion order and a fixed digest vector. See docs/run-input.md.
This is a prerequisite only: atomic admission, database persistence, repository membership
verification and outbox scheduling remain unimplemented. Execution containment is unchanged.

## Increment 1d: unverified submission persistence

Added an append-only PostgreSQL submission table and internal transactional recording service.
Repository enabled/URL checks serialize with disable; actor-scoped request keys provide safe
retries and reject changed input. Digest constraints, foreign keys, immutable-row triggers and
populated-downgrade protection preserve evidence. Audit writes share the caller's transaction.
These are recorded requests, not admitted executions. Next: verified revision/policy admission,
run lifecycle and transactional outbox; expose a run API only with those boundaries in place.

## Increment 2a: verification outbox foundation

Submission insertion now atomically creates one verification intent through a database trigger.
Internal services claim with skip-locked row locks, database-time leases, fresh fencing tokens,
five-attempt limits, retry delay and transactional transition audit. Existing submissions receive
pending verification intents on migration. Populated downgrade is protected. This is not an
execution scheduler: dispatcher, idempotent verification consumer, verified admission, run
lifecycle and downstream effect fencing remain next. See docs/submission-outbox.md.

## Increment 2b: explicit dispatcher and idempotent inbox

Added a one-pass operator command with committed claims, bounded handoff and fenced
acknowledgement. The implemented receiver writes immutable PostgreSQL receipts and audit,
revalidates source input and deduplicates delivery by submission ID. Transport carries only
that ID. No automatic poller or legacy execution worker is enabled. Crash-after-acceptance,
acknowledgement failure, concurrent receipt creation, audit rollback and cancellation are
covered by PostgreSQL tests. Next: independent revision/policy verification and admitted run
lifecycle; receipt creation must never be treated as verification success.

## Increment 1e: public revision metadata adapter

Added bounded, unauthenticated fixed-origin GitHub metadata observation for exact SHA-1
commits. Checks repository identity/state before and after commit lookup, rejects redirects
and ambiguous responses, caps body size and elapsed time, and reports classified failures.
This is not admission or branch-membership proof. Observations are not yet persisted or wired
into inbox processing. Next: pin provider identity in registration, trusted policy selection,
persisted fresh evidence and atomic admission. See docs/revision-observation.md.

## Increment 1f: authenticated metadata intake and persisted evidence

Added explicit immutable provider-ID pinning, authenticated submission/read/status/observation
APIs, fixed metadata-only policy and immutable revision observations with transactional audit.
Observation persistence rechecks enabled registration after network I/O and enforces exact
input/provider identities and freshness. Added real-PostgreSQL API, concurrency, disable-during-
lookup, wrong-policy, unpinned, stale-evidence, rollback and database-guard tests.
No execution is admitted. See docs/metadata-intake.md.
