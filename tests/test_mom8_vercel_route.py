from api.mom8_assets import mom8_asset_response


def test_mom8_index_is_served_from_canonical_public_asset() -> None:
    content_type, body = mom8_asset_response("/mom8/")
    text = body.decode("utf-8")
    assert content_type == "text/html; charset=utf-8"
    assert "MOM OF 8 / MOM8" in text
    assert "MOM8::prelaunch-brand-assets::v1" in text
    assert "Brand-ready does not mean launch-authorized." in text


def test_mom8_static_assets_are_allowlisted() -> None:
    css_type, css = mom8_asset_response("/mom8/styles.css")
    svg_type, svg = mom8_asset_response("/mom8/logo.svg")
    assert css_type == "text/css; charset=utf-8"
    assert b"--purple: #6b46c1" in css
    assert svg_type == "image/svg+xml; charset=utf-8"
    assert b"MOM8 public identity mark" in svg
    assert svg.count(b"<circle") >= 10


def test_mom8_route_does_not_become_a_generic_file_server() -> None:
    for path in (
        "/mom8/../../rules/rules.json",
        "/mom8/wallet",
        "/mom8/mint",
        "/mom8/trade",
        "/mom8/launch",
        "/mom8/secret",
    ):
        assert mom8_asset_response(path) is None
