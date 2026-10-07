from fastapi import Depends, FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from adwe.api.audit import router as audit_router
from adwe.api.auth import require_operator
from adwe.api.middleware import RequestIDMiddleware
from adwe.api.patch_apply import router as patch_apply_router
from adwe.api.patch_preview import router as patch_preview_router
from adwe.api.patches import router as patches_router
from adwe.api.pull_request_records import router as pull_request_records_router
from adwe.api.pull_requests import router as pull_requests_router
from adwe.api.queue import router as queue_router
from adwe.api.queue_metrics import router as queue_metrics_router
from adwe.api.repositories import router as repositories_router
from adwe.api.worker_health import router as worker_health_router
from adwe.api.workflow_analytics import router as workflow_analytics_router
from adwe.api.workflow_leaderboard import router as workflow_leaderboard_router
from adwe.api.workflow_metrics import router as workflow_metrics_router
from adwe.api.workflow_timeline import router as workflow_timeline_router
from adwe.api.workflows import router as workflows_router
from adwe.core.logging import configure_logging
from adwe.db.session import engine

configure_logging()

app = FastAPI(
    dependencies=[Depends(require_operator)],
    title="Agentic Development Workflow Engine",
    description="A platform for repository analysis, agentic planning, patch generation, test execution, audit logging, and pull request automation.",
    version="0.1.0",
)

app.add_middleware(RequestIDMiddleware)
app.include_router(repositories_router)
app.include_router(workflow_timeline_router)
app.include_router(workflows_router)
app.include_router(worker_health_router)
app.include_router(workflow_metrics_router)
app.include_router(workflow_leaderboard_router)
app.include_router(workflow_analytics_router)
app.include_router(audit_router)
app.include_router(patches_router)
app.include_router(patch_apply_router)
app.include_router(patch_preview_router)
app.include_router(pull_requests_router)
app.include_router(pull_request_records_router)
app.include_router(queue_router)
app.include_router(queue_metrics_router)


Instrumentator().instrument(app).expose(app)


@app.get("/v1/health", tags=["health"])
async def health():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))

    return {"status": "ok", "database": "ok"}
