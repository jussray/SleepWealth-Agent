from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime


SCHEMA = "sleepwealth-investor-lens-v1"

LENSES = (
    {
        "id": "quality_compounding",
        "weight": 0.30,
        "influences": ["Berkshire Hathaway", "Fundsmith"],
        "question": "Does the business have durable economics, strong reinvestment, and owner-minded management?",
    },
    {
        "id": "scale_shared",
        "weight": 0.15,
        "influences": ["Nomad Investment Partnership / Nick Sleep"],
        "question": "Does scale improve the customer proposition and reinforce the moat instead of only extracting margin?",
    },
    {
        "id": "valuation_discipline",
        "weight": 0.20,
        "influences": ["Berkshire Hathaway", "Oaktree / Howard Marks"],
        "question": "Is the evidence for value strong enough relative to price, expectations, and downside?",
    },
    {
        "id": "financial_resilience",
        "weight": 0.15,
        "influences": ["Berkshire Hathaway", "Oaktree / Howard Marks"],
        "question": "Can the business survive adverse conditions without relying on fragile financing?",
    },
    {
        "id": "regime_diversification",
        "weight": 0.10,
        "influences": ["Bridgewater Associates"],
        "question": "Is the thesis overly dependent on one geography, inflation regime, supply chain, or macro outcome?",
    },
    {
        "id": "trend_confirmation",
        "weight": 0.10,
        "influences": ["macro and trend investors"],
        "question": "Does current evidence confirm the thesis without overruling quality, valuation, or risk evidence?",
    },
)

REGIME_OVERLAYS = (
    {
        "id": "ai_modern_mercantilism",
        "source": "Bridgewater Associates — Taking Stock of the New Paradigm",
        "source_date": "2026-07-27",
        "source_url": (
            "https://www.bridgewater.com/research-and-insights/"
            "from-our-cios-taking-stock-of-the-new-paradigm-content-ctd"
        ),
        "max_age_days": 180,
        "research_effect": (
            "stress-test AI-capex dependence, supply-chain choke points, industrial-policy "
            "fragmentation, geographic concentration, and inflation sensitivity"
        ),
    },
    {
        "id": "credit_expansion_watch",
        "source": "Oaktree / Howard Marks — What’s Going on in Private Credit?",
        "source_date": "2026-04-09",
        "source_url": (
            "https://www.oaktreecapital.com/insights/memo/whats-going-on-in-private-credit"
        ),
        "max_age_days": 365,
        "research_effect": (
            "stress-test refinancing, liquidity, borrower quality, and margin of safety when "
            "credit availability expands quickly"
        ),
    },
)

COPYCAT_CONTEXT = {
    "source_type": "SEC Form 13F holdings",
    "signal_weight": 0.0,
    "rule": (
        "Manager holdings are lagged and incomplete context only. They never become a buy, sell, "
        "position-size, approval, or execution instruction."
    ),
}

BOUNDARIES = {
    "authority": "none",
    "decision_support_only": True,
    "paper_only": True,
    "real_money": False,
    "live_execution": False,
    "execution_authorized": False,
    "contains_order_instructions": False,
    "can_change_order_allowed": False,
}


def _utc_now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        return current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def _fingerprint() -> str:
    static_policy = {
        "schema": SCHEMA,
        "lenses": LENSES,
        "regime_overlays": REGIME_OVERLAYS,
        "copycat_context": COPYCAT_CONTEXT,
        "boundaries": BOUNDARIES,
    }
    canonical = json.dumps(static_policy, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sw-investor-lens-v1:{digest[:24]}"


def build_investor_lens_policy_receipt(now: datetime | None = None) -> dict:
    """Return non-authorizing research policy with freshness-aware market context."""

    current = _utc_now(now)
    overlays = []
    for overlay in REGIME_OVERLAYS:
        source_time = datetime.fromisoformat(overlay["source_date"]).replace(tzinfo=UTC)
        age_days = max(0, (current - source_time).days)
        overlays.append(
            {
                **overlay,
                "age_days": age_days,
                "fresh": age_days <= int(overlay["max_age_days"]),
            }
        )

    return {
        "schema": SCHEMA,
        "fingerprint": _fingerprint(),
        "generated_at": current.isoformat(),
        "lenses": [dict(lens) for lens in LENSES],
        "regime_overlays": overlays,
        "fresh_overlay_ids": [row["id"] for row in overlays if row["fresh"]],
        "stale_overlay_ids": [row["id"] for row in overlays if not row["fresh"]],
        "copycat_context": dict(COPYCAT_CONTEXT),
        "boundaries": dict(BOUNDARIES),
    }


__all__ = ["build_investor_lens_policy_receipt"]
