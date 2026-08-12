"""Race scoring.

Primary metric: return % on stake. Chosen because it's simple, hard to game,
and creates real tension — Musk will swing and sometimes blow up, Gates will
grind and sometimes look pointless. The tension is the curriculum.

Everything else here is diagnostic. The curator reads these to tell luck from
skill; the harness only uses `return_pct` to pick a winner.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from race.modes import Decision


@dataclass
class EngineScore:
    engine: str
    stake: float
    ending_balance: float
    decisions: List[Decision] = field(default_factory=list)
    peak_equity: float = 0.0
    trough_equity: float = 0.0

    @property
    def return_pct(self) -> float:
        if self.stake == 0:
            return 0.0
        return ((self.ending_balance - self.stake) / self.stake) * 100

    @property
    def profit(self) -> float:
        return self.ending_balance - self.stake

    @property
    def max_drawdown_pct(self) -> float:
        if self.peak_equity == 0:
            return 0.0
        return max(0.0, ((self.peak_equity - self.trough_equity) / self.peak_equity) * 100)

    @property
    def executed(self) -> List[Decision]:
        return [d for d in self.decisions if d.executed]

    @property
    def vetoed(self) -> List[Decision]:
        return [d for d in self.decisions if d.vetoed_by]

    @property
    def holds(self) -> List[Decision]:
        return [d for d in self.decisions if d.action == "hold"]

    @property
    def durable_pct(self) -> float:
        """% of decisions this engine itself marked durable at +3 races."""
        if not self.decisions:
            return 0.0
        durable = sum(1 for d in self.decisions if d.futureyou.durable)
        return (durable / len(self.decisions)) * 100

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "stake": round(self.stake, 2),
            "ending_balance": round(self.ending_balance, 2),
            "profit": round(self.profit, 4),
            "return_pct": round(self.return_pct, 3),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "decisions": len(self.decisions),
            "executed": len(self.executed),
            "vetoed": len(self.vetoed),
            "holds": len(self.holds),
            "futureyou_durable_pct": round(self.durable_pct, 1),
        }


@dataclass
class RaceResult:
    race_id: int
    duration_label: str
    ticks: int
    scores: List[EngineScore]

    @property
    def winner(self) -> Optional[EngineScore]:
        if not self.scores:
            return None
        best = max(self.scores, key=lambda s: s.return_pct)
        ties = [s for s in self.scores if abs(s.return_pct - best.return_pct) < 1e-9]
        return None if len(ties) > 1 else best

    @property
    def loser(self) -> Optional[EngineScore]:
        w = self.winner
        if w is None:
            return None
        return min(self.scores, key=lambda s: s.return_pct)

    @property
    def is_draw(self) -> bool:
        return self.winner is None

    def score_for(self, engine: str) -> Optional[EngineScore]:
        return next((s for s in self.scores if s.engine == engine), None)

    def to_dict(self) -> dict:
        return {
            "race_id": self.race_id,
            "duration": self.duration_label,
            "ticks": self.ticks,
            "winner": self.winner.engine if self.winner else None,
            "draw": self.is_draw,
            "scores": [s.to_dict() for s in self.scores],
        }

    def render(self) -> str:
        lines = [f"RACE {self.race_id} — {self.duration_label} ({self.ticks} ticks)"]
        for s in sorted(self.scores, key=lambda x: -x.return_pct):
            mark = "🏆" if self.winner and s.engine == self.winner.engine else "  "
            lines.append(
                f" {mark} {s.engine:<6} ${s.stake:.2f} → ${s.ending_balance:.4f}  "
                f"{s.return_pct:+.2f}%   "
                f"exec {len(s.executed)} / veto {len(s.vetoed)} / hold {len(s.holds)}  "
                f"/futureyou durable {s.durable_pct:.0f}%"
            )
        if self.is_draw:
            lines.append("    DRAW — no bonus, both re-stake at base")
        return "\n".join(lines)
