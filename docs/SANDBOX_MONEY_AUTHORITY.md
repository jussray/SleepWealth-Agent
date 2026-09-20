# Sandbox money-moving authority

SleepWealth now has a production-shaped authority path for **sandbox/paper execution only**.
It is deliberately separate from provider credentials and does not enable real-money execution.

## Flow

1. The existing `ApprovalQueue` stores the explicit human approval and binds it to the exact order + reviewed evaluation fingerprint.
2. `issue_sandbox_money_authority(...)` creates a short-lived HMAC-authenticated receipt that binds:
   - proposal ID
   - human approval fingerprint
   - runtime subject
   - provider
   - non-secret account fingerprint
   - action (`order-submit` only)
   - symbol, asset class, side, and quantity
   - exact reviewed notional ceiling
   - nonce and idempotency key
   - issuance and expiry timestamps
3. `SandboxMoneyExecutionManager` verifies that receipt against the current approval and runtime identity.
4. `SandboxAuthorityLedger` checks revocation, the operator kill switch, and replay/idempotency state before execution crosses the broker boundary.
5. The existing `ExecutionManager` performs fresh-market revalidation, dynamic risk gates, simulated broker submission, approval-state persistence, append-only audit logging, and reconciliation handling.
6. The authority ledger records the terminal result as `completed`, `blocked`, or `reconcile_required`.

## Fail-closed invariants

- An evidence object cannot create authority.
- A caller cannot self-mint trust by naming an issuer. The runtime must supply the trusted HMAC key.
- A valid receipt expires within five minutes.
- Provider, account fingerprint, approval fingerprint, order scope, and reviewed ceiling must all match exactly.
- A receipt cannot authorize funding, transfers, withdrawals, wallet signatures, or live execution.
- The execution broker must report `is_paper_only() == True`.
- A revoked receipt cannot cross the sandbox execution boundary.
- When the authority kill switch is engaged, no new sandbox authority can be reserved.
- An idempotency key is single-use once it crosses the boundary, including uncertain/reconciliation outcomes.
- Fresh market evidence and risk gates are rechecked by the existing execution path after human approval.
- Unknown post-submission outcomes remain reconciliation-required instead of being retried blindly.

## What this proves

This architecture proves that SleepWealth can carry explicit human approval through a scoped, authenticated, replay-resistant authority layer into the existing paper execution and reconciliation path.

It does **not** prove or enable a live broker order, bank/crypto transfer, wallet signature, provider compliance approval, adult eligibility, or real-money execution.

## Future provider boundary

A future live deployment for an independently eligible adult operator must keep this same separation:

`provider/account evidence -> explicit human approval -> scoped authority -> risk/kill checks -> provider execution -> reconciliation -> immutable evidence`

A live adapter must not be registered merely because a read-only provider session exists. It requires separate provider authorization, eligibility evidence, execution credentials, broker-side cancellation/reconciliation proof, and a dedicated live authority policy.
