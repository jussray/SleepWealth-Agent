from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ProviderManifest:
    provider: str
    provider_class: str
    environments: tuple[str, ...]
    actions: tuple[str, ...]
    authority_required_actions: tuple[str, ...]
    human_permission_required_actions: tuple[str, ...]
    write_preparation_actions: tuple[str, ...]
    money_moving_actions: tuple[str, ...]
    customer_approval_actions: tuple[str, ...]
    external_signer_actions: tuple[str, ...]
    live_consequence_blocked_environments: tuple[str, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        return {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in payload.items()
        }


_PROVIDER_MANIFESTS = {
    "github-control": ProviderManifest(
        provider="github-control",
        provider_class="control-plane",
        environments=("external",),
        actions=("repo-read", "repo-write", "pr-review", "workflow-observe"),
        authority_required_actions=(),
        human_permission_required_actions=(),
        write_preparation_actions=(),
        money_moving_actions=(),
        customer_approval_actions=(),
        external_signer_actions=(),
        live_consequence_blocked_environments=(),
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
        authority_required_actions=("broadcast-signed-transaction",),
        human_permission_required_actions=(
            "get-balance",
            "simulate-signed-transaction",
            "get-signature-status",
        ),
        write_preparation_actions=(),
        money_moving_actions=("broadcast-signed-transaction",),
        customer_approval_actions=("broadcast-signed-transaction",),
        external_signer_actions=("broadcast-signed-transaction",),
        live_consequence_blocked_environments=("mainnet-beta",),
        notes=(
            "SleepWealth never accepts a private key through MCP.",
            "Read/simulation/status actions require a standing human read grant; connection alone is insufficient.",
            "Broadcast accepts an already-signed transaction and binds authority to its SHA-256 fingerprint.",
        ),
    ),
    "vybe-solana-mcp": ProviderManifest(
        provider="vybe-solana-mcp",
        provider_class="solana-intelligence-provider",
        environments=("mainnet-readonly",),
        actions=(
            "list-endpoints",
            "search-endpoints",
            "get-endpoint",
            "query-vybe-api",
            "query-vybe-api-batch",
            "build-vybe-transaction",
        ),
        authority_required_actions=(),
        human_permission_required_actions=(
            "list-endpoints",
            "search-endpoints",
            "get-endpoint",
            "query-vybe-api",
            "query-vybe-api-batch",
            "build-vybe-transaction",
        ),
        write_preparation_actions=("build-vybe-transaction",),
        money_moving_actions=(),
        customer_approval_actions=(),
        external_signer_actions=(),
        live_consequence_blocked_environments=(),
        notes=(
            "Vybe is a human-permission-routed Solana capability lane inside Sleep Wealth.",
            "Read actions and unsigned transaction preparation can be granted separately.",
            "x402 payment remains excluded from dispatch.",
            "Unsigned transaction preparation never grants signing, broadcast, settlement, or money movement.",
            "Observed remote tool schemas are fingerprinted so capability drift renews evidence.",
        ),
    ),
    "cash-app-pay": ProviderManifest(
        provider="cash-app-pay",
        provider_class="payment-network",
        environments=("sandbox", "production"),
        actions=("create-customer-request", "create-payment", "retrieve-payment"),
        authority_required_actions=("create-customer-request", "create-payment"),
        human_permission_required_actions=(),
        money_moving_actions=("create-payment",),
        customer_approval_actions=("create-customer-request", "create-payment"),
        external_signer_actions=(),
        live_consequence_blocked_environments=("production",),
        notes=(
            "Cash App Pay is modeled as customer-approved merchant payments, not arbitrary peer-to-peer balance control.",
            "Customer-request creation and payment dispatch both require SleepWealth product authority; payment also requires the Cash App customer grant.",
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
