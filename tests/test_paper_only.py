import pytest
from typer.testing import CliRunner

from broker.factory import KNOWN_BROKERS, get_broker
from cli.main import app


def test_factory_exposes_mock_only():
    assert KNOWN_BROKERS == ("mock",)


def test_factory_refuses_live_mode():
    with pytest.raises(ValueError, match="Live broker execution is disabled"):
        get_broker("mock", paper_only=False)


@pytest.mark.parametrize("broker_name", ["alpaca", "ibkr"])
def test_factory_refuses_external_brokers(broker_name):
    with pytest.raises(ValueError, match="External broker adapters are disabled"):
        get_broker(broker_name, paper_only=True)


def test_factory_refuses_credentials():
    with pytest.raises(ValueError, match="credentials are not accepted"):
        get_broker("mock", credentials={"token": "placeholder"})


def test_direct_external_adapters_are_disabled():
    from broker.alpaca import AlpacaBroker, ExternalBrokerDisabled as AlpacaDisabled
    from broker.ibkr import IBKRBroker, ExternalBrokerDisabled as IbkrDisabled

    with pytest.raises(AlpacaDisabled):
        AlpacaBroker()
    with pytest.raises(IbkrDisabled):
        IBKRBroker()


def test_cli_advertises_mock_only_execution():
    result = CliRunner().invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    help_text = result.stdout.lower()
    assert "mock only" in help_text
    assert "mock | alpaca" not in help_text
    assert "live execution is disabled" in help_text
