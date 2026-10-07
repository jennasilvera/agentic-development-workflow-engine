"""Pinned provider identities and immutable revision observations.

Revision ID: c264b8da5eb7
Revises: b153a7c94da6
"""

import sqlalchemy as sa
from alembic import op

revision = "c264b8da5eb7"
down_revision = "b153a7c94da6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("repositories", sa.Column("github_repository_id", sa.BigInteger()))
    op.create_check_constraint(
        "ck_repository_github_id",
        "repositories",
        "github_repository_id IS NULL OR github_repository_id > 0",
    )
    op.execute("""CREATE FUNCTION preserve_repository_identity() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        IF OLD.github_repository_id IS NOT NULL AND
          (NEW.github_repository_id IS DISTINCT FROM OLD.github_repository_id OR
           NEW.canonical_url IS DISTINCT FROM OLD.canonical_url) THEN
          RAISE EXCEPTION 'Pinned repository identity is immutable';
        END IF;
        RETURN NEW;
        END $$""")
    op.execute("""CREATE TRIGGER repository_identity_guard BEFORE UPDATE ON repositories
        FOR EACH ROW EXECUTE FUNCTION preserve_repository_identity()""")
    op.create_table(
        "revision_observations",
        sa.Column(
            "submission_id",
            sa.String(36),
            sa.ForeignKey("verification_inbox.submission_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("github_repository_id", sa.BigInteger(), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("tree_sha", sa.String(40), nullable=False),
        sa.Column("policy_version", sa.String(128), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "commit_sha ~ '^[0-9a-f]{40}$' AND tree_sha ~ '^[0-9a-f]{40}$'",
            name="ck_revision_object_ids",
        ),
        sa.CheckConstraint("github_repository_id > 0", name="ck_revision_provider_id"),
        sa.CheckConstraint(
            "policy_version = 'public-metadata-v1'", name="ck_revision_policy"
        ),
        sa.CheckConstraint(
            "recorded_by ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'",
            name="ck_revision_actor",
        ),
    )
    op.execute("""CREATE FUNCTION guard_revision_observation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Revision observations are immutable'; END IF;
        IF NOT EXISTS (SELECT 1 FROM run_submissions s JOIN repositories r ON r.id=s.repository_id
          WHERE s.id=NEW.submission_id AND s.input_digest=NEW.input_digest
          AND r.github_repository_id=NEW.github_repository_id AND r.enabled
          AND s.canonical_input::jsonb ->> 'base_commit_sha'=NEW.commit_sha
          AND s.canonical_input::jsonb ->> 'policy_version'=NEW.policy_version) THEN
          RAISE EXCEPTION 'Revision observation input mismatch';
        END IF;
        RETURN NEW;
        END $$""")
    op.execute("""CREATE TRIGGER revision_observation_guard BEFORE INSERT OR UPDATE OR DELETE
        ON revision_observations FOR EACH ROW EXECUTE FUNCTION guard_revision_observation()""")


def downgrade():
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM revision_observations) OR
           EXISTS (SELECT 1 FROM repositories WHERE github_repository_id IS NOT NULL) THEN
          RAISE EXCEPTION 'Identity/evidence exists; populated downgrade refused';
        END IF;
    END $$""")
    op.drop_table("revision_observations")
    op.execute("DROP FUNCTION guard_revision_observation()")
    op.execute("DROP TRIGGER repository_identity_guard ON repositories")
    op.execute("DROP FUNCTION preserve_repository_identity()")
    op.drop_constraint("ck_repository_github_id", "repositories", type_="check")
    op.drop_column("repositories", "github_repository_id")
