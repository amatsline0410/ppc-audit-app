"""Bid Optimizer — a full-portfolio bid plan, not just flagged targets.

For every enabled keyword/product-target with enough clicks, compute the optimal
bid from first principles (target-CPC), capped by break-even and clamped per pass.
Outputs a reviewable plan + an Amazon bulk update sheet.

Optimal bid:  max_cpc = goal_acos * (sales / clicks)
  - goal_acos is the per-ASIN goal override if set, else the global goal.
  - capped so the implied ACoS never exceeds the product's break-even.
  - clamped to [max_bid_cut, max_bid_up] of the current bid, floored.
"""
from __future__ import annotations
from sqlalchemy.orm import Session
from .. import models as md
from .. import metrics as M
from ..config import Thresholds
from . import audit as audit_stage, benchmark as bench_stage
from . import bid_optimizer as bo


def optimize(db: Session, t: Thresholds) -> dict:
    snap = audit_stage.active_snapshot(db)
    fm = audit_stage._fact_map(db, snap)
    be_map = bench_stage.break_even_map(db)
    goal_map = bench_stage.goal_map(db)
    groups = {g.ad_group_id: g for g in db.query(md.DimAdGroup).all()}
    # break-even fallback when the ad's ASIN isn't in the benchmark/catalog map:
    # match the catalog LISTING by normalized SKU (real Transactions-ledger fees
    # + per-SKU COGS) — same join the audit / Product Ads / Strategy use.
    from .. import database as dbmod
    from . import catalog as cat
    sku_be = cat.be_by_sku(db.info.get("store"),
                           dbmod.get_project_econ(db.info.get("store"), db.info.get("project")))
    ag_asin, ag_sku = {}, {}
    for ad in db.query(md.DimAd).all():
        ag_asin.setdefault(ad.ad_group_id, ad.asin)
        if ad.sku:
            ag_sku.setdefault(ad.ad_group_id, ad.sku)
    # BidLedger overlay: bids already exported (but not yet visible in a fresh
    # snapshot) win over the stale snapshot bid — never double-apply a change.
    from . import ledger as ledger_stage
    base = ledger_stage.base_session(db)
    try:
        effective = ledger_stage.effective_map(base)
    finally:
        base.close()

    rows = []
    for tg in db.query(md.DimTarget).all():
        eff = effective.get(str(tg.target_id), {})
        state = eff.get("state") or tg.state
        if state and state not in ("enabled", "ok", None):
            continue
        m = fm.get(("target", tg.target_id))
        # guardrail rule 1 — need enough clicks + spend before touching a bid.
        # (purchases are only required to *raise*; a 0-order spender can still be cut.)
        th = bo.CONFIG["thresholds"]
        if not m or m["clicks"] < th["min_clicks"] or m["spend"] < th["min_spend"]:
            continue
        asin = ag_asin.get(tg.ad_group_id)
        goal = goal_map.get(asin) or t.target_acos
        be = be_map.get(asin)
        if be is None:
            be = sku_be.get(cat.norm_sku(ag_sku.get(tg.ad_group_id)))
        cur = eff.get("bid") if eff.get("bid") is not None else tg.bid
        # overbid (rule 6): bid over the hard cap or way above observed CPC —
        # skip the per-pass cut cap + step limiter, reset to target in one pass.
        overbid = bo.is_overbid(cur, "keyword_bid", m["cpc"])
        if m["acos"] is not None and m["acos"] > goal:
            # over goal -> CUT path. safe_bid_cut never raises — on up/down
            # campaigns CPC runs ~2x the bid, so the target-CPC formula can
            # exceed the current bid and turn a cut into a raise.
            new = M.safe_bid_cut(cur, m["cpc"], m["acos"], goal, None, floor=t.bid_floor)
            if new is not None and cur and not overbid:
                new = max(new, round(cur * t.max_bid_cut, 2))   # keep per-pass cut cap
        else:
            new = M.target_cpc_bid(m["clicks"], m["sales"], goal, cur,
                                   t.max_bid_cut, t.max_bid_up, t.bid_floor, cap_acos=be)
        if new is None or cur is None:
            continue
        # guardrails rule 3+4 — hard $ caps + absolute per-cycle step. Most
        # conservative: this stacks on target_cpc_bid's relative clamp, smaller wins.
        new = bo.clamp_caps(new, "keyword_bid")
        if not overbid:
            new = round(bo.limit_step(cur, new, "keyword_bid"), 2)
        if abs(new - cur) < 0.01:
            continue
        direction = "raise" if new > cur else "cut"
        # don't raise on thin conversion evidence (guardrail rule 1, raise side)
        if direction == "raise" and m["orders"] < th["min_purchases"]:
            continue
        if overbid and direction == "cut":
            cpc_txt = f" vs ${m['cpc']:.2f} CPC" if m["cpc"] else ""
            reason = f"overbid ${cur:.2f}{cpc_txt} — reset to ${new:.2f} in one pass"
        elif m["orders"] == 0:
            reason = f"{m['clicks']} clicks, 0 orders — pull bid back"
        elif direction == "raise":
            reason = f"profitable @ {m['acos']:.0%} — bid up to reach goal {goal:.0%}"
        else:
            reason = f"{m['acos']:.0%} ACoS over goal {goal:.0%} — bid down to target CPC"
        grp = groups.get(tg.ad_group_id)
        rows.append({
            "target_id": tg.target_id, "target_type": tg.target_type,
            "label": tg.keyword_text or tg.expression, "asin": asin,
            "campaign_id": grp.campaign_id if grp else None, "ad_group_id": tg.ad_group_id,
            "current_bid": cur, "suggested_bid": new, "delta": round(new - cur, 2),
            "direction": direction, "overbid": overbid, "clicks": m["clicks"], "orders": m["orders"],
            "spend": m["spend"], "acos": m["acos"], "goal_acos": round(goal, 4),
            "break_even_acos": be, "reason": reason})

    rows.sort(key=lambda r: r["spend"], reverse=True)
    raises = [r for r in rows if r["direction"] == "raise"]
    cuts = [r for r in rows if r["direction"] == "cut"]
    return {"count": len(rows), "raises": len(raises), "cuts": len(cuts),
            "spend_optimized": round(sum(r["spend"] for r in rows), 2),
            "rows": rows}


def to_bulk(db: Session, chosen: list[dict]) -> bytes:
    """Chosen optimizer rows -> Amazon SP bulk bid-update sheet (reuses automate)."""
    from . import automate as automate_stage
    pseudo = [{"entity_id": r["target_id"], "flag": "OVERBID",
               "new_bid": r["suggested_bid"], "stage": None} for r in chosen]
    return automate_stage.flags_to_bulk(db, pseudo)
