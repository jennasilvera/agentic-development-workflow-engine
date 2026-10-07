# Current-state assessment

Assessed 2026-10-07 against `a37fc64812fcda06af70d897b553a97897cf9e1f`.
This is a source review and local test baseline, not a production certification.
The subsequent containment change is described separately in `SECURITY.md`.

## Conclusion

ADWE is a working prototype of repository inspection, plan generation, patch proposals,
and separately invoked patch/PR operations. It is not yet a safe autonomous development
platform. Retain its modular Python layout, FastAPI contracts, SQLAlchemy/Alembic foundation,
and useful Git fixture tests. Establish security boundaries and durable lifecycle semantics
before expanding agents or analytics.

## Inspection coverage

Reviewed all 170 tracked files: application code, all 62 baseline test modules, all 16 migration
revisions, migration configuration/template, deployment/CI configuration, documentation,
and dependency manifest. Inspected the lock through a successful frozen install.
There is no repository AGENTS.md. No application files were changed before this assessment.

| Area | Existing implementation | Disposition |
| --- | --- | --- |
| API | 16 route modules; workflows, patches, PRs, summaries, audit, queue/worker health, analytics | Refactor: preserve documented paths while establishing authenticated application services |
| Orchestration | `workflows/engine.py`: three synchronous nodes, analysis → plan → modification | Redesign durable execution; retain LangGraph provisionally |
| Domain | Four ORM tables: workflows, patches, pull_requests, audit_events; string statuses and JSON blobs | Redesign lifecycle/relations; migrate existing data explicitly |
| Agents | Filename/framework heuristics; rule-based or optional LLM plan; Markdown artifact generator | Retain useful deterministic inventory; replace generic artifact generator for real task implementation |
| Model access | `services/llm.py`: synchronous OpenAI-compatible chat call | Refactor behind typed gateway; Anthropic, budgets and usage accounting missing |
| Queue | Redis/ARQ, workflow and patch jobs | Retain initially; fix delivery/transaction boundaries before considering replacement |
| Workspace | Temporary directory and fresh clone | Replace as execution isolation; retain temp directory mechanics inside future isolated executor |
| Git | Small clone/apply/branch/commit/push helpers | Refactor; duplicate branch and clone logic, no revision pinning or execution limits |
| GitHub | Token-based PR POST, hardcoded `master`, persisted PR record | Redesign authorization, App identity and reconciliation |
| Audit | Transactional insertion helper and list/timeline endpoints | Retain helper concept; add actor, revision, step and policy provenance |
| Observability | Text logging, request ID header, HTTP metrics, DB aggregate endpoints | Refactor; JSON logs, trace propagation and workflow telemetry missing |
| Tests | 73 collected tests, mostly schema/import/OpenAPI assertions, some real local Git tests | Retain useful checks; add behavior, concurrency, failure and adversarial coverage |
| CI/container | Pytest + Compose config; one-stage root image with dev dependencies | Harden; migrations, static checks, image/smoke validation missing |
| Documentation | README plus minimal diagram; contradictory current/planned capabilities | Replace capability claims with current versus target architecture |
| Entrypoint/duplicates | `main.py` prints greeting; `github_branch.py` duplicates branch operations | Remove/consolidate after caller inventory; no speculative deletion in first increment |

## Verified baseline

- `uv sync --frozen`: succeeded on Python 3.12.14.
- `PYTHONPATH=src uv run --frozen pytest -q --tb=short`: **72 passed, 1 failed**.
- Failure: `test_workflow_timeline_route_registered` requires live PostgreSQL despite its
  location under unit tests; connection to localhost:5432 refused in this environment.
- Two warnings: Starlette/httpx deprecation and pytest discovery of `TestExecutionError`.
- Docker and PostgreSQL executables are unavailable here. No claim of successful container,
  database migration, end-to-end or recovery testing is made.
- No live model request, target-repository test execution, push or PR creation was exercised.

## Correctness and security blockers

1. `api/patch_apply.py` passes user-controlled `test_command` to
   `services/test_runner.py`, which invokes `subprocess.run` on the API host without
   authentication, command policy, timeout, resource limits or output cap. Argument arrays
   avoid shell interpolation but still permit arbitrary programs. Even fixed pytest commands
   execute arbitrary repository code. Removing only GITHUB_TOKEN from the environment does
   not protect database/model credentials, host files or network access.
2. Both `agents/repository_analyzer.py` and `services/repository_clone.py` embed the GitHub
   token into clone URLs. Git can retain that URL in `.git/config`; error text may include it.
   Analyzer reads may follow file symlinks outside checkout. No repository authorization,
   pinned revision, bounded inventory, clone timeout or egress policy exists.
