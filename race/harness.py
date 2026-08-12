"""Race harness.

Runs both engines over the same market data for a user-set window. Identical
input, identical rules, different styles. Scores on return % of stake.

Duration is chosen by the curator at start (`--duration`). The harness maps a
duration to a tick budget; in `--live-clock` mode it also sleeps between ticks
so a "1h" race actually takes an hour.

Every decision is Redteamed by its own engine before it can touch the sandbox,
and every decision is written to the append-only audit log with its mode tags —
including /futureyou, which is enforced at construction in race.modes.
"""

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from audit.logger import AuditLogger
from race.engines.base import EngineState, MarketSnapshot, RaceEngine, Tick
from race.ledger import StakeLedger
from race.modes import Decision
from race.scoring import EngineScore, RaceResult

DURATIONS = {
    "5m": 10, "15m": 20, "30m": 40,
    "1h": 60, "4h": 120, "1d": 240, "1w": 480,
}


def parse_duration(label: str) -> int:
    if label in DURATIONS:
        return DURATIONS[label]
    raise ValueError(
        f"Unknown duration '{label}'. Choose from: {', '.join(DURATIONS)}"
    )


class PriceFeed:
    """Seeded random walk. SIMULATION ONLY — contains no alpha and no real data.

    Exists so races diverge and the harness can be exercised end to end. Swap
    for a broker-backed feed via `BrokerFeed` before any number here means
    anything.
    """

    def __init__(self, symbols: List[str], seed: Optional[int] = None,
                 start_price: float = 100.0):
        self.rng = random.Random(seed)
        self.symbols = symbols
        self.prices: Dict[str, float] = {s: start_price for s in symbols}
        self.prev: Dict[str, float] = dict(self.prices)
        self.history: Dict[str, List[float]] = {s: [start_price] for s in symbols}
        # Each symbol gets its own character so ranking is non-trivial.
        self.vol: Dict[str, float] = {
            s: self.rng.uniform(0.15, 1.4) for s in symbols
        }
        self.drift: Dict[str, float] = {
            s: self.rng.uniform(-0.06, 0.10) for s in symbols
        }

    def advance(self, tick_index: int) -> MarketSnapshot:
        ticks = {}
        for s in self.symbols:
            self.prev[s] = self.prices[s]
            move = self.rng.gauss(self.drift[s], self.vol[s])
            self.prices[s] = max(0.01, self.prices[s] * (1 + move / 100))
            self.history[s].append(self.prices[s])
            ticks[s] = Tick(s, self.prices[s], self.prev[s])
        return MarketSnapshot(
            tick_index=tick_index,
            ticks=ticks,
            history={k: list(v) for k, v in self.history.items()},
        )


class BrokerFeed:
    """Live-ish feed backed by a BaseBroker. Use with mock/alpaca/ibkr."""

    def __init__(self, broker, symbols: List[str]):
        self.broker = broker
        self.symbols = symbols
        self.prev: Dict[str, float] = {}
        self.history: Dict[str, List[float]] = {s: [] for s in symbols}

    async def advance(self, tick_index: int) -> MarketSnapshot:
        ticks = {}
        for s in self.symbols:
            data = await self.broker.get_market_data(s)
            price = float(data["price"])
            prev = self.prev.get(s, price)
            self.prev[s] = price
            self.history[s].append(price)
            ticks[s] = Tick(s, price, prev)
        return MarketSnapshot(
            tick_index=tick_index,
            ticks=ticks,
            history={k: list(v) for k, v in self.history.items()},
        )


@dataclass
class _Sandbox:
    """Each engine races its own stake. No shared account, no interference."""
    state: EngineState
    peak: float
    trough: float
    fills: List[dict] = field(default_factory=list)

    def apply(self, decision: Decision, snapshot: MarketSnapshot) -> Optional[dict]:
        if not decision.executed or not decision.symbol:
            return None
        price = snapshot.ticks[decision.symbol].price
        st = self.state

        if decision.action == "buy":
            cost = decision.qty * price
            if cost > st.cash + 1e-9 or decision.qty <= 0:
                return None
            st.cash -= cost
            held = st.positions.get(decision.symbol, 0.0)
            prev_entry = st.entry_prices.get(decision.symbol, price)
            total = held + decision.qty
            st.entry_prices[decision.symbol] = (
                (prev_entry * held + price * decision.qty) / total if total else price
            )
            st.positions[decision.symbol] = total

        elif decision.action == "sell":
            held = st.positions.get(decision.symbol, 0.0)
            qty = min(decision.qty, held)
            if qty <= 0:
                return None
            st.cash += qty * price
            st.positions[decision.symbol] = held - qty
            if st.positions[decision.symbol] <= 1e-9:
                st.positions.pop(decision.symbol, None)
                st.entry_prices.pop(decision.symbol, None)
        else:
            return None

        fill = {
            "action": decision.action,
            "symbol": decision.symbol,
            "qty": round(decision.qty, 6),
            "price": round(price, 4),
            "tick": snapshot.tick_index,
        }
        self.fills.append(fill)
        return fill


