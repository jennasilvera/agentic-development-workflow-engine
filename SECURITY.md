# Security and containment

ADWE is not approved for production use or untrusted repository execution.

## Implemented containment contract

`services/execution_policy.py` denies live workflow admission, repository acquisition,
patch execution, host tests and publication. There is no environment opt-in. These are
release containment decisions, not a finished per-actor authorization/policy engine.

- All existing mutating API routes return HTTP **503**, with `detail.code` equal to
  `operation_unavailable` and `detail.policy_version` equal to `containment-v1`.
  Rejection happens before route database/queue/external effects. Request parsing may still
  return validation errors for malformed transport input.
- Preview is POST but read-only; `/v1/patch-workflows/preview` remains available. OpenAPI and
  existing GET endpoints remain available. They do not acquire repositories or run code.
- Workflow and patch workers reject even old queued jobs before heartbeat, database access
  or status changes. They raise `OperationUnavailable` to ARQ; no application retry is made.
- Clone, patch-workflow, test-runner, push and PR service entry points reject direct calls.
  Analyzer uses the guarded clone service rather than a duplicate clone implementation.
- The test runner no longer contains a host subprocess implementation. An allowlisted pytest
  command would still execute malicious repository code and is not an acceptable substitute.
- Clone URL construction never adds platform credentials. Future private acquisition requires
  a separate scoped credential broker with evidence that credentials do not reach worktrees.
- Denials log a constant operation name, code and policy version. No URL, command, diff,
  token or request body is logged by the guard. These log records are not durable audit rows.

Compatibility change: callers that previously created workflows, approved/rejected/applied
patches, ran tests or published PRs now receive explicit unavailability. Lack of a GitHub
credential no longer produces a success-shaped skipped PR. Low-level Git helpers still exist
for trusted local fixture development; they are not supported untrusted execution interfaces.

## Residual risks

Read APIs remain unauthenticated and may expose historical source/prompt/audit data. Do not
expose the service publicly or attach sensitive production data. Preview/input sizes are not
yet bounded. Existing database credentials/configuration, lifecycle defects, deployment
hardening and durability gaps remain as recorded in PRODUCTION_READINESS_GAP_ANALYSIS.md.
Containment cannot stop old processes or prevent a trusted host operator from importing
low-level helpers, editing code, monkeypatching the guard or invoking Git independently.

| Asset | Threat / attack path | Implemented containment | Residual work |
| --- | --- | --- | --- |
| Host and platform secrets | API test command or malicious pytest code | Host runner removed; API/service/worker admission denied | Isolated executor with no platform credentials and resource/egress limits |
| GitHub credentials/source | Credential-bearing clone, symlink reads, unauthorized target | Acquisition denied; credential injection removed | Scoped broker, registration, revision pinning, safe bounded inventory |
| Remote branches/PRs | Direct API or worker bypasses approval/tests | Publication and patch workflow denied | Digest-bound approval, durable effect intent, reconciliation |
| Workflow/audit integrity | Duplicate queue delivery or false APPLIED status | Mutating endpoints/jobs denied | Authenticated atomic lifecycle and auditable legacy-data repair |
| Historical private data | Unauthenticated GET requests | No new access-control guarantee | Identity/authorization on reads, redaction and retention |

## Deployment and recovery procedure

1. Stop admission to old API processes and stop/drain old workers. Guard code cannot revoke
   already running host processes; inspect and terminate outstanding untrusted jobs separately.
2. Quarantine pending legacy queue deliveries; preserve workflow rows and audit data for
   reconciliation. Do not reset states or automatically delete remote branches/PRs.
3. Start the containment build. Verify mutation requests return 503 and preview still works.
4. Keep the service in a trusted development environment with no production credentials.
5. Implement the corresponding roadmap phase and its negative/failure tests before replacing
   a denial. Never add an `unsafe=true` escape hatch. If rollout fails, stop the service rather
   than restoring the unsafe network-exposed path.

No database migration is needed for containment. No queued-run status is fabricated as
canceled/failed: a future reconciliation procedure must determine actual prior effects.
