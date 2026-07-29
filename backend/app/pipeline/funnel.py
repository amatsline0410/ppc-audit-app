"""Ads Studio — the segmented funnel strategy.

The doctrine this implements, in one line per phase:

  Phase 1 · Discovery   AUTO campaigns mine new search terms and competitor ASINs
                        (15-20% of budget); BROAD + PHRASE campaigns capture search
                        variations on tightly-themed keyword groups.
  Phase 2 · Performance  proven converters move into EXACT campaigns, which carry the
                        highest bids and the primary budget; PT (ASIN) campaigns target
                        competitor detail pages.
  Phase 3 · Defense      Sponsored Brands + Sponsored Display. **Not emitted here** —
                        this app has no SB/SD bulk writer (see `channels.py`, read-only),
                        so the funnel report flags the gap instead of pretending to fix it.

Two hard structural rules ride along:
  * never mix match types inside one campaign — it destroys bid control and muddies the
    data. `mix_violations()` reports every campaign that breaks it.
  * every promotion out of a discovery tier is negative-exacted upstream, so the term
    stops costing money twice and the funnel keeps flowing one way.

Everything here is pure-ish: it reads the rows Ads Studio already parsed and returns
plain dicts. Bulk emission stays in `adsstudio.to_bulk` / `funnel_to_bulk` below it.
"""
from __future__ import annotations

from .. import metrics as M
from . import bid_optimizer as bo, bulkfmt

# funnel tiers, in flow order
AUTO, BROAD, PHRASE, EXACT, PT = "AUTO", "BROAD", "PHRASE", "EXACT", "PT"
TIERS = [AUTO, BROAD, PHRASE, EXACT, PT]
TIER_LABEL = {
    AUTO: "Auto discovery", BROAD: "Broad research", PHRASE: "Phrase research",
    EXACT: "Exact performance", PT: "Product targeting (ASIN)",
}
TIER_PHASE = {AUTO: 1, BROAD: 1, PHRASE: 1, EXACT: 2, PT: 2}

# tiers whose winners graduate, and where they graduate to
DISCOVERY = {AUTO, BROAD, PHRASE}
PROMOTE_TO = {AUTO: EXACT, BROAD: EXACT, PHRASE: EXACT}

# Phase 1 budget guidance: auto discovery should hold 15-20% of spend
AUTO_SHARE_MIN, AUTO_SHARE_MAX = 0.15, 0.20

# Top-of-Search placement rule: raise the multiplier on proven exact campaigns
TOS_UPLIFT_MIN, TOS_UPLIFT_MAX = 0.20, 0.50
TOS_CAP = 900.0                 # Amazon's ceiling for a placement multiplier
TOS_MIN_ORDERS = 5              # "once conversion data is stable"


def target_tier(row: dict) -> str:
    """Funnel tier of one target row (as returned by `adsstudio.board`)."""
    if row.get("is_auto_clause"):
        return AUTO
    if row.get("entity") == "product_target":
        return PT
    match = (row.get("match_type") or "").strip().lower()
    if match.startswith("broad"):
        return BROAD
    if match.startswith("phrase"):
        return PHRASE
    if match.startswith("exact"):
        return EXACT
    # a keyword in an auto campaign has no match type of its own
    return AUTO if (row.get("campaign_type") == "auto") else EXACT


def campaign_tier(camp: dict) -> str:
    """A campaign's tier = where most of its spend sits, so one stray target can't
    reclassify it. Falls back to the campaign's targeting kind when it has no rows."""
    if camp.get("campaign_type") == "auto":
        return AUTO
    spend: dict[str, float] = {}
    for r in camp.get("targets") or []:
        tier = target_tier({**r, "campaign_type": camp.get("campaign_type")})
        spend[tier] = spend.get(tier, 0.0) + ((r.get("metrics") or {}).get("spend") or 0)
    if spend:
        # ties -> the earliest tier in flow order, so a fresh campaign reads as research
        return max(sorted(spend, key=TIERS.index), key=lambda k: spend[k])
    return PT if camp.get("campaign_type") == "product" else EXACT


def mix_violations(campaigns: list[dict]) -> list[dict]:
    """Campaigns carrying more than one match type — the "never mix" rule.

    Auto campaigns are exempt: their clause rows are Amazon's own match groups, not
    match types the operator chose to mix.
    """
    out = []
    for c in campaigns:
        if c.get("campaign_type") == "auto":
            continue
        tiers: dict[str, int] = {}
        for r in c.get("targets") or []:
            tier = target_tier({**r, "campaign_type": c.get("campaign_type")})
            tiers[tier] = tiers.get(tier, 0) + 1
        if len(tiers) > 1:
            out.append({
                "campaign_id": c["campaign_id"], "campaign_name": c["campaign_name"],
                "tiers": {k: tiers[k] for k in sorted(tiers, key=TIERS.index)},
                "reason": "one campaign holds several match types — split it so each "
                          "tier has its own budget and bid control",
            })
    return out


