"""Tier Router — suggest a campaign-architecture tier from catalog size.

Seven strategy tiers keyed to the number of advertisable catalog units
(parents + standalone SKUs from the store-level `_catalog.json`; child
variations share the parent's campaign set so they don't multiply structure).
When no catalog is uploaded, falls back to counting distinct advertised ASINs
in the current audit db (DimAd), so the router still works from a PPC bulk
alone. Pure data + one `suggest()` entry point — no db writes.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from . import catalog as cat


# lo/hi inclusive; hi=None = open-ended. Order matters (first match wins).
TIERS = [
    {
        "key": "t1", "tier": 1, "lo": 1, "hi": 5, "range": "1-5 ASINs",
        "name": "Full Waterfall (RAF Funnel)",
        "structure": "1 campaign = 1 ASIN = 1 slot; AT > BROAD > PHRASE > EXACT > PT per ASIN",
        "campaigns_per_asin": "5-7",
        "acos": "per-ASIN Goal ACoS (margin-derived)",
        "automation": "none needed",
        "cadences": ["daily", "weekly"],
        "app": "Waterfall engine (phased A-D bulks) + Daily Watch during launch + Weekly bid tweaks/harvest",
        "techniques": [
            "Launch aggression: EXACT on 5-10 researched keywords at 120-150% CPC, judge on TACoS",
            "Top-of-Search modifiers on the EXACT money tier",
            "PT defense campaign on your own ASINs",
            "Hand-read the full STR weekly: harvest every converter, negate every bleeder",
        ],
    },
    {
        "key": "t2", "tier": 2, "lo": 6, "hi": 20, "range": "6-20 ASINs",
        "name": "Hero Waterfall + SPAG",
        "structure": "Top 3-5 ASINs get the full waterfall; the rest run a 3-campaign SPAG (Auto > Research > Exact)",
        "campaigns_per_asin": "3-7",
        "acos": "per-ASIN Goal ACoS",
        "automation": "optional",
        "cadences": ["weekly", "mid_month"],
        "app": "Cannibalization engine (sibling term ownership) + Weekly on heroes + Mid-Month negatives sweep",
        "techniques": [
            "Quarterly promotion review: sustained hero revenue upgrades a SPAG ASIN to full waterfall",
            "Shared-term ownership: highest-CVR ASIN keeps the generic term, siblings carry the negative",
            "Portfolio budget caps per product line",
            "Advertise the best-converting child per variation family only",
        ],
    },
    {
        "key": "t3", "tier": 3, "lo": 21, "hi": 50, "range": "21-50 ASINs",
        "name": "SPAG + ABC Tiering",
        "structure": "Class A (top ~20%) waterfall; Class B SPAG; Class C tail shares grouped auto catch-alls",
        "campaigns_per_asin": "2-5",
        "acos": "per-class targets (A margin-derived, B blended, C break-even)",
        "automation": "bid rules recommended",
        "cadences": ["weekly", "mid_month", "full_month"],
        "app": "Weekly (Class A) + Mid-Month bleeders + Full-Month superset; BidOptimizer guardrails = the bid rules",
        "techniques": [
            "Monthly ABC re-rank by revenue x margin; catch-all is a nursery — converters graduate to SPAG",
            "Weekly recomputed target CPC with step caps and thin-data holds",
            "Every promotion ships its upstream negative in the same bulk",
            "Dayparting viable on Class A only",
        ],
    },
    {
        "key": "t4", "tier": 4, "lo": 51, "hi": 100, "range": "51-100 ASINs",
        "name": "Goal-Segmented + Bid Automation",
        "structure": "Campaigns belong to LAUNCH / SCALE / PROFIT segments; heroes SPAG, tail multi-ASIN ad groups",
        "campaigns_per_asin": "1.5-4",
        "acos": "per-segment x margin band (9 targets govern everything)",
        "automation": "required for bids",
        "cadences": ["mid_month", "full_month", "pause_scale"],
        "app": "Mid-Month + Full-Month + Pause/Scale loops; Monitoring alerts are the exception queue; Channels for SB/SD entry",
        "techniques": [
            "Segment state machine: launch clock 30-45 days, scale while marginal ACoS holds, profit freezes budget",
            "Budget reallocation monthly, top-down — no manual campaign budget edits",
            "Exception-based review: read flags, never the campaign list",
            "SB brand defense + SD retargeting funded from PROFIT savings",
        ],
    },
    {
        "key": "t5", "tier": 5, "lo": 101, "hi": 500, "range": "101-500 ASINs",
        "name": "Category Clusters + Hero Carve-outs",
        "structure": "Default unit = cluster of 5-15 similar ASINs per ad group; top ~10% earn per-ASIN carve-outs",
        "campaigns_per_asin": "0.5-2",
        "acos": "per-portfolio (one per category, hard budget caps)",
        "automation": "required: bids + harvest + negatives on schedule",
        "cadences": ["full_month", "pause_scale"],
        "app": "Full-Month + Pause/Scale; Catalog readiness gate; Product Ads status board drives triage; Bid Ledger stops double-applied bids",
        "techniques": [
            "Cluster by shared search intent, price band (+/-30%) and margin",
            "Quarterly triage score = revenue x margin x velocity; granularity is earned, not granted",
            "Harvested Exact terms land in cluster-level campaigns (best-CVR ASIN gets the ad)",
            "Retail-readiness gate before an ASIN may enter a cluster",
        ],
    },
    {
        "key": "t6", "tier": 6, "lo": 501, "hi": 1000, "range": "501-1000 ASINs",
        "name": "Template Structure, Bulk-Generated",
        "structure": "No hand-made campaigns: naming template BRAND|CAT|TIER|SLOT|ID generates everything from catalog data",
        "campaigns_per_asin": "0.2-1",
        "acos": "per-portfolio, exception-flagged",
        "automation": "bulk-file-only management; console read-only by policy",
        "cadences": ["full_month", "pause_scale"],
        "app": "Waterfall phased A-D plan migrates legacy structures; scheduled Cannibalization ownership sweeps; Transactions ledger feeds margin scores",
        "techniques": [
            "SKU lifecycle state machine: NEW > INCUBATE > CLUSTERED > HERO / PARKED / SUPPRESSED",
            "Inventory-aware bidding off weeks-of-cover (throttle pre-stockout, push overstock)",
            "Continuous duplicate consolidation — the #1 silent waste at this scale",
            "Exact-string entity IDs everywhere; floats mangle 16-18 digit IDs",
        ],
    },
    {
        "key": "t7", "tier": 7, "lo": 1001, "hi": None, "range": "1000+ ASINs",
        "name": "Portfolio Machine, Exception-Managed",
        "structure": "Velocity bands (HOT/STEADY/COLD/DEAD) x category, multi-product ad groups; keywords only inside hero carve-outs",
        "campaigns_per_asin": "<0.2",
        "acos": "account TACoS + portfolio caps",
        "automation": "fully automated; humans clear <50 exceptions/week",
        "cadences": ["pause_scale"],
        "app": "Pause/Scale moves bands; Monitoring health score + alerts = the exception queue; hero carve-outs recurse through the Waterfall engine",
        "techniques": [
            "Budget is the steering wheel: reallocating between bands beats any bid tweak",
            "Category product-targeting clauses cover the long tail at scale",
            "Hero set (20-50 ASINs) runs as a Tier 2 account inside the machine",
            "Tune alert thresholds so the human queue stays clearable",
        ],
    },
]


def tier_for(n: int) -> dict | None:
    """Tier for an advertisable-unit count (None when n <= 0)."""
    if n is None or n <= 0:
        return None
    for t in TIERS:
        if n >= t["lo"] and (t["hi"] is None or n <= t["hi"]):
            return t
    return None


def _catalog_counts(store_id: str | None) -> dict:
    """Advertisable units from the store catalog: parents + standalone.

    Children share the parent's campaign set, so they never add structure."""
    prods = (cat.read_catalog(store_id) or {}).get("products", {}) or {}
    parents = children = 0
    categories: set[str] = set()
    for p in prods.values():
        pg = p.get("parentage")
        if pg == "parent":
            parents += 1
        elif pg == "child":
            children += 1
        if p.get("product_type"):
            categories.add(str(p["product_type"]).strip().lower())
    total = len(prods)
    standalone = total - parents - children
    return {"units": parents + standalone, "parents": parents, "children": children,
            "standalone": standalone, "total": total, "categories": len(categories)}


