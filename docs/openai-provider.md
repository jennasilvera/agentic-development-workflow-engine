# OpenAI Chat Completions adapter

`OpenAIChatProvider` is an opt-in internal adapter for `openai-chat-v1`. It sends one
request to `https://api.openai.com/v1/chat/completions`, with the explicitly configured
model, `max_completion_tokens`, `response_format: {type: json_object}`, no tools, one
choice, `stream: false` and `store: false`. JSON mode is not schema enforcement: the
gateway independently validates the complete proposal against exact supplied input.

API contract reference, checked 2026-10-07:
[Create chat completion](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).
Model support and account access must be verified before enabling a deployment. No model
is selected by default. Use a pinned model ID that the response reports exactly; aliases
that resolve to a different returned ID fail closed. This adapter does not implement
Anthropic, arbitrary compatible endpoints, Responses API, streaming events or tool calls.

Credentials must be passed explicitly as `SecretStr` by trusted application configuration.
No environment key discovery, arbitrary base URL, environment proxy or redirect is used.
The adapter constructs a fresh TLS-verifying HTTP client per call. Credential headers,
task text, response bodies and provider error text are never logged by this module.
The optional transport argument is a trusted test seam, never repository-controlled input.

The system message defines the proposal schema; user context contains the immutable input
digest, task/file data and exact source hashes to copy into replacements. This separation
does not guarantee resistance to prompt injection or code correctness. Returned proposals
still have no authority to write files, execute commands or publish changes.

The transport requests identity encoding and rejects compressed responses. It bounds the
HTTP envelope while reading, allowing JSON-escaping overhead, then separately bounds decoded
proposal bytes. Requests have a 30-second overall adapter deadline and five-second HTTP
operation timeouts; a shorter gateway policy deadline also applies. Responses must have one
completed assistant text choice, exact model identity and strict usage within the output-token
reservation. Refusals, tool calls, truncated content and ambiguous JSON are rejected. The
gateway then checks schema, digest, target paths and source-content identity.

429 and server/transport failures are classified without response text. There are no automatic
retries, fallback providers or redirected credential requests. Provider rejection includes
authentication/permission errors and must be investigated through account configuration,
not retried with automatically changed credentials. `store: false` does not establish an
account-wide zero-retention guarantee; deployment data policy requires independent review.

Use this adapter through `propose_with_budget` after creating a trusted per-submission budget.
There is no API/worker wiring or environment switch enabling live calls, and no live call was
made during implementation. Transport tests use synthetic responses, not model evaluations.
Remaining qualification includes real-account compatibility, data handling, monetary/global
budgets, task evaluations, verified curated context and isolated execution.