def report(campaigns: list[dict], target_acos: float) -> dict:
    """Funnel health for the selected products: tier rollups, the Phase-1 budget
    split, structural gaps, and the never-mix violations."""
    by_tier: dict[str, dict] = {}
    for c in campaigns:
        tier = campaign_tier(c)
        b = by_tier.setdefault(tier, {"tier": tier, "label": TIER_LABEL[tier],
                                      "phase": TIER_PHASE[tier], "campaigns": [],
                                      "impressions": 0, "clicks": 0, "orders": 0,
                                      "units": 0, "spend": 0.0, "sales": 0.0})
        b["campaigns"].append({"campaign_id": c["campaign_id"],
                               "campaign_name": c["campaign_name"],
                               "metrics": c.get("metrics") or {}})
        m = c.get("metrics") or {}
        for k in ("impressions", "clicks", "orders", "units"):
            b[k] += m.get(k) or 0
        b["spend"] = round(b["spend"] + (m.get("spend") or 0), 2)
        b["sales"] = round(b["sales"] + (m.get("sales") or 0), 2)

    total_spend = round(sum(b["spend"] for b in by_tier.values()), 2)
    tiers = []
    for tier in TIERS:
        b = by_tier.get(tier)
        if b is None:
            tiers.append({"tier": tier, "label": TIER_LABEL[tier], "phase": TIER_PHASE[tier],
                          "campaigns": [], "count": 0, "present": False,
                          "spend_share": None, "metrics": M.all_metrics()})
            continue
        tiers.append({
            "tier": tier, "label": b["label"], "phase": b["phase"],
            "campaigns": b["campaigns"], "count": len(b["campaigns"]), "present": True,
            "spend_share": round(b["spend"] / total_spend, 4) if total_spend else None,
            "metrics": M.all_metrics(b["impressions"], b["clicks"], b["spend"],
                                     b["sales"], b["orders"], b["units"]),
        })

    auto_spend = by_tier.get(AUTO, {}).get("spend", 0.0)
    auto_share = round(auto_spend / total_spend, 4) if total_spend else None
    if auto_share is None:
        budget_verdict, budget_note = "unknown", "no spend recorded for these products yet"
    elif auto_share < AUTO_SHARE_MIN:
        budget_verdict = "under"
        budget_note = (f"auto discovery is {auto_share * 100:.1f}% of spend — under the "
                       f"{AUTO_SHARE_MIN * 100:.0f}% floor, so you're mining fewer new "
                       "search terms than the funnel needs")
    elif auto_share > AUTO_SHARE_MAX:
        budget_verdict = "over"
        budget_note = (f"auto discovery is {auto_share * 100:.1f}% of spend — over the "
                       f"{AUTO_SHARE_MAX * 100:.0f}% ceiling; move budget to Exact once "
                       "its winners are proven")
    else:
        budget_verdict = "ok"
        budget_note = f"auto discovery is {auto_share * 100:.1f}% of spend — inside the target band"

    gaps = []
    present = {t["tier"] for t in tiers if t["present"]}
    for tier in TIERS:
        if tier not in present:
            gaps.append({"tier": tier, "label": TIER_LABEL[tier], "phase": TIER_PHASE[tier],
                         "reason": _gap_reason(tier)})
    # Phase 3 is real strategy but outside what this app can emit — say so plainly.
    gaps.append({"tier": "SB_SD", "label": "Sponsored Brands / Display", "phase": 3,
                 "reason": "brand defense and retargeting are Phase 3 of the funnel. This "
                           "app reads SB/SD in the Channels tab but cannot write an SB/SD "
                           "bulk file, so set these up in Amazon's console."})

    return {
        "tiers": tiers,
        "total_spend": total_spend,
        "auto_share": auto_share,
        "auto_share_target": [AUTO_SHARE_MIN, AUTO_SHARE_MAX],
        "budget_verdict": budget_verdict,
        "budget_note": budget_note,
        "gaps": gaps,
        "mix_violations": mix_violations(campaigns),
        "target_acos": target_acos,
    }


def _gap_reason(tier: str) -> str:
    return {
        AUTO: "no auto campaign — nothing is mining new search terms or competitor ASINs",
        BROAD: "no broad campaign — you're not capturing wide search variations",
        PHRASE: "no phrase campaign — the middle of the funnel is missing",
        EXACT: "no exact campaign — proven converters have nowhere to graduate to, which "
               "is where your highest bids and primary budget belong",
        PT: "no product-targeting campaign — you're not siphoning traffic from competitor "
            "detail pages",
    }[tier]


