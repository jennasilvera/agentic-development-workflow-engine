# Production-readiness gaps

Baseline: `a37fc64`. Status after the first increment is containment only; blocked features
are not implemented production capabilities. Evidence paths are relative to repository root.

| ID | Priority | Gap / evidence | Required exit evidence |
| --- | --- | --- | --- |
| SEC-01 | P0 | Arbitrary host command execution: api/patch_apply.py → services/test_runner.py | Isolated executor adversarial tests for host/secret access, egress, timeout, fork/output/disk limits; current increment denies execution |
| SEC-02 | P0 | No authentication/repository authorization on read/write APIs | Actor-scoped access tests, registered repository allowlist, deny by default; single-operator authentication now covers reads/writes/metrics; execution-specific repository authorization remains |
| SEC-03 | P0 | Credential URL persistence and unbounded/symlink-unsafe acquisition: repository_clone.py, repository_analyzer.py | Credential-free worktree/config/logs; pinned SHA; hostile URL/path/symlink/size tests; acquisition currently blocked |
| SEC-04 | P0 | Direct PR creation bypasses validations; Github effect before DB lookup | Exact changeset validation/approval and durable effect reconciliation; publication currently blocked |
| COR-01 | P0 | Approval/application separation and rejection-handler fix implemented; worker claim/lease and verified completion remain | Atomic lifecycle transition/approval tests with two real DB connections, explicit legacy migration; routes/jobs contained |
| DUR-01 | P1 | Enqueue before commit; no outbox or reconciliation | Crash matrix covering commit/dispatch/ack; no lost work and safe duplicate handling |
| DUR-02 | P1 | No checkpoint, lease/fencing, cancellation or stale-run recovery | Worker kill/restart/concurrency tests; terminal states immutable; bounded classified retries |
| REV-01 | P1 | Separate moving-HEAD clones; shared branch across patches | Persisted base SHA, aggregated changeset digest, branch conflict handling and deterministic replay |
| DOM-01 | P1 | Legacy unconstrained tables, no task specification or normalized action evidence; constrained repository registry now added | Alembic upgrade/backfill tests; FK/check/unique constraints; typed task/run/action contracts |
| GEN-01 | P1 | Markdown new-file generator targets existing code/YAML; unvalidated LLM JSON | Typed proposals and bounded patches, path/content validation, task-based fixture evaluation |
| MOD-01 | P1 | Provider-specific synchronous text API, implicit fallback | Typed gateway contract, capability checks, usage/budget accounting, explicit fallback and adapter failure tests |
| AUD-01 | P1 | Post-hoc audit, raw prompts/errors, no actor/policy/revision | Causal events on failure as well as success, bounded/redacted payloads and provenance report |
| TST-01 | P1 | Import/OpenAPI tests dominate; timeline unit test requires DB | Behavioral unit suite; real PostgreSQL migrations/concurrency; malicious fixtures and simulated effects |
| OPS-01 | P2 | Root app container, missing migration runtime, unbounded blocking calls | Non-root reproducible image, migration/readiness/smoke CI, graceful termination and cleanup tests |
| CFG-01 | P2 | Database URL now shared by app/migrations; remaining insecure defaults and production config validation | Shared typed config, production validation, placeholders and documented local setup |
| OBS-01 | P2 | Text logs; HTTP-only metrics; no trace propagation | Redaction/correlation tests; workflow/provider/tool metrics; operational dashboards/runbooks |
| SCM-01 | P2 | Long-lived token, hardcoded master, no webhook verification | Scoped GitHub App flow, base-branch resolution, signed/deduplicated webhook tests |
| API-01 | P2 | No pagination, inconsistent errors, direct ORM response handling | Stable envelopes, pagination bounds and API compatibility tests |
| CI-01 | P2 | Unlocked install, no lint/type/migration/container gates | Reproducible CI with required checks; branch protection independently verified |
| EVAL-01 | P2 | No agent effectiveness benchmark or evaluation history | Versioned tasks; regression, unnecessary edits, cost/latency and human-intervention measurements |
| PERF-01 | P3 | N+1 leaderboard, analytics ahead of fundamentals | Workload-backed profiling and accurate aggregation tests; no speculative new infrastructure |

Dependencies: containment → identity/registration + lifecycle semantics → durable scheduling
and revision-bound execution → validated proposals → controlled publication → operational
qualification. Security boundary proof is required before lifting the corresponding containment
guard, even if other functional tests pass.

Progress: single-operator authentication and transactional repository registration are implemented.
This is partial phase 1, not completion of lifecycle, revision binding or isolated execution.

Patch decision transition, exact-diff binding, concurrent review and conservative legacy-state
migration are implemented. Durable worker ownership and revision-bound execution remain blocked.
