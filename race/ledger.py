"""Stake ledger.

This replaces the old `floor_cash` semantics, which were wrong for racing.

The old rule said "never let cash drop below $5". With exactly $5 in the
account that blocks every order forever — the agent sits idle and earns $0.
Verified: qty=0.001 ($0.10) was rejected as a floor breach.

The racing rule is different and is what was actually meant:

    * A race is STAKED at $5. The engine may spend the whole stake — that is
      the entire point of a race.
    * Profit above the stake is SWEPT into a vault at race end.
    * The vault is locked. No engine can spend from it, ever.
    * A race never starts below $5. Losses do not compound across races.
    * The only withdrawal from the vault is the explicit +$5 winner bonus,
      applied by the harness, never by an engine decision.

So the floor protects the *pool*, not the *stake*. The stake is meant to be
risked. The pool is meant to survive.

INTERPRETATION FLAG: "winner gets +$5 out of the balance made" is read here as
the winner's next stake becoming $10 (base $5 + $5 bonus drawn from the vault),
while the loser resets to $5. If the intent was that the winner keeps its whole
ending balance instead, change `WINNER_BONUS` / `carry_full_balance` and the
harness picks it up — no other file needs to change.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

BASE_STAKE = 5.00
WINNER_BONUS = 5.00


class VaultBreach(Exception):
    """Raised if anything tries to spend locked profit."""


@dataclass
class LedgerEntry:
    race_id: int
    engine: str
    stake: float
    ending_balance: float
    swept_to_vault: float
    vault_after: float
    next_stake: float
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "race_id": self.race_id,
            "engine": self.engine,
            "stake": round(self.stake, 2),
            "ending_balance": round(self.ending_balance, 2),
            "swept_to_vault": round(self.swept_to_vault, 2),
            "vault_after": round(self.vault_after, 2),
            "next_stake": round(self.next_stake, 2),
            "timestamp": self.timestamp,
        }


class StakeLedger:
    """Tracks stakes and the locked vault across races.

    The vault is deliberately not exposed as a mutable attribute to engines.
    Only `sweep_profit` (adds) and `_draw_winner_bonus` (subtracts, harness-only)
    can move it.
    """

    def __init__(self, base_stake: float = BASE_STAKE, winner_bonus: float = WINNER_BONUS):
        self.base_stake = base_stake
        self.winner_bonus = winner_bonus
        self._vault = 0.0
        self._stakes: dict[str, float] = {}
        self.entries: List[LedgerEntry] = []

    # ---- reads -------------------------------------------------------

    @property
    def vault(self) -> float:
        """Locked profit. Read-only to everything outside this class."""
        return round(self._vault, 2)

    def stake_for(self, engine: str) -> float:
        return self._stakes.get(engine, self.base_stake)

    def can_start_race(self, engine: str) -> tuple[bool, str]:
        stake = self.stake_for(engine)
        if stake < self.base_stake:
            return False, (
                f"{engine} stake ${stake:.2f} is below the ${self.base_stake:.2f} floor. "
                "Race cannot start."
            )
        return True, f"{engine} staked at ${stake:.2f}"

    # ---- writes ------------------------------------------------------

    def settle_race(
        self,
        race_id: int,
        engine: str,
        ending_balance: float,
        is_winner: bool,
    ) -> LedgerEntry:
        """Close out one engine's race.

        Profit sweeps to the vault. The stake resets to base. A winner gets the
        bonus added on top for the next race, drawn from the vault if funded.
        """
        stake = self.stake_for(engine)
        profit = ending_balance - stake
        swept = max(profit, 0.0)

        if swept > 0:
            self._vault += swept

        next_stake = self.base_stake

        if is_winner:
            bonus = self._draw_winner_bonus()
            next_stake += bonus

        self._stakes[engine] = next_stake

        entry = LedgerEntry(
            race_id=race_id,
            engine=engine,
            stake=stake,
            ending_balance=ending_balance,
            swept_to_vault=swept,
            vault_after=self.vault,
            next_stake=next_stake,
        )
        self.entries.append(entry)
        return entry

    def _draw_winner_bonus(self) -> float:
        """Harness-only. The single legal withdrawal from the vault."""
        available = min(self.winner_bonus, self._vault)
        self._vault -= available
        return available

    def spend_from_vault(self, amount: float) -> None:
        """Engines calling this is a bug. It exists to fail loudly."""
        raise VaultBreach(
            f"Attempt to spend ${amount:.2f} from the locked vault. "
            "Engines race with the stake, never the pool."
        )

    # ---- reporting ---------------------------------------------------

    def summary(self) -> dict:
        return {
            "vault": self.vault,
            "base_stake": self.base_stake,
            "stakes": {k: round(v, 2) for k, v in self._stakes.items()},
            "races_settled": len({e.race_id for e in self.entries}),
        }

    def render(self) -> str:
        s = self.summary()
        lines = [
            f"VAULT (locked, untouchable): ${s['vault']:.2f}",
            f"Next stakes: "
            + ", ".join(f"{k} ${v:.2f}" for k, v in s["stakes"].items())
            if s["stakes"]
            else "Next stakes: base for all",
        ]
        return "\n".join(lines)
