"""Separate review decisions from execution and quarantine ambiguous legacy rows."""

import sqlalchemy as sa
from alembic import op

revision = "8c20d4e61f73"
down_revision = "7b91e2c40a16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patches", sa.Column("approved_by", sa.String(64), nullable=True))
    op.add_column(
        "patches", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "patches", sa.Column("approved_diff_sha256", sa.String(64), nullable=True)
    )
    op.add_column("patches", sa.Column("legacy_status", sa.String(), nullable=True))
    # Neither a commit SHA nor the old APPLIED label proves validated application.
    op.execute("""INSERT INTO audit_events (id, workflow_id, event_type, payload, created_at)
        SELECT 'migration-8c20d4e61f73-' || id, workflow_id, 'patch.legacy_quarantined',
            json_build_object('patch_id', id, 'previous_status', status, 'migration', '8c20d4e61f73'),
            CURRENT_TIMESTAMP
        FROM patches WHERE status NOT IN ('proposed', 'rejected')""")
    op.execute(
        "UPDATE patches SET legacy_status = status, status = 'requires_review' WHERE status NOT IN ('proposed', 'rejected')"
    )
    op.create_check_constraint(
        "ck_patches_status",
        "patches",
        "status IN ('proposed','approved','applying','applied','rejected','failed','requires_review')",
    )
    op.create_check_constraint(
        "ck_patches_approval_evidence",
        "patches",
        "(status IN ('approved','applying','applied') AND approved_by IS NOT NULL "
        "AND approved_by ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$' AND approved_at IS NOT NULL "
        "AND approved_diff_sha256 IS NOT NULL "
        "AND approved_diff_sha256 = encode(sha256(convert_to(diff, 'UTF8')), 'hex')) "
        "OR (status NOT IN ('approved','applying','applied') AND approved_by IS NULL "
        "AND approved_at IS NULL AND approved_diff_sha256 IS NULL)",
    )
    op.create_check_constraint(
        "ck_patches_applied_commit",
        "patches",
        "status <> 'applied' OR (commit_sha IS NOT NULL AND commit_sha ~ '^([0-9a-f]{40}|[0-9a-f]{64})$')",
    )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM patches WHERE legacy_status IS NOT NULL OR approved_by IS NOT NULL
                   OR status IN ('approved', 'requires_review')) THEN
            RAISE EXCEPTION 'Patch decisions or quarantined history require reconciliation before downgrade';
        END IF;
    END $$""")
    op.drop_constraint("ck_patches_applied_commit", "patches", type_="check")
    op.drop_constraint("ck_patches_approval_evidence", "patches", type_="check")
    op.drop_constraint("ck_patches_status", "patches", type_="check")
    for column in (
        "legacy_status",
        "approved_diff_sha256",
        "approved_at",
        "approved_by",
    ):
        op.drop_column("patches", column)
