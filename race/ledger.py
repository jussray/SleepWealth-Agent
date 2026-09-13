"""Stake ledger for the local race simulation."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List

BASE_STAKE = 5.00
WINNER_BONUS = 5.00


class VaultBreach(Exception):
    """Raised if anything tries to spend locked simulated profit."""


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
    """Tracks simulated stakes and the locked vault across races."""

    def __init__(self, base_stake: float = BASE_STAKE, winner_bonus: float = WINNER_BONUS):
        self.base_stake = base_stake
        self.winner_bonus = winner_bonus
        self._vault = 0.0
        self._stakes: dict[str, float] = {}
        self.entries: List[LedgerEntry] = []

    @property
    def vault(self) -> float:
        """Locked simulated profit. Read-only outside this class."""
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

    def settle_race(
        self,
        race_id: int,
        engine: str,
        ending_balance: float,
        is_winner: bool,
    ) -> LedgerEntry:
        stake = self.stake_for(engine)
        profit = ending_balance - stake
        swept = max(profit, 0.0)

        if swept > 0:
            self._vault += swept

        next_stake = self.base_stake
        if is_winner:
            next_stake += self._draw_winner_bonus()

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
        """Simulation harness-only withdrawal."""
        available = min(self.winner_bonus, self._vault)
        self._vault -= available
        return available

    def spend_from_vault(self, amount: float) -> None:
        raise VaultBreach(
            f"Attempt to spend ${amount:.2f} from the locked vault. "
            "Engines race with the simulated stake, never the pool."
        )

    def summary(self) -> dict:
        return {
            "vault": self.vault,
            "base_stake": self.base_stake,
            "stakes": {k: round(v, 2) for k, v in self._stakes.items()},
            "races_settled": len({entry.race_id for entry in self.entries}),
        }

    def render(self) -> str:
        summary = self.summary()
        lines = [
            f"VAULT (locked, untouchable): ${summary['vault']:.2f}",
            "Next stakes: "
            + ", ".join(f"{name} ${value:.2f}" for name, value in summary["stakes"].items())
            if summary["stakes"]
            else "Next stakes: base for all",
        ]
        return "\n".join(lines)
