# Public GitHub revision observations

`observe_public_revision` is a read-only metadata adapter. It is not wired into the dispatcher,
a public endpoint, or execution. It returns an observation of the exact requested commit and
its tree through a public repository's GitHub API. No files are acquired or commands run.

The adapter validates a serialized RunInput before network access, accepts full lowercase
40-character SHA-1 object IDs, and constructs three fixed-origin HTTPS GET requests:
repository metadata, exact Git commit metadata, then repository metadata again. Canonical name,
public/available state and numeric GitHub repository ID must match across the observation.
Commit and tree SHA fields must be exact and valid. The immutable observation binds the input
digest, registry UUID, canonical URL, provider repository ID, commit/tree and observation time.
The wider domain contract supports 64-character IDs, but this adapter explicitly rejects them.

## Request and response boundaries

The client uses no authentication, environment proxies or environment credentials. Cookies
returned by GitHub are cleared before subsequent requests. Redirects are rejected; neither
returned URLs nor default-branch names are followed. TLS verification stays enabled. A fixed
API version and identity content encoding are requested. Encoded responses are rejected,
JSON is limited to 64 KiB per response, duplicate object keys/non-finite numbers are rejected,
and the response must be an object with the required identity fields. The cap intentionally
rejects unusually large commit metadata rather than truncating it or claiming success.

Each HTTP operation has a three-second timeout, with a ten-second deadline for the whole
observation. Cancellation propagates. Transient transport/timeouts, rate limiting and server
errors carry retryable codes but are never retried inside the adapter. Other status/identity/
format errors fail closed. Exceptions do not include response bodies, headers or supplied URLs.
Public unauthenticated rate limits constrain throughput; private repositories are unsupported.

## Evidence limits and remaining admission work

A commit returned by a repository-scoped API is not proof of branch reachability, trusted
provenance, a verified signature or safe content. This adapter deliberately calls the result
an observation. A repository may be renamed, transferred or replaced outside the observation
window. The registry does not yet pin provider numeric identity at registration; admission must
add and reconcile that identity rather than treating a reusable URL as permanent ownership.

The caller still needs to select trusted policy, check enabled registration before the lookup,
persist evidence with a freshness policy, and atomically recheck current registration and
input/policy identities before admitting a run. These operations must not hold database row
locks during network calls. Branch ancestry requirements, private GitHub App access, observation
persistence, policy authorization and isolated checkout are not implemented here. No observation
lifts execution containment.

Tests use an HTTP transport double: success identity, cookies/credentials, fixed request paths,
redirects, rate limits, provider errors, malformed/oversized/encoded responses, repository and
commit/tree mismatches, replacement between reads, cancellation, and unsupported IDs. They do
not claim live GitHub conformance or an isolated execution boundary.

Provider contract reference: [GitHub REST Git commits](https://docs.github.com/en/rest/git/commits?apiVersion=2022-11-28).
