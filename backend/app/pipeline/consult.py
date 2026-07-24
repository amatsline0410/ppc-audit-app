"""Consultation — right campaign structure for the ASIN count, plus a tier-tuned
problem scan of the uploaded bulk.

One SP bulk upload -> count distinct advertised ASINs -> route to one of seven
structure tiers (1-5 Waterfall ... 1000+ Capital Allocation). Each tier carries
its own audit thresholds (min spend/clicks/impressions, bid step, mixed-ad-group
policy, automation mode); the scan applies THAT tier's rules to the bulk and
returns problems with concrete resolutions.

Pure functions + one `analyze(path, target_acos, ...)` entry point. The router
persists the result JSON per project (`_meta.json` extra) — no own tables.
"""
from __future__ import annotations

import pandas as pd

from . import ingest as ingest_stage
from . import waterfall as wf
from . import weekly as wk

# ---- the seven structure tiers ----------------------------------------------
# Thresholds straight from the tier playbook: data gates rise with catalog size
# (more products = more noise = more evidence required before acting).
TIERS = [
    {
        "tier": 1, "lo": 1, "hi": 5, "range": "1-5 ASINs", "name": "Waterfall",
        "tldr": "One portfolio per ASIN, full funnel, run every lever by hand weekly. "
                "Maximum control while data is thin.",
        "structure": [
            "One portfolio per ASIN; inside, a five-campaign waterfall (one ad group each):",
            "Auto — discovery, cast wide",
            "Broad — expand on discovered terms",
            "Phrase — refine",
            "Exact — scale + defend winners",
            "ASIN targeting — competitor/complementary products",
        ],
        "loop": "Data (manual ST report, weekly) → Harvest → Bid → Negate → repeat",
        "cautions": [
            "Don't automate — sample sizes are too small; a single fluke order can mislead a rule.",
            "Keep exact-match winners negated out of upstream campaigns or they cannibalize each other.",
        ],
        "min_spend": 5, "min_clicks": 15, "min_impr": 1000, "bid_step": 0.15,
        "mixed_mode": "error", "automation_mode": "manual",
        "resolutions": {
            "harvest": "Promote up the ladder (auto → broad → phrase → exact); negate the term in its source campaign.",
            "mixed": "Split into one ASIN per ad group — the waterfall needs exactly one ASIN per ad group.",
        },
    },
    {
        "tier": 2, "lo": 6, "hi": 20, "range": "6-20 ASINs", "name": "Group + Hero",
        "tldr": "Heroes keep the full waterfall; everything else collapses into grouped "
                "campaigns with one ad group per ASIN. Still manual, still weekly.",
        "structure": [
            "Hero portfolio — each hero ASIN gets its own full funnel (Auto, Broad, Phrase, Exact, ASIN targeting).",
            "Grouped portfolio — secondary ASINs grouped by theme / similar target ACoS; one grouped campaign with one ad group per ASIN.",
        ],
        "loop": "Data (manual, weekly) → Harvest → Bid → Negate → repeat",
        "cautions": [
            "Only group ASINs that share a target ACoS — mixing margins in one campaign muddies budget decisions.",
            "Watch cross-ASIN cannibalization once several products chase the same keywords.",
        ],
        "min_spend": 5, "min_clicks": 15, "min_impr": 1000, "bid_step": 0.15,
        "mixed_mode": "warn", "automation_mode": "manual",
        "resolutions": {
            "harvest": "Hero winners → the hero's own exact; grouped winners → the shared exact ad group.",
            "mixed": "Grouped campaigns should stay one ad group per ASIN — split mixed ad groups.",
        },
    },
    {
        "tier": 3, "lo": 21, "hi": 50, "range": "21-50 ASINs", "name": "Split Tier",
        "tldr": "Three performance bands. Top sellers get own campaigns, mid gets "
                "single-product ad groups, tail rides one grouped auto. Rules start assisting.",
        "structure": [
            "Rank ASINs by ~60-day sales into three bands:",
            "Top sellers — own campaign, full funnel (Auto + Broad + Exact + product targeting).",
            "Mid — one campaign with single-product ad groups (1 ASIN per ad group, shared budget).",
            "Tail — one grouped auto campaign, low bid, harvest-only; graduate winners upward.",
        ],
        "loop": "Data (manual + rules, 3 bands) → Harvest → Bid → Negate → repeat",
        "cautions": [
            "Keep the tail's bids genuinely low — it's a discovery net, not a profit center.",
            "Re-rank bands monthly; yesterday's mid can become today's hero.",
        ],
        "min_spend": 8, "min_clicks": 15, "min_impr": 1000, "bid_step": 0.15,
        "mixed_mode": "warn", "automation_mode": "batch",
        "resolutions": {
            "harvest": "Tail auto mines terms — graduate winners into mid single-product ad groups.",
            "mixed": "Mid band should be single-ASIN ad groups (tail auto may stay grouped).",
        },
    },
    {
        "tier": 4, "lo": 51, "hi": 100, "range": "51-100 ASINs", "name": "Automate",
        "tldr": "The crossover. A rules engine runs the daily loop; you set the guardrails "
                "and work the exception queue. SKU tiering begins.",
        "structure": [
            "Reorganize around SKU tiers, portfolios by tier:",
            "Core portfolio — Auto + Manual (all match types).",
            "Growth portfolio — Auto + Manual (all match types).",
            "Slow portfolio — Auto (low bid) + harvest-only.",
        ],
        "loop": "Data (tool feed, daily) → Harvest → Bid → Negate → repeat",
        "cautions": [
            "Set guardrails (max bid change per run, budget ceilings) before enabling auto-apply.",
            "The exception queue is your job now — don't let it pile up; that's where the money leaks.",
            "Data gates rise on purpose: more products means more noise, so require more evidence before acting.",
        ],
        "min_spend": 10, "min_clicks": 20, "min_impr": 1000, "bid_step": 0.20,
        "mixed_mode": "warn", "automation_mode": "auto",
        "resolutions": {
            "harvest": "Auto-harvest daily (audit weekly): promote winners into the tier's manual campaigns.",
            "mixed": "Keep tier portfolios' ad groups single-ASIN so per-SKU targets stay readable.",
        },
    },
    {
        "tier": 5, "lo": 101, "hi": 500, "range": "101-500 ASINs", "name": "Portfolio",
        "tldr": "Stop optimizing keyword-by-keyword; manage budget buckets. Three SKU tiers "
                "with their own bid logic, plus catch-all campaigns for the tail.",
        "structure": [
            "Core portfolio — defend, run at break-even to protect rank + brand.",
            "Growth portfolio — aggressive bids, push rank velocity.",
            "Liquidation portfolio — minimum bid, harvest only, clear stock.",
            "Catch-all campaigns (tail) — multi-ASIN ad groups, grouped ONLY by shared target ACoS.",
        ],
        "loop": "Data (classify SKU: core/growth/liq) → Harvest → Bid → Negate → repeat",
        "cautions": [
            "Reallocate budget across tiers monthly — that's the real lever at this scale.",
            "Keep brand and non-brand separated so brand's low ACoS doesn't mask non-brand waste.",
            "Only combine SKUs into a catch-all when they share a target ACoS.",
        ],
        "min_spend": 12, "min_clicks": 20, "min_impr": 1000, "bid_step": 0.20,
        "mixed_mode": "warn", "automation_mode": "auto",
        "resolutions": {
            "harvest": "A winning term triggers SKU reclassification (e.g. tail → growth), not just a keyword promotion.",
            "mixed": "Multi-ASIN is fine in the catch-all layer; elsewhere keep single-ASIN ad groups.",
        },
    },
    {
        "tier": 6, "lo": 501, "hi": 1000, "range": "501-1000 ASINs", "name": "Multi-Ad-Group",
        "tldr": "Most tail ASINs get a handful of clicks — too thin for own campaigns. Bundle "
                "them into multi-product ad groups; heroes stay isolated. Harvest spots breakouts.",
        "structure": [
            "Isolated heroes — one campaign per hero SKU, full funnel (includes graduates promoted from the tail).",
            "Tail campaign — a multi-product ad group: one ad group holding many ASINs sharing keywords.",
        ],
        "loop": "Data (automation, bundles + heroes) → Harvest → Bid → Negate → repeat",
        "cautions": [
            "The mixed-ad-group suppression is deliberate; don't 'fix' tail ad groups back to single-ASIN — that defeats the bundling.",
            "Set the isolation threshold (clicks/month) per category; too low and you drown in tiny campaigns.",
        ],
        "min_spend": 15, "min_clicks": 25, "min_impr": 1000, "bid_step": 0.20,
        "mixed_mode": "suppress_tail", "automation_mode": "auto",
        "resolutions": {
            "harvest": "A bundled SKU crossing ~10 clicks/month → auto-isolate into its own campaign.",
            "mixed": "Intentional on tail bundles — only flag isolated hero campaigns that turned multi-ASIN.",
        },
    },
    {
        "tier": 7, "lo": 1001, "hi": None, "range": "1000+ ASINs", "name": "Capital Allocation",
        "tldr": "You don't manage campaigns — you allocate capital across the whole catalog "
                "toward one account goal. Everything below runs on autopilot; you steer the money.",
        "structure": [
            "Target TACoS set at the account; budget allocated dynamically into tier portfolios:",
            "Core portfolio → Auto cluster (multi-product ad groups, AI-bid).",
            "Growth portfolio → Launch cluster (rank + discovery, tolerate high ACoS).",
            "Liquidation portfolio → Clear cluster (min bid, harvest, stock exit).",
        ],
        "loop": "Data (AI engine, target TACoS) → Harvest → Bid → Negate → repeat",
        "cautions": [
            "Discovery may run above target on purpose — judge on incrementality, not single-campaign ACoS.",
            "The guardrail (target TACoS + budget ceilings) is the only thing between the engine and a blown budget.",
            "TACoS needs total sales (ad + organic) — not in the PPC bulk; wire it in as an external input before relying on it.",
        ],
        "min_spend": 20, "min_clicks": 25, "min_impr": 1000, "bid_step": 0.20,
        "mixed_mode": "off_except_heroes", "automation_mode": "continuous",
        "resolutions": {
            "harvest": "Continuous harvest; budget follows winners across the whole catalog automatically.",
            "mixed": "Multi-product ad groups are the design — only isolated hero carve-outs must stay single-ASIN.",
        },
    },
]

