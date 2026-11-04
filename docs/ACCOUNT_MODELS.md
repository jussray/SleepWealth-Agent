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
5. Capital ceilings must be positive finite numbers. They are configuration, and they are never inferred.
6. Live execution still requires the existing `LiveGate`, the provider-session receipt and the kill-switch drill.

## Shared infrastructure, separate authority

Shared pieces: the receipt verifier, the audit log and the monitoring hooks. Separate pieces: the scope evaluator, the capital ceilings and the approval path. Shared code must not be a route for one model's authority to reach the other.

## FCR interface

FCR is the authority host. It may act as a trusted issuer by minting receipts for the gates above. This repository does not hold FCR's signing keys. FCR changes stay on FCR's own branches and merge through FCR's gates.

## Not yet built (blocked on founder inputs)

- Customer OAuth and consent flow with a real broker
- Pool custody, participant accounting and allocation records
- Regulatory and legal receipts (entity, approvals, agreements)
- Capital ceiling values
- Monitoring and automated kill switches for each model
- Broker sandbox adapter (requires a policy change in `AGENTS.md`)

## Rollback

Delete `execution/account_models.py`, `tests/test_account_models.py` and this document. No runtime path imports them.
