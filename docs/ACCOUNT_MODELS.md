# Account models: customer-connected and pooled-managed

Status: architecture and authorization evaluator. No live execution is enabled by this document or by `execution/account_models.py`. Every scope evaluates to `live_execution_authorized: false`. Passing the evaluator only makes a scope eligible for the existing `LiveGate` review.

## Two distinct execution modes

| | Customer-connected | Pooled-managed |
|---|---|---|
| Whose money | The customer's own brokerage account | Participants' funds in one governed pool |
| Subject | One customer id | One pool id |
| Credentials | Per customer, held by the customer's broker OAuth grant | Pool-level custody arrangement only |
| Required receipts | `customer_consent`, `broker_oauth_grant`, `account_risk_ceiling` | `legal_entity`, `regulatory_approval`, `custody_agreement`, `participant_agreements`, `independent_risk_authority`, `pooled_capital_ceiling`, `participant_accounting` |
| Risk control | Per-account ceiling | Pool ceiling plus independent risk authority |

The two modes never share a scope. A customer receipt cannot satisfy a pooled gate, and a receipt for one subject cannot satisfy another subject's scope.

## Authorization rules

1. Every gate is a receipt signed by a trusted issuer with a key of at least 32 bytes.
2. Each receipt is bound to one gate and one subject, and must not be expired.
3. Caller-supplied booleans are not evidence.
4. A missing or invalid gate blocks the scope, and the result names every failing gate.
5. Capital ceilings must be positive finite numbers and match the amount bound into a trusted issuer-signed `account_risk_ceiling` or `pooled_capital_ceiling` receipt. Changing a runtime number without a new signed receipt cannot raise authority.
6. Live execution still requires the existing `LiveGate`, the provider-session receipt and the kill-switch drill.

## Shared infrastructure, separate authority

Shared pieces: the receipt verifier, the audit log and the monitoring hooks. Separate pieces: the scope evaluator, the capital ceilings and the approval path. Shared code must not be a route for one model's authority to reach the other.

## FCR interface

FCR is the authority host. It may act as a trusted issuer by minting receipts for the gates above. This repository does not hold FCR's signing keys. FCR changes stay on FCR's own branches and merge through FCR's gates.

## Current implementation truth

The account-scope evaluator and the environment-key-backed receipt issuer are committed on the AI-runtime branch. Issued receipts are signed with a per-scope subject and explicit capital ceiling where applicable. This is cryptographic input integrity, **not independent validation of the underlying legal approval, customer consent, custody arrangement, or broker session**. A trusted issuer must not sign these claims without verifying the underlying evidence.

There is still **no runtime execution path** that selects a broker by account model or consumes these account eligibility decisions. A passing scope result is advisory and never enables live trading.

## Not yet built (requires integration and evidence)

- Customer OAuth and consent flow with a real broker
- Pool custody, participant accounting and allocation records
- Regulatory and legal receipts (entity, approvals, agreements)
- Founder-approved capital ceiling values and durable per-account/pool ceiling registry
- Monitoring and automated kill switches for each model
- Broker sandbox adapter (requires a policy change in `AGENTS.md`)

## Rollback

Revert the account-model and receipt-issuer commits and tests as a bounded change on the existing branch. No runtime execution path imports these account-mode evaluators yet.
