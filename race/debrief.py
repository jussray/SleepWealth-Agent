"""Curator debrief — the third layer.

The engines race. You read. You decide what they learn next.

This module does not decide anything. It assembles the evidence in the shape of
the mode stack so the read is fast, and it records the verdict you enter so the
next race is a consequence of a judgement rather than a drift.

Modes applied here are yours, not the engines': ULTRATHINK, /confess, /TRUTHMODE,
Lindy, OODA, /steal, and /futureyou on the whole architecture.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from race.modes import Decision, FutureYou, Mode
from race.scoring import RaceResult


@dataclass
class CuratorVerdict:
    """What you decided after reading. Logged, and applied to the next race."""
    race_id: int
    whose_logic_held: str
    was_it_luck: str
    next_duration: str
    changes: List[str] = field(default_factory=list)
    futureyou: Optional[FutureYou] = None
    recorded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self):
        if self.futureyou is None:
            raise ValueError(
                "Curator verdict needs a /futureyou. If you can't say what this "
                "decision enables or breaks three races out, you haven't decided yet."
            )

    def to_dict(self) -> dict:
        return {
            "event": "curator_verdict",
            "race_id": self.race_id,
            "whose_logic_held": self.whose_logic_held,
            "was_it_luck": self.was_it_luck,
            "next_duration": self.next_duration,
            "changes": self.changes,
            "futureyou": self.futureyou.to_dict(),
            "recorded_at": self.recorded_at,
        }


class CuratorDebrief:
    def __init__(self, result: RaceResult,
                 transcripts: Dict[str, List[Decision]],
                 patches: Dict[str, List[str]]):
        self.result = result
        self.transcripts = transcripts
        self.patches = patches

    def ultrathink(self) -> List[str]:
        out = []
        for s in self.result.scores:
            paths = [
                m.note for d in s.decisions for m in d.modes
                if m.mode is Mode.ULTRATHINK
            ]
            out.append(
                f"{s.engine}: {len(s.decisions)} decisions, {len(s.executed)} executed, "
                f"{len(s.vetoed)} self-vetoed, {len(s.holds)} holds. "
                f"{len(paths)} explicit path-explorations logged."
            )
        return out

    def confess(self) -> List[str]:
        """Luck vs skill. The question the score cannot answer."""
        out = []
        w = self.result.winner
        if w is None:
            return ["Draw. Nothing to attribute — neither style was tested to failure."]

        loser = self.result.loser
        margin = w.return_pct - (loser.return_pct if loser else 0.0)

        if len(w.executed) == 0:
            out.append(
                f"{w.engine} won without executing a single trade. That is not a "
                "strategy result, it is the market moving while it stood still. "
                "Do not read skill into this."
            )
        elif len(w.executed) <= 2:
            out.append(
                f"{w.engine} won on {len(w.executed)} execution(s). Sample size one "
                "or two is a coin, not an edge."
            )
        else:
            out.append(
                f"{w.engine} won across {len(w.executed)} executions — enough to be "
                "worth a look, not enough to be proof."
            )

        if abs(margin) < 0.5:
            out.append(
                f"Margin was {margin:+.2f}%. That's inside noise. Treat this as a draw "
                "when deciding anything."
            )
        if w.max_drawdown_pct > 15:
            out.append(
                f"{w.engine} took a {w.max_drawdown_pct:.1f}% drawdown on the way to "
                "winning. It was closer to dead than the final number admits."
            )
        return out

    def truthmode(self) -> List[str]:
        """Attack the winner's story."""
        w = self.result.winner
        if w is None:
            return ["No winner to attack."]
        out = []
        durable = w.durable_pct
        out.append(
            f"{w.engine} marked {durable:.0f}% of its own moves durable at +3 races. "
            + ("Consistent with a repeatable process."
               if durable >= 80 else
               "It won with moves it would not want to repeat. That is a warning, "
               "not a win.")
        )
        if w.vetoed:
            out.append(
                f"Its own Redteam stopped it {len(w.vetoed)}x. The governance is load-"
                "bearing here — without it the result would be a different number."
            )
        else:
            out.append(
                "Its Redteam never fired. Either the threshold is too loose to bind, "
                "or the window was too calm to test it. Check which before trusting it."
            )
        return out

    def lindy(self) -> List[str]:
        out = []
        for s in self.result.scores:
            per_trade = (s.profit / len(s.executed)) if s.executed else 0.0
            out.append(
                f"{s.engine}: {len(s.executed)} executions, ${per_trade:+.4f} per trade, "
                f"max DD {s.max_drawdown_pct:.1f}%. "
                + ("Shape looks repeatable across 10+ races."
                   if s.max_drawdown_pct < 12 and len(s.executed) >= 2 else
                   "Shape does not obviously survive repetition.")
            )
        return out

    def steal(self) -> List[str]:
        out = []
        for name, applied in self.patches.items():
            if applied:
                out.append(f"{name} took {len(applied)} patch(es) from the opponent:")
                out.extend(f"    – {p}" for p in applied)
            else:
                out.append(f"{name} extracted nothing. Either it's already right, or it isn't looking.")
        return out

    def ooda(self) -> List[str]:
        winner, loser = self.result.winner, self.result.loser
        out = ["Observe: race scored on return % of stake."]
        if winner and loser:
            out.append(
                f"Orient: {winner.engine} {winner.return_pct:+.2f}% vs "
                f"{loser.engine} {loser.return_pct:+.2f}%."
            )
            out.append(
                f"Decide: the open question is whether {winner.engine}'s edge is style or "
                "window. One more race at the same duration answers it."
            )
        else:
            out.append("Orient: draw. Neither style was distinguished by this window.")
            out.append("Decide: lengthen the window or widen the symbol set to force separation.")
        out.append("Act: enter a verdict below; it sets the next race's parameters.")
        return out

    def futureyou(self) -> List[str]:
        """Forward-look on the architecture, not the trade."""
        out = []
        total_durable = [
            d for s in self.result.scores for d in s.decisions if d.futureyou.durable
        ]
        total = [d for s in self.result.scores for d in s.decisions]
        pct = (len(total_durable) / len(total) * 100) if total else 0.0
        out.append(
            f"+3 races: {pct:.0f}% of all decisions this race were marked durable by "
            "the engine that made them."
        )
        out.append(
            "Enables: if the durable share holds above ~80%, the audit log becomes a "
            "real training corpus — you can diff race 1 against race 10 and see whether "
            "the reasoning improved, not just the P&L."
        )
        out.append(
            "Breaks: if engines learn to mark everything durable to avoid their own "
            "veto, /futureyou degrades into a rubber stamp. Watch for durable% pinned "
            "at 100 with rising drawdown — that's the tell."
        )
        out.append(
            "Architecture check: the governance shell is the asset here. The $5 is the "
            "test fixture. If a race result ever tempts a rule change that weakens the "
            "vault lock or the human-only ceiling, that's the failure mode, not a win."
        )
        return out

    def render(self) -> str:
        head = (
            f"CURATOR DEBRIEF — RACE {self.result.race_id}\n"
            f"{self.result.render()}\n"
        )
        blocks = [
            ("ULTRATHINK", self.ultrathink()),
            ("/confess", self.confess()),
            ("/TRUTHMODE", self.truthmode()),
            ("LINDY", self.lindy()),
            ("/steal", self.steal()),
            ("OODA", self.ooda()),
            ("/futureyou", self.futureyou()),
        ]
        parts = [head]
        for title, lines in blocks:
            parts.append(f"\n{title}")
            parts.extend(f"  {ln}" for ln in lines)
        parts.append("\nYOUR CALL")
        parts.append("  1. Whose logic held — Musk, Gates, neither, or both?")
        parts.append("  2. Luck or skill? (/confess)")
        parts.append("  3. Next race duration?")
        parts.append("  4. What changes — thresholds, symbols, sizing, nothing?")
        parts.append("  5. /futureyou on your own call: what does it enable or break?")
        return "\n".join(parts)
