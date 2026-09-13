"""Read-only canonical MOM8 public asset lookup for the Vercel entrypoint."""

from pathlib import Path


_MOM8_ROOT = Path(__file__).resolve().parents[1] / "public" / "mom8"
_MOM8_ASSETS = {
    "/mom8": ("index.html", "text/html; charset=utf-8"),
    "/mom8/": ("index.html", "text/html; charset=utf-8"),
    "/mom8/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/mom8/logo.svg": ("logo.svg", "image/svg+xml; charset=utf-8"),
}


def mom8_asset_response(path: str):
    """Return canonical MOM8 public asset bytes for an allowlisted path only."""
    asset = _MOM8_ASSETS.get(path)
    if asset is None:
        return None
    filename, content_type = asset
    file_path = _MOM8_ROOT / filename
    return content_type, file_path.read_bytes()
