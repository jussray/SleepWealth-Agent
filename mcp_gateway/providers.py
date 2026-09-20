from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ProviderManifest:
    provider: str
    provider_class: str
    environments: tuple[str, ...]
    actions: tuple[str, ...]
    money_moving_actions: tuple[str, ...]
    customer_approval_actions: tuple[str, ...]
    external_signer_actions: tuple[str, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        return {key: list(value) if isinstance(value, tuple) else value for key, value in payload.items()}


_PROVIDER_MANIFESTS = {
    "github-control": ProviderManifest(
        provider="github-control",
        provider_class="control-plane",
        environments=("external",),
        actions=("repo-read", "repo-write", "pr-review", "workflow-observe"),
        money_moving_actions=(),
        customer_approval_actions=(),
        external_signer_actions=(),
        notes=(
            "GitHub is a control-plane/MCP caller surface, not a financial provider.",
            "Repository credentials stay in GitHub-native secret or app storage.",
        ),
    ),
    "solana-rpc": ProviderManifest(
        provider="solana-rpc",
        provider_class="onchain-network",
        environments=("devnet", "testnet", "mainnet-beta"),
        actions=(
            "get-balance",
            "simulate-signed-transaction",
            "broadcast-signed-transaction",
            "get-signature-status",
        ),
        money_moving_actions=("broadcast-signed-transaction",),
        customer_approval_actions=("broadcast-signed-transaction",),
        external_signer_actions=("broadcast-signed-transaction",),
        notes=(
            "SleepWealth never accepts a private key through MCP.",
            "Broadcast accepts an already-signed transaction and binds authority to its SHA-256 fingerprint.",
        ),
    ),
    "cash-app-pay": ProviderManifest(
        provider="cash-app-pay",
        provider_class="payment-network",
        environments=("sandbox", "production"),
        actions=("create-customer-request", "create-payment", "retrieve-payment"),
        money_moving_actions=("create-payment",),
        customer_approval_actions=("create-payment",),
        external_signer_actions=(),
        notes=(
            "Cash App Pay is modeled as customer-approved merchant payments, not arbitrary peer-to-peer balance control.",
            "A Cash App grant plus SleepWealth product authority is required before create-payment dispatch.",
        ),
    ),
}


def provider_manifests() -> list[dict[str, object]]:
    return [_PROVIDER_MANIFESTS[name].to_dict() for name in sorted(_PROVIDER_MANIFESTS)]


def get_provider_manifest(provider: str) -> ProviderManifest:
    normalized = str(provider or "").strip().lower()
    try:
        return _PROVIDER_MANIFESTS[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported provider: {normalized or '<empty>'}") from exc
