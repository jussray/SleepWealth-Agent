# SleepWealth MCP Provider Plane

## Goal

Expose SleepWealth as a standard MCP server that GitHub/Codex/ChatGPT-compatible and custom MCP clients can call without turning the MCP transport into an authority source.

The product flow is:

`MCP caller fingerprint + human subject fingerprint + exact source SHA -> continuity cookie -> provider/account/resource fingerprint -> trusted product authority -> replay/kill ledger -> provider adapter -> provider receipt -> reconciliation`

## Fingerprints and cookies

- Fingerprints are SHA-256 continuity identities for the MCP caller, human subject, provider subject/account, approved resource, and authority receipt.
- Continuity cookies are short-lived HMAC-authenticated state markers.
- Cookies bind the exact SleepWealth source SHA and explicit capability set.
- Cookies explicitly carry `authorizes=false`, `execution_authorized=false`, and `contains_secret=false`.
- Neither a fingerprint nor a cookie is accepted as provider credentials or provider-action authority.
- Provider credentials stay in deployment secret storage and are loaded into provider clients at runtime.
- A cookie from a different caller, subject, build SHA, provider account, environment, or capability fails closed.

## MCP tools

The server deliberately exposes only:

1. `sleepwealth_capabilities`
2. `sleepwealth_validate_continuity`
3. `sleepwealth_dispatch`

There is no MCP tool that can mint a product action authority receipt. Authority issuance belongs to a separately trusted control plane after current human approval, independently verified eligible-adult evidence, and current provider-session evidence have been checked.

## GitHub

GitHub is represented as a control-plane / MCP caller surface rather than as a money provider. Repository credentials remain GitHub-native. GitHub/Codex can call the SleepWealth MCP tools, but repository identity does not satisfy financial-provider identity or adult eligibility.

## Solana

Supported product actions:

- `get-balance`
- `simulate-signed-transaction`
- `broadcast-signed-transaction`
- `get-signature-status`

The adapter has an external-signer boundary. It never accepts a private key. A broadcast action accepts an already-signed base64 transaction, fingerprints the exact transaction bytes, and requires product authority bound to that fingerprint before calling `sendTransaction`.

Networks are explicit: `devnet`, `testnet`, or `mainnet-beta`. The requested environment must equal the network configured in the running provider client. The RPC endpoint must use HTTPS outside loopback.

## Cash App Pay

Cash App Pay is represented according to its supported developer model: customer-approved merchant payments, not arbitrary peer-to-peer Cash App balance control.

Supported product actions:

- `create-customer-request`
- `create-payment`
- `retrieve-payment`

Both customer-request creation and payment dispatch are external consequential actions and therefore require SleepWealth product authority. `create-payment` additionally requires the Cash App grant produced by customer approval. Network API requests are HMAC-SHA256 signed, idempotent, and use runtime credentials that never enter MCP payloads or receipts.

The MCP command idempotency key must equal the Cash App request-body idempotency key. Sandbox and production are distinct environments, and the requested environment must match the configured Cash App client.

## Product action authority

A product action authority receipt binds:

- trusted issuer
- human subject fingerprint
- provider
- environment
- provider account/merchant fingerprint
- exact action
- exact resource fingerprint
- current human approval fingerprint
- independently verified eligible-adult receipt fingerprint
- current provider-session fingerprint
- idempotency key
- optional amount/currency ceiling
- short issue/expiry window

Changing any bound field invalidates the authority.

## Replay, revocation, and kill behavior

The product action ledger is HMAC-sealed and file-locked. It records whether a provider/idempotency pair has crossed the provider boundary. A second attempt is refused. Authority can be revoked and a global product-action kill switch can be engaged.

The ledger is checked once when an action is reserved and again immediately before dispatch. If a consequential provider call errors after crossing the dispatch boundary, the outcome is classified `RECONCILE_REQUIRED` rather than retried blindly.

## Runtime configuration

Required MCP control-plane variables:

- `SLEEPWEALTH_SOURCE_SHA`
- `SLEEPWEALTH_MCP_COOKIE_ISSUER`
- `SLEEPWEALTH_MCP_COOKIE_KEY`
- `SLEEPWEALTH_MCP_AUTHORITY_ISSUER`
- `SLEEPWEALTH_MCP_AUTHORITY_KEY`
- `SLEEPWEALTH_MCP_LEDGER_KEY`

Optional provider variables configure Solana RPC and Cash App Pay. Secrets must be supplied by deployment secret storage. Never commit provider secrets or private keys.

The server defaults to MCP stdio. `SLEEPWEALTH_MCP_TRANSPORT=streamable-http` exposes `/mcp`; the default host remains loopback so remote deployment must explicitly configure its network/authentication boundary instead of silently opening the server.
