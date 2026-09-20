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

RICHEST_BUILDERS_SNAPSHOT = {
    "source": "Forbes — The Top 10 Richest People In The World | September 2026",
    "source_date": "2026-09-01",
    "source_url": (
        "https://www.forbes.com/sites/forbeswealthteam/article/"
        "the-top-ten-richest-people-in-the-world/"
    ),
    "ranking_signal_weight": 0.0,
    "descriptive_only": True,
    "people": (
        {"rank": 1, "name": "Elon Musk", "wealth_source": "SpaceX, Tesla"},
        {"rank": 2, "name": "Larry Page", "wealth_source": "Google"},
        {"rank": 3, "name": "Jeff Bezos", "wealth_source": "Amazon"},
        {"rank": 4, "name": "Sergey Brin", "wealth_source": "Google"},
        {"rank": 5, "name": "Michael Dell", "wealth_source": "Dell Technologies"},
        {"rank": 6, "name": "Mark Zuckerberg", "wealth_source": "Meta"},
        {"rank": 7, "name": "Larry Ellison", "wealth_source": "Oracle"},
        {"rank": 8, "name": "Jensen Huang", "wealth_source": "Nvidia"},
        {"rank": 9, "name": "Steve Ballmer", "wealth_source": "Microsoft"},
        {"rank": 10, "name": "Amancio Ortega", "wealth_source": "Inditex / Zara"},
    ),
    "rule": (
        "Rank, fame, net worth, founder ownership, and individual holdings never become security "
        "selection, position-size, approval, or execution instructions."
    ),
}

WEALTH_FORMATION_PATTERNS = (
    {
        "id": "productive_ownership",
        "weight": 0.30,
        "observation": (
            "Extreme wealth in the snapshot is dominated by meaningful ownership of productive "
            "operating businesses rather than frequent portfolio turnover."
        ),
        "application": (
            "Prefer evidence about durable ownership economics and compounding capacity over "
            "short-term ranking or price-chasing narratives."
        ),
    },
    {
        "id": "long_duration_compounding",
        "weight": 0.20,
        "observation": (
            "Several fortunes reflect stakes held across long operating histories and multiple "
            "business cycles."
        ),
        "application": "Measure thesis durability and reinvestment runway before trend excitement.",
    },
    {
        "id": "reinvestment_capacity",
        "weight": 0.20,
        "observation": (
            "Large wealth creators repeatedly reinvest into technology, infrastructure, products, "
            "distribution, or adjacent productive assets."
        ),
        "application": (
            "Ask whether incremental capital can plausibly earn attractive long-run returns without "
            "weakening financial resilience."
        ),
    },
    {
        "id": "survival_and_liquidity",
        "weight": 0.15,
        "observation": (
            "Compounding only matters if the owner or business can survive adverse conditions long "
            "enough for the thesis to mature."
        ),
        "application": "Treat liquidity, financing fragility, and downside survival as first-class evidence.",
    },
    {
        "id": "creation_vs_preservation",
        "weight": 0.15,
        "observation": (
            "Concentrated founder ownership can explain wealth creation, but it does not establish "
            "that concentrated personal portfolios are appropriate for preserving wealth."
        ),
        "application": (
            "Keep founder-concentration evidence descriptive and require a separate diversification "
            "and loss-tolerance check for any real-money readiness review."
        ),
    },
)

REAL_MONEY_READINESS_PATH = {
    "schema": "sleepwealth-real-money-readiness-v1",
    "status": "readiness-only",
    "repo_execution_capability": "none",
    "execution_authorized": False,
    "live_execution": False,
    "real_money": False,
    "stages": (
        {
            "id": "lawful_surplus",
            "gate": (
                "Real capital must come from lawful earned income, business cash flow, gifts, or "
                "other legitimately controlled funds; borrowed or required-living money does not "
                "count as risk capital."
            ),
        },
        {
            "id": "survival_liquidity",
            "gate": (
                "Protect near-term needs and define money that can remain untouched through losses "
                "or long holding periods before considering investment exposure."
            ),
        },
        {
            "id": "evidence_backed_ownership_thesis",
            "gate": (
                "Require current evidence for business quality, valuation, financial resilience, "
                "reinvestment capacity, and identifiable falsification conditions."
            ),
        },
        {
            "id": "diversification_and_loss_check",
            "gate": (
                "Separate billionaire founder concentration from personal portfolio construction; "
                "stress-test concentration, correlated risks, and affordable loss."
            ),
        },
        {
            "id": "legal_eligibility_and_account_authority",
            "gate": (
                "Satisfy applicable age, account-ownership, tax, identity, and guardian or custodian "
                "requirements where legally required; never bypass eligibility or supervision rules."
            ),
        },
        {
            "id": "repeated_paper_proof",
            "gate": (
                "Demonstrate the process repeatedly in paper simulation with fresh evidence, "
                "documented losses, rollback, and no hidden authority expansion."
            ),
        },
        {
            "id": "explicit_external_human_decision",
            "gate": (
                "Any future real-money decision must occur outside this repository under explicit "
                "authorized-human control and a separately reviewed legal, safety, broker, and "
                "money-movement architecture."
            ),
        },
    ),
}

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
        "richest_builders_snapshot": RICHEST_BUILDERS_SNAPSHOT,
        "wealth_formation_patterns": WEALTH_FORMATION_PATTERNS,
        "real_money_readiness_path": REAL_MONEY_READINESS_PATH,
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
        "richest_builders_snapshot": {
            **RICHEST_BUILDERS_SNAPSHOT,
            "people": [dict(person) for person in RICHEST_BUILDERS_SNAPSHOT["people"]],
        },
        "wealth_formation_patterns": [dict(pattern) for pattern in WEALTH_FORMATION_PATTERNS],
        "real_money_readiness_path": {
            **REAL_MONEY_READINESS_PATH,
            "stages": [dict(stage) for stage in REAL_MONEY_READINESS_PATH["stages"]],
        },
        "copycat_context": dict(COPYCAT_CONTEXT),
        "boundaries": dict(BOUNDARIES),
    }


__all__ = ["build_investor_lens_policy_receipt"]
