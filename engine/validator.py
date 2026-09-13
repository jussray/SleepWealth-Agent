class RulesValidator:
    """Minimal, dependency-free rules validation. Lindy: no ajv, no jsonschema."""

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

        symbol_scope = rules.get("symbol_scope")
        if symbol_scope not in {"approved", "observable-market"}:
            errors.append("'symbol_scope' must be approved or observable-market")

        ceiling = rules.get("ceiling")
        if ceiling is None:
            errors.append("missing 'ceiling'")
        else:
            if ceiling.get("can_auto_increase") is not False:
                errors.append("'ceiling.can_auto_increase' must be false (human-only ladder)")
            if "current" not in ceiling:
                errors.append("missing 'ceiling.current'")

        lanes = rules.get("lanes")
        if not isinstance(lanes, dict):
            errors.append("missing 'lanes'")
            return not errors, errors

        expected_scopes = {
            "stock-market": "us-listed-directory",
            "crypto": "classified-observation",
        }
        for lane, expected_scope in expected_scopes.items():
            config = lanes.get(lane)
            if not isinstance(config, dict):
                errors.append(f"missing 'lanes.{lane}'")
                continue
            if config.get("enabled") is not True:
                errors.append(f"'lanes.{lane}.enabled' must be true")
            if config.get("paper_only") is not True:
                errors.append(f"'lanes.{lane}.paper_only' must be true")
            if config.get("symbol_scope") != expected_scope:
                errors.append(
                    f"'lanes.{lane}.symbol_scope' must be {expected_scope}"
                )
            featured = config.get("featured_symbols")
            if not isinstance(featured, list) or not featured:
                errors.append(f"'lanes.{lane}.featured_symbols' must be a non-empty list")
            elif not all(isinstance(symbol, str) and symbol.strip() for symbol in featured):
                errors.append(f"'lanes.{lane}.featured_symbols' must contain strings")

        return not errors, errors
