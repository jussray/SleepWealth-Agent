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

        ceiling = rules.get("ceiling")
        if ceiling is None:
            errors.append("missing 'ceiling'")
        else:
            if ceiling.get("can_auto_increase") is not False:
                errors.append("'ceiling.can_auto_increase' must be false (human-only ladder)")
            if "current" not in ceiling:
                errors.append("missing 'ceiling.current'")

        return not errors, errors
