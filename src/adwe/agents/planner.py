import json

from adwe.services.llm import LLMError, generate_text, llm_available
from adwe.workflows.state import WorkflowState


def _candidate_targets(analysis: dict, recommended_steps: list[str]) -> list[str]:
    tools = analysis.get("detected_tools", {})
    targets: list[str] = []

    if tools.get("alembic") and any(
        "migration validation" in step.lower() for step in recommended_steps
    ):
        targets.append("docs/adwe-migration-validation.md")

    if tools.get("docker") and any(
        "health checks" in step.lower() for step in recommended_steps
    ):
        targets.append("docs/adwe-docker-healthchecks.md")

    if tools.get("fastapi") and analysis.get("api_routes"):
        targets.append("docs/adwe-api-surface.md")

    if tools.get("github_actions"):
        targets.append("docs/adwe-ci-recommendations.md")

    if not targets:
        targets.append("ADWE_ANALYSIS.md")

    return targets


def _rule_based_plan(analysis: dict) -> dict:
    tools = analysis.get("detected_tools", {})
    languages = analysis.get("languages", {})
    api_routes = analysis.get("api_routes", [])
    database_models = analysis.get("database_models", [])
    config_files = analysis.get("config_files", [])
    migration_files = analysis.get("migration_files", [])
    test_files = analysis.get("test_files", [])

    recommended_steps: list[str] = []
    risks: list[str] = []
    strengths: list[str] = []

    if tools.get("fastapi"):
        strengths.append("FastAPI API layer detected.")
    if tools.get("sqlalchemy"):
        strengths.append("SQLAlchemy persistence layer detected.")
    if tools.get("alembic"):
        strengths.append("Alembic migration system detected.")
    if tools.get("docker"):
        strengths.append("Docker-based local development detected.")
    if tools.get("github_actions"):
        strengths.append("GitHub Actions CI detected.")

    if not tools.get("github_actions"):
        recommended_steps.append("Add GitHub Actions CI for tests and linting.")
    if not tools.get("docker"):
        recommended_steps.append("Add Docker support for local development.")
    if tools.get("alembic") and migration_files:
        recommended_steps.append("Add migration validation to CI.")

    if len(test_files) < 10:
        risks.append("Test coverage appears light for a workflow automation platform.")
        recommended_steps.append(
            "Increase automated test coverage for API, workers, and services."
        )
    else:
        strengths.append("Substantial test suite detected.")

    if api_routes:
        recommended_steps.append(
            "Add endpoint-level smoke tests for all public API routes."
        )
    if database_models:
        recommended_steps.append(
            "Add database model relationship tests and migration regression tests."
        )
    if "docker-compose.yml" in config_files:
        recommended_steps.append(
            "Add Docker Compose health checks for Postgres, Redis, API, and worker."
        )

    recommended_steps.append("Add structured audit events for every agent transition.")
    recommended_steps.append(
        "Record evidence and limitations for each proposed repository change."
    )

    candidate_targets = _candidate_targets(analysis, recommended_steps)

    return {
        "summary": "Generated structured implementation plan from repository architecture analysis.",
        "detected_languages": languages,
        "detected_tools": tools,
        "architecture": {
            "api_route_count": len(api_routes),
            "database_model_count": len(database_models),
            "migration_count": len(migration_files),
            "test_count": len(test_files),
            "config_files": config_files,
        },
        "strengths": strengths,
        "risks": risks,
        "recommended_next_steps": recommended_steps,
        "candidate_targets": candidate_targets,
        "planner": "rule_based",
        "planner_trace": {
            "mode": "rule_based",
            "prompt": None,
            "raw_response": None,
            "fallback_used": False,
        },
    }


def _build_llm_prompt(analysis: dict) -> str:
    return (
        "You are a senior engineering-platform architect. "
        "Given this repository analysis, return a concise JSON implementation plan "
        "with keys: summary, strengths, risks, recommended_next_steps, candidate_targets. "
        "candidate_targets must be documentation proposal paths from this list: ADWE_ANALYSIS.md, docs/adwe-migration-validation.md, docs/adwe-docker-healthchecks.md, docs/adwe-api-surface.md, docs/adwe-ci-recommendations.md. "
        "Do not include markdown.\n\n"
        f"{json.dumps(analysis, indent=2)}"
    )


def _llm_plan(analysis: dict) -> dict:
    prompt = _build_llm_prompt(analysis)
    text = generate_text(prompt)
    parsed = json.loads(text)

    fallback = _rule_based_plan(analysis)
    fallback.update(
        {
            "summary": parsed.get("summary", fallback["summary"]),
            "strengths": parsed.get("strengths", fallback["strengths"]),
            "risks": parsed.get("risks", fallback["risks"]),
            "recommended_next_steps": parsed.get(
                "recommended_next_steps",
                fallback["recommended_next_steps"],
            ),
            "candidate_targets": parsed.get(
                "candidate_targets",
                fallback["candidate_targets"],
            ),
            "planner": "llm",
            "planner_trace": {
                "mode": "llm",
                "prompt": prompt,
                "raw_response": text,
                "fallback_used": False,
            },
        }
    )
    return fallback


def create_plan(state: WorkflowState):
    analysis = state["repository_analysis"]

    if llm_available():
        try:
            plan = _llm_plan(analysis)
        except (LLMError, json.JSONDecodeError, TypeError, KeyError) as exc:
            plan = _rule_based_plan(analysis)
            plan["planner_fallback_reason"] = "llm_failed"
            plan["planner_trace"]["fallback_used"] = True
            plan["planner_trace"]["fallback_reason"] = str(exc)

    else:
        plan = _rule_based_plan(analysis)

    return {"implementation_plan": plan}
