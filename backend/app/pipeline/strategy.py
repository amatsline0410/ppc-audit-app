"""Strategy Advisor — runs the PPC playbook over the account.

Classifies each campaign from the loaded bulk and emits the strategies that
apply (with the numbers that triggered them), routing each to the engine that
executes it (Harvest / Bid Optimizer / Placement / Negatives). Also returns the
full 16-strategy playbook with a status per strategy so the operator sees what's
active, what's available, and what needs more data/config.
"""
from __future__ import annotations
import io
from collections import defaultdict
import pandas as pd
from sqlalchemy.orm import Session
from .. import models as md
from ..config import Thresholds
from . import audit as audit_stage
from . import bulkfmt

# strategies that can emit an Amazon bulk file in one click
BULK_STRATEGIES = {"Exact Match Scaling", "Negative Keyword Sculpting",
                   "Placement Bid Optimization", "Budget Segmentation"}
BUDGET_RAISE = 1.2   # capped campaigns: raise daily budget 20% per pass

# tunables (sensible PPC defaults)
HARVEST_CLICKS = 30      # clicks before a discovery campaign is worth harvesting
LIMITED_CLICKS = 30      # below this = limited data / catch-all phase
SKAG_ORDERS = 3          # orders to justify isolating a keyword into its own ad group
CAP_RATIO = 0.9          # spend/(budget) over this ≈ budget-capped (period proxy)


# 16-strategy reference catalog. tool = which app engine runs it.
PLAYBOOK = [
    ("Catch-All (Low Bid Broad)", "New / limited-data campaigns", "Add broad + auto at low bids", "Mine search terms weekly", "auto", "harvest"),
    ("Search Term Harvesting", "≥30–50 clicks per term", "Move converting terms to Exact", "Reduce discovery bids after harvest", "auto", "harvest"),
    ("SKAG (Single Keyword Ad Group)", "High-performing keyword", "Isolate keyword in its own ad group", "Full bid + budget control", "auto", "manual"),
    ("Exact Match Scaling", "High CVR + low ACoS terms", "Create exact-only scaling campaign", "Add TOS bid adjustment if profitable", "auto", "bidopt"),
    ("Broad Match Research", "Launch / exploration phase", "Run broad at moderate bids", "Pair with negatives weekly", "auto", "harvest"),
    ("Product Targeting (ASIN)", "Competitors with weak offer/reviews", "Target competitor ASINs", "Optimize bids per ASIN", "manual", "bidopt"),
    ("Category Targeting Funnel", "High-demand categories", "Target categories with filters", "Start low; scale after CVR proof", "manual", "bidopt"),
    ("Defensive Branded Campaign", "Existing brand search volume", "Target own brand exact", "Keep low bids for cheap conversions", "config", "manual"),
    ("Offensive Competitor Targeting", "Competitors dominate SERP", "Target competitor brand keywords", "Monitor TACoS impact", "config", "manual"),
    ("Dayparting Optimization", "Clear hourly performance trend", "Adjust bids by time/day", "Cut bids on low-conversion hours", "na", "manual"),
    ("Placement Bid Optimization", "Strong Top-of-Search CVR", "Increase TOS multiplier", "Only scale if ACoS profitable", "auto", "placement"),
    ("Budget Segmentation", "Campaigns hitting budget cap", "Split by match type / intent", "Protect high-intent budget", "auto", "manual"),
    ("Long-Tail Keyword Isolation", "Long queries, high CVR", "Move to exact campaigns", "Lower CPC, higher ROAS", "auto", "ngram"),
    ("Negative Keyword Sculpting", "High spend, low conversion", "Add negatives at campaign/ad group", "Maintain query quality", "auto", "harvest"),
    ("Portfolio Segmentation", "Different goals per campaign set", "Group into portfolios", "Allocate budget by objective", "auto", "manual"),
    ("Lifecycle Campaign Structure", "Launch → Growth → Scale", "Adjust bids/match per stage", "Don't use one structure for all", "auto", "manual"),
]


def _lifecycle(orders: int) -> str:
    return "Launch" if orders < 5 else ("Growth" if orders <= 25 else "Scale")


