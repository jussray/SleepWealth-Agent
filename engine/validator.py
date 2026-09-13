from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError

from rules import load_schema


class RulesValidator:
    """Validate rules against the checked-in JSON Schema and policy invariants."""

    def __init__(self, schema: dict | None = None):
        self.schema = schema if schema is not None else load_schema()
        self._schema_validator: Draft7Validator | None = None
        self._schema_error: str | None = None

        try:
            Draft7Validator.check_schema(self.schema)
        except SchemaError as exc:
            self._schema_error = f"rules schema is invalid: {exc.message}"
        else:
            self._schema_validator = Draft7Validator(self.schema)

    @staticmethod
    def _schema_path(error) -> str:
        parts = [str(part) for part in error.absolute_path]
        return ".".join(parts) if parts else "$"

    def _schema_errors(self, rules: object) -> list[str]:
        if self._schema_error is not None:
            return [self._schema_error]

        assert self._schema_validator is not None
        validation_errors = sorted(
            self._schema_validator.iter_errors(rules),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        return [
            f"schema {self._schema_path(error)}: {error.message}"
            for error in validation_errors
        ]

    def validate(self, rules: dict) -> tuple[bool, list[str]]:
        errors = self._schema_errors(rules)

        # The schema is authoritative for structure and types. If the root is not
        # an object, policy checks cannot run safely and the schema failure is
        # already sufficient to block the ruleset.
        if not isinstance(rules, dict):
            return False, errors

        # Policy checks remain independent and human-readable. They intentionally
        # duplicate a few load-bearing constraints so policy intent cannot be
        # weakened merely by broadening schema syntax.
        if "version" not in rules:
            errors.append("missing 'version'")

        if "floor_cash" not in rules:
            errors.append("missing 'floor_cash'")
        elif not isinstance(rules["floor_cash"], (int, float)) or isinstance(
            rules["floor_cash"], bool
        ):
            errors.append("'floor_cash' must be a number")
        elif rules["floor_cash"] < 0:
            errors.append("'floor_cash' must be >= 0")

        symbol_scope = rules.get("symbol_scope")
        if symbol_scope not in {"approved", "observable-market"}:
            errors.append("'symbol_scope' must be approved or observable-market")

        ceiling = rules.get("ceiling")
        if ceiling is None:
            errors.append("missing 'ceiling'")
        elif isinstance(ceiling, dict):
            if ceiling.get("can_auto_increase") is not False:
                errors.append("'ceiling.can_auto_increase' must be false (human-only ladder)")
            if "current" not in ceiling:
                errors.append("missing 'ceiling.current'")

        lanes = rules.get("lanes")
        if not isinstance(lanes, dict):
            errors.append("missing 'lanes'")
        else:
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
                    errors.append(f"'lanes.{lane}.symbol_scope' must be {expected_scope}")
                featured = config.get("featured_symbols")
                if not isinstance(featured, list) or not featured:
                    errors.append(f"'lanes.{lane}.featured_symbols' must be a non-empty list")
                elif not all(isinstance(symbol, str) and symbol.strip() for symbol in featured):
                    errors.append(f"'lanes.{lane}.featured_symbols' must contain strings")

        ladder = rules.get("capital_ladder")
        if isinstance(ladder, dict):
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
