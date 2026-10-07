import asyncio
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from adwe.api import patches
from adwe.api.app import app
from adwe.domain.patch_decision import PatchDecisionConflict, diff_digest
from adwe.models.audit_event import AuditEvent
from adwe.models.patch import Patch
from adwe.models.patch_status import PatchStatus
from adwe.models.workflow import Workflow
from adwe.services.patch_decisions import decide_patch

DIFF = "diff --git a/README.md b/README.md\n+reviewed content\n"


@pytest.fixture
def proposal(registry_database):
    engine, _, _ = registry_database
    workflow_id, patch_id = str(uuid4()), str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            Workflow.__table__.insert().values(
                id=workflow_id,
                repository_url="https://github.com/a/b",
                status="completed",
            )
        )
        conn.execute(
            Patch.__table__.insert().values(
                id=patch_id,
                workflow_id=workflow_id,
                file_path="README.md",
                diff=DIFF,
                status="proposed",
            )
        )
    return workflow_id, patch_id


def test_review_api_is_content_bound_auditable_and_not_execution(
    registry_database, proposal, operator_headers, monkeypatch
):
    engine, sessions, _ = registry_database
    monkeypatch.setattr(patches, "AsyncSessionLocal", sessions)
    workflow_id, patch_id = proposal
    path = f"/v1/workflows/{workflow_id}/patches/{patch_id}"
    payload = {"expected_diff_sha256": diff_digest(DIFF)}
    with TestClient(app, headers=operator_headers) as client:
        assert client.post(path + "/approve").status_code == 422
        bad = client.post(path + "/approve", json={"expected_diff_sha256": "0" * 64})
        assert bad.status_code == 409
        assert bad.json()["detail"]["code"] == "patch_changed"
        approved = client.post(path + "/approve", json=payload)
        assert approved.status_code == 200
        body = approved.json()
        assert body["status"] == "approved"
        assert body["commit_sha"] is None
        assert body["approved_diff_sha256"] == body["diff_sha256"] == diff_digest(DIFF)
        assert body["approved_by"] == "test-operator"
        repeated = client.post(path + "/approve", json=payload)
        assert repeated.json()["approved_at"] == body["approved_at"]
        assert client.post(path + "/apply").status_code == 503
        summary = client.get(f"/v1/workflows/{workflow_id}/patches-summary").json()
        assert summary["approved"] == 1 and summary["applied"] == 0
        rejected = client.post(path + "/reject", json=payload)
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["approved_by"] is None
        assert client.post(path + "/reject", json=payload).status_code == 200
        assert client.post(path + "/approve", json=payload).status_code == 409
        assert (
            client.post(
                f"/v1/workflows/wrong/patches/{patch_id}/approve", json=payload
            ).status_code
            == 404
        )
    with engine.connect() as conn:
        events = conn.execute(
            select(AuditEvent.event_type, AuditEvent.payload).order_by(
                AuditEvent.created_at, AuditEvent.id
            )
        ).all()
        assert [event[0] for event in events] == ["patch.approved", "patch.rejected"]
        assert all(event[1]["actor_id"] == "test-operator" for event in events)
        assert all(event[1]["diff_sha256"] == diff_digest(DIFF) for event in events)


@pytest.mark.asyncio
async def test_concurrent_approvals_create_one_audit_transition(
    registry_database, proposal
):
    _, sessions, _ = registry_database
    workflow_id, patch_id = proposal

    async def approve():
        async with sessions() as session, session.begin():
            return await decide_patch(
                session,
                workflow_id,
                patch_id,
                PatchStatus.APPROVED,
                diff_digest(DIFF),
                "operator",
            )

    await asyncio.gather(approve(), approve())
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 1
        assert (await session.get(Patch, patch_id)).status == "approved"


