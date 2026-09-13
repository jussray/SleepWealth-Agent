import math

import pytest

from broker.base import Order
from broker.mock import MockBroker


@pytest.mark.asyncio
async def test_mock_quote_and_fill_share_the_same_observed_price():
    broker = MockBroker(initial_cash=1_000.0)
    broker.set_market_price("AAPL", 123.45)
    await broker.connect()

    quote = await broker.get_market_data("AAPL")
    result = await broker.submit_order(Order("AAPL", 1, "buy"))

    assert quote["price"] == 123.45
    assert quote["bid"] == quote["price"]
    assert quote["ask"] == quote["price"]
    assert result["filled_price"] == quote["price"]
    assert result["fill_classification"] == "SIMULATED_AT_OBSERVED_PRICE"


@pytest.mark.parametrize("price", [math.nan, math.inf, -math.inf, 0.0, -1.0])
def test_mock_price_rejects_non_finite_or_non_positive_values(price):
    broker = MockBroker()

    with pytest.raises(ValueError, match="finite and greater than zero"):
        broker.set_market_price("AAPL", price)