3. `api/pull_requests.py` calls GitHub before validating the optional workflow ID. Direct PR
   creation bypasses patch validation. Missing token returns a success-shaped `skipped`
   result. No approval identity, verified changeset, idempotency key or ambiguous-outcome
   reconciliation exists.
4. `api/patches.py` marks approval as APPLIED, permitting repeated application after actual
   application. Rejection references undefined `job_id`. Worker assigns APPLYING without
   checking previous status or obtaining exclusive ownership. No enforced transition table.
5. `api/workflows.py` enqueues before database commit. Worker can observe no row and return,
   or a queue message can survive a rolled-back transaction. Similar race exists for patches.
6. Worker unconditionally moves any workflow to RUNNING. No lease, fencing, duplicate-delivery
   protection, cancellation, resume, stale-run reconciliation or terminal-state enforcement.
   Graph is compiled without a checkpointer. Entire result is stored after graph execution;
   bounded whole-run retries are not durable node recovery. Retry failure categories are absent.
7. Fresh clones for analysis and application can refer to different HEADs. Multiple independent
   patches use the same workflow branch name, without a persisted aggregate changeset.
8. Code modifier always emits new-file Markdown, including when its selected target is a
   GitHub Actions YAML path. It cannot implement arbitrary user engineering tasks; input
   `WorkflowCreate` does not even contain a task specification. Existing files produce
   conflicting new-file diffs. File-name counts are not architecture understanding.

## Persistence, operations and observability

- No foreign keys link the four tables, no status/check constraints, no business uniqueness
  constraints or query indexes beyond primary keys. No repositories, revisions, attempts,
  steps, checkpoints, approval identities, model/tool invocations or artifact catalog.
- Audit rows are insertion-oriented in application code but not protected against database
  mutation; agent audit events are recorded after the entire graph returns, losing failed-node
  context. Payloads can retain raw prompts, provider responses and command errors.
- Async routes/workers perform synchronous cloning, model calls, tests and Git operations;
  event-loop blocking undermines cancellation and worker health. Heartbeat is only written
  when a workflow starts; Redis pools are repeatedly created and not closed.
- Settings have local credentials/defaults and no production mode validation. Alembic uses a
  separate hardcoded URL in alembic.ini rather than application DATABASE_URL.
- Compose exposes API/database/Redis ports, has no readiness health checks or migration job.
  Dockerfile omits migrations and Alembic config, runs as root, has no multi-stage build,
  .dockerignore, explicit health check or dependency separation.
- CI runs unlocked `uv sync`, no migration application, no lint/type/security checks, no
  Docker build. Branch protection was not verified. Installed package versions are locked
  but actions/images use moving tags.
- List endpoints have no pagination or access control. Errors have inconsistent shapes.
  Request IDs are not propagated to durable jobs; tracing is missing. Leaderboard queries
  are N+1 and patch-type analytics count top-target entries rather than all patches.

## Testing and scope discipline

OpenAPI registration tests do not verify route behavior. `test_agent_audit_events.py` checks
only a locally constructed set; worker test-gate test searches source text. There are no
real DB/migration, crash/concurrency, hostile repository, provider adapter or replay tests.
The isolated Git tests are useful but cannot establish a safe execution boundary.
There are no explicit TODO/FIXME markers identifying these gaps.

Analytics, leaderboard and priority scores are ahead of lifecycle correctness. Stop expanding
these surfaces until the execution and authorization boundaries are proven. Redis is already
present: removing it now adds migration risk without measured benefit. No additional broker,
vector store, service mesh or Kubernetes deployment is justified by this review.

## First increment verification (local)

Containment regression suite plus unchanged baseline tests: **96 passed, 1 failed**;
only remaining failure is the same unavailable-PostgreSQL timeline test. No tests were
skipped, deleted or weakened to hide that failure. Three legacy test contracts were updated
because host execution, tokenless PR skipping and push are now explicitly unavailable.

Targeted Ruff checks pass for both new policy modules, guarded clone/test-runner modules
and affected/new unit tests. Mypy passes for the two new policy modules with imported
implementation checking skipped; this is not a claim of whole-repository type safety.
Whole-repository Ruff reports 18 remaining findings in legacy code, including the already
identified undefined `job_id`; the corresponding mutation route is contained, not repaired.
Tools used: Ruff 0.16.10, mypy 2.4.0 (verification environment only, not added runtime deps).

Alembic has one head (`b4741e3f30d9`); offline upgrade SQL generation succeeds across all
16 revisions. Offline SQL generation does not verify actual migration execution or downgrade.
CI now uses a frozen dependency install and applies migrations against its PostgreSQL service
before pytest. Remote CI results must be checked separately. `git diff --check` passes.
