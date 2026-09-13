"""Base race engine.

Both engines implement this identically. They differ in *style* and in the
threshold their Redteam runs at — not in what governance they're subject to.
Musk is not ungoverned. Musk has a Redteam with a higher tolerance.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from race.modes import Decision, FutureYou, ModeNote


@dataclass
class Tick:
    """One symbol's state at one moment in a race."""
    symbol: str
    price: float
    prev_price: float

    @property
    def change_pct(self) -> float:
        if self.prev_price == 0:
            return 0.0
        return ((self.price - self.prev_price) / self.prev_price) * 100


@dataclass
class MarketSnapshot:
    """What both engines see. Identical input, different reads."""
    tick_index: int
    ticks: Dict[str, Tick]
    history: Dict[str, List[float]] = field(default_factory=dict)

    def volatility(self, symbol: str) -> float:
        """Crude realized vol: mean absolute % move across history."""
        prices = self.history.get(symbol, [])
        if len(prices) < 2:
            return 0.0
        moves = [
            abs((prices[i] - prices[i - 1]) / prices[i - 1]) * 100
            for i in range(1, len(prices))
            if prices[i - 1] != 0
        ]
        return sum(moves) / len(moves) if moves else 0.0

    def trend(self, symbol: str) -> float:
        """% change from first observation to now."""
        prices = self.history.get(symbol, [])
        if len(prices) < 2 or prices[0] == 0:
            return 0.0
        return ((prices[-1] - prices[0]) / prices[0]) * 100


@dataclass
class EngineState:
    """One engine's position inside a live race."""
    cash: float
    stake: float
    positions: Dict[str, float] = field(default_factory=dict)
    entry_prices: Dict[str, float] = field(default_factory=dict)

    def equity(self, snapshot: MarketSnapshot) -> float:
        held = 0.0
        for sym, qty in self.positions.items():
            tick = snapshot.ticks.get(sym)
            if tick and qty:
                held += qty * tick.price
        return self.cash + held

    def unrealized_pct(self, symbol: str, snapshot: MarketSnapshot) -> float:
        entry = self.entry_prices.get(symbol)
        tick = snapshot.ticks.get(symbol)
        if not entry or not tick or entry == 0:
            return 0.0
        return ((tick.price - entry) / entry) * 100


class RaceEngine(ABC):
    """Contract both racers implement."""

    def __init__(
        self,
        name: str,
        risk_threshold: float,
        max_drawdown_pct: float,
        approved_symbols: List[str],
    ):
        self.name = name
        self.risk_threshold = risk_threshold
        self.max_drawdown_pct = max_drawdown_pct
        self.approved_symbols = approved_symbols
        self.lessons: List[str] = []
        self.decisions: List[Decision] = []

    @abstractmethod
    def decide(self, snapshot: MarketSnapshot, state: EngineState) -> Decision:
        """Produce one mode-tagged decision. Must include /futureyou."""

    @abstractmethod
    def learn_from_moves(self, opponent_decisions: List[Decision]) -> List[str]:
        """Read the opponent's MOVES, not their P&L. Return patches applied."""

    def redteam(self, decision: Decision, state: EngineState,
                snapshot: MarketSnapshot) -> Decision:
        """Same Redteam contract for both engines. Different tolerance."""
        if decision.action == "hold":
            return decision

        if decision.risk_score > self.risk_threshold:
            return decision.veto(
                f"{self.name}:REDTEAM",
                f"risk {decision.risk_score:.0f} > threshold {self.risk_threshold:.0f}",
            )

        if not decision.futureyou.durable:
            return decision.veto(
                f"{self.name}:/futureyou",
                "move is not durable at +3 races; refusing to make it a habit",
            )

        if decision.action == "buy":
            cost = decision.qty * snapshot.ticks[decision.symbol].price
            if cost > state.cash + 1e-9:
                return decision.veto(
                    f"{self.name}:REDTEAM",
                    f"cost ${cost:.2f} exceeds available stake ${state.cash:.2f}",
                )

        if decision.symbol and decision.symbol not in self.approved_symbols:
            return decision.veto(
                f"{self.name}:REDTEAM",
                f"{decision.symbol} not in approved symbols",
            )

        drawdown = ((state.stake - state.equity(snapshot)) / state.stake) * 100
        if drawdown > self.max_drawdown_pct:
            return decision.veto(
                f"{self.name}:REDTEAM",
                f"drawdown {drawdown:.1f}% > max {self.max_drawdown_pct:.1f}%",
            )

        return decision

    def hold(self, reason: str, futureyou: FutureYou,
             modes: Optional[List[ModeNote]] = None) -> Decision:
        """Standard no-op move. Holding is a decision and gets logged like one."""
        return Decision(
            engine=self.name,
            action="hold",
            symbol=None,
            qty=0.0,
            confidence=0.0,
            risk_score=0.0,
            reasoning=reason,
            futureyou=futureyou,
            modes=modes or [],
        )

    def record(self, decision: Decision) -> Decision:
        self.decisions.append(decision)
        return decision
