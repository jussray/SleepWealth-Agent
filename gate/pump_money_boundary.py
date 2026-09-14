"""Fail-closed Pump Live Box money-boundary receipt.

This module makes the Pump practice surface's execution ceiling explicit and
machine-readable. Environment/config hints are observations only; none of them
can create wallet, funding, signing, brokerage, or real-money authority.
"""

from __future__ import annotations

import hashlib
import json
import os

_OVERRIDE_NAMES = (
    "SLEEPWEALTH_REAL_MONEY",
    "SLEEPWEALTH_LIVE_EXECUTION",
    "SLEEPWEALTH_PUMP_REAL_MONEY",
    "SLEEPWEALTH_PUMP_LIVE_EXECUTION",
    "SLEEPWEALTH_PUMP_WALLET",
    "SLEEPWEALTH_PUMP_BROKER",
)


def pump_money_boundary() -> dict[str, object]:
    """Return the immutable execution ceiling for the Pump practice surface.

    Only override *names* are reported. Values are intentionally ignored so a
    secret, wallet address, token, or provider setting can never become
    authority or leak through this receipt.
    """

    attempted_overrides = sorted(name for name in _OVERRIDE_NAMES if name in os.environ)
    core = {
        "event": "pump_money_boundary_evaluated",
        "classification": "BLOCKED",
        "authority": "sandbox-simulation-only",
        "execution_authorized": False,
        "real_money": False,
        "live_execution": False,
        "wallet_connection": False,
        "funding": False,
        "signing": False,
        "brokerage_order_submission": False,
        "attempted_override_names": attempted_overrides,
        "override_effect": "none",
        "truth": (
            "Pump public evidence and practice results may inform simulation only. "
            "Configuration or environment values cannot open a real-money path."
        ),
    }
    canonical = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return {
        **core,
        "fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "cookie": "pump-money-boundary-v1:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24],
    }
