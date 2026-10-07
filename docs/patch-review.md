# Patch review and legacy-state migration

Approval is a control-plane review decision. It does not authorize the currently unavailable
execution/publication services. Base-revision, registered-repository and validation binding
must be implemented before those services can consume approval evidence.

## Implemented contract

Read `diff_sha256` from PatchRead, review the exact diff, then POST
`{"expected_diff_sha256":"<64 lowercase hex characters>"}` to approve or reject.
The authenticated operator supplies actor identity; caller-supplied actor fields are rejected.
An absent body is 422, a missing/mismatched patch/workflow is 404, stale content and illegal
transitions are 409. Orphaned legacy patches return 409 pending reconciliation.

| Current state | Approve | Reject |
| --- | --- | --- |
| proposed | approved | rejected |
| approved | Idempotent if digest still matches | rejected, approval cleared |
| rejected | Conflict | Idempotent |
| applying/applied/failed/requires_review | Conflict | Conflict |

Decisions lock the patch row. Status, approved actor/time/digest and the audit event share
one transaction. Duplicate approval/rejection creates no extra event. Approval stores the
exact UTF-8 diff hash; PostgreSQL prevents changing approved content without revoking its
approval metadata. APPLIED additionally requires a commit hash, but that constraint alone
is not evidence of validated execution. Only a future verified executor may claim completion.
Summary responses distinguish approved, applying, applied, rejected, failed and requires_review.

## Migration 8c20d4e61f73

Stop old workers/API writers before migrating. The old code used APPLIED both for approval
and execution and had no trustworthy approval identity. Even a stored commit SHA is not
proof that the intended changes passed validation.

- Preserve proposed and rejected labels.
- Move every other historical label to requires_review, preserving its exact original value
  in legacy_status and retaining diff, branch, commit and error fields.
- Write patch.legacy_quarantined audit evidence in the migration transaction.
- Never fabricate approval timestamps, actors or validated application.
- Add legal-status, approval-evidence and applied-commit constraints.

This is deliberately conservative: historical failed/applying rows may have uncertain external
effects. New decisions cannot revive quarantined records. A later operator reconciliation flow
must inspect remote/local evidence and create traceable new work rather than replay old jobs.

Downgrade refuses while approval or quarantine information would be lost. Export and reconcile
first; do not bulk reset statuses to bypass the guard. Empty or unaffected proposed/rejected
records can downgrade. This migration does not delete remote commits or PRs.
