from adwe.workflows.state import WorkflowState

DOCUMENTATION_TARGETS = frozenset(
    {
        "ADWE_ANALYSIS.md",
        "docs/adwe-migration-validation.md",
        "docs/adwe-docker-healthchecks.md",
        "docs/adwe-api-surface.md",
        "docs/adwe-ci-recommendations.md",
    }
)


def _validate_documentation_target(path: str) -> str:
    if not isinstance(path, str) or path not in DOCUMENTATION_TARGETS:
        raise ValueError("Legacy proposals support only fixed documentation targets")
    return path


def _new_file_patch(path: str, content: str) -> str:
    _validate_documentation_target(path)
    lines = content.splitlines()
    added_lines = "".join(f"+{line}\n" for line in lines)

    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
        f"{added_lines}"
    )


def _score_target(target_file: str) -> tuple[int, str]:
    if target_file == "docs/adwe-ci-recommendations.md":
        return 95, "CI recommendations concern validation across all contributors."

    if "migration" in target_file:
        return 85, "Migration validation reduces production database deployment risk."

    if "docker" in target_file or "healthcheck" in target_file:
        return 75, "Docker health checks improve local and CI environment reliability."

    if "api" in target_file:
        return (
            65,
            "API surface documentation improves maintainability and test planning.",
        )

    if target_file.startswith("docs/"):
        return (
            45,
            "Documentation improves project clarity but has lower runtime impact.",
        )

    return 30, "General repository artifact with limited operational impact."


def _default_candidate_targets(analysis: dict, plan: dict) -> list[str]:
    target_file, _ = _select_patch_target(analysis, plan)
    return [target_file]


def _select_patch_target(analysis: dict, plan: dict) -> tuple[str, str]:
    tools = analysis.get("detected_tools", {})
    steps = plan.get("recommended_next_steps", [])
    candidate_targets = plan.get("candidate_targets", [])

    if candidate_targets:
        target = _validate_documentation_target(candidate_targets[0])
        return target, f"Generated analysis documentation proposal for {target}."

    if tools.get("alembic") and any(
        "migration validation" in step.lower() for step in steps
    ):
        return (
            "docs/adwe-migration-validation.md",
            "Generated migration validation documentation.",
        )

    if tools.get("docker") and any("health checks" in step.lower() for step in steps):
        return (
            "docs/adwe-docker-healthchecks.md",
            "Generated Docker Compose health check recommendations.",
        )

    if tools.get("fastapi") and analysis.get("api_routes"):
        return (
            "docs/adwe-api-surface.md",
            "Generated API surface analysis documentation.",
        )

    return "ADWE_ANALYSIS.md", "Generated repository-specific ADWE analysis artifact."


def _analysis_markdown(analysis: dict, plan: dict, target_file: str) -> str:
    tools = analysis.get("detected_tools", {})
    architecture = plan.get("architecture", {})
    strengths = plan.get("strengths", [])
    risks = plan.get("risks", [])
    steps = plan.get("recommended_next_steps", [])

    priority_score, priority_reason = _score_target(target_file)

    lines = [
        "# ADWE Generated Artifact",
        "",
        f"Target file: `{target_file}`",
        f"Priority score: {priority_score}",
        f"Priority reason: {priority_reason}",
        "",
        "This is an unvalidated analysis proposal, not an implemented task or test result.",
        "",
        "## Repository Summary",
        "",
        f"- Files analyzed: {analysis.get('file_count', 0)}",
        f"- API routes detected: {architecture.get('api_route_count', 0)}",
        f"- Database models detected: {architecture.get('database_model_count', 0)}",
        f"- Migrations detected: {architecture.get('migration_count', 0)}",
        f"- Tests detected: {architecture.get('test_count', 0)}",
        "",
        "## Detected Tooling",
        "",
    ]

    for name, detected in sorted(tools.items()):
        status = "yes" if detected else "no"
        lines.append(f"- {name}: {status}")

    if strengths:
        lines.extend(["", "## Strengths", ""])
        lines.extend(f"- {item}" for item in strengths)

    if risks:
        lines.extend(["", "## Risks", ""])
        lines.extend(f"- {item}" for item in risks)

    if steps:
        lines.extend(["", "## Recommended Next Steps", ""])
        lines.extend(f"- {item}" for item in steps)

    lines.extend(["", "Generated as part of an agentic development workflow."])

    return "\n".join(lines) + "\n"


def _build_modification(analysis: dict, plan: dict, target_file: str) -> dict:
    _validate_documentation_target(target_file)
    content = _analysis_markdown(analysis, plan, target_file)
    patch = _new_file_patch(target_file, content)
    priority_score, priority_reason = _score_target(target_file)

    return {
        "status": "proposed",
        "artifact_kind": "analysis_documentation",
        "validation_status": "not_run",
        "summary": f"Generated analysis documentation proposal for {target_file}.",
        "patch": patch,
        "target_file": target_file,
        "priority_score": priority_score,
        "priority_reason": priority_reason,
        "based_on": {
            "file_count": analysis.get("file_count"),
            "detected_tools": analysis.get("detected_tools", {}),
            "recommended_steps": plan.get("recommended_next_steps", []),
        },
    }


def modify_code(state: WorkflowState):
    analysis = state["repository_analysis"]
    plan = state["implementation_plan"]

    candidate_targets = plan.get("candidate_targets") or _default_candidate_targets(
        analysis,
        plan,
    )

    if not isinstance(candidate_targets, list) or len(candidate_targets) > 20:
        raise ValueError("Candidate targets must be a bounded list")
    # Validate every supplied target, including ones beyond the output limit.
    for target in candidate_targets:
        _validate_documentation_target(target)
    candidate_targets = list(dict.fromkeys(candidate_targets))

    code_modifications = [
        _build_modification(analysis, plan, target) for target in candidate_targets[:3]
    ]

    code_modifications.sort(
        key=lambda modification: modification.get("priority_score", 0),
        reverse=True,
    )

    return {
        "code_modification": code_modifications[0],
        "code_modifications": code_modifications,
    }
