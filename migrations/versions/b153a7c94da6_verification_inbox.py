"""Immutable deduplicated verification receipts.

Revision ID: b153a7c94da6
Revises: a042f6b83c95
"""

import sqlalchemy as sa
from alembic import op

revision = "b153a7c94da6"
down_revision = "a042f6b83c95"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "verification_inbox",
        sa.Column(
            "submission_id",
            sa.String(36),
            sa.ForeignKey("run_submissions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute("""CREATE FUNCTION guard_verification_receipt() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'Verification receipts are immutable';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM run_submissions
            WHERE id=NEW.submission_id AND input_digest=NEW.input_digest) THEN
            RAISE EXCEPTION 'Verification receipt input mismatch';
        END IF;
        RETURN NEW;
        END $$""")
    op.execute("""CREATE TRIGGER verification_receipt_guard
        BEFORE INSERT OR UPDATE OR DELETE ON verification_inbox
        FOR EACH ROW EXECUTE FUNCTION guard_verification_receipt()""")


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM verification_inbox) THEN
            RAISE EXCEPTION 'Verification receipts exist; populated downgrade refused';
        END IF;
    END $$""")
    op.drop_table("verification_inbox")
    op.execute("DROP FUNCTION guard_verification_receipt()")