# mixed-ad-group policy: how the finding is reported per tier
MIXED_ACTIVE = {"error", "warn"}          # emit rows
MIXED_PASSIVE = {"suppress_tail", "off_except_heroes", "ignore"}   # count only

MAX_ROWS = 300     # per problem type in the stored result (totals stay exact)


def tier_for(n: int) -> dict | None:
    if not n or n <= 0:
        return None
    for t in TIERS:
        if n >= t["lo"] and (t["hi"] is None or n <= t["hi"]):
            return t
    return None


def _num(v) -> float:
    try:
        f = float(v)
        return 0.0 if pd.isna(f) else f
    except (TypeError, ValueError):
        return 0.0


def _target_problems(df: pd.DataFrame, kind: str, t: dict, target_acos: float) -> list[dict]:
    """Tier-thresholded scan of one target frame (keyword / product targeting)."""
    out = []
    if not len(df):
        return out
    step = t["bid_step"]
    for _, r in df.iterrows():
        state = wf._s(r.get("state")).lower()
        if state and state != "enabled":
            continue
        clicks = _num(r.get("clicks")); spend = _num(r.get("spend"))
        sales = _num(r.get("sales")); orders = _num(r.get("orders"))
        impr = _num(r.get("impressions")); bid = _num(r.get("bid"))
        label = wf._s(r.get("keyword_text")) or wf._s(r.get("expression"))
        base = {
            "kind": kind, "campaign_id": wf._s(r.get("campaign_id")),
            "ad_group_id": wf._s(r.get("ad_group_id")), "target": label,
            "clicks": int(clicks), "spend": round(spend, 2), "sales": round(sales, 2),
            "orders": int(orders), "acos": round(spend / sales, 4) if sales else None,
            "bid": round(bid, 2) if bid else None,
        }
        if spend >= t["min_spend"] and orders == 0:
            out.append({**base, "problem": "WASTED_SPEND",
                        "resolution": f"${spend:.2f} spent, 0 orders — add as negative and pause the target."})
            continue
        acos = (spend / sales) if sales else None
        if acos is not None and clicks > t["min_clicks"] and acos > target_acos * 1.2:
            new_bid = round(max(bid * (1 - step), 0.02), 2) if bid else None
            out.append({**base, "problem": "HIGH_ACOS",
                        "resolution": f"ACoS {acos:.0%} > target+20% — cut bid {int(step*100)}%"
                                      + (f" → ${new_bid:.2f}." if new_bid else ".")})
            continue
        if acos is not None and orders > 0 and acos < target_acos * 0.8 and impr < t["min_impr"]:
            new_bid = round(bid * (1 + step), 2) if bid else None
            out.append({**base, "problem": "RAISE_WINNER",
                        "resolution": f"ACoS {acos:.0%} < target−20% with low impressions — raise bid {int(step*100)}%"
                                      + (f" → ${new_bid:.2f}." if new_bid else ".")})
            continue
        if bid and clicks >= 5:
            cpc = spend / clicks if clicks else 0
            if cpc and bid > cpc * 1.5:
                out.append({**base, "problem": "OVERBID",
                            "resolution": f"Bid ${bid:.2f} far above actual CPC ${cpc:.2f} — tighten toward CPC×1.1 (${cpc*1.1:.2f})."})
    return out


