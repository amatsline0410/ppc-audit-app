"""Placement bid optimization (Top of Search / Product page / Rest of search).

Amazon lets you bump bids by placement via a percentage modifier ('Bidding
Adjustment' bulk rows carry each placement's current % + its performance + the
campaign's Bidding Strategy). Per campaign AND account rollup we compute
spend/sales/ACoS/CVR/CPC/share-of-spend, flag the classic placement diseases,
and recommend a new modifier:

  flags:
    FLAT_MODIFIER    same % on every placement with spend (real case: +20%
                     everywhere — placement data unused)
    PLACEMENT_BLEED  placement ACoS > 2x goal with real spend (real case:
                     product page 76.7% vs top-of-search 21.9%)
    TOS_STARVED      top-of-search converts under goal but gets < 25% of the
                     campaign's spend — the winner is being starved

  modifier math (cut path, never raises a bleeding placement):
    new_pct = clip(current_pct * (goal_acos / placement_acos), 0, 400)
  TOS raise path (step raises only): ACoS < goal -> min(current + 25, 150).
  Product Page floors at 0 — a modifier can't go negative; if PP still bleeds
  at 0% the fix is the campaign's BASE bids, so we emit companion bid-cut
  suggestions via metrics.safe_bid_cut on that campaign's targets.
"""
from __future__ import annotations
import io
from collections import defaultdict
import pandas as pd
from sqlalchemy.orm import Session
from .. import models as md
from .. import metrics as M
from ..config import Thresholds
from . import audit as audit_stage
from . import bid_optimizer as bo
from . import bulkfmt

# canonical placement label cleanup for display
_NICE = {"placement top": "Top of Search", "placement product page": "Product pages",
         "placement rest of search": "Rest of search", "placement amazon business": "Amazon Business"}
TOS_RAISE_STEP = 25.0     # step raises only — never jump a modifier
TOS_RAISE_CAP = 150.0
CUT_CAP = 400.0           # clip ceiling on the cut path
BLEED_MULT = 2.0          # PLACEMENT_BLEED: acos >= this x goal
TOS_STARVED_SHARE = 0.25  # TOS share-of-spend below this while under goal


def _nice(p: str) -> str:
    return _NICE.get(p.strip().lower(), p)


def _is_tos(p: str) -> bool:
    return bo.normalize_placement(p) == "top_of_search"


def _is_pp(p: str) -> bool:
    return bo.normalize_placement(p) == "product_pages"


# ---- pure modifier recommendation --------------------------------------------
def recommend_pct(placement: str, cur: float, acos: float | None, goal: float,
                  clicks: int, orders: int, spend: float, th: dict) -> tuple[float, str]:
    """(new_pct, reason). Never raises a bleeding placement; TOS raises step +25
    capped at 150; cuts clip to [0, 400] — Product Page floors at 0."""
    if clicks < th["min_clicks"]:
        return cur, "not enough clicks"
    if orders == 0 and spend >= th["min_spend"]:
        return 0.0, f"${spend:.0f} spend, 0 orders — drop to +0%"
    if acos is None or acos <= 0:
        return cur, "no signal"
    if acos > goal:
        # CUT path — scale the modifier itself toward goal, hard floor 0
        new = max(0.0, min(cur * (goal / acos), CUT_CAP))
        new = min(new, cur)                       # never raise on a bleeding placement
        return new, f"{acos:.0%} ACoS vs goal {goal:.0%} — lower placement modifier"
    # under goal -> raise path, TOS only, step raises, thin-data guard
    if _is_tos(placement):
        if orders < th["min_purchases"]:
            return cur, "too few orders to raise placement"
        new = min(cur + TOS_RAISE_STEP, TOS_RAISE_CAP)
        if new <= cur:
            return cur, f"at the +{TOS_RAISE_CAP:.0f}% cap"
        return new, f"{acos:.0%} ACoS under goal {goal:.0%} — step TOS up +{TOS_RAISE_STEP:.0f}%"
    return cur, "profitable — leave as is"


