# trading-agent

A governed trading agent. The machine proposes; the human owns the ceiling.

Paper/simulation only. Live execution is disabled at both the CLI and broker-factory layers.

## Why this exists

Most "AI trading bot" designs fail in the same place: the action layer has more authority
than the evidence layer. This repo inverts that. Every order passes through four gates
before it reaches a broker:

1. **Evaluator** (TRUTHMODE) - is this order supported by the rules?
2. **Approval queue** - has a human said yes?
3. **Risk gates** (REDTEAM) - cash floor, daily loss, drawdown, kill switch.
4. **Audit log** (L99) - append-only evidence of every decision, including the rejections.

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
                     └─ broker/ mock | alpaca ... the only thing that touches money
                         └─ audit/ logger ....... L99 evidence trail
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

## Broker adapters

| Adapter | Paper | Live | Notes |
|---|---|---|---|
| `mock` | yes | never | in-memory, no network, used by CI |
| `alpaca` | yes | disabled | paper-mode adapter only in this repository |

Adding a broker: implement the 8 methods on `BaseBroker`, register it in
`broker/factory.py`. The CLI picks it up with no other changes.

## CLI

```bash
python -m cli.main validate
python -m cli.main status --broker mock
python -m cli.main run --mode paper --broker mock --symbol AAPL --qty 1 --side buy --auto-approve

# External broker adapters are not required for the mock paper simulator.
```

`--auto-approve` exists only for the local paper/demo path. Live mode is refused entirely.

## Live execution policy

Live execution is intentionally disabled. The pre-live gate remains as a design and testing artifact only; it cannot unlock real-money execution.

## Honest limits

This does not pick winners. There is no alpha in this repo. It is the governance and
execution shell around whatever strategy you supply. `ProposalEvaluator` assumes a
placeholder price for stocks and does not fetch live quotes before sizing; wire
`get_market_data` into the evaluator before trusting the risk numbers on real orders.

## License

MIT
