# Claude session state — SleepWealth-Agent

## 2026-11-04 — Account models, execution-authority separation, and FCR alignment

- REALITY @ `c42b839` on `claude/ai-runtime-repos-automation-uhpoz6`: paper-only. Live broker adapters raise `ExternalBrokerDisabled` at construction. `broker/factory.py` accepts only `mock`. No customer or pooled account is connected. VERIFIED by reading the code and the remote head.
- FIX (this session):
  - `d70de72` paper-only AI proposal seam (`gate/ai_paper_proposal.py`). Rejects blank lanes, which `normalize_lane` would otherwise default to stock. Requires caller-supplied `human_approved`.
  - `c42b839` two account models (`execution/account_models.py`, `docs/ACCOUNT_MODELS.md`). Customer-connected needs 3 receipts; pooled-managed needs 7. Each receipt is HMAC-signed by a trusted issuer, bound to one subject, and unexpired. Result never sets `live_execution_authorized`.
- PROOF: full suite `SLEEPWEALTH_MARKET_SOURCE=mock pytest tests` = 493 passed. CI lint `ruff check . --select E4,E7,E9,F` passes. CI runs `pytest tests/`, so the new tests execute.
- RISK:
  - Evaluators only check receipts. Nothing mints receipts yet, so no scope can reach eligibility in practice.
  - Broker sandbox adapter is not built. Enabling it changes the `AGENTS.md` ceiling, which needs founder sign-off.
  - The FCR-side profile update lives on FCR branch `claude/fcr-sleepwealth-account-models` (`2ed6df87`), not on FCR `main`.
- ROLLBACK: revert `c42b839` and `d70de72`. Delete this file to remove the state record.
- NEXT GATE (founder decisions):
  1. Name the broker and approve the sandbox adapter policy change in `AGENTS.md`.
  2. Account model details: customer consent wording, and pooled entity, custody and counsel sign-off.
  3. Capital ceilings, given as numbers in writing.
  4. Confirm FCR as the trusted receipt issuer and provision its key.
