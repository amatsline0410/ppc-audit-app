"""Flag rules. Each is a pure function (metrics, thresholds) -> Flag | None.

Independent + individually testable. Thresholds come from config, overridable
per request (so the goal-ACoS input on the frontend flows straight in here).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from .config import Thresholds
from . import metrics as M


@dataclass
class Flag:
    entity_type: str
    entity_id: str
    asin: Optional[str]
    flag: str
    severity: str            # high | medium | low
    observed: Optional[float]
    threshold: Optional[float]
    suggested_action: str
    new_bid: Optional[float] = None   # filled for bid-change flags
    label: Optional[str] = None       # human label (keyword text / expression)
    stage: Optional[str] = None       # bid-ladder stage: REDUCE | MONITOR | PAUSE
    break_even: Optional[float] = None  # the ASIN's break-even ACoS (benchmark/catalog)


def _sev(ratio: float) -> str:
    if ratio >= 2.0:
        return "high"
    if ratio >= 1.4:
        return "medium"
    return "low"


def high_acos(m, t: Thresholds, ctx) -> Optional[Flag]:
    """Over-goal ACoS. For entities WITH sales, a graduated ladder decides the
    action: reduce bid -> monitor -> pause. History wins (consecutive over-goal
    periods); on a single upload, severity stands in (cut once, never pause)."""
    a = m["acos"]
    if a is not None and a > t.target_acos and m["spend"] >= t.min_spend:
        ratio = a / t.target_acos
        over = ctx.get("over_periods", 1) or 1   # trailing consecutive over-goal snapshots
        nb = M.target_acos_bid(ctx.get("bid"), a, t.target_acos, t.max_bid_cut, t.max_bid_up, t.bid_floor)
        if over >= 3:
            stage, action, new_bid = "PAUSE", "Over goal 3+ periods — pause / negate", t.bid_floor
        elif over == 2:
            stage, action, new_bid = "MONITOR", "Bid already cut, still over goal — hold & monitor", None
        elif ratio >= 2.0:
            stage, action, new_bid = "MONITOR", "Far over goal — cut once, then monitor", nb
        else:
            stage, action, new_bid = "REDUCE", f"Lower bid toward {t.target_acos:.0%} ACoS", nb
        return Flag(ctx["entity_type"], ctx["entity_id"], ctx.get("asin"), "HIGH_ACOS",
                    _sev(ratio), round(a, 4), t.target_acos, action, new_bid, ctx.get("label"), stage)
    return None


def bleeding(m, t: Thresholds, ctx) -> Optional[Flag]:
    """ACoS above the product's break-even = losing money on every ad sale.
    Worse than HIGH_ACOS (which is just over goal). Cut hard toward goal."""
    be, a = ctx.get("break_even_acos"), m["acos"]
    if be and a is not None and a > be and m["spend"] >= t.min_spend:
        nb = M.target_acos_bid(ctx.get("bid"), a, t.target_acos, t.max_bid_cut, t.max_bid_up, t.bid_floor)
        return Flag(ctx["entity_type"], ctx["entity_id"], ctx.get("asin"), "BLEEDING",
                    "high", round(a, 4), round(be, 4),
                    f"Above break-even {be:.0%} — losing money, cut hard / pause",
                    nb, ctx.get("label"))
    return None


def wasted_spend(m, t: Thresholds, ctx) -> Optional[Flag]:
    if m["orders"] == 0 and m["spend"] >= t.min_spend:
        return Flag(ctx["entity_type"], ctx["entity_id"], ctx.get("asin"), "WASTED_SPEND",
                    "high", m["spend"], t.min_spend,
                    "Pause target / add as negative", t.bid_floor, ctx.get("label"))
    return None


def low_ctr(m, t: Thresholds, ctx) -> Optional[Flag]:
    c = m["ctr"]
    if c is not None and c < t.low_ctr and m["impressions"] >= t.min_impressions:
        return Flag(ctx["entity_type"], ctx["entity_id"], ctx.get("asin"), "LOW_CTR",
                    "low", round(c, 4), t.low_ctr,
                    "Review listing image/relevance", None, ctx.get("label"))
    return None


def low_cvr(m, t: Thresholds, ctx) -> Optional[Flag]:
    c = m["cvr"]
    if c is not None and c < t.low_cvr and m["clicks"] >= t.min_clicks:
        return Flag(ctx["entity_type"], ctx["entity_id"], ctx.get("asin"), "LOW_CVR",
                    "medium", round(c, 4), t.low_cvr,
                    "Listing/price issue, not a bid problem", None, ctx.get("label"))
    return None


def overbid(m, t: Thresholds, ctx) -> Optional[Flag]:
    bid, c = ctx.get("bid"), m["cpc"]
    if bid and c and m["clicks"] >= t.min_clicks and bid > c * t.overbid_multiplier:
        nb = max(round(c * 1.1, 2), t.bid_floor)
        return Flag(ctx["entity_type"], ctx["entity_id"], ctx.get("asin"), "OVERBID",
                    "low", bid, round(c * t.overbid_multiplier, 2),
                    "Lower bid toward actual CPC", nb, ctx.get("label"))
    return None


def scale_winner(m, t: Thresholds, ctx) -> Optional[Flag]:
    """Offensive: profitable target with ACoS headroom under goal -> raise bid.

    The mirror of high_acos. Only fires when there are real orders and the
    suggested bid actually goes UP (target_acos_bid caps the raise at max_bid_up).
    """
    a, bid = m["acos"], ctx.get("bid")
    if (a is not None and a > 0 and m["orders"] >= t.scale_min_orders
            and a <= t.target_acos * t.scale_acos_frac and m["spend"] >= t.min_spend):
        nb = M.target_acos_bid(bid, a, t.target_acos, t.max_bid_cut, t.max_bid_up, t.bid_floor)
        if bid and nb and nb > bid:
            return Flag(ctx["entity_type"], ctx["entity_id"], ctx.get("asin"), "SCALE_WINNER",
                        _sev(t.target_acos / a), round(a, 4), t.target_acos,
                        f"Raise bid — {m['orders']} orders @ {a:.0%} ACoS, headroom under goal",
                        nb, ctx.get("label"))
    return None


# registry — audit.py iterates this; add a rule = add a line
TARGET_RULES = [bleeding, high_acos, scale_winner, wasted_spend, low_ctr, low_cvr, overbid]


def run_target_rules(m: dict, t: Thresholds, ctx: dict) -> list[Flag]:
    out = []
    for rule in TARGET_RULES:
        f = rule(m, t, ctx)
        if f:
            out.append(f)
    return out
