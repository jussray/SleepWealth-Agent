from backend.pump_live_box_server import HTML


def test_pump_live_box_does_not_claim_unverified_mom8_contract():
    assert "MOM8-DEMO-MINT" not in HTML
    assert 'value="https://pump.fun/coin/MOM8"' not in HTML
    assert 'value="MOM8"' not in HTML
    assert "MOM8</strong> is the founder-owned token identity" in HTML
    assert "External contracts are observation targets only and never replace MOM8" in HTML
    assert 'placeholder="Exact mint address"' in HTML
    assert 'placeholder="Current observed price"' in HTML


def test_local_playwright_fixture_is_generic_and_local_only():
    assert "['127.0.0.1','localhost'].includes(location.hostname)" in HTML
    assert "TEST-DEMO-MINT" in HTML
    assert "TEST-OBSERVATION" in HTML
