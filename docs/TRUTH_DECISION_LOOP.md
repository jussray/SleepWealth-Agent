# SleepWealth Truth Decision Loop

SleepWealth adapts a small set of existing Juss trust primitives instead of copying whole systems into the trading simulator.

## Donor evidence

- **Founder Control Room**: claim-state separation and the rule that current failures, unknowns, and verified facts keep separate receipts.
  - inspected `main`: `74e5953ba4c710188f4372ef296417840bd33bae`
- **Chief AI / ProofMode**: layered proof that refuses to promote implementation or test evidence into runtime verification without a runtime witness.
  - inspected `main`: `2fd4fda0cab12e52ab5096e723884d98bcfe7d10`
- **PromptOS**: source / execution / outcome truth planes, non-authorizing decision support, and stale-fingerprint invalidation.
  - inspected `main`: `64ed5f8ff9971a919071c0b7f049d69486bb09d4`

These are design donors only. SleepWealth keeps its own authority, rules, tests, market lanes, capital ladder, fingerprints, and proof artifacts.

## SleepWealth contract

`engine/truth_mode.py` implements:

```text
source truth
→ execution truth
→ outcome truth
→ bounded decision
→ confess unsupported claims
→ risk
→ rollback
→ next gate
```

Claim states are:

```text
VERIFIED | OBSERVED | INFERRED | UNKNOWN | BLOCKED
```

Every generated receipt is `decision_support_only` and `authorizes=false`.

### Paper-cycle receipt

A successful mock execution may verify the **paper execution** and **paper outcome** for that exact cycle. It does not prove:

- live execution authority;
- real-money movement;
- future profitability;
- automatic promotion or a ceiling increase.

A blocked cycle keeps its execution failure separate from outcome truth. The outcome remains `UNKNOWN` when no successful paper outcome exists.

### Capital-ladder receipt

The existing `CapitalLadder` remains the economic policy carrier. The Truth Decision Loop does not replace or alter its thresholds.

`POST /api/capital/truth` accepts ordered simulated cycles, recomputes the existing ladder, and binds the advisory decision to a deterministic cycle + policy fingerprint.

Decision examples:

- no evidence → `MEASURE`;
- current proof incomplete → `HOLD`;
- current cycle blocked → `HOLD_OR_REVIEW`;
- loss threshold reached → `PROPOSE_TUNE_OR_STOP`;
- repeated qualifying proof → `PROPOSE_PROMOTION_REVIEW`;
- changed/mismatched fingerprint → `REOBSERVE`.

A promotion recommendation remains human review only. It cannot mutate rules, raise the configured ceiling, connect a broker, fund a wallet, or authorize real-money execution.

## Continuity

Historical evidence is preserved as historical evidence. If the bound cycle or policy fingerprint changes, the predecessor receipt is stale for current decision use and the system returns `REOBSERVE`.

Fingerprints and continuity cookies are non-secret state markers. They never create or renew authority.

## Verification

The existing CI lane remains authoritative:

1. exact-head binding;
2. unit tests and critical lint;
3. real read-only stock/crypto probes;
4. Playwright runtime identity proof;
5. Playwright SleepWealth browser proof;
6. independent proof-manifest verification.

The runtime-identity Playwright receipt now verifies both the paper-cycle TruthMode receipt and the capital-ladder TruthMode receipt while keeping `live_execution=false`.
