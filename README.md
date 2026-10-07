# Agentic Development Workflow Engine

![CI](https://github.com/jennasilvera/adwe/actions/workflows/ci.yml/badge.svg)

ADWE is being rebuilt as a controlled, durable platform for AI-assisted repository changes.
The existing Python/FastAPI/PostgreSQL/ARQ/LangGraph implementation is a prototype.
It is **not production ready**.

## Current operating mode

Live repository acquisition, workflow mutations, host test execution and GitHub publication
are disabled by containment policy. Mutating API requests return `503` with
`detail.code = "operation_unavailable"`. Existing queued workflow/patch jobs also reject
before operational effects. There is no environment switch to bypass containment.

Available capabilities:

- Offline rule-based planning and Markdown proposal generation from supplied inventory.
- Diff preview at `POST /v1/patch-workflows/preview` without clone or execution.
- OpenAPI documentation at `/docs` and `/openapi.json`.
- Existing persisted workflow, patch, audit, timeline and aggregate read APIs when their
  PostgreSQL/Redis dependencies are available.
- Local Git fixture tests and development of the future trusted execution interfaces.

Read APIs are not authenticated yet. Run only in a trusted development environment without
production credentials or sensitive data. See [SECURITY.md](SECURITY.md) for the precise
containment contract, residual risks and rollout procedure.

## Engineering documents

- [Current-state assessment](CURRENT_STATE_ASSESSMENT.md): source evidence and verified baseline.
- [Architecture](ARCHITECTURE.md): implemented versus target system and trust boundaries.
- [Production-readiness gaps](PRODUCTION_READINESS_GAP_ANALYSIS.md): prioritized blockers.
- [Implementation roadmap](IMPLEMENTATION_ROADMAP.md): independently verifiable phases.

The target product authorizes typed model proposals, executes them in isolated workspaces,
and records revision-bound validation and publication evidence. Durable execution,
repository authorization, real task implementation, isolated tests and safe publication
remain roadmap work, not capabilities established by this release.

## Local development

Python 3.12+ and uv are required. Git is needed by local fixture tests.

```bash
uv sync --frozen
PYTHONPATH=src uv run --frozen pytest -q
```

The existing timeline test requires PostgreSQL and migrated tables even though it resides
under `tests/unit`. A missing database causes a real test failure; do not interpret the suite
as entirely infrastructure-free. CI provisions PostgreSQL and applies migrations before tests.

For development infrastructure only:

```bash
docker compose up -d postgres redis
```

Compose exposes PostgreSQL on host port **5433**, while the existing Alembic config defaults
to port **5432**. To use the Compose database, set `sqlalchemy.url` in a local `alembic.ini`
to `postgresql+psycopg://adwe:adwe@127.0.0.1:5433/adwe`, then run:

```bash
PYTHONPATH=src uv run --frozen alembic upgrade head
DATABASE_URL=postgresql+asyncpg://adwe:adwe@127.0.0.1:5433/adwe \
  PYTHONPATH=src uv run --frozen uvicorn adwe.api.app:app --host 127.0.0.1
```

Use the same DATABASE_URL when running the full test suite against that database. The sample
credentials are local development values only. The split migration/application configuration
is a tracked gap, not a recommended production setup. Settings currently read environment
variables; creating a `.env` file alone does not configure the standalone application.

Do not start a worker expecting live execution in containment mode. Existing Docker/Compose
files are development scaffolding and do not provide the required isolated execution plane.

## Preview example

```bash
curl -X POST http://127.0.0.1:8000/v1/patch-workflows/preview \
  -H 'Content-Type: application/json' \
  -d '{"repository_url":"https://github.com/example/project","branch_name":"adwe/preview","diff":"diff --git a/README.md b/README.md\n","commit_message":"Preview only"}'
```

Preview extracts a summary; it is not proof that a patch is valid, safe, authorized or tested.
