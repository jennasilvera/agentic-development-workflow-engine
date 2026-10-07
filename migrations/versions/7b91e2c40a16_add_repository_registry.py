"""Add the operator-managed repository registry.

Revision ID: 7b91e2c40a16
Revises: b4741e3f30d9
"""

import sqlalchemy as sa
from alembic import op

revision = "7b91e2c40a16"
down_revision = "b4741e3f30d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("canonical_url", sa.String(160), nullable=False),
        sa.Column("registered_by", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("canonical_url", name="uq_repositories_canonical_url"),
        sa.CheckConstraint(
            "canonical_url ~ '^https://github[.]com/[a-z0-9][a-z0-9-]{0,38}/[a-z0-9_.-]{1,100}$' "
            "AND canonical_url NOT LIKE '%.git' "
            "AND split_part(canonical_url, '/', 5) NOT IN ('.', '..')",
            name="ck_repositories_canonical_url",
        ),
        sa.CheckConstraint(
            "registered_by ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'",
            name="ck_repositories_actor",
        ),
    )


def downgrade() -> None:
    # Never silently destroy operator decisions on a populated deployment.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM repositories) THEN
            RAISE EXCEPTION 'Export and explicitly remove repository registrations before downgrade';
        END IF;
    END $$""")
    op.drop_table("repositories")