class RaceHarness:
    """Runs one race between two engines, then settles the ledger."""

    def __init__(
        self,
        engines: List[RaceEngine],
        ledger: StakeLedger,
        audit: AuditLogger,
        feed=None,
        live_clock: bool = False,
    ):
        if len(engines) != 2:
            raise ValueError("A race needs exactly two engines.")
        self.engines = engines
        self.ledger = ledger
        self.audit = audit
        self.feed = feed
        self.live_clock = live_clock
        self.race_id = 0
        self.transcripts: Dict[int, Dict[str, List[Decision]]] = {}

    async def run_race(self, duration: str = "1h", seed: Optional[int] = None,
                       verbose: bool = True) -> RaceResult:
        self.race_id += 1
        ticks = parse_duration(duration)

        for eng in self.engines:
            ok, msg = self.ledger.can_start_race(eng.name)
            if not ok:
                raise RuntimeError(msg)

        symbols = sorted({s for e in self.engines for s in e.approved_symbols})
        feed = self.feed or PriceFeed(symbols, seed=seed)
        is_async_feed = hasattr(feed, "advance") and asyncio.iscoroutinefunction(feed.advance)

        boxes: Dict[str, _Sandbox] = {}
        for eng in self.engines:
            stake = self.ledger.stake_for(eng.name)
            boxes[eng.name] = _Sandbox(
                state=EngineState(cash=stake, stake=stake),
                peak=stake,
                trough=stake,
            )
            eng.decisions = []

        await self.audit.log({
            "event": "race_started",
            "race_id": self.race_id,
            "duration": duration,
            "ticks": ticks,
            "symbols": symbols,
            "stakes": {e.name: self.ledger.stake_for(e.name) for e in self.engines},
            "vault_locked": self.ledger.vault,
        })

        if verbose:
            print(f"\n{'=' * 64}")
            print(f"RACE {self.race_id} — {duration} — {ticks} ticks — {', '.join(symbols)}")
            for e in self.engines:
                print(f"  {e.name:<6} stake ${self.ledger.stake_for(e.name):.2f}  "
                      f"risk≤{e.risk_threshold:.0f}  maxDD {e.max_drawdown_pct:.0f}%")
            print(f"  VAULT (locked): ${self.ledger.vault:.2f}")
            print("=" * 64)

        for i in range(ticks):
            snapshot = await feed.advance(i) if is_async_feed else feed.advance(i)

            for eng in self.engines:
                box = boxes[eng.name]
                decision = eng.decide(snapshot, box.state)
                decision = eng.redteam(decision, box.state, snapshot)
                fill = box.apply(decision, snapshot)

                equity = box.state.equity(snapshot)
                box.peak = max(box.peak, equity)
                box.trough = min(box.trough, equity)

                await self.audit.log({
                    "event": "race_decision",
                    "race_id": self.race_id,
                    "tick": i,
                    "equity": round(equity, 4),
                    "fill": fill,
                    **decision.to_dict(),
                })

                if verbose and (decision.executed or decision.vetoed_by):
                    print(f"  t{i:03d} {decision.render()}")

            if self.live_clock:
                await asyncio.sleep(self._tick_seconds(duration, ticks))

        # Liquidate to a comparable number.
        final_snapshot = snapshot
        scores = []
        for eng in self.engines:
            box = boxes[eng.name]
            ending = box.state.equity(final_snapshot)
            scores.append(EngineScore(
                engine=eng.name,
                stake=box.state.stake,
                ending_balance=ending,
                decisions=list(eng.decisions),
                peak_equity=box.peak,
                trough_equity=box.trough,
            ))

        result = RaceResult(
            race_id=self.race_id,
            duration_label=duration,
            ticks=ticks,
            scores=scores,
        )

        self.transcripts[self.race_id] = {
            e.name: list(e.decisions) for e in self.engines
        }

        winner = result.winner
        for s in scores:
            entry = self.ledger.settle_race(
                race_id=self.race_id,
                engine=s.engine,
                ending_balance=s.ending_balance,
                is_winner=bool(winner and s.engine == winner.engine),
            )
            await self.audit.log({
                "event": "race_settled",
                **entry.to_dict(),
                **s.to_dict(),
            })

        await self.audit.log({
            "event": "race_finished",
            **result.to_dict(),
            "vault_after": self.ledger.vault,
        })

        if verbose:
            print("-" * 64)
            print(result.render())
            print(self.ledger.render())

        return result

    @staticmethod
    def _tick_seconds(duration: str, ticks: int) -> float:
        seconds = {
            "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
        }.get(duration, 3600)
        return seconds / max(ticks, 1)

    def cross_learn(self, result: RaceResult, verbose: bool = True) -> Dict[str, List[str]]:
        """The whole point: the loser reads the winner's MOVES, not the score.

        Runs both directions — the winner also reads the loser, because a win
        can be luck and the loser's process may still contain the better idea.
        """
        patches: Dict[str, List[str]] = {}
        by_name = {e.name: e for e in self.engines}
        transcript = self.transcripts.get(result.race_id, {})

        for eng in self.engines:
            opponent = next(e for e in self.engines if e.name != eng.name)
            opponent_moves = transcript.get(opponent.name, [])
            patches[eng.name] = eng.learn_from_moves(opponent_moves)

        if verbose:
            print(f"\n{'-' * 64}\nCROSS-LEARNING (moves, not outcomes)")
            for name, applied in patches.items():
                print(f"\n  {name} patched from {('Gates' if name == 'Musk' else 'Musk')}:")
                for p in applied:
                    print(f"    • {p}")
        return patches
