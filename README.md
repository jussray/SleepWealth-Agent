# trading-agent

A governed trading agent. The machine proposes; the human owns the ceiling.

Paper/simulation execution only. Live account observation is being built as a separate evidence plane; live order execution remains disabled at both the CLI and broker-factory layers.

## Public token identity

The approved public token branding identity for the crypto lane is **MOM OF 8 / MOM8**. The canonical machine-readable record lives at `identity/mom8-public-token.json`.

That approval is branding-only. It does not authorize token launch, minting, wallet access, trading, spending, transfers, or any other live-money action. Those remain separate authority gates and receipts.

## Why this exists

Most "AI trading bot" designs fail in the same place: the action layer has more authority
than the evidence layer. This repo inverts that. Every order passes through four gates
before it reaches a broker:

1. **Evaluator** (TRUTHMODE) - is this order supported by the rules?
2. **Approval queue** - has a human said yes?
3. **Risk gates** (REDTEAM) - cash floor, daily loss, drawdown, kill switch.
4. **Audit log** (L99) - append-only evidence of every decision, including the rejections.

Live-money readiness adds separate provider/account evidence. An adult-eligibility receipt
and a live-provider-session receipt must independently authenticate and bind to the same
non-secret account fingerprint. Neither receipt grants execution authority.

## Quick start

```bash
make setup       # install editable + dev deps
make validate    # check rules.json against the schema contract
make test        # run the suite
make run-paper   # one full cycle against the in-memory mock broker
```

No API keys needed for `run-paper`. The mock broker never touches a network.

The shipped `ceiling.current` is `$5`, so `run-paper` buys a fractional share. Run
`make run-paper-blocked` to watch the ceiling refuse a full $100 share. That refusal is
the whole point of the repo.

## Architecture

```
CLI (typer)
 └─ rules/          rules.json + schema  ........ the contract
     └─ engine/     evaluator + validator ....... TRUTHMODE
         └─ approvals/  queue ................... human gate
             └─ risk/   gates + kill switch ..... REDTEAM
                 └─ execution/ executor ......... OODA "act"
                     └─ broker/ mock ............. current execution adapter
                         └─ audit/ logger ....... L99 evidence trail

broker/ read-only observers ...................... provider/account evidence only
gate/ provider + eligibility receipts ............ authenticated, non-authorizing truth
```

`portfolio/` sits alongside as the single source of truth for account state.

## Load-bearing rules

These are not suggestions. Tests enforce them.

| Rule | Where | Enforcement |
|---|---|---|
| $5 cash floor | `rules.json` -> `floor_cash` | evaluator + risk gates both check |
| Ceiling is human-only | `rules.json` -> `ceiling.can_auto_increase` | schema requires `false`; validator rejects `true` |
| No auto-approve in live | `cli/main.py` | CLI exits before touching the broker |
| Mock can never go live | `broker/factory.py` | factory raises on `paper_only=False` |
| Nothing executes unapproved | `execution/executor.py` | status check before broker call |
| Audit is append-only | `audit/logger.py` | no update or delete methods exist |
| Adult eligibility cannot self-mint trust | `gate/live_money_readiness.py` | trusted issuer HMAC + expiry + account fingerprint |
| Live session must bind to the same adult account | `gate/live_money_readiness.py` | provider + account fingerprint equality required |

## Broker and provider surfaces

| Surface | Network | Money-moving | Current truth |
|---|---:|---:|---|
| `mock` | no | simulated only | active CI/paper execution adapter |
| `alpaca` | no | no | disabled compatibility stub; not a paper or live execution adapter |
| `ibkr` | no | no | disabled compatibility stub; not an execution adapter |
| `alpaca_readonly` | yes, live account GET only | no | source implementation for privacy-preserving Alpaca live-account observation |
| `ibkr_readonly` | local TWS/Gateway observation | no | source implementation; client read-only request does not prove provider-side read-only enforcement |

The Alpaca observer is intentionally **not** registered in `broker/factory.py`: an
observation object must not be substitutable for an execution broker. It reads the
canonical live `/v2/account` endpoint, hashes the provider account identity, records
observed stock/crypto account status, and exposes no order/cancel/funding/transfer methods.

Provider observations become durable readiness evidence only after the trusted runtime
authenticates a short-lived session receipt in `gate/provider_session.py`. That receipt
must bind to the same provider and account fingerprint as the independently authenticated
adult-eligibility receipt before `LIVE_BROKER_SESSION_RECEIPT` can turn green.

Adding a future execution broker still requires implementing the `BaseBroker` contract,
registering it in `broker/factory.py`, proving broker-side kill/reconciliation behavior,
and separately enabling real-money authority. A read-only observer never satisfies those
execution requirements.

## CLI

```bash
python -m cli.main validate
python -m cli.main status --broker mock
python -m cli.main run --mode paper --broker mock --symbol AAPL --qty 1 --side buy --auto-approve
python -m cli.main ibkr-readonly-receipt
```

`--auto-approve` exists only for the local paper/demo path. Live mode is refused entirely.
The IBKR command is observation-only. The Alpaca live observer currently has source/test
coverage but no CLI or web OAuth onboarding flow; runtime provider proof therefore remains
UNKNOWN until an authorized account connection is actually exercised.

## Live execution policy

Live execution is intentionally disabled. The pre-live gate and live-money readiness
receipts can prove increasingly strong prerequisites, but they cannot unlock real-money
execution by themselves.

For third-party Alpaca users, a production product also needs the applicable Alpaca app
registration/approval and OAuth flow. Repository source or a successful read-only account
observation is not evidence that those external provider requirements are satisfied.

## Investor research lens

Every paper evaluation now carries a non-authorizing `investor_lens` receipt. It applies
durable research questions drawn from Berkshire Hathaway, Fundsmith, Nick Sleep's Nomad
letters, Bridgewater, and Howard Marks/Oaktree:

- quality and long-duration compounding
- scale benefits shared with customers
- valuation and margin-of-safety discipline
- balance-sheet and financing resilience
- macro, geographic, inflation, and supply-chain diversification
- trend confirmation only as secondary evidence

Current market-regime observations expire instead of becoming permanent rules. Public
manager holdings such as SEC Form 13F disclosures are explicitly zero-weight context:
they cannot become buy/sell instructions, position sizing, approval, or execution
authority.

The investor lens does **not** alter `allowed`, the human ceiling, approval state, risk
gates, or broker behavior. It is paper-only decision-support metadata.

## Honest limits

This does not pick winners. There is no demonstrated alpha in this repo. It is the
governance and execution shell around whatever strategy you supply. `ProposalEvaluator`
still assumes a placeholder price for stocks before the executor's fresh-market recheck;
do not treat proposal-stage sizing as production order sizing.

A green provider-session receipt proves only that trusted runtime code recently observed
the matching live provider/account state. It does **not** prove provider app approval,
adult eligibility by itself, order authority, available funds, strategy quality, or a
successful live trade.

## License

MIT