# ---- promotion planning -------------------------------------------------------
def plan(campaigns: list[dict], bosses: dict[str, str], target_acos: float,
         min_bid: float = 0.20) -> dict:
    """Route every winner to where the funnel says it belongs.

    `bosses` maps tier -> the campaign id that owns that tier (EXACT and PT are the
    ones that receive; the rest are optional and only used for consolidation).

      promotes    winner in AUTO/BROAD/PHRASE -> created Exact in the EXACT boss
                  (an ASIN term, or a product target, -> the PT boss instead)
      migrates    winner already in EXACT/PT but in the wrong campaign -> the boss
      negatives   every promotion, negative-exacted in the campaign it came from
      pauses      losers, paused where they sit
      skipped     winners that cannot move, with the reason
    """
    by_id = {c["campaign_id"]: c for c in campaigns}
    exact_boss = by_id.get(bulkfmt.idstr(bosses.get(EXACT) or ""))
    pt_boss = by_id.get(bulkfmt.idstr(bosses.get(PT) or ""))

    promotes, migrates, negatives, pauses, skipped = [], [], [], [], []
    # what each destination already carries, so nothing is created twice
    seen_exact = {_kw_sig(r) for r in (exact_boss or {}).get("targets", [])}
    seen_pt = {_pt_sig(r) for r in (pt_boss or {}).get("targets", [])}

    for c in campaigns:
        tier = campaign_tier(c)
        for r in c.get("targets") or []:
            row = {**r, "campaign_type": c.get("campaign_type")}
            r_tier = target_tier(row)
            ctx = {**r, "from_campaign_id": c["campaign_id"],
                   "from_campaign_name": c["campaign_name"],
                   "from_tier": r_tier, "campaign_tier": tier}

            if r["verdict"] == "drop":
                if r.get("id"):
                    pauses.append({**ctx, "campaign_name": c["campaign_name"]})
                continue
            if r["verdict"] != "keep":
                continue        # review: too thin to act on, left alone

            # --- where does this winner belong? ---
            term_is_asin = (r_tier == PT) or bulkfmt.is_asin(r.get("keyword_text"))
            dest = pt_boss if term_is_asin else exact_boss
            dest_tier = PT if term_is_asin else EXACT

            if dest is None:
                skipped.append({**ctx, "skip_reason":
                                f"no {TIER_LABEL[dest_tier]} campaign chosen to receive it"})
                continue
            dest_ag = dest["ad_groups"][0]["ad_group_id"] if dest.get("ad_groups") else None
            if not dest_ag:
                skipped.append({**ctx, "skip_reason":
                                f"{dest['campaign_name']} has no ad group to receive it"})
                continue

            # already home?
            if c["campaign_id"] == dest["campaign_id"]:
                continue

            if term_is_asin:
                expr = (r.get("expression") or "").strip()
                if not expr and bulkfmt.is_asin(r.get("keyword_text")):
                    expr = f'asin="{str(r["keyword_text"]).strip().upper()}"'
                if r.get("is_auto_clause") or not bulkfmt.neg_pt_expression(expr):
                    skipped.append({**ctx, "skip_reason":
                                    "auto-campaign clause or non-ASIN expression — Amazon "
                                    "can't recreate it as a product target"})
                    continue
                sig = ("pt", expr.lower())
                if sig in seen_pt:
                    skipped.append({**ctx, "skip_reason": f"{dest['campaign_name']} already targets it"})
                    continue
                seen_pt.add(sig)
                moved = {**ctx, "to_campaign_id": dest["campaign_id"],
                         "to_campaign_name": dest["campaign_name"], "to_ad_group_id": dest_ag,
                         "to_tier": PT, "entity": "product_target", "expression": expr,
                         "new_bid": _bid(r, target_acos, min_bid)}
            else:
                text = (r.get("keyword_text") or "").strip()
                if not bulkfmt.valid_keyword(text):
                    skipped.append({**ctx, "skip_reason":
                                    "keyword text Amazon would reject (length / characters)"})
                    continue
                sig = ("kw", text.lower())
                if sig in seen_exact:
                    skipped.append({**ctx, "skip_reason": f"{dest['campaign_name']} already has it as Exact"})
                    continue
                seen_exact.add(sig)
                moved = {**ctx, "to_campaign_id": dest["campaign_id"],
                         "to_campaign_name": dest["campaign_name"], "to_ad_group_id": dest_ag,
                         "to_tier": EXACT, "entity": "keyword", "keyword_text": text,
                         "match_type": "exact", "new_bid": _bid(r, target_acos, min_bid)}

            if r_tier in DISCOVERY:
                promotes.append(moved)
                # sculpt: stop the discovery campaign paying for a term the money tier owns
                negatives.append({
                    "campaign_id": c["campaign_id"], "campaign_name": c["campaign_name"],
                    "ad_group_id": r.get("ad_group_id"), "ad_group_name": r.get("ad_group_name"),
                    "entity": moved["entity"],
                    "keyword_text": moved.get("keyword_text"),
                    "expression": moved.get("expression"),
                    "label": r.get("label"),
                    "reason": f"promoted to {dest['campaign_name']} — negated here so the "
                              "funnel only flows one way",
                })
            else:
                migrates.append(moved)

    return {
        "bosses": {t: bosses.get(t) for t in TIERS if bosses.get(t)},
        "promotes": promotes, "migrates": migrates, "negatives": negatives,
        "pauses": pauses, "skipped": skipped,
        "counts": {"promotes": len(promotes), "migrates": len(migrates),
                   "negatives": len(negatives), "pauses": len(pauses),
                   "skipped": len(skipped)},
    }


