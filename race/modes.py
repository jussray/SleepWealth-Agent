"""The mode stack.

Every decision any engine makes carries mode tags explaining *why* it was made.
/futureyou is mandatory: a Decision without a forward-look raises at construction.
That is deliberate. A move you can't justify three races out is a move you got
lucky on, and luck doesn't compound.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

FUTUREYOU_HORIZON_RACES = 3


class Mode(str, Enum):
    ULTRATHINK = "ULTRATHINK"   # explore N paths, surface assumptions, name unknowns
    OODA = "OODA"               # observe -> orient -> decide -> act
    LINDY = "LINDY"             # what survives 10+ races; boring works
    REDTEAM = "REDTEAM"         # attack your own move before the market does
    STEAL = "/steal"            # extract signal from the opponent; copy what won
    CONFESS = "/confess"        # uncertainty, and luck vs skill, named out loud
    TRUTHMODE = "/TRUTHMODE"    # does the story hold up under attack?
    FUTUREYOU = "/futureyou"    # what does this enable or break 3 races from now?


@dataclass
class ModeNote:
    """One mode's contribution to a decision."""
    mode: Mode
    note: str

    def to_dict(self) -> dict:
        return {"mode": self.mode.value, "note": self.note}


@dataclass
class FutureYou:
    """The forward-look. Required on every decision, gate, and debrief.

    Not a prediction of price. A prediction of *consequence*: if this move
    becomes the habit, what does race N+3 look like?
    """
    enables: str            # what this unlocks if it becomes the pattern
    breaks: str             # what this costs or forecloses if it becomes the pattern
    durable: bool           # would you want this to still be true in 3 races?
    horizon_races: int = FUTUREYOU_HORIZON_RACES

    def __post_init__(self):
        if not self.enables.strip():
            raise ValueError("/futureyou: 'enables' cannot be empty")
        if not self.breaks.strip():
            raise ValueError("/futureyou: 'breaks' cannot be empty")

    def to_dict(self) -> dict:
        return {
            "enables": self.enables,
            "breaks": self.breaks,
            "durable": self.durable,
            "horizon_races": self.horizon_races,
        }

    def as_note(self) -> ModeNote:
        verdict = "durable" if self.durable else "NOT durable"
        return ModeNote(
            Mode.FUTUREYOU,
            f"+{self.horizon_races} races: enables {self.enables}; "
            f"breaks {self.breaks}; {verdict}",
        )


@dataclass
class Decision:
    """A single mode-tagged move. The atom of the audit trail."""
    engine: str
    action: str                     # "buy" | "sell" | "hold"
    symbol: Optional[str]
    qty: float
    confidence: float               # 0-100
    risk_score: float               # 0-100
    reasoning: str
    futureyou: FutureYou            # REQUIRED
    modes: List[ModeNote] = field(default_factory=list)
    vetoed_by: Optional[str] = None
    veto_reason: Optional[str] = None

    def __post_init__(self):
        if not isinstance(self.futureyou, FutureYou):
            raise TypeError(
                f"{self.engine}: every Decision needs a /futureyou. "
                "No forward-look, no move."
            )
        # /futureyou is always the last word on a decision.
        if not any(m.mode is Mode.FUTUREYOU for m in self.modes):
            self.modes.append(self.futureyou.as_note())

    @property
    def executed(self) -> bool:
        return self.vetoed_by is None and self.action != "hold"

    def veto(self, by: str, reason: str) -> "Decision":
        self.vetoed_by = by
        self.veto_reason = reason
        return self

    def mode_tags(self) -> List[str]:
        return [m.mode.value for m in self.modes]

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "action": self.action,
            "symbol": self.symbol,
            "qty": round(self.qty, 6),
            "confidence": round(self.confidence, 1),
            "risk_score": round(self.risk_score, 1),
            "reasoning": self.reasoning,
            "modes": [m.to_dict() for m in self.modes],
            "mode_tags": self.mode_tags(),
            "futureyou": self.futureyou.to_dict(),
            "vetoed_by": self.vetoed_by,
            "veto_reason": self.veto_reason,
            "executed": self.executed,
        }

    def render(self) -> str:
        """One-line human-readable form for race transcripts."""
        head = f"[{self.engine}] {self.action.upper()}"
        if self.symbol:
            head += f" {self.qty:.4f} {self.symbol}"
        head += f" (conf {self.confidence:.0f} / risk {self.risk_score:.0f})"
        if self.vetoed_by:
            head += f"  ⛔ VETOED by {self.vetoed_by}: {self.veto_reason}"
        tags = " ".join(self.mode_tags())
        return f"{head}\n    modes: {tags}\n    why: {self.reasoning}"