# ---- pure per-campaign flags ----------------------------------------------------
def campaign_flags(placements: list[dict], goal: float, min_spend: float) -> list[str]:
    """placements: [{placement, pct, spend, sales, acos, orders}] for ONE campaign."""
    flags = []
    with_spend = [p for p in placements if (p.get("spend") or 0) > 0]
    pcts = {round(p.get("pct") or 0) for p in with_spend}
    if len(with_spend) >= 2 and len(pcts) == 1 and pcts != {0}:
        flags.append("FLAT_MODIFIER")
    for p in with_spend:
        if (p.get("acos") is not None and p["acos"] >= BLEED_MULT * goal
                and p["spend"] >= min_spend):
            flags.append("PLACEMENT_BLEED")
            break
    total = sum(p["spend"] for p in with_spend)
    tos = next((p for p in with_spend if _is_tos(p["placement"])), None)
    if (tos and total and tos.get("acos") is not None and tos["acos"] < goal
            and tos["spend"] / total < TOS_STARVED_SHARE):
        flags.append("TOS_STARVED")
    return flags


def _ensure_schema(db: Session) -> None:
    """Old dbs predate the `strategy` column on fact_placement — add it once."""
    from sqlalchemy import text
    cols = [r[1] for r in db.execute(text("PRAGMA table_info(fact_placement)")).fetchall()]
    if cols and "strategy" not in cols:
        db.execute(text("ALTER TABLE fact_placement ADD COLUMN strategy VARCHAR"))
        db.commit()


