import pytest

from broker.factory import get_broker


@pytest.mark.parametrize("broker_name", ["mock", "alpaca", "ibkr"])
def test_factory_refuses_all_live_brokers(broker_name):
    with pytest.raises(ValueError, match="Live broker execution is disabled"):
        get_broker(broker_name, paper_only=False)
