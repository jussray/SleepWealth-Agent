from dataclasses import dataclass


@dataclass(frozen=True)
class FlipCycle:
    """One simulated buy/sell cycle used to evaluate the capital ladder."""

    buy_cost: float
    sale_proceeds: float
    fees: float = 0.0
    other_costs: float = 0.0
    days_held: int = 0

    def __post_init__(self):
        numeric = {
            "buy_cost": self.buy_cost,
            "sale_proceeds": self.sale_proceeds,
            "fees": self.fees,
            "other_costs": self.other_costs,
        }
        for name, value in numeric.items():
            if not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if value < 0:
                raise ValueError(f"{name} must be >= 0")
        if not isinstance(self.days_held, int):
            raise TypeError("days_held must be an integer")
        if self.days_held < 0:
            raise ValueError("days_held must be >= 0")

    @property
    def total_cost(self) -> float:
        return float(self.buy_cost + self.fees + self.other_costs)

    @property
    def net_profit(self) -> float:
        return float(self.sale_proceeds - self.total_cost)

    @property
    def margin_pct(self) -> float:
        if self.total_cost == 0:
            return 0.0
        return self.net_profit / self.total_cost * 100.0


class CapitalLadder:
    """Advisory small-to-large compounding policy for paper simulations.

    The ladder can recommend a larger human-reviewed ceiling after repeated proof.
    It never mutates rules, raises a ceiling, approves an order, or grants execution
    authority.
    """

    def __init__(self, rules: dict):
        config = rules.get("capital_ladder") or {}
        ceiling = rules.get("ceiling") or {}

        if config.get("paper_only") is not True:
            raise ValueError("capital_ladder.paper_only must be true")
        if config.get("can_auto_promote") is not False:
            raise ValueError("capital_ladder.can_auto_promote must be false")

        self.current_limit = float(ceiling.get("current", 0.0))
        self.max_limit = float(ceiling.get("max", self.current_limit))
        self.min_net_margin_pct = float(config.get("min_net_margin_pct", 15.0))
        self.max_days_held = int(config.get("max_days_held", 30))
        self.promotion_wins_required = int(config.get("promotion_wins_required", 3))
        self.protected_profit_pct = float(config.get("protected_profit_pct", 30.0))
        self.max_step_multiplier = float(config.get("max_step_multiplier", 1.5))
        self.max_cycle_loss_pct = float(config.get("max_cycle_loss_pct", 20.0))

        if self.current_limit < 0 or self.max_limit < self.current_limit:
            raise ValueError("ceiling max must be >= current and both must be non-negative")
        if self.min_net_margin_pct < 0:
            raise ValueError("min_net_margin_pct must be >= 0")
        if self.max_days_held < 1:
            raise ValueError("max_days_held must be >= 1")
        if self.promotion_wins_required < 1:
            raise ValueError("promotion_wins_required must be >= 1")
        if not 0 <= self.protected_profit_pct <= 100:
            raise ValueError("protected_profit_pct must be between 0 and 100")
        if self.max_step_multiplier < 1:
            raise ValueError("max_step_multiplier must be >= 1")
        if self.max_cycle_loss_pct <= 0:
            raise ValueError("max_cycle_loss_pct must be > 0")

    def assess(self, cycle: FlipCycle, prior_qualified_wins: int = 0) -> dict:
        if not isinstance(prior_qualified_wins, int) or prior_qualified_wins < 0:
            raise ValueError("prior_qualified_wins must be a non-negative integer")

        total_cost = cycle.total_cost
        net_profit = cycle.net_profit
        margin_pct = cycle.margin_pct
        loss_pct = min(margin_pct, 0.0)
        within_limit = total_cost <= self.current_limit
        fast_enough = cycle.days_held <= self.max_days_held
        strong_margin = net_profit > 0 and margin_pct >= self.min_net_margin_pct
        qualified = within_limit and fast_enough and strong_margin
        qualified_wins = prior_qualified_wins + (1 if qualified else 0)

        protected_profit = max(net_profit, 0.0) * self.protected_profit_pct / 100.0
        reinvestable_profit = max(net_profit, 0.0) - protected_profit

        status = "hold"
        reason = "cycle has not earned promotion"
        suggested_next_limit = self.current_limit

        if not within_limit:
            status = "blocked"
            reason = (
                f"cycle cost ${total_cost:.2f} exceeds the human-owned "
                f"${self.current_limit:.2f} ceiling"
            )
        elif loss_pct <= -self.max_cycle_loss_pct:
            status = "pause"
            reason = (
                f"cycle loss {abs(loss_pct):.1f}% meets the "
                f"{self.max_cycle_loss_pct:.1f}% pause threshold"
            )
        elif not fast_enough:
            reason = (
                f"capital was tied up {cycle.days_held}d; "
                f"target is <= {self.max_days_held}d"
            )
        elif not strong_margin:
            reason = (
                f"net margin {margin_pct:.1f}% is below the "
                f"{self.min_net_margin_pct:.1f}% proof threshold"
            )
        elif qualified_wins >= self.promotion_wins_required:
            status = "promotion_ready"
            suggested_next_limit = min(
                round(self.current_limit * self.max_step_multiplier, 2),
                self.max_limit,
            )
            if suggested_next_limit <= self.current_limit:
                status = "hold"
                reason = "human ceiling is already at its configured maximum"
            else:
                reason = (
                    f"{qualified_wins} qualifying wins support human review of "
                    f"a ${suggested_next_limit:.2f} ceiling"
                )
        else:
            reason = (
                f"qualifying win {qualified_wins}/{self.promotion_wins_required}; "
                "repeat the same proof before scaling"
            )

        return {
            "status": status,
            "qualified": qualified,
            "qualified_wins": qualified_wins,
            "required_wins": self.promotion_wins_required,
            "cycle": {
                "buy_cost": round(float(cycle.buy_cost), 2),
                "sale_proceeds": round(float(cycle.sale_proceeds), 2),
                "fees": round(float(cycle.fees), 2),
                "other_costs": round(float(cycle.other_costs), 2),
                "total_cost": round(total_cost, 2),
                "net_profit": round(net_profit, 2),
                "margin_pct": round(margin_pct, 2),
                "days_held": cycle.days_held,
            },
            "profit_split": {
                "protected": round(protected_profit, 2),
                "reinvestable": round(reinvestable_profit, 2),
            },
            "effective_limit": round(self.current_limit, 2),
            "suggested_next_limit": round(suggested_next_limit, 2),
            "max_limit": round(self.max_limit, 2),
            "reason": reason,
            "authority": "advisory",
            "paper_only": True,
            "can_auto_increase": False,
        }

    def assess_history(self, cycles: list[FlipCycle]) -> dict:
        """Recompute ladder proof from cycle evidence and return compounding analytics.

        Historical proof is derived from the supplied cycles in order. A non-qualifying
        cycle breaks the consecutive-win streak; a pause/block status also stops promotion.
        No result mutates the configured ceiling.
        """
        if not isinstance(cycles, list):
            raise TypeError("cycles must be a list of FlipCycle values")
        if any(not isinstance(cycle, FlipCycle) for cycle in cycles):
            raise TypeError("every cycle must be a FlipCycle")

        streak = 0
        qualified_count = 0
        profitable_count = 0
        failed_count = 0
        total_cost = 0.0
        total_profit = 0.0
        total_days = 0
        assessments: list[dict] = []

        for cycle in cycles:
            result = self.assess(cycle, prior_qualified_wins=streak)
            assessments.append(result)
            total_cost += cycle.total_cost
            total_profit += cycle.net_profit
            total_days += cycle.days_held
            profitable_count += int(cycle.net_profit > 0)

            if result["qualified"]:
                qualified_count += 1
                streak += 1
            else:
                failed_count += 1
                streak = 0

        cycle_count = len(cycles)
        failure_rate_pct = (failed_count / cycle_count * 100.0) if cycle_count else 0.0
        win_rate_pct = (profitable_count / cycle_count * 100.0) if cycle_count else 0.0
        capital_velocity_per_day = total_cost / max(total_days, 1) if cycle_count else 0.0
        latest = assessments[-1] if assessments else None

        promotion_ready = bool(
            latest
            and latest["status"] == "promotion_ready"
            and streak >= self.promotion_wins_required
        )
        suggested_next_limit = (
            latest["suggested_next_limit"] if promotion_ready else self.current_limit
        )

        return {
            "cycles": cycle_count,
            "qualified_cycles": qualified_count,
            "profitable_cycles": profitable_count,
            "failed_cycles": failed_count,
            "current_qualified_streak": streak,
            "failure_rate_pct": round(failure_rate_pct, 2),
            "win_rate_pct": round(win_rate_pct, 2),
            "total_deployed": round(total_cost, 2),
            "total_net_profit": round(total_profit, 2),
            "capital_velocity_per_day": round(capital_velocity_per_day, 2),
            "promotion_ready": promotion_ready,
            "effective_limit": round(self.current_limit, 2),
            "suggested_next_limit": round(float(suggested_next_limit), 2),
            "authority": "advisory",
            "paper_only": True,
            "can_auto_increase": False,
            "latest_status": latest["status"] if latest else "no_data",
            "assessments": assessments,
        }
