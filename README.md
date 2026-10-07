# Agentic Development Workflow Engine

[![CI](https://github.com/jennasilvera/agentic-development-workflow-engine/actions/workflows/ci.yml/badge.svg?branch=hardening%2Fproduction-foundation)](https://github.com/jennasilvera/agentic-development-workflow-engine/actions/workflows/ci.yml)

**ADWE is a platform for controlled AI-assisted software development.** Its purpose is to
turn an engineering task into a reviewable repository change with explicit authorization,
reproducible validation and a traceable record of every consequential action.

Models propose changes. The platform owns policy, execution and evidence.

The current development branch implements an authenticated control plane, repository
registration and content-bound patch review. Live repository acquisition, code execution
and GitHub publication remain disabled while durable orchestration and execution isolation
are rebuilt. This is an active implementation, not a production-ready release.

## What works today

| Capability | Implemented behavior |
| --- | --- |
| Operator authentication | Bearer authentication on application APIs, health and metrics; missing configuration fails closed |
| Repository registry | Canonical GitHub identities, duplicate-safe registration, bounded listing, enable/disable controls |
| Patch review | Approval and rejection bound to the exact diff digest; operator identity and timestamp recorded |
| Concurrency and audit | PostgreSQL uniqueness/row locks; decisions and audit events commit together |
| Legacy reconciliation | Ambiguous execution labels quarantined as `requires_review`, with original status/evidence retained |
| Offline preview | Diff summary without cloning or executing a repository |
| Existing records | Authenticated workflow, patch, timeline, audit and aggregate reads |
| Validation | Unit tests and real PostgreSQL tests covering concurrency, rollback and migration safeguards |

Repository registration does not verify remote access or enable execution. Patch approval
means the operator reviewed that content; it does not mean tests ran, a commit was created
or a PR was published. Historical planner/artifact helpers remain limited to heuristic
inventory and Markdown proposals, not general-purpose task implementation.

## Architecture

The initial deployment is a Python modular monolith with PostgreSQL and existing ARQ/Redis
worker adapters. LangGraph remains the orchestration framework; durable step recovery is
planned work. No additional distributed infrastructure is introduced without a measured need.

```mermaid
flowchart TD
    Operator[Authenticated operator] --> API[FastAPI control plane]
    API --> Registry[Repository registration]
    API --> Review[Content-bound patch review]
    Registry --> DB[(PostgreSQL)]
    Review --> DB
    Registry --> Audit[Transactional audit events]
    Review --> Audit
    Audit --> DB
    API --> Guard[Execution containment]
    Worker[Legacy worker jobs] --> Guard
    Guard --> Denied[Live effects unavailable]
```

The target design separates control, orchestration, execution and integration responsibilities.
Untrusted repository code will execute outside the credential-bearing control plane. A
temporary directory or allowlisted pytest command is not that security boundary.

## Quick start

Requirements: Python 3.12+, uv, Git, and PostgreSQL 16 for integration tests. Docker Compose
can supply development PostgreSQL and Redis. Run from the repository root.

```bash
uv sync --frozen
docker compose up -d postgres redis
export DATABASE_URL=postgresql+asyncpg://adwe:adwe@127.0.0.1:5433/adwe
export ADWE_TEST_DATABASE_URL="$DATABASE_URL"
PYTHONPATH=src uv run --frozen alembic upgrade head
```

Compose publishes PostgreSQL on port **5433**. Alembic and the application share DATABASE_URL;
Alembic selects its synchronous driver internally. Sample database credentials are for local
development only. Registry integration tests require permission to create temporary schemas.

Generate a high-entropy operator credential for your development session:

```bash
export ADWE_OPERATOR_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export API_TOKEN_SHA256="$(python -c 'import hashlib, os; print(hashlib.sha256(os.environ["ADWE_OPERATOR_TOKEN"].encode()).hexdigest())')"
export API_OPERATOR_ID=operator
PYTHONPATH=src uv run --frozen uvicorn adwe.api.app:app --host 127.0.0.1
```

The server needs only API_TOKEN_SHA256 and the stable operator ID. ADWE_OPERATOR_TOKEN is a
client-side example variable. Store operational credentials in a secret manager and send
bearer tokens only over TLS or loopback. Rotate the digest on every API instance and restart
them; preserve the operator ID for attribution. Never commit raw tokens.

This is a single-operator deployment: that identity can access all deployment records.
Multitenancy, end-user RBAC, token expiry and rate limits are not implemented. Use a trusted
development environment. Worker jobs remain blocked; starting a worker does not enable them.

## API

Interactive schema: `/docs`. OpenAPI: `/openapi.json`. These expose metadata without credentials;
all application operations, including `/metrics` and `/v1/health`, require bearer authentication.

| Operation | Endpoint | Behavior |
| --- | --- | --- |
| Register repository | `POST /v1/repositories` | 201 for new identity; 200 for an existing identity |
| List repositories | `GET /v1/repositories?limit=50&offset=0` | Bounded page with `next_offset` |
| Enable/disable | `PATCH /v1/repositories/{id}` | Accepts `enabled`; does not start a run |
| Read patch | `GET /v1/workflows/{workflow_id}/patches/{patch_id}` | Includes current `diff_sha256` and approval evidence |
| Approve/reject | `POST .../patches/{patch_id}/approve` or `/reject` | Requires `expected_diff_sha256`; stale/illegal decisions return 409 |
| Preview | `POST /v1/patch-workflows/preview` | Read-only summary, not validation or authorization |
| Execute/publish | Existing workflow/apply/PR endpoints | 503 `operation_unavailable`, even with a valid operator token |

Register a repository:

```bash
curl -X POST http://127.0.0.1:8000/v1/repositories \
  -H "Authorization: Bearer $ADWE_OPERATOR_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"repository_url":"https://github.com/example/project"}'
```

URL case and an optional `.git` suffix/trailing slash normalize to the same identity.
Re-registering a disabled repository never re-enables it. No network request is made.

To review a persisted proposal, GET the patch, review the entire diff, and submit its
`diff_sha256` as `expected_diff_sha256` to the decision endpoint. Repeat decisions are
idempotent. Rejecting an approved patch revokes approval. Rejected, terminal or quarantined
patches cannot silently return to approved. There is no automatic reconciliation shortcut.

## Verification

```bash
# No PostgreSQL or Redis required
PYTHONPATH=src uv run --frozen pytest tests/unit -q

# Real PostgreSQL, including migration and concurrency behavior
PYTHONPATH=src uv run --frozen pytest tests/integration -q
```

Integration tests fail if PostgreSQL is unavailable; they do not silently skip or substitute
SQLite. Registry/lifecycle fixtures create and drop isolated random schemas. Use a disposable
test database. The preserved workflow timeline test uses DATABASE_URL and migrated tables.
CI installs frozen dependencies, applies migrations, runs both suites and validates Compose.

Targeted lint/type checks accompany each increment. Whole-project static cleanup, container
hardening, crash recovery and adversarial executor qualification remain roadmap work.

## Engineering documentation

- [Architecture](ARCHITECTURE.md): current implementation, target design and trust boundaries.
- [Current-state assessment](CURRENT_STATE_ASSESSMENT.md): evidence from the original code baseline.
- [Production-readiness gaps](PRODUCTION_READINESS_GAP_ANALYSIS.md): prioritized remaining work.
- [Implementation roadmap](IMPLEMENTATION_ROADMAP.md): phased acceptance criteria and recovery risks.
- [Security](SECURITY.md): supported operating scope and containment contract.
- [Operator admission ADR](docs/adr/001-single-operator-admission.md).
- [Patch review and migration](docs/patch-review.md).

Next foundations: immutable repository/revision/task binding, transactional run admission,
durable worker recovery, isolated execution, typed model proposals and reconciled publication.

Run admission is under development. The [immutable run-input contract](docs/run-input.md)
defines versioned task/repository/revision identity; it does not yet admit or execute runs.

An internal submission service now persists those inputs with repository checks, request-key
idempotency and atomic audit. Submissions remain unverified and cannot dispatch execution.

The [verification outbox](docs/submission-outbox.md) records submission intents atomically and
provides bounded, fenced delivery leases. An explicit one-pass dispatcher delivers to a durable inbox; revision verification and execution remain blocked.
