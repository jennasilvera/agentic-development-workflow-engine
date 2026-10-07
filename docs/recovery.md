# Control-plane recovery

## Reproducible CI drill

`scripts/recovery_drill.py` creates two random disposable databases on the development
PostgreSQL instance. It migrates and seeds the first, streams a custom-format pg_dump backup
to a temporary file, and restores it into the second using pg_restore with exit-on-error.
It never restores over an existing database. Its finally block drops only databases created
by that invocation. A killed process may leave `adwe_drill_<random>` databases; inspect and
remove only those positively identified as that drill's disposable resources.

The fixture includes a delivered submission with a synthetic revision observation, a pending
submission, and a handoff committed to the inbox but not acknowledged by the sender. No
GitHub/model calls or repository execution occur. Verification checks:

- Exact equality of every public-table row, including migration state and audit payloads.
- Restored triggers reject deletion of immutable submissions, receipts and observations.
- Delivery replay processes pending and expired leased work without duplicate receipts/audit.
- The old delivery token cannot acknowledge work after recovery.

Run locally against **disposable development PostgreSQL**, with CREATEDB permission:

```bash
docker compose up -d postgres
export ADWE_TEST_DATABASE_URL=postgresql+psycopg://adwe:adwe@127.0.0.1:5433/adwe
export ADWE_DRILL_CONTAINER="$(docker compose ps -q postgres)"
PYTHONPATH=src uv run --frozen python scripts/recovery_drill.py
```

The URL and container must refer to the same database server. The container supplies matching
PostgreSQL client tools and uses its local development database role. Do not grant this drill
production authority. Backups contain task text and audit data; the temporary fixture backup
is deleted on normal completion and is never uploaded as a CI artifact.

## Deployed recovery procedure

1. Stop admission, dispatchers and publishers before switching databases. Preserve the failed
   instance and its evidence. Containment must remain enabled during recovery.
2. Restore a verified backup into a separate database. Confirm the migration head, repository
   identity pins, exact input digests, audit history and immutable-table guards. Restore
   database roles/permissions and deployment secrets separately; this drill omits ownership
   and grants and does not cover those controls.
3. Determine the backup's recovery point. Identify inputs and any external effects after
   that point from independent records. Never infer that missing local evidence means a
   remote operation did not happen. Current metadata intake has no publisher; any legacy
   or future publication requires its own remote reconciliation before resumption.
4. Ensure old workers cannot reach the restored database. Wait for database-time lease
   expiry and use normal claim/replay; do not reset attempts or replace tokens manually.
   Delivered means durable receipt, not verified revision or completed execution. Inspect
   dead deliveries individually; do not bulk-reset them to pending.
5. Recheck observation freshness and repository enablement. Restored observations do not
   authorize execution. Test authenticated reads and one controlled delivery before opening
   intake again. Retain the incident record and measured recovery timings.

The CI fixture is not an off-site backup, point-in-time recovery, encryption/key-restoration,
production-scale restore, credential-rotation or capacity drill. No RPO/RTO is claimed. Those
require a chosen deployment, backup service and measured rehearsals with its real access
boundaries. Restore success alone does not authorize a production release.