def _mixed_ad_groups(frames: dict) -> list[dict]:
    """Ad groups advertising more than one distinct ASIN (enabled Product Ads)."""
    ads = wf._frame(frames, "product ad")
    if not len(ads):
        return []
    groups: dict[tuple, set] = {}
    names: dict[tuple, str] = {}
    for _, r in ads.iterrows():
        state = wf._s(r.get("state")).lower()
        if state and state != "enabled":
            continue
        key = (wf._s(r.get("campaign_id")), wf._s(r.get("ad_group_id")))
        asin = wf._s(r.get("asin"))
        if not key[0] or not key[1] or not asin:
            continue
        groups.setdefault(key, set()).add(asin)
        names.setdefault(key, wf._s(r.get("campaign_name")))
    return [{"kind": "ad_group", "campaign_id": c, "ad_group_id": g,
             "target": f"{len(asins)} ASINs in one ad group",
             "asins": sorted(asins)[:10], "n_asins": len(asins)}
            for (c, g), asins in groups.items() if len(asins) > 1]


def _harvest_candidates(str_rows: list[dict], t: dict) -> list[dict]:
    """Search terms worth promoting: clicks >= 5 OR orders >= 1 (spec rule)."""
    out = []
    for r in str_rows or []:
        if (r.get("clicks") or 0) >= 5 or (r.get("orders") or 0) >= 1:
            spend, sales = r.get("spend") or 0, r.get("sales") or 0
            out.append({
                "kind": "search_term", "campaign_id": r["campaign_id"],
                "ad_group_id": r["ad_group_id"], "target": r["search_term"],
                "clicks": r.get("clicks") or 0, "spend": spend, "sales": sales,
                "orders": r.get("orders") or 0,
                "acos": round(spend / sales, 4) if sales else None,
                "problem": "HARVEST_CANDIDATE", "resolution": t["resolutions"]["harvest"],
            })
    return out


