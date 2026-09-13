import math

import pytest

from broker.base import Order
from execution.executor import ExecutionManager


@pytest.mark.parametrize("side, field", [("buy", "ask"), ("sell", "bid")])
def test_present_zero_executable_side_does_not_fall_back(side, field):
    order = Order("AAPL", 1, side)
    market_data = {field: 0.0, "price": 123.45}

    with pytest.raises(ValueError, match="finite and greater than zero"):
        ExecutionManager._execution_price(order, market_data)


@pytest.mark.parametrize("side, field", [("buy", "ask"), ("sell", "bid")])
@pytest.mark.parametrize("bad_price", [math.nan, math.inf, -math.inf, -1.0])
def test_non_finite_or_negative_executable_side_is_rejected(side, field, bad_price):
    order = Order("AAPL", 1, side)
    market_data = {field: bad_price, "price": 123.45}

    with pytest.raises(ValueError, match="finite and greater than zero"):
        ExecutionManager._execution_price(order, market_data)


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_reference_price_is_only_used_when_side_quote_is_absent(side):
    order = Order("AAPL", 1, side)

    assert ExecutionManager._execution_price(order, {"price": 123.45}) == 123.45


def test_unknown_side_fails_closed():
    order = Order("AAPL", 1, "hold")

    with pytest.raises(ValueError, match="unknown side"):
        ExecutionManager._execution_price(order, {"price": 123.45})