@pytest.mark.asyncio
async def test_decision_and_audit_rollback_together(registry_database, proposal):
    _, sessions, _ = registry_database
    workflow_id, patch_id = proposal
    with pytest.raises(RuntimeError):
        async with sessions() as session, session.begin():
            await decide_patch(
                session,
                workflow_id,
                patch_id,
                PatchStatus.APPROVED,
                diff_digest(DIFF),
                "operator",
            )
            raise RuntimeError("injected failure before commit")
    async with sessions() as session:
        assert (await session.get(Patch, patch_id)).status == "proposed"
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 0


@pytest.mark.asyncio
async def test_approved_content_cannot_change_without_revocation(
    registry_database, proposal
):
    engine, sessions, _ = registry_database
    workflow_id, patch_id = proposal
    async with sessions() as session, session.begin():
        await decide_patch(
            session,
            workflow_id,
            patch_id,
            PatchStatus.APPROVED,
            diff_digest(DIFF),
            "operator",
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            update(Patch)
            .where(Patch.id == patch_id)
            .values(diff=DIFF + "+unreviewed\n")
        )
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(update(Patch).where(Patch.id == patch_id).values(status="applied"))


@pytest.mark.asyncio
async def test_orphaned_patch_cannot_be_approved(registry_database):
    engine, sessions, _ = registry_database
    patch_id = str(uuid4())
    with engine.begin() as conn:
        conn.execute(
            Patch.__table__.insert().values(
                id=patch_id,
                workflow_id="missing",
                file_path="README.md",
                diff=DIFF,
                status="proposed",
            )
        )
    with pytest.raises(PatchDecisionConflict, match="no workflow"):
        async with sessions() as session, session.begin():
            await decide_patch(
                session,
                "missing",
                patch_id,
                PatchStatus.APPROVED,
                diff_digest(DIFF),
                "operator",
            )


def test_legacy_migration_quarantines_without_inventing_success(registry_database):
    engine, _, config = registry_database
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "7b91e2c40a16")
        for status in (
            "proposed",
            "rejected",
            "applied",
            "applying",
            "failed",
            "unrecognized",
        ):
            conn.execute(
                text("""INSERT INTO patches
                (id,workflow_id,file_path,diff,status,created_at,commit_sha)
                VALUES (:status,'legacy-workflow','README.md','legacy diff',:status,CURRENT_TIMESTAMP,:sha)"""),
                {"status": status, "sha": "a" * 40 if status == "applied" else None},
            )
        command.upgrade(config, "head")
    with engine.connect() as conn:
        rows = conn.execute(
            select(Patch.id, Patch.status, Patch.legacy_status, Patch.commit_sha)
        ).all()
        by_id = {row.id: row for row in rows}
        assert by_id["proposed"].status == "proposed"
        assert by_id["rejected"].status == "rejected"
        for old in ("applied", "applying", "failed", "unrecognized"):
            assert by_id[old].status == "requires_review"
            assert by_id[old].legacy_status == old
        assert by_id["applied"].commit_sha == "a" * 40
        assert conn.scalar(select(func.count()).select_from(AuditEvent)) == 4
    with (
        pytest.raises(DBAPIError, match="require reconciliation"),
        engine.begin() as conn,
    ):
        config.attributes["connection"] = conn
        command.downgrade(config, "7b91e2c40a16")


@pytest.mark.asyncio
async def test_concurrent_approve_reject_never_revives_rejection(
    registry_database, proposal
):
    _, sessions, _ = registry_database
    workflow_id, patch_id = proposal

    async def decide(target):
        try:
            async with sessions() as session, session.begin():
                await decide_patch(
                    session,
                    workflow_id,
                    patch_id,
                    target,
                    diff_digest(DIFF),
                    "operator",
                )
            return "accepted"
        except PatchDecisionConflict:
            return "conflict"

    outcomes = await asyncio.gather(
        decide(PatchStatus.APPROVED), decide(PatchStatus.REJECTED)
    )
    assert outcomes[1] == "accepted"
    async with sessions() as session:
        patch = await session.get(Patch, patch_id)
        assert patch.status == "rejected"
        assert patch.approved_diff_sha256 is None
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) in (
            1,
            2,
        )
