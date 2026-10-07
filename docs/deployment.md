# Development deployment and release limits

## Start the control plane

Generate a random operator bearer and export only its SHA-256 digest as API_TOKEN_SHA256
(see README). Keep the bearer separately for client requests. Then:

```bash
docker compose up --build -d
```

PostgreSQL must become healthy, then the one-shot `migrate` service must succeed before the
API starts. Check `docker compose logs migrate` on startup failure. Migrations are packaged in
the image. The API runs as UID 10001 with a read-only root filesystem, no Linux capabilities,
no privilege escalation, and a bounded temporary mount. The Python dependencies use the
committed frozen lock; runtime omits development dependencies. The uv installer version is
pinned. Base image and system packages are not digest-pinned: this is not a certified release.

Development ports bind only to localhost: API 8000, PostgreSQL 5433, Redis 6379. PostgreSQL's
`adwe/adwe` credentials are development-only. Use secret-managed independent credentials and
TLS in a deployed environment; do not expose this Compose database to other networks. The
Compose API does not receive GitHub or model credentials. Redis remains for legacy diagnostics.
The legacy worker is behind the explicit `legacy-contained` profile; it cannot execute jobs.

Check the authenticated `/v1/health` endpoint for database readiness. Public `/openapi.json`
proves only HTTP startup, not database health. Missing operator digest causes authenticated
endpoints to fail closed. See metadata-intake.md for the supported end-to-end flow.

Deliver one submission intent using the same image/database:

```bash
docker compose run --rm api python -m adwe.workers.verification_dispatcher
```

The command returns a delivery result and exits. It is not a run executor. If scheduling it,
monitor pending/leased/dead rows and non-delivered outcomes rather than assuming exit means
work completed. No background poller or automatic admission is installed.

## CI evidence

CI applies all migrations on PostgreSQL, runs unit and integration tests, validates Compose,
builds the image, confirms non-root UID and packaged Alembic migrations, and starts the API
with read-only root, dropped capabilities and no-new-privileges. The smoke test checks public
schema startup and rejection of an unauthenticated submission request. It does not claim
production deployability or isolation of hostile repository code.

## Release blockers

- An independently provisioned and tested execution environment for untrusted workloads,
  with egress/resource/filesystem/output limits and cleanup reconciliation.
- Model-provider integration, budgets, evaluation fixtures and credential handling.
- Revision/branch provenance policy, admitted-run lifecycle and durable execution recovery.
- Changeset validation, evidence-bound approval and publication reconciliation using scoped
  GitHub App credentials.
- Backup/restore and disaster-recovery drills, key rotation, retention, monitoring and measured
  capacity; image digest pinning, supply-chain/security gates and deployment configuration review.

Do not lift containment because a control-plane container passes these smoke tests. This image
is not a sandbox. Preserve database volumes on shutdown (`docker compose down` without `-v`).
Before upgrades, back up PostgreSQL and verify restoration in a separate database. Populated
migration downgrades intentionally refuse evidence loss; use a reviewed compatible forward fix.