def analyze(path: str, target_acos: float = 0.30, tier_override: int | None = None) -> dict:
    """Parse the bulk, route the tier from the advertised-ASIN count, run that
    tier's problem scan. Returns the full consultation result (JSON-safe)."""
    frames = ingest_stage.frames(path)
    ads = wf._frame(frames, "product ad")
    asins = set()
    if len(ads):
        for _, r in ads.iterrows():
            a = wf._s(r.get("asin"))
            if a:
                asins.add(a)
    n = len(asins)
    if n == 0:
        raise ValueError("No advertised ASINs found in that bulk — is it a Sponsored Products "
                         "bulk export with Product Ad rows?")
    auto = tier_for(n)
    t = (next((x for x in TIERS if x["tier"] == int(tier_override)), None)
         if tier_override else None) or auto

    problems: list[dict] = []
    problems += _target_problems(wf._frame(frames, "keyword"), "keyword", t, target_acos)
    problems += _target_problems(wf._frame(frames, "product targeting"), "product_target", t, target_acos)

    mixed = _mixed_ad_groups(frames)
    mixed_mode = t["mixed_mode"]
    if mixed_mode in MIXED_ACTIVE:
        sev = "error" if mixed_mode == "error" else "warn"
        for m in mixed:
            problems.append({**m, "problem": "MIXED_AD_GROUP", "severity": sev,
                             "resolution": t["resolutions"]["mixed"]})

    try:
        str_rows = wk.parse_str_sheet(path)
    except ValueError:
        str_rows = []
    problems += _harvest_candidates(str_rows, t)

    # group + cap for storage; totals stay exact
    by_type: dict[str, list[dict]] = {}
    for p in problems:
        by_type.setdefault(p["problem"], []).append(p)
    counts = {k: len(v) for k, v in by_type.items()}
    for k, v in by_type.items():
        v.sort(key=lambda p: -(p.get("spend") or 0))
        by_type[k] = v[:MAX_ROWS]

    camp = wf._frame(frames, "campaign")
    n_campaigns = int(camp["campaign_id"].nunique()) if len(camp) and "campaign_id" in camp else 0

    pub = {k: v for k, v in t.items() if k not in ("resolutions",)}
    return {
        "asin_count": n, "campaigns": n_campaigns, "has_str": bool(str_rows),
        "tier": pub, "auto_tier": auto["tier"] if auto else None,
        "tier_overridden": bool(tier_override and auto and tier_override != auto["tier"]),
        "target_acos": target_acos,
        "counts": counts, "total_problems": sum(counts.values()),
        "mixed_suppressed": (len(mixed) if mixed_mode in MIXED_PASSIVE else 0),
        "problems": by_type,
    }
