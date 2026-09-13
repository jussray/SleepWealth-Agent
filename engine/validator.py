class RulesValidator:
    """Dependency-free validation for the repository's explicit safety contract."""

    def validate(self, rules: dict) -> tuple[bool, list[str]]:
        errors: list[str] = []

        if "version" not in rules:
            errors.append("missing 'version'")

        if "floor_cash" not in rules:
            errors.append("missing 'floor_cash'")
        elif not isinstance(rules["floor_cash"], (int, float)):
            errors.append("'floor_cash' must be a number")
        elif rules["floor_cash"] < 0:
            errors.append("'floor_cash' must be >= 0")

        ceiling = rules.get("ceiling")
        if ceiling is None:
            errors.append("missing 'ceiling'")
        else:
            if ceiling.get("can_auto_increase") is not False:
                errors.append("'ceiling.can_auto_increase' must be false (human-only ladder)")
            if "current" not in ceiling:
                errors.append("missing 'ceiling.current'")

        ladder = rules.get("capital_ladder")
        if ladder is not None:
            if ladder.get("paper_only") is not True:
                errors.append("'capital_ladder.paper_only' must be true")
            if ladder.get("can_auto_promote") is not False:
                errors.append(
                    "'capital_ladder.can_auto_promote' must be false (human-only promotion)"
                )

            for key in ("max_days_held", "promotion_wins_required"):
                value = ladder.get(key)
                if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                    errors.append(f"'capital_ladder.{key}' must be an integer >= 1")

            multiplier = ladder.get("max_step_multiplier")
            if (
                not isinstance(multiplier, (int, float))
                or isinstance(multiplier, bool)
                or multiplier < 1
            ):
                errors.append("'capital_ladder.max_step_multiplier' must be >= 1")

            loss_limit = ladder.get("max_cycle_loss_pct")
            if (
                not isinstance(loss_limit, (int, float))
                or isinstance(loss_limit, bool)
                or loss_limit <= 0
            ):
                errors.append("'capital_ladder.max_cycle_loss_pct' must be > 0")

            margin = ladder.get("min_net_margin_pct")
            if (
                not isinstance(margin, (int, float))
                or isinstance(margin, bool)
                or margin < 0
            ):
                errors.append("'capital_ladder.min_net_margin_pct' must be >= 0")

            protected = ladder.get("protected_profit_pct")
            if (
                not isinstance(protected, (int, float))
                or isinstance(protected, bool)
                or protected < 0
                or protected > 100
            ):
                errors.append("'capital_ladder.protected_profit_pct' must be between 0 and 100")

        return not errors, errors