def _ads_count(db: Session | None) -> int:
    """Fallback: distinct advertised ASINs in the current audit db."""
    if db is None:
        return 0
    from ..models import DimAd
    rows = db.query(DimAd.asin).filter(DimAd.asin.isnot(None), DimAd.asin != "").distinct().count()
    return int(rows or 0)


def suggest(db: Session | None) -> dict:
    """Tier suggestion for the active store. Catalog counts win; the audit db's
    advertised-ASIN count is the fallback so the router works pre-catalog."""
    store = db.info.get("store") if db is not None else None
    c = _catalog_counts(store)
    if c["units"] > 0:
        n, source = c["units"], "catalog"
    else:
        n, source = _ads_count(db), "ads"
    t = tier_for(n)
    notes = []
    if t and c["categories"] >= 3:
        notes.append(f"{c['categories']} categories in the catalog — run one Portfolio per "
                     "category with its own Goal ACoS instead of lifecycle portfolios.")
    if t and c["children"] > 0:
        notes.append(f"{c['children']} child variations share their parent's campaigns — "
                     "counted as part of the parent, not extra structure.")
    if t and t["tier"] >= 3:
        notes.append("If the top 20% of ASINs make 70%+ of sales, manage those heroes with the "
                     "Tier 1-2 playbook and keep this tier's structure for the tail.")
    return {
        "asin_count": n,
        "source": source,                      # 'catalog' | 'ads'
        "counts": c,                           # parents/children/standalone/categories detail
        "tier": t,                             # None when nothing to count yet
        "tiers": TIERS,
        "notes": notes,
    }
