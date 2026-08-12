import json
from datetime import datetime, timezone
from pathlib import Path


class AuditLogger:
    """Append-only JSONL log. No update, no delete. L99 evidence trail."""

    def __init__(self, log_path: str = "audit.log"):
        self.log_path = Path(log_path)
        if self.log_path.parent != Path("."):
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    async def log(self, event: dict) -> None:
        event = {**event, "logged_at": datetime.now(timezone.utc).isoformat()}
        with open(self.log_path, "a") as fh:
            fh.write(json.dumps(event, default=str) + "\n")

    async def read(self, limit: int = 100) -> list[dict]:
        if not self.log_path.exists():
            return []
        events = []
        with open(self.log_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events[-limit:]
