from typing import Optional

from .base import BaseBroker

# Adapters are imported lazily so the mock path (and CI) never requires
# network libraries like httpx to be installed.
KNOWN_BROKERS = ("mock", "alpaca", "ibkr")


def _load_broker_class(broker_name: str):
    if broker_name == "mock":
        from .mock import MockBroker

        return MockBroker
    if broker_name == "alpaca":
        from .alpaca import AlpacaBroker

        return AlpacaBroker
    if broker_name == "ibkr":
        from .ibkr import IBKRBroker

        return IBKRBroker
    raise ValueError(
        f"Unknown broker: {broker_name}. Choose from: {sorted(KNOWN_BROKERS)}"
    )


def get_broker(
    broker_name: str,
    paper_only: bool = True,
    credentials: Optional[dict] = None,
) -> BaseBroker:
    """Return a broker instance by name.

    Raises ValueError for unknown brokers, or if live mode is requested
    from an adapter that is paper-only by construction.
    """
    broker_class = _load_broker_class(broker_name)
    credentials = credentials or {}

    instance = broker_class(paper_mode=paper_only, **credentials)

    if not paper_only and instance.is_paper_only():
        raise ValueError(f"Broker '{broker_name}' cannot run in live mode.")

    return instance