def analyze(db: Session, t: Thresholds) -> dict:
    tree = audit_stage.build_tree(db)              # cached, current period
    camps = {c.campaign_id: c for c in db.query(md.DimCampaign).all()}
    goal = t.target_acos

    # per-product break-even ACoS: benchmark upload wins, else catalog listing
    # (price + per-SKU COGS + real Transactions-ledger fees). ASIN match first,
    # normalized-SKU listing match as fallback — same join the audit uses.
    from .. import database as dbmod
    from . import benchmark as bench_stage
    from . import catalog as cat
    be_map = bench_stage.break_even_map(db)
    goal_map = bench_stage.goal_map(db)      # per-ASIN goal overrides (benchmark upload)
    sku_be = cat.be_by_sku(db.info.get("store"),
                           dbmod.get_project_econ(db.info.get("store"), db.info.get("project")))
    asin_sku = {}
    for ad in db.query(md.DimAd).all():
        if ad.asin and ad.sku:
            asin_sku.setdefault(ad.asin, ad.sku)

    def be_for(asin):
        be = be_map.get(asin)
        if be is None:
            be = sku_be.get(cat.norm_sku(asin_sku.get(asin)))
        return be

    recs = []
    fired = set()
    have_portfolio = any(c.portfolio_id for c in camps.values())

    for asin, node in tree.items():
        be = be_for(asin)
        for c in node["campaigns"]:
            cid = c["campaign_id"]; dimc = camps.get(cid)
            if dimc and (dimc.state or "").lower() == "archived":
                continue
            m = c["metrics"]; clicks, orders, spend = m["clicks"], m["orders"], m["spend"]
            acos = m["acos"]
            ttype = (dimc.targeting_type or "").lower() if dimc else ""
            budget = dimc.daily_budget if dimc else None
            # match-type mix across the campaign's targets
            mset = {(tg.get("match_type") or "").lower()
                    for ag in c["ad_groups"] for tg in ag["targets"]} - {""}

            def add(strategy, criteria, action, tool, priority):
                fired.add(strategy)
                recs.append({"strategy": strategy, "campaign_id": cid, "campaign": c["name"],
                             "asin": asin, "criteria": criteria, "action": action,
                             "tool": tool, "priority": priority, "spend": round(spend, 2),
                             "acos": acos, "break_even": be,
                             "stage": _lifecycle(orders), "bulk": strategy in BULK_STRATEGIES})

            # Over Break-Even — the campaign's ACoS exceeds the PRODUCT's real
            # break-even (catalog COGS + Transactions-ledger fees): losing money
            # on every ad sale regardless of the goal ACoS.
            if be is not None and acos is not None and acos > be and spend >= t.min_spend:
                add("Over Break-Even (Bleeding)",
                    f"{acos:.0%} ACoS vs {be:.0%} break-even",
                    "Cut bids below break-even or pause; re-check price/COGS", "bidopt", "high")

            # Catch-All / limited data
            if clicks < LIMITED_CLICKS and ttype == "auto":
                add("Catch-All (Low Bid Broad)", f"auto campaign, {clicks} clicks (limited data)",
                    "Keep low bids; mine search terms weekly", "harvest", "low")
            # Search Term Harvesting — discovery campaign with enough clicks
            if ttype == "auto" and clicks >= HARVEST_CLICKS:
                add("Search Term Harvesting", f"{clicks} clicks on auto campaign",
                    "Harvest converting terms → Exact, then trim discovery bids", "harvest", "high")
            # Broad Match Research
            if "broad" in mset:
                add("Broad Match Research", "broad match present",
                    "Run broad at moderate bids; add negatives weekly", "harvest", "med")
            # Negative Sculpting — wasted spend in campaign
            if orders == 0 and spend >= t.min_spend:
                add("Negative Keyword Sculpting", f"${spend:.0f} spend, 0 orders",
                    "Add negatives at campaign / ad-group", "harvest", "high")
            # Exact Match Scaling — profitable exact campaign
            if "exact" in mset and acos is not None and orders >= t.scale_min_orders and acos <= goal * t.scale_acos_frac:
                add("Exact Match Scaling", f"exact, {orders} orders @ {acos:.0%} ACoS",
                    "Scale bids + add TOS placement adjustment", "bidopt", "high")
            # Budget Segmentation — capped proxy
            if budget and spend >= budget * CAP_RATIO:
                add("Budget Segmentation", f"${spend:.0f} spend vs ${budget:.0f} budget (capped)",
                    "Split by match type/intent or raise budget", "manual", "med")
            # Lifecycle
            if orders >= 26:
                add("Lifecycle Campaign Structure", f"{orders} orders — Scale stage",
                    "Tighten to exact + raise budget on winners", "manual", "low")
            # Portfolio Segmentation
            if dimc and not dimc.portfolio_id:
                add("Portfolio Segmentation", "no portfolio assigned",
                    "Group campaigns into portfolios by objective", "manual", "low")

            # SKAG — keyword worth isolating
            for ag in c["ad_groups"]:
                kw = [tg for tg in ag["targets"] if tg.get("type") == "keyword"]
                if len(kw) < 2:
                    continue
                for tg in kw:
                    tm = tg["metrics"]; ta = tm["acos"]
                    if tm["orders"] >= SKAG_ORDERS and ta is not None and ta <= goal:
                        add("SKAG (Single Keyword Ad Group)",
                            f"'{tg['label']}' {tm['orders']} orders @ {ta:.0%} in {len(kw)}-kw ad group",
                            "Isolate this keyword into its own ad group (SKAG)", "manual", "med")
                        break

    # Placement strategy from placement facts (TOS converting under goal)
    snap = audit_stage.active_snapshot(db)
    pl = db.query(md.FactPlacement)
    if snap:
        pl = pl.filter(md.FactPlacement.snapshot_date == snap)
    tos = defaultdict(lambda: {"spend": 0.0, "sales": 0.0, "orders": 0})
    for f in pl.all():
        if "top" in (f.placement or "").lower():
            a = tos[f.campaign_id]; a["spend"] += f.spend; a["sales"] += f.sales; a["orders"] += f.orders
    for cid, a in tos.items():
        ac = a["spend"] / a["sales"] if a["sales"] else None
        if a["orders"] > 0 and ac is not None and ac <= goal:
            fired.add("Placement Bid Optimization")
            recs.append({"strategy": "Placement Bid Optimization", "campaign_id": cid,
                         "campaign": camps.get(cid).name if camps.get(cid) else cid, "asin": None,
                         "criteria": f"Top-of-Search {ac:.0%} ACoS (profitable)",
                         "action": "Raise TOS placement multiplier", "tool": "placement",
                         "priority": "med", "spend": round(a["spend"], 2), "stage": "Scale",
                         "bulk": True})

    prio = {"high": 0, "med": 1, "low": 2}
    recs.sort(key=lambda r: (prio.get(r["priority"], 3), -r["spend"]))

    # playbook with computed status
    playbook = []
    for name, criteria, action, reco, avail, tool in PLAYBOOK:
        if name in fired:
            status = "active"
        elif avail == "na":
            status = "n/a"
        elif avail == "config":
            status = "needs config"
        elif avail == "manual":
            status = "manual"
        else:
            status = "available"
        playbook.append({"strategy": name, "criteria": criteria, "action": action,
                         "recommendation": reco, "tool": tool, "status": status,
                         "bulk": name in BULK_STRATEGIES})

    counts = {"high": sum(1 for r in recs if r["priority"] == "high"),
              "med": sum(1 for r in recs if r["priority"] == "med"),
              "low": sum(1 for r in recs if r["priority"] == "low")}

    return {"has_portfolio": have_portfolio, "counts": counts,
            "states": account_states(db, t),
            "recommendations": recs, "playbook": playbook}