def analyze(db: Session, t: Thresholds) -> dict:
    _ensure_schema(db)
    snap = audit_stage.active_snapshot(db)
    q = db.query(md.FactPlacement)
    if snap:
        q = q.filter(md.FactPlacement.snapshot_date == snap)
    facts = q.all()
    names = {c.campaign_id: c.name for c in db.query(md.DimCampaign).all()}
    th = bo.CONFIG["thresholds"]

    # campaign -> its product's break-even ACoS (benchmark upload wins, else the
    # catalog listing's price + per-SKU COGS + real Transactions-ledger fees;
    # ASIN match, normalized-SKU fallback) via the campaign's first product ad
    from .. import database as dbmod
    from . import benchmark as bench_stage
    from . import catalog as cat
    be_map = bench_stage.break_even_map(db)
    sku_be = cat.be_by_sku(db.info.get("store"),
                           dbmod.get_project_econ(db.info.get("store"), db.info.get("project")))
    ag_camp = {g.ad_group_id: g.campaign_id for g in db.query(md.DimAdGroup).all()}
    camp_be: dict[str, float] = {}
    for ad in db.query(md.DimAd).all():
        cid = ag_camp.get(ad.ad_group_id)
        if not cid:
            continue
        be = be_map.get(ad.asin)
        if be is None and ad.sku:
            be = sku_be.get(cat.norm_sku(ad.sku))
        if be is not None:
            camp_be.setdefault(cid, be)

    # group by campaign for flags + share-of-spend
    by_camp: dict[str, list] = defaultdict(list)
    for f in facts:
        by_camp[f.campaign_id].append(f)

    rows, all_flags = [], []
    by_place = defaultdict(lambda: {"clicks": 0, "spend": 0.0, "sales": 0.0, "orders": 0})
    pp_bleed_at_zero: list[str] = []          # campaigns needing base-bid companions
    for cid, fs in by_camp.items():
        camp_total = sum(f.spend or 0 for f in fs)
        pl_dicts = []
        for f in fs:
            m = M.all_metrics(f.impressions, f.clicks, f.spend, f.sales, f.orders, 0)
            pl_dicts.append({"placement": f.placement, "pct": f.percentage or 0.0,
                             "spend": f.spend, "sales": f.sales, "acos": m["acos"],
                             "orders": f.orders})
        cflags = campaign_flags(pl_dicts, t.target_acos, t.min_spend)
        for f in fs:
            m = M.all_metrics(f.impressions, f.clicks, f.spend, f.sales, f.orders, 0)
            acos = m["acos"]
            cur = f.percentage or 0.0
            new, reason = recommend_pct(f.placement, cur, acos, t.target_acos,
                                        f.clicks, f.orders, f.spend, th)
            # per-cycle step limit + whole-% rounding (cuts can move further than
            # raises; the limiter keeps every move bounded)
            target_new = new
            new = round(bo.limit_step(cur, new, "placement_adj"))
            if abs(target_new - cur) > bo.CONFIG["max_step"]["placement_adj"]:
                reason += " (step-limited)"
            fl = []
            be = camp_be.get(f.campaign_id)
            if (acos is not None and acos >= BLEED_MULT * t.target_acos
                    and f.spend >= t.min_spend):
                fl.append("PLACEMENT_BLEED")
                if _is_pp(f.placement) and cur <= 0:
                    fl.append("BASE_BID_FIX")     # can't go below 0% — cut base bids
                    pp_bleed_at_zero.append(cid)
            # over the PRODUCT's break-even (real unit economics) — losing money
            # on this placement even when it's under the 2x-goal bleed bar
            if (be is not None and acos is not None and acos > be
                    and f.spend >= t.min_spend and "PLACEMENT_BLEED" not in fl):
                fl.append("OVER_BREAK_EVEN")
            if "FLAT_MODIFIER" in cflags:
                fl.append("FLAT_MODIFIER")
            if "TOS_STARVED" in cflags and _is_tos(f.placement):
                fl.append("TOS_STARVED")
            agg = by_place[f.placement]
            agg["clicks"] += f.clicks; agg["spend"] += f.spend
            agg["sales"] += f.sales; agg["orders"] += f.orders
            if abs(new - cur) >= 1 or fl:         # surface changes AND flagged rows
                rows.append({"campaign_id": f.campaign_id, "campaign_name": names.get(f.campaign_id),
                             "placement": _nice(f.placement), "placement_raw": f.placement,
                             "strategy": f.strategy,
                             "clicks": f.clicks, "spend": round(f.spend, 2), "orders": f.orders,
                             "sales": round(f.sales, 2), "cvr": m["cvr"], "cpc": m["cpc"],
                             "share_of_spend": round(f.spend / camp_total, 4) if camp_total else None,
                             "acos": acos, "break_even_acos": be,
                             "current_pct": round(cur, 1),
                             "suggested_pct": round(new, 1), "delta": round(new - cur, 1),
                             "flags": fl, "reason": reason})
        if cflags:
            all_flags.append({"campaign_id": cid, "campaign_name": names.get(cid), "flags": cflags})

    rows.sort(key=lambda r: r["spend"], reverse=True)

    # companion base-bid cuts for campaigns whose product page bleeds at +0%
    companions = _companion_bid_cuts(db, set(pp_bleed_at_zero), names, t, snap) \
        if pp_bleed_at_zero else []

    # account-level placement scorecard (+ share of account spend, cvr, cpc)
    total_spend = sum(a["spend"] for a in by_place.values())
    summary = []
    for place, a in by_place.items():
        m = M.all_metrics(0, a["clicks"], a["spend"], a["sales"], a["orders"], 0)
        summary.append({"placement": _nice(place), "clicks": a["clicks"],
                        "spend": round(a["spend"], 2), "sales": round(a["sales"], 2),
                        "orders": a["orders"], "acos": m["acos"], "cvr": m["cvr"],
                        "cpc": m["cpc"],
                        "share_of_spend": round(a["spend"] / total_spend, 4) if total_spend else None})
    summary.sort(key=lambda r: r["spend"], reverse=True)
    return {"has_data": bool(facts), "summary": summary, "count": len(rows), "rows": rows,
            "campaign_flags": all_flags, "companions": companions}


