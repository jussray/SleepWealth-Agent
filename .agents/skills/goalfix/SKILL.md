---
name: "goalfix"
description: "Token-efficient repair skill for any AI agent working on Juss-owned GitHub projects: finds the real blocker, makes the smallest verified fix, and proves it on the real path."
---

# /goalfix — Seek, Build, Fix, Verify

Author: Juss
Triggers: /goalfix, /fixfast, /repair-verify-merge

Mission
Given a founder goal, find the real blocker, make the smallest safe fix, verify the real path, and stop token waste.
Do not wander. Do not rewrite the whole project. Do not claim success without proof.

Operating stack
Use:
/garyvee lindymode redteam l99 redteam ooda
Meaning:
1. Founder value: what outcome matters?
2. Lindy: what fix will still make sense later?
3. Redteam I: should this change exist?
4. L99: authority, state, evidence, rollback, compounding value.
5. Redteam II: how could the selected fix fail?
6. OODA: observe, orient, decide, act, verify, loop.

## Token budget rules
Before reading broadly, state:
- authoritative repo
- target branch
- current goal
- suspected failure area
- exact files or logs needed first
- stop condition

Use narrow search first. Read only files that can affect the goal. Prefer exact errors, failing test names, route names, config names, and recent diffs over whole-repo scanning.
Never paste huge files back unless asked. Summarize only the relevant lines and cite file paths, commits, tests, logs, screenshots, or artifacts.

## Work order

### 1. Observe
Inspect the real source of truth:
- repo
- branch
- PR
- CI logs
- deployment logs
- runtime behavior
- Playwright evidence when UI or browser flow is involved

Separate:
- VERIFIED
- INFERRED
- UNKNOWN
- BLOCKED

### 2. Orient
Map the goal using 5W1H:
- Who owns the decision?
- What must change?
- Where is the authoritative source?
- When should this stop, rerun, merge, or roll back?
- Why does this serve the product or business?
- How will it be tested and reversed?

### 3. Decide
Pick one focused fix.

Rules:
- one cause before many symptoms
- smallest reversible patch
- no unrelated refactors
- no deleting without explicit approval
- no merge unless checks and real-path evidence are green
- no public claim without proof

### 4. Act
Patch only the needed files.

For code:
- preserve unrelated work
- keep diffs small
- add or update the narrowest useful test
- do not suppress failing signals
- do not fake green with mocks, fallbacks, or hidden errors

### 5. Verify
Run the cheapest valid verification first, then escalate only as needed:
1. typecheck or lint for touched area
2. focused unit/integration test
3. targeted Playwright test for real UI flow
4. CI or deployment check only when needed
5. inspect artifacts/logs/screenshots/traces if failed

For Se’kret Bip UI/runtime work, Playwright evidence is required before calling it done.

### 6. Report
Return only this:

REALITY:
What is verified right now.

FIX:
What changed, with files/commit/PR if applicable.

PROOF:
Tests, logs, screenshots, traces, CI, or runtime evidence.

RISK:
What could still be wrong.

ROLLBACK:
How to reverse safely.

NEXT GATE:
One exact founder decision or next action.