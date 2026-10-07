# ADR 001: Single-operator admission and repository registry

Status: accepted for the contained development deployment, 2026-10-07.

## Context

The prototype exposes historical source/audit information through unauthenticated reads.
Mutating workflow paths are already contained, but this does not authorize readers. No
identity provider, tenancy model or user-administration product has been selected.

## Decision

Use one configured operator identity per deployment. Require an opaque bearer token on all
application endpoints, including readiness and metrics. Store only its SHA-256 digest in
`API_TOKEN_SHA256` (masked as SecretStr in settings); compare digests in constant time.
The operator generates a high-entropy token, transmits it only over TLS or loopback, and
keeps the raw value in their credential store. This is a machine/operator credential, not
a human password authentication scheme. Never derive it from a memorable password.

Missing digest configuration makes application endpoints unavailable (503); malformed digest
or actor configuration fails settings validation. Missing/wrong bearer returns 401 with a
challenge. Public docs/OpenAPI contain metadata only. No anonymous data access or development
bypass exists. Rotation changes the configured digest and restarts all API processes;
old credentials cease working once those processes are replaced. Actor ID is stable across
rotation so audit attribution is not lost.

The authenticated operator can read all legacy deployment data and manage the registry.
This is explicitly not multitenant authorization, end-user RBAC or a verified GitHub identity.
No additional token roles are promised. A future identity-provider integration should map
verified identities into actor/principal domain contracts rather than share this token.

Register canonical HTTPS GitHub identities without making a network request. Case and the
optional `.git`/trailing slash normalize to one identity. Reject credentials, query strings,
fragments, redirects/non-GitHub hosts, SSH/file URLs and ambiguous paths. Database constraints
reinforce canonical form. Registration is an operator allowlist decision, not proof of remote
existence or GitHub installation access.

Registration is idempotent under concurrent requests through PostgreSQL unique constraints
and INSERT ON CONFLICT. It never re-enables an existing disabled repository. Enable/disable
changes lock the row; only actual transitions emit an event. Registry changes and their audit
rows commit or roll back together. These events carry actor and repository identities, but
inherit the legacy audit table's mutable/unconstrained storage limitations.

## Consequences

Repository mutations are now allowed control-plane operations; the live workflow/test/push/PR
containment guards remain. A registry row alone cannot authorize execution. Before lifting
those guards, runs must bind a registered/enabled repository, immutable base revision,
authorized plan/changeset and validated isolated execution evidence. Historical workflow URLs
are not silently promoted to approved registrations.

The registry migration is additive. A downgrade refuses to drop a populated registry. After
an explicit offline export/reconciliation, an operator can remove registrations and downgrade;
the guard intentionally favors preserving authorization decisions over an automatic rollback.

This approach limits deployment scope while giving immediate authenticated admission and
traceable repository administration. Public production deployment still requires identity/
credential lifecycle decisions, rate/request limits, durable audit hardening and the remaining
security roadmap. Existing workers remain blocked and do not gain new credentials.