def _companion_bid_cuts(db: Session, campaign_ids: set[str], names: dict,
                        t: Thresholds, snap) -> list[dict]:
    """Product page bleeding at +0% modifier: the modifier can't go negative, so
    the lever is the campaign's BASE bids — safe_bid_cut on its targets."""
    fm = audit_stage._fact_map(db, snap)
    ag_camp = {g.ad_group_id: g.campaign_id for g in db.query(md.DimAdGroup).all()}
    strat_by_camp = {f.campaign_id: f.strategy
                     for f in db.query(md.FactPlacement).all() if f.strategy}
    out = []
    for tg in db.query(md.DimTarget).all():
        cid = ag_camp.get(tg.ad_group_id)
        if cid not in campaign_ids:
            continue
        if tg.state and tg.state not in ("enabled", "ok", None):
            continue
        if tg.target_type not in ("keyword", "product_target"):
            continue
        m = fm.get(("target", tg.target_id))
        if not m or not tg.bid:
            continue
        new = M.safe_bid_cut(tg.bid, m["cpc"], m["acos"], t.target_acos,
                             strat_by_camp.get(cid), floor=t.bid_floor)
        if new is None:
            continue
        out.append({"campaign_id": cid, "campaign_name": names.get(cid),
                    "target_id": tg.target_id, "kind": tg.target_type,
                    "target_type": tg.target_type, "direction": "cut",
                    "ad_group_id": tg.ad_group_id,
                    "label": tg.keyword_text or tg.expression,
                    "current_bid": round(tg.bid, 2), "suggested_bid": new,
                    "delta": round(new - tg.bid, 2), "acos": m["acos"],
                    "spend": m["spend"],
                    "reason": "product page bleeds at +0% — lower the base bid instead"})
    out.sort(key=lambda r: r["spend"], reverse=True)
    return out


_COLS = ["Product", "Entity", "Operation", "Campaign ID", "Ad Group ID", "Keyword ID",
         "Product Targeting ID", "Bidding Strategy", "Placement", "Percentage", "Bid", "State"]


def to_bulk(chosen: list[dict], companion_rows: list[dict] | None = None) -> bytes:
    """Chosen placement rows -> Amazon SP 'Bidding Adjustment' updates (+ optional
    companion base-bid cuts as Keyword / Product Targeting updates by exact ID)."""
    out, seen = [], set()
    for r in chosen:
        cid = bulkfmt.idstr(r["campaign_id"])
        sig = ("pl", cid, str(r.get("placement_raw") or r["placement"]).lower())
        if sig in seen:
            continue
        seen.add(sig)
        row = {c: None for c in _COLS}
        row.update({"Product": "Sponsored Products", "Entity": "Bidding Adjustment",
                    "Operation": "update", "Campaign ID": cid,
                    "Bidding Strategy": r.get("strategy"),
                    "Placement": r.get("placement_raw") or r["placement"],
                    "Percentage": r["suggested_pct"]})
        out.append(row)
    for r in companion_rows or []:
        tid = bulkfmt.idstr(r.get("target_id"))
        if not tid or ("t", tid) in seen:
            continue
        seen.add(("t", tid))
        row = {c: None for c in _COLS}
        is_kw = r.get("kind") == "keyword"
        row.update({"Product": "Sponsored Products",
                    "Entity": "Keyword" if is_kw else "Product Targeting",
                    "Operation": "update", "Campaign ID": bulkfmt.idstr(r.get("campaign_id")),
                    "Ad Group ID": bulkfmt.idstr(r.get("ad_group_id")),
                    "Bid": r.get("suggested_bid"), "State": "enabled"})
        row["Keyword ID" if is_kw else "Product Targeting ID"] = tid
        out.append(row)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(out, columns=_COLS).to_excel(w, index=False, sheet_name="Sponsored Products Campaigns")
    return buf.getvalue()
