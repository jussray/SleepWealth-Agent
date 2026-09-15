from __future__ import annotations

# Source checkout default. The Vercel runtime packager rewrites this module in the
# deployment artifact with the exact source SHA that produced the bundle.
SOURCE_SHA: str | None = None
SOURCE_PROVIDER = "vercel-bundle"