def account_states(db: Session, t: Thresholds) -> dict:
    """Per-campaign state classifier — the methodology map's four
    ACoS-vs-break-even states, computed live. Each campaign lands in ONE state
    with its goal lever: below_target (grow) / at_target (balance, ±15% band) /
    above_target (cut) / over_break_even (cut hard — over the product's REAL
    break-even from the catalog + Transactions-ledger fees) / no_data (rank).
    Shared by the generic advisor AND the cadence strategy sets."""
    from .. import database as dbmod
    from . import benchmark as bench_stage
    from . import catalog as cat

    tree = audit_stage.build_tree(db)
    be_map = bench_stage.break_even_map(db)
    goal_map = bench_stage.goal_map(db)
    sku_be = cat.be_by_sku(db.info.get("store"),
                           dbmod.get_project_econ(db.info.get("store"), db.info.get("project")))
    asin_sku = {}
    for ad in db.query(md.DimAd).all():
        if ad.asin and ad.sku:
            asin_sku.setdefault(ad.asin, ad.sku)
    camps = {c.campaign_id: c for c in db.query(md.DimCampaign).all()}

    AT_BAND = 0.15

    def classify(acos, be, goal, spend, orders, clicks):
        if acos is None:
            if spend >= t.min_spend and orders == 0:
                return "over_break_even", "cut hard", "spend with zero sales — pure bleed"
            return "no_data", "rank", f"{clicks} clicks — not enough data yet"
        if be is not None and acos > be:
            return "over_break_even", "cut hard", f"{acos:.0%} ACoS over {be:.0%} break-even"
        if acos > goal * (1 + AT_BAND):
            return "above_target", "cut", f"{acos:.0%} ACoS over goal {goal:.0%}"
        if acos < goal * (1 - AT_BAND):
            return "below_target", "grow", f"{acos:.0%} ACoS under goal {goal:.0%} — room to scale"
        return "at_target", "balance", f"{acos:.0%} ACoS ≈ goal {goal:.0%}"

    state_rows: dict[str, dict] = {}       # campaign_id -> row (first ASIN wins)
    for asin, node in tree.items():
        be = be_map.get(asin)
        if be is None:
            be = sku_be.get(cat.norm_sku(asin_sku.get(asin)))
        for c in node["campaigns"]:
            cid = c["campaign_id"]
            if cid in state_rows:
                continue
            dimc = camps.get(cid)
            if dimc and (dimc.state or "").lower() == "archived":
                continue
            m = c["metrics"]
            goal_eff = goal_map.get(asin) or t.target_acos
            state, lever, why = classify(m["acos"], be, goal_eff, m["spend"], m["orders"], m["clicks"])
            state_rows[cid] = {"campaign_id": cid, "campaign": c["name"], "asin": asin,
                               "spend": round(m["spend"], 2), "sales": round(m["sales"], 2),
                               "orders": m["orders"], "acos": m["acos"], "break_even": be,
                               "goal": round(goal_eff, 4), "state": state,
                               "lever": lever, "why": why}

    rows = sorted(state_rows.values(), key=lambda r: -r["spend"])
    order = ("below_target", "at_target", "above_target", "over_break_even", "no_data")
    return {"counts": {k: sum(1 for r in rows if r["state"] == k) for k in order},
            "campaigns": rows}


