# Agentic Development Workflow Engine

![CI](https://github.com/jennasilvera/adwe/actions/workflows/ci.yml/badge.svg)

ADWE is being rebuilt as a controlled, durable platform for AI-assisted repository changes.
The existing Python/FastAPI/PostgreSQL/ARQ/LangGraph implementation is a prototype.
It is **not production ready**.

## Current operating mode

Live repository acquisition, workflow mutations, host test execution and GitHub publication
are disabled by containment policy. Authenticated live-workflow mutation requests return `503` with
`detail.code = "operation_unavailable"`. Existing queued workflow/patch jobs also reject
before operational effects. There is no environment switch to bypass containment.

Available capabilities:

- Offline rule-based planning and Markdown proposal generation from supplied inventory.
- Diff preview at `POST /v1/patch-workflows/preview` without clone or execution.
- Authenticated repository registration, listing and enable/disable administration at `/v1/repositories`.
- OpenAPI documentation at `/docs` and `/openapi.json`.
- Existing persisted workflow, patch, audit, timeline and aggregate read APIs when their
  PostgreSQL/Redis dependencies are available.
- Local Git fixture tests and development of the future trusted execution interfaces.

Application endpoints now require the configured operator bearer token, including read APIs,
preview, health and metrics. Docs/OpenAPI remain public metadata. The single operator has access
to all deployment data; multitenant authorization is not implemented. Continue using a trusted
development environment. See [SECURITY.md](SECURITY.md) for the precise
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

Run `PYTHONPATH=src uv run --frozen pytest tests/unit -q` for the infrastructure-free suite.
`tests/integration` requires real PostgreSQL; unavailable infrastructure fails rather than
silently skipping tests. CI runs both suites. The timeline test was moved into integration
without replacing its database with a mock. Registry tests create and drop isolated random
schemas; use a disposable test database and a role allowed to create schemas.
Set `ADWE_TEST_DATABASE_URL` for registry integration fixtures and `DATABASE_URL` for the API/
timeline test to point at that test database.

For development infrastructure only:

```bash
docker compose up -d postgres redis
```

Compose exposes PostgreSQL on host port **5433**. Application and Alembic now share
`DATABASE_URL`; Alembic selects the synchronous psycopg driver internally.

```bash
export DATABASE_URL=postgresql+asyncpg://adwe:adwe@127.0.0.1:5433/adwe
export ADWE_TEST_DATABASE_URL="$DATABASE_URL"
PYTHONPATH=src uv run --frozen alembic upgrade head
```

Configure the operator credential before starting the API. Generate a random token and keep
it in a secret manager; this shell example holds it only for the current session:

```bash
export ADWE_OPERATOR_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export API_TOKEN_SHA256="$(python -c 'import hashlib, os; print(hashlib.sha256(os.environ["ADWE_OPERATOR_TOKEN"].encode()).hexdigest())')"
export API_OPERATOR_ID=operator
PYTHONPATH=src uv run --frozen uvicorn adwe.api.app:app --host 127.0.0.1
```

`ADWE_OPERATOR_TOKEN` is a client-side example variable, not an application setting. The server
needs only the digest and actor ID. Configure those variables explicitly in your deployment;
Compose passes them to the API when supplied by the operator. Restart all API instances when
rotating the digest, and retain the actor ID. Do not put raw credentials in tracked files.
The sample database credentials are local development values only.

Missing authentication config returns `503 authentication_unconfigured`; incorrect or missing
bearer returns `401 unauthorized`. The operator token does not bypass execution containment.

Do not start a worker expecting live execution in containment mode. Existing Docker/Compose
files are development scaffolding and do not provide the required isolated execution plane.

## Preview example

```bash
curl -X POST http://127.0.0.1:8000/v1/patch-workflows/preview \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $ADWE_OPERATOR_TOKEN" \
  -d '{"repository_url":"https://github.com/example/project","branch_name":"adwe/preview","diff":"diff --git a/README.md b/README.md\n","commit_message":"Preview only"}'
```

Preview extracts a summary; it is not proof that a patch is valid, safe, authorized or tested.

## Repository registration

```bash
curl -X POST http://127.0.0.1:8000/v1/repositories \
  -H "Authorization: Bearer $ADWE_OPERATOR_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"repository_url":"https://github.com/example/project"}'
```

New registrations return 201; canonical duplicates return the same record with 200. Repeating
registration does not re-enable a disabled repository. `GET /v1/repositories?limit=50&offset=0`
returns bounded pages; `PATCH /v1/repositories/{id}` accepts only `{"enabled":false}` or
`{"enabled":true}`. This is metadata-only registration: no clone, GitHub call or run is started.
See [ADR 001](docs/adr/001-single-operator-admission.md) for scope and trust assumptions.
