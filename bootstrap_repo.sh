#!/usr/bin/env bash
# bootstrap_repo.sh — create the GitHub repo and push this tree.
# Run from inside the unzipped trading-agent/ directory, in Codespaces or any
# machine with the `gh` CLI authenticated.
#
#   chmod +x bootstrap_repo.sh
#   ./bootstrap_repo.sh                      # defaults to jussray/trading-agent, private
#   ./bootstrap_repo.sh wealth-agent public  # custom name + visibility

set -euo pipefail

REPO_NAME="${1:-trading-agent}"
VISIBILITY="${2:-private}"
OWNER="${GH_OWNER:-jussray}"

echo "==> repo:       ${OWNER}/${REPO_NAME}"
echo "==> visibility: ${VISIBILITY}"
echo

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh CLI not found."
  echo "  Codespaces has it preinstalled. Elsewhere: https://cli.github.com"
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "ERROR: gh not authenticated. Run: gh auth login"
  exit 1
fi

if [ ! -f "pyproject.toml" ] || [ ! -d "broker" ]; then
  echo "ERROR: run this from inside the trading-agent/ directory."
  exit 1
fi

# --- local git ---------------------------------------------------------------
if [ ! -d ".git" ]; then
  git init -b main
  echo "==> git initialised"
fi

git add -A
if git diff --cached --quiet; then
  echo "==> nothing to commit"
else
  git commit -m "feat: governed trading agent — rules engine, approval queue, risk gates, audit trail

Paper trading only by default. Live execution gated behind explicit config,
risk preflight, and manual approval.

- broker/: adapter contract + mock (no network) + Alpaca (paper/live)
- engine/: TRUTHMODE evaluator + rules validator
- approvals/: human-in-the-loop queue
- risk/: REDTEAM preflight gates + kill switch
- execution/: OODA act stage
- audit/: append-only L99 evidence trail
- \$5 cash floor and human-only ceiling ladder enforced by tests"
  echo "==> committed"
fi

# --- remote ------------------------------------------------------------------
if gh repo view "${OWNER}/${REPO_NAME}" >/dev/null 2>&1; then
  echo "==> ${OWNER}/${REPO_NAME} already exists — adding remote and pushing"
  git remote remove origin 2>/dev/null || true
  git remote add origin "https://github.com/${OWNER}/${REPO_NAME}.git"
  git push -u origin main
else
  gh repo create "${OWNER}/${REPO_NAME}" \
    --"${VISIBILITY}" \
    --source=. \
    --remote=origin \
    --push \
    --description "Governed trading agent: rules engine, approval queue, risk gates, append-only audit. Paper first."
  echo "==> repo created and pushed"
fi

echo
echo "==> done: https://github.com/${OWNER}/${REPO_NAME}"
echo
echo "Next:"
echo "  make setup      # install editable + dev deps"
echo "  make validate   # check rules.json"
echo "  make test       # run the suite"
echo "  make run-paper  # one cycle against the mock broker"
