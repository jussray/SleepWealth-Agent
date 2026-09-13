from typing import Optional

from .base import BaseBroker

KNOWN_BROKERS = ("mock",)


def _load_broker_class(broker_name: str):
    if broker_name == "mock":
        from .mock import MockBroker

        return MockBroker
    raise ValueError(
        "External broker adapters are disabled in this build. Choose broker='mock'."
    )


def get_broker(
    broker_name: str,
    paper_only: bool = True,
    credentials: Optional[dict] = None,
) -> BaseBroker:
    """Return the local mock broker only."""
    if not paper_only:
        raise ValueError("Live broker execution is disabled by repository policy.")
    if credentials:
        raise ValueError("Broker credentials are not accepted in the simulation-only build.")

    broker_class = _load_broker_class(broker_name)
    return broker_class(paper_mode=True)