# ---- one-click bulk per strategy --------------------------------------------
_BUDGET_COLS = ["Product", "Entity", "Operation", "Campaign ID", "Daily Budget"]


def _budget_bulk(db: Session, t: Thresholds):
    """Capped campaigns -> raise daily budget by BUDGET_RAISE."""
    tree = audit_stage.build_tree(db)
    camps = {c.campaign_id: c for c in db.query(md.DimCampaign).all()}
    rows, entries = [], []
    seen = set()
    for node in tree.values():
        for c in node["campaigns"]:
            cid = c["campaign_id"]
            if cid in seen:
                continue
            seen.add(cid)
            dimc = camps.get(cid)
            budget = dimc.daily_budget if dimc else None
            spend = c["metrics"]["spend"]
            if budget and spend >= budget * CAP_RATIO:
                new = round(budget * BUDGET_RAISE, 2)
                rows.append({"Product": "Sponsored Products", "Entity": "Campaign",
                             "Operation": "update", "Campaign ID": bulkfmt.idstr(cid), "Daily Budget": new})
                entries.append(dict(campaign_id=cid, entity_type="campaign", entity_id=cid,
                                    label=c["name"], field="daily_budget",
                                    old_value=str(budget), new_value=str(new),
                                    action="raise_budget",
                                    reason=f"${spend:.0f} spend vs ${budget:.0f} budget (capped)"))
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(rows, columns=_BUDGET_COLS).to_excel(w, index=False,
            sheet_name="Sponsored Products Campaigns")
    return buf.getvalue(), entries, len(rows)


def build_bulk(db: Session, t: Thresholds, strategy: str):
    """One-click: strategy name -> (xlsx bytes, changelog entries, row count).
    Routes to the engine that owns the action. Raises ValueError if the strategy
    has no auto-bulk (manual / needs an STR upload)."""
    from . import bidopt as bidopt_stage, placement as placement_stage, changelog as cl

    if strategy == "Exact Match Scaling":
        plan = bidopt_stage.optimize(db, t)
        exact = {tg.target_id for tg in db.query(md.DimTarget)
                 .filter(md.DimTarget.match_type.ilike("exact")).all()}
        rows = [r for r in plan["rows"] if r["direction"] == "raise" and r["target_id"] in exact]
        return bidopt_stage.to_bulk(db, rows), cl.from_bidopt(rows), len(rows)

    if strategy == "Negative Keyword Sculpting":
        from ..rules import Flag  # noqa: F401  (audit returns Flag objects)
        flags = [f.__dict__ for f in audit_stage.audit(db, t) if f.flag == "WASTED_SPEND"]
        from . import automate as automate_stage
        return automate_stage.flags_to_bulk(db, flags), cl.from_flags(db, flags), len(flags)

    if strategy == "Placement Bid Optimization":
        pl = placement_stage.analyze(db, t)
        return placement_stage.to_bulk(pl["rows"]), cl.from_placement(pl["rows"]), len(pl["rows"])

    if strategy == "Budget Segmentation":
        return _budget_bulk(db, t)

    raise ValueError(f"strategy '{strategy}' has no one-click bulk "
                     "(run it via its tool or it needs a Search Term Report)")
