"""SleepWealth MCP/provider integration plane.

MCP is a transport and tool surface. It never creates authority by itself.
Fingerprints and continuity cookies are non-secret state markers; credentials
remain in provider-native secret storage and money-moving actions require a
separately authenticated product authority receipt.
"""

from .authority import (
    ProductAuthorityDecision,
    issue_product_action_authority,
    validate_product_action_authority,
)
from .continuity import (
    ContinuityDecision,
    issue_continuity_cookie,
    validate_continuity_cookie,
)
from .providers import ProviderManifest, get_provider_manifest, provider_manifests

__all__ = [
    "ContinuityDecision",
    "ProductAuthorityDecision",
    "ProviderManifest",
    "get_provider_manifest",
    "issue_continuity_cookie",
    "issue_product_action_authority",
    "provider_manifests",
    "validate_continuity_cookie",
    "validate_product_action_authority",
]
