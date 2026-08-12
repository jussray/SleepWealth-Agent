# Musk vs Gates — $5 Race Harness

Two governed engines race the same $5 over a window you choose. The loser reads
the winner's **moves**, not its P&L. You read both and decide what happens next.

```
  MuskEngine  (risk ≤ 75, maxDD 25%)      GatesEngine (risk ≤ 30, maxDD 8%)
  ULTRATHINK · OODA · /steal · REDTEAM     LINDY · REDTEAM · /confess · TRUTHMODE
        └──────────── same rules.json, different styles ────────────┘
                              │
                      RaceHarness (time-boxed, return % scoring)
                              │
                   cross_learn  ← loser reads winner's MOVES
                              │
                   CuratorDebrief  ← YOU, all seven modes
                              │
                     CuratorVerdict → next race params
```

## Run it

```bash
make race                                    # 1h race
make race-series                             # 4 races, cross-learning between
python -m cli.race run --duration 1d --seed 7
python -m cli.race series --races 10 --duration 30m --quiet
python -m cli.race gate                      # pre-live gate
python -m cli.race modes                     # the mode stack
```

Durations: `5m 15m 30m 1h 4h 1d 1w`. You pick at start; the harness maps it to a
tick budget.

## The mode stack

| Mode | Job |
|---|---|
| `ULTRATHINK` | explore N paths, surface assumptions, name unknowns |
| `OODA` | observe → orient → decide → act |
| `LINDY` | what survives 10+ races; boring works |
| `REDTEAM` | attack your own move before the market does |
| `/steal` | extract signal from the opponent; copy process not outcome |
| `/confess` | uncertainty, and luck vs skill, named out loud |
| `/TRUTHMODE` | does the story hold up under attack? |
| `/futureyou` | what does this enable or break **3 races** from now? |

**`/futureyou` is enforced, not documented.** A `Decision` constructed without a
forward-look raises `TypeError`. A decision whose `/futureyou.durable` is `False`
is vetoed by its own engine before it can execute. It also runs on gates, on the
debrief, and on your own verdict — you can't close a race without saying what
your call enables or breaks.

## Money rules

The old `floor_cash` semantics were wrong for racing: with exactly $5 and a $5
floor, every order is refused forever — verified, a $0.10 order was rejected.

The racing rules:

| Rule | Where | Enforcement |
|---|---|---|
| Race staked at $5 | `ledger.BASE_STAKE` | `can_start_race` refuses below it |
| Stake is fully riskable | `_Sandbox` | that's the point of a race |
| Profit sweeps to a locked vault | `settle_race` | test: `test_profit_sweeps_to_vault` |
| Engines can never spend the vault | `spend_from_vault` | raises `VaultBreach` |
| Losses never compound across races | `settle_race` | test: `test_losses_do_not_compound` |
| Only legal withdrawal is the +$5 winner bonus | `_draw_winner_bonus` | harness-only |

**Known behaviour:** the vault won't accumulate until profit per race exceeds the
$5 winner bonus, because the bonus draws from it. Tune `WINNER_BONUS` in
`race/ledger.py` if you'd rather the vault build first.

## Cross-learning

Runs **both** directions. The winner also reads the loser — a win can be luck,
and the loser's process may still hold the better idea. Engines mutate real
parameters: Musk drops `conviction_size`, Gates lowers `min_conviction` and
raises `position_size`.

## Pre-live gate

`gate/live_gate.py` — 12 machine-checkable conditions, fail-closed. Counts are
derived by replaying the append-only audit log, not read from a mutable counter.
Grounded in SEC Rule 15c3-5, MiFID II RTS 6, FIA guidance, and the Knight Capital
2012 control failures. None of those bind a solo operator; they're the source of
*which* controls matter.

## IBKR adapter

`broker/ibkr.py` on `ib_async` (ib_insync was archived read-only in March 2024).
Paper mode is **proven at runtime**, never configured: three signals must agree —
paper port (7497/4002), every `managedAccounts()` id prefixed `DU`, and the caller
asking for paper. Any disagreement disconnects without trading.

## Honest limits

- **No alpha here.** `PriceFeed` is a seeded random walk for exercising the
  harness. Point `BrokerFeed` at a real broker before any number means anything.
- The engines are style archetypes, not trading strategies.
- The asset is the governance shell — the $5 is the test fixture.
