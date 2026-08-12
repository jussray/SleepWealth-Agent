import json
from pathlib import Path

_HERE = Path(__file__).parent


def load_rules(path: str | None = None) -> dict:
    with open(path or _HERE / "rules.json") as fh:
        return json.load(fh)


def load_schema(path: str | None = None) -> dict:
    with open(path or _HERE / "schema.json") as fh:
        return json.load(fh)


__all__ = ["load_rules", "load_schema"]
