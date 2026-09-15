"""Observation-only HTTP capability helpers for external crypto sources.

This module is intentionally separate from paper execution. Pump.fun evidence is
user-supplied and normalized without network access. SideShift access is limited
to its public supported-coin catalog. Neither helper creates authority.
"""

from __future__ import annotations

from typing import Any, Callable

from market import (
    PumpFunPublicEvidenceObserver,
    SideShiftPublicCoinCatalogObserver,
    external_crypto_source_capabilities,
)


def external_crypto_sources_status() -> dict[str, Any]:
    return {
        "status": "ok",
        "lane": "crypto",
        "mode": "observation-only",
        "sources": external_crypto_source_capabilities(),
        "read_only": True,
        "authority": "none",
        "real_money": False,
        "live_execution": False,
        "truth": "external crypto sources can add evidence only; they never grant execution authority",
    }


def normalize_pump_fun_public_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    observation = PumpFunPublicEvidenceObserver().observe(payload)
    return {
        "status": "observed",
        "lane": "crypto",
        "mode": "manual-public-evidence",
        "observation": observation,
        "read_only": True,
        "authority": "none",
        "real_money": False,
        "live_execution": False,
        "truth": "Pump.fun evidence was normalized locally; no Pump.fun network request or trading action occurred",
    }


def get_sideshift_public_catalog(
    fetch_json: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    catalog = SideShiftPublicCoinCatalogObserver().list_supported_coins(fetch_json=fetch_json)
    return {
        "status": "ok",
        "lane": "crypto",
        "mode": "public-coin-catalog",
        "catalog": catalog,
        "read_only": True,
        "authority": "none",
        "real_money": False,
        "live_execution": False,
        "truth": "SideShift access is limited to the public coin catalog; no quote, shift, wallet, or funding action occurred",
    }
