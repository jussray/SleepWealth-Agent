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

Direct Solana read/simulation/status actions (`get-balance`, `simulate-signed-transaction`, and `get-signature-status`) also require a bounded standing human read grant. Connecting an RPC endpoint does not authorize autonomous reads by itself.

The repository's current paper/simulation ceiling is enforced at dispatch: `broadcast-signed-transaction` is allowed only on `devnet` or `testnet`. A `mainnet-beta` client may be used for human-approved observation/simulation/status reads, but the MCP gateway refuses mainnet broadcast with `PAPER_ONLY_CEILING` even if a structurally valid product-authority receipt is supplied.

## Vybe Solana capability lane

Vybe is **human-permission-routed**. Connection, OAuth, continuity, provider availability, model preference, or race strategy do not independently authorize capabilities.

The required sequence is:

`human approval -> bounded standing capability grant -> OAuth mcp:read + mcp:write -> autonomous use inside grant scope`

A trusted control plane issues `sleepwealth-human-capability-grant-v1` only after explicit human authorization. The grant binds:

- running source SHA
- caller fingerprint
- subject fingerprint
- provider and environment
- approved actions
- approved resource/path prefixes
- approved effects: `read` and/or `prepare-write`
- human approval fingerprint
- purpose
- issue and expiry times

The grant is **not bound to one exact request**. While valid, Sleep Wealth may choose when to perform multiple reads or unsigned write-preparation actions inside the approved envelope without asking again for each call.

The capability grant explicitly cannot authorize:

- signing
- broadcast
- settlement
- x402 payment
- capital allocation
- money movement
- live execution

**Human authorization comes first. Autonomy exists only inside the granted capability envelope. OAuth connection alone grants nothing.**

Sleep Wealth locally allowlists these Vybe read actions:

- `list-endpoints`
- `search-endpoints`
- `get-endpoint`
- `query-vybe-api`
- `query-vybe-api-batch`

It additionally allowlists one `prepare-write` action:

- `build-vybe-transaction`

The builder may only use the locally approved Vybe transaction-builder paths and returns an **unsigned** payload. The adapter never signs or broadcasts it. `pay-with-x402` remains excluded from dispatch.

OAuth is expected to request `openid email mcp:read mcp:write`; the local human capability grant remains the controlling authorization boundary after connection.

Every Vybe action records:

- canonical provider endpoint fingerprint
- observed remote tool-schema fingerprint
- exact Sleep Wealth resource fingerprint
- returned-result fingerprint
- observation/preparation time
- human capability-grant ID and scope fingerprint
- capability effect (`read` or `prepare-write`)

Read evidence may feed either race engine as opportunity evidence. Prepared write payloads are not outcomes, executions, or profit evidence and do not authorize later signing/broadcast.

Runtime OAuth remains deployment-secret material and is never accepted in Sleep Wealth MCP command payloads or included in receipts.


## Vercel Vybe proof runtime

The public Sleep Wealth Vercel bundle does **not** expose the full MCP provider gateway. It packages only the reviewed read-only Vybe client plus opportunity-evidence code for one bounded deployment proof.

The internal proof route is `GET /internal/vybe-proof`. It is a deployment diagnostic, not a user-facing analytics workflow; user-facing Vybe reads must pass the standing human read-grant gate above.

Rules:

- preview-only by default; production refuses unless `SLEEPWEALTH_VYBE_PROOF_ALLOW_PRODUCTION=true`
- requires `SLEEPWEALTH_VYBE_PROOF_ENABLED=true`
- requires `SLEEPWEALTH_VYBE_MCP_BEARER_TOKEN` in runtime secret storage
- executes one fixed documented token-details read after first validating the endpoint contract
- returns fingerprints, observation time, and the non-authorizing opportunity-evidence receipt
- never returns raw market data
- never exposes the bearer token
- never packages or exposes the Sleep Wealth MCP transaction/payment dispatcher
- never grants allocation, transaction, payment, signing, or execution authority

This route exists only to prove that the deployed source can reach the authorized Vybe MCP session and bind the live observation to exact evidence. It is not a public analytics proxy.

## Cash App Pay

Cash App Pay is represented according to its supported developer model: customer-approved merchant payments, not arbitrary peer-to-peer Cash App balance control.

Supported product actions:

- `create-customer-request`
- `create-payment`
- `retrieve-payment`

Both customer-request creation and payment dispatch are external consequential actions and therefore require SleepWealth product authority. `create-payment` additionally requires the Cash App grant produced by customer approval. Network API requests are HMAC-SHA256 signed, idempotent, and use runtime credentials that never enter MCP payloads or receipts.

The MCP command idempotency key must equal the Cash App request-body idempotency key. Sandbox and production are distinct environments, and the requested environment must match the configured Cash App client.

The current paper/simulation ceiling permits consequential Cash App Pay calls only in `sandbox`. Production may be used for non-authorizing retrieval/observation, but `create-customer-request` and `create-payment` fail closed with `PAPER_ONLY_CEILING` before any provider request is sent. Product authority cannot override this repository-level ceiling.

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
- `SLEEPWEALTH_MCP_PERMISSION_ISSUER`
- `SLEEPWEALTH_MCP_PERMISSION_KEY`
- `SLEEPWEALTH_MCP_LEDGER_KEY`

Optional provider variables configure Solana RPC, Vybe Solana intelligence, and Cash App Pay. Secrets must be supplied by deployment secret storage. Never commit provider secrets, OAuth bearer tokens, or private keys.

The server defaults to MCP stdio. `SLEEPWEALTH_MCP_TRANSPORT=streamable-http` exposes `/mcp`.

Loopback HTTP uses the SDK's safe local default. A non-loopback host fails closed unless `SLEEPWEALTH_MCP_ALLOWED_HOSTS` is explicitly configured as a comma-separated allowlist. `SLEEPWEALTH_MCP_ALLOWED_ORIGINS` may additionally bind accepted browser/application origins. These are transport-level DNS-rebinding/origin protections, not substitutes for deployment authentication.

A remote deployment must also sit behind a real authenticated identity boundary, such as the MCP SDK's bearer-token/OAuth resource-server integration with the deployment's actual identity provider. This repository does not invent or self-issue that external identity provider.
