"""Atomic verification intents, without a dispatcher.

Revision ID: a042f6b83c95
Revises: 9d31e5f72a84
"""

import sqlalchemy as sa
from alembic import op

revision = "a042f6b83c95"
down_revision = "9d31e5f72a84"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "submission_outbox",
        sa.Column(
            "submission_id",
            sa.String(36),
            sa.ForeignKey("run_submissions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'leased', 'delivered', 'dead')",
            name="ck_outbox_status",
        ),
        sa.CheckConstraint("attempts BETWEEN 0 AND 5", name="ck_outbox_attempts"),
        sa.CheckConstraint(
            "(status = 'leased' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'leased' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_outbox_lease",
        ),
    )
    op.create_index(
        "ix_outbox_ready", "submission_outbox", ["status", "available_at", "created_at"]
    )
    op.execute("""CREATE FUNCTION create_submission_intent() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        INSERT INTO submission_outbox (submission_id) VALUES (NEW.id);
        RETURN NEW;
        END $$""")
    op.execute("""CREATE TRIGGER run_submission_intent AFTER INSERT ON run_submissions
        FOR EACH ROW EXECUTE FUNCTION create_submission_intent()""")
    # Existing unverified requests get a verification intent, never an execution job.
    op.execute(
        "INSERT INTO submission_outbox (submission_id) SELECT id FROM run_submissions"
    )


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM submission_outbox) THEN
            RAISE EXCEPTION 'Outbox evidence exists; populated downgrade refused';
        END IF;
    END $$""")
    op.execute("DROP TRIGGER run_submission_intent ON run_submissions")
    op.execute("DROP FUNCTION create_submission_intent()")
    op.drop_table("submission_outbox")