# The money tier carries the highest bids, so a graduating term is allowed a bigger
# step up than a routine bid tweak — but still a clamped one, not a blank cheque.
PROMOTE_MAX_CUT, PROMOTE_MAX_UP = 0.50, 1.50


def _bid(row: dict, target_acos: float, min_bid: float) -> float:
    """Opening bid in the money tier: the goal-ACoS CPC computed from the term's own
    history, clamped against its current bid and floored. Falls back to what it
    already bids when there's no click history to compute on."""
    m = row.get("metrics") or {}
    cur = float(row.get("bid") or 0) or None
    suggested = M.target_cpc_bid(m.get("clicks") or 0, m.get("sales") or 0.0, target_acos,
                                 cur, PROMOTE_MAX_CUT, PROMOTE_MAX_UP, min_bid)
    if suggested:
        return round(max(suggested, min_bid), 2)
    return round(max(cur or min_bid, min_bid), 2)


def _kw_sig(r: dict) -> tuple:
    return ("kw", (r.get("keyword_text") or "").strip().lower())


def _pt_sig(r: dict) -> tuple:
    return ("pt", (r.get("expression") or "").strip().lower())


# ---- placement: Top of Search uplift -----------------------------------------
def placement_recommendations(campaigns: list[dict], current: dict[str, dict],
                              target_acos: float) -> list[dict]:
    """Raise the Top-of-Search multiplier on Exact campaigns whose conversion is
    already stable (>= TOS_MIN_ORDERS orders at or under goal ACoS).

    `current` maps campaign_id -> {placement_raw: percentage} read from the bulk's
    Bidding Adjustment rows. Uplift is +20% when the campaign is merely at goal and
    +50% when it is comfortably under, scaled linearly between.
    """
    out = []
    for c in campaigns:
        if campaign_tier(c) != EXACT:
            continue
        m = c.get("metrics") or {}
        orders, acos = m.get("orders") or 0, m.get("acos")
        if orders < TOS_MIN_ORDERS or acos is None or acos > target_acos:
            continue
        # comfortably under goal -> the top of the band; right at goal -> the bottom
        headroom = 0.0 if target_acos <= 0 else max(0.0, min(1.0, 1 - (acos / target_acos)))
        uplift = TOS_UPLIFT_MIN + (TOS_UPLIFT_MAX - TOS_UPLIFT_MIN) * headroom
        placements = current.get(c["campaign_id"]) or {}
        raw, cur = _tos_entry(placements)
        new = round(min((cur or 0.0) * (1 + uplift) if cur else uplift * 100, TOS_CAP), 1)
        if cur is not None and new <= cur:
            continue
        out.append({
            "campaign_id": c["campaign_id"], "campaign_name": c["campaign_name"],
            "placement_raw": raw, "current_pct": cur, "new_pct": new,
            "uplift": round(uplift, 2), "orders": orders, "acos": acos,
            "reason": f"{orders} orders at {acos * 100:.0f}% ACoS (goal {target_acos * 100:.0f}%) "
                      f"— raise Top of Search by {uplift * 100:.0f}%",
        })
    return out


def _tos_entry(placements: dict) -> tuple[str, float | None]:
    """The campaign's Top-of-Search adjustment: its raw bulk label + current percent.

    Uses the app's canonical placement alias table rather than a loose substring
    match — Amazon's own label is "Placement Top", which contains no "search" at all.
    """
    for raw, pct in (placements or {}).items():
        if bo.normalize_placement(raw) == "top_of_search":
            return raw, float(pct or 0)
    return "Placement Top", None
