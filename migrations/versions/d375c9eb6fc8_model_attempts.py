"""Immutable model budgets, reservations and outcomes.

Revision ID: d375c9eb6fc8
Revises: c264b8da5eb7
"""

from alembic import op

revision = "d375c9eb6fc8"
down_revision = "c264b8da5eb7"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE model_budgets (
      submission_id varchar(36) PRIMARY KEY REFERENCES run_submissions(id),
      policy text NOT NULL,
      actor_id varchar(64) NOT NULL CHECK (actor_id ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      CHECK (jsonb_typeof(policy::jsonb)='object'),
      CHECK ((policy::jsonb->>'max_calls') IS NOT NULL AND
             (policy::jsonb->>'max_calls')::integer BETWEEN 1 AND 20),
      CHECK ((policy::jsonb->>'max_output_tokens') IS NOT NULL AND
             (policy::jsonb->>'max_output_tokens')::integer BETWEEN 1 AND 32000),
      CHECK ((policy::jsonb->>'output_token_reservation') IS NOT NULL AND
             (policy::jsonb->>'output_token_reservation')::integer BETWEEN 1 AND 640000)
    )""")
    op.execute("""CREATE TABLE model_attempts (
      id varchar(36) PRIMARY KEY,
      submission_id varchar(36) NOT NULL REFERENCES model_budgets(submission_id),
      request_key varchar(128) NOT NULL CHECK (request_key ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$'),
      input_digest varchar(64) NOT NULL CHECK (input_digest ~ '^[0-9a-f]{64}$'),
      reserved_tokens integer NOT NULL CHECK (reserved_tokens BETWEEN 1 AND 32000),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      UNIQUE (submission_id, request_key)
    )""")
    op.execute("""CREATE TABLE model_attempt_results (
      attempt_id varchar(36) PRIMARY KEY REFERENCES model_attempts(id),
      outcome varchar(16) NOT NULL CHECK (outcome IN ('succeeded','failed','uncertain')),
      evidence text,
      failure_code varchar(64),
      created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
      CHECK ((outcome='succeeded' AND evidence IS NOT NULL AND failure_code IS NULL)
        OR (outcome IN ('failed','uncertain') AND evidence IS NULL AND failure_code IS NOT NULL AND failure_code IN
          ('rate_limited','provider_unavailable','provider_refused','provider_timeout',
           'invalid_provider_reply','budget_exhausted','invalid_gateway_input'))),
      CHECK (evidence IS NULL OR jsonb_typeof(evidence::jsonb)='object')
    )""")
    op.execute("""CREATE FUNCTION preserve_model_record() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'Model budget and attempt records are immutable';
      END $$""")
    for table in ("model_budgets", "model_attempts", "model_attempt_results"):
        op.execute(f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}
          FOR EACH ROW EXECUTE FUNCTION preserve_model_record()""")
    op.execute("""CREATE FUNCTION enforce_model_reservation() RETURNS trigger
      LANGUAGE plpgsql AS $$ DECLARE p jsonb; calls bigint; tokens bigint; BEGIN
        SELECT policy::jsonb INTO p FROM model_budgets
          WHERE submission_id=NEW.submission_id FOR UPDATE;
        IF p IS NULL THEN RAISE EXCEPTION 'Model budget missing'; END IF;
        SELECT count(*), coalesce(sum(reserved_tokens),0) INTO calls,tokens
          FROM model_attempts WHERE submission_id=NEW.submission_id;
        IF NEW.reserved_tokens <> (p->>'max_output_tokens')::integer OR
           calls >= (p->>'max_calls')::integer OR
           tokens + NEW.reserved_tokens > (p->>'output_token_reservation')::integer THEN
          RAISE EXCEPTION 'Model reservation exceeds budget';
        END IF;
        RETURN NEW;
      END $$""")
    op.execute("""CREATE TRIGGER model_reservation_guard BEFORE INSERT ON model_attempts
      FOR EACH ROW EXECUTE FUNCTION enforce_model_reservation()""")
    op.execute("""CREATE FUNCTION bind_model_result() RETURNS trigger
      LANGUAGE plpgsql AS $$ DECLARE a record; e jsonb; BEGIN
        IF NEW.outcome <> 'succeeded' THEN RETURN NEW; END IF;
        SELECT m.input_digest,m.reserved_tokens,b.policy::jsonb AS policy INTO a
          FROM model_attempts m JOIN model_budgets b ON b.submission_id=m.submission_id
          WHERE m.id=NEW.attempt_id;
        e := NEW.evidence::jsonb;
        IF e->>'attempt_id' IS DISTINCT FROM NEW.attempt_id OR
           e->>'input_digest' IS DISTINCT FROM a.input_digest OR
           e->'proposal'->>'input_digest' IS DISTINCT FROM a.input_digest OR
           e->>'provider' IS DISTINCT FROM a.policy->>'provider' OR
           e->>'model' IS DISTINCT FROM a.policy->>'model' OR
           e->>'policy_version' IS DISTINCT FROM a.policy->>'version' OR
           e->'usage'->>'output_tokens' IS NULL OR
           (e->'usage'->>'output_tokens')::integer NOT BETWEEN 0 AND a.reserved_tokens THEN
          RAISE EXCEPTION 'Model result identity or usage mismatch';
        END IF;
        RETURN NEW;
      END $$""")
    op.execute("""CREATE TRIGGER model_result_guard BEFORE INSERT ON model_attempt_results
      FOR EACH ROW EXECUTE FUNCTION bind_model_result()""")


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM model_budgets) THEN
        RAISE EXCEPTION 'Model budgets exist; populated downgrade refused';
      END IF;
    END $$""")
    op.drop_table("model_attempt_results")
    op.drop_table("model_attempts")
    op.drop_table("model_budgets")
    op.execute("DROP FUNCTION enforce_model_reservation()")
    op.execute("DROP FUNCTION bind_model_result()")
    op.execute("DROP FUNCTION preserve_model_record()")
