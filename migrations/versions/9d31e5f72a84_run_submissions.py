"""Persist immutable unverified run submissions.

Revision ID: 9d31e5f72a84
Revises: 8c20d4e61f73
"""

import sqlalchemy as sa
from alembic import op

revision = "9d31e5f72a84"
down_revision = "8c20d4e61f73"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "run_submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("repositories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("canonical_input", sa.Text(), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "actor_id", "request_key", name="uq_run_submission_request"
        ),
        sa.CheckConstraint(
            "actor_id ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'", name="ck_submission_actor"
        ),
        sa.CheckConstraint(
            "request_key ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$'",
            name="ck_submission_key",
        ),
        sa.CheckConstraint(
            "input_digest = encode(sha256(convert_to('adwe.run-input.v1', 'UTF8') || decode('00', 'hex') || convert_to(canonical_input, 'UTF8')), 'hex')",
            name="ck_submission_digest",
        ),
        sa.CheckConstraint(
            "(canonical_input::jsonb ->> 'repository_id') IS NOT NULL AND canonical_input::jsonb ->> 'repository_id' = repository_id",
            name="ck_submission_repository",
        ),
    )
    op.execute("""CREATE FUNCTION reject_submission_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'Run submissions are immutable';
        END $$""")
    op.execute("""CREATE TRIGGER run_submissions_immutable
        BEFORE UPDATE OR DELETE ON run_submissions FOR EACH ROW
        EXECUTE FUNCTION reject_submission_mutation()""")


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM run_submissions) THEN
            RAISE EXCEPTION 'Run submissions must be preserved; populated downgrade refused';
        END IF;
    END $$""")
    op.drop_table("run_submissions")
    op.execute("DROP FUNCTION reject_submission_mutation()")
