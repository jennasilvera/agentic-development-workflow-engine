"""Containment must reject before infrastructure and untrusted side effects."""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from adwe.api import patch_apply, patches, pull_requests, workflows
from adwe.api.app import app
from adwe.core.config import settings
from adwe.services import git_push, github_pr, patch_workflow, repository_clone
from adwe.services.execution_policy import (
    Operation,
    OperationUnavailable,
    require_operation,
)
from adwe.workers import patch_runner, workflow_runner

PATCH = {
    "repository_url": "https://github.com/example/project",
    "branch_name": "adwe/test",
    "diff": "untrusted diff text",
    "commit_message": "test",
    "test_command": ["sh", "-c", "touch /tmp/adwe-must-not-exist"],
    "push": True,
    "open_pr": True,
}


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/v1/workflows", {"repository_url": "https://github.com/example/project"}),
        ("/v1/workflows/run-1/run", None),
        ("/v1/workflows/run-1/patches/patch-1/approve", None),
        ("/v1/workflows/run-1/patches/patch-1/reject", None),
        ("/v1/workflows/run-1/patches/patch-1/apply?push=true&open_pr=true", None),
        ("/v1/patch-workflows/apply", PATCH),
        (
            "/v1/pull-requests",
            {
                "repository_url": "https://github.com/example/project",
                "branch_name": "adwe/test",
                "title": "test",
                "body": "test",
                "workflow_id": "missing-workflow",
            },
        ),
    ],
)
def test_api_denies_before_database_queue_or_external_effects(
    monkeypatch, path, payload, operator_headers
):
    forbidden = Mock(side_effect=AssertionError("Side effect reached before denial"))
    for module in (workflows, patches, pull_requests):
        monkeypatch.setattr(module, "AsyncSessionLocal", forbidden)
    monkeypatch.setattr(workflows, "enqueue_workflow_run", forbidden)
    monkeypatch.setattr(patches, "enqueue_patch_apply", forbidden)
    monkeypatch.setattr(pull_requests, "create_pull_request", forbidden)
    monkeypatch.setattr(patch_apply, "apply_patch_workflow", forbidden)

    with TestClient(app) as client:
        response = client.post(path, json=payload, headers=operator_headers)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "operation_unavailable"
    assert response.json()["detail"]["policy_version"] == "containment-v1"
    assert response.headers["x-request-id"]
    forbidden.assert_not_called()


def test_preview_remains_available_without_execution(monkeypatch, operator_headers):
    forbidden = Mock(side_effect=AssertionError("Preview must not execute"))
    monkeypatch.setattr(patch_apply, "apply_patch_workflow", forbidden)
    payload = {**PATCH, "diff": "diff --git a/readme.md b/readme.md\n+example\n"}
    with TestClient(app) as client:
        response = client.post(
            "/v1/patch-workflows/preview", json=payload, headers=operator_headers
        )
    assert response.status_code == 200
    assert response.json()["files_changed"] == ["readme.md"]
    forbidden.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("job", ["workflow", "patch"])
async def test_queued_jobs_deny_before_database_heartbeat_or_retry(monkeypatch, job):
    forbidden = Mock(side_effect=AssertionError("Infrastructure reached before denial"))
    heartbeat = AsyncMock()
    redis = Mock()
    redis.enqueue_job = AsyncMock()
    monkeypatch.setattr(workflow_runner, "AsyncSessionLocal", forbidden)
    monkeypatch.setattr(patch_runner, "AsyncSessionLocal", forbidden)
    monkeypatch.setattr(workflow_runner, "record_heartbeat", heartbeat)
    function = (
        workflow_runner.run_workflow
        if job == "workflow"
        else patch_runner.apply_patch_job
    )
    with pytest.raises(OperationUnavailable):
        await function({"redis": redis}, "legacy-queued-id")
    forbidden.assert_not_called()
    heartbeat.assert_not_awaited()
    redis.enqueue_job.assert_not_awaited()


def test_clone_rejected_before_git_even_with_credentials(monkeypatch, tmp_path):
    forbidden = Mock(side_effect=AssertionError("Clone executed"))
    monkeypatch.setattr(settings, "github_token", "synthetic-secret")
    monkeypatch.setattr(repository_clone.Repo, "clone_from", forbidden)
    with pytest.raises(OperationUnavailable):
        repository_clone.clone_repository(
            "https://github.com/example/project", tmp_path
        )
    forbidden.assert_not_called()
    assert repository_clone.build_clone_url("https://github.com/example/project") == (
        "https://github.com/example/project"
    )


def test_analyzer_cannot_bypass_acquisition_policy(monkeypatch):
    from adwe.agents.repository_analyzer import analyze_repository

    forbidden = Mock(side_effect=AssertionError("Clone executed"))
    monkeypatch.setattr(repository_clone.Repo, "clone_from", forbidden)
    with pytest.raises(OperationUnavailable):
        analyze_repository({"repository_url": "https://github.com/example/project"})
    forbidden.assert_not_called()


@pytest.mark.parametrize("dry_run", [False, True])
def test_patch_workflow_denied_before_workspace_creation(monkeypatch, dry_run):
    forbidden = Mock(side_effect=AssertionError("Workspace created"))
    monkeypatch.setattr(patch_workflow, "repository_workspace", forbidden)
    with pytest.raises(OperationUnavailable):
        patch_workflow.apply_patch_workflow(
            repository_url=PATCH["repository_url"],
            branch_name=PATCH["branch_name"],
            diff=PATCH["diff"],
            commit_message=PATCH["commit_message"],
            dry_run=dry_run,
            push=True,
            open_pr=True,
        )
    forbidden.assert_not_called()


@pytest.mark.parametrize("token", [None, "synthetic-secret"])
def test_publication_denied_before_git_or_http(monkeypatch, tmp_path, token):
    forbidden = Mock(side_effect=AssertionError("Remote effect attempted"))
    monkeypatch.setattr(settings, "github_token", token)
    monkeypatch.setattr(git_push.subprocess, "run", forbidden)
    monkeypatch.setattr(github_pr.httpx, "post", forbidden)
    with pytest.raises(OperationUnavailable):
        git_push.push_branch(tmp_path, "adwe/test")
    with pytest.raises(OperationUnavailable):
        github_pr.create_pull_request(
            "https://github.com/example/project", "adwe/test", "t", "b"
        )
    forbidden.assert_not_called()


@pytest.mark.parametrize("operation", list(Operation))
def test_decision_has_stable_code_and_safe_log(operation, caplog):
    with pytest.raises(OperationUnavailable) as caught:
        require_operation(operation)
    decision = caught.value.decision
    assert decision.operation == operation
    assert decision.policy_version == "containment-v1"
    assert caught.value.code == "operation_unavailable"
    assert f"operation={operation.value}" in caplog.text
