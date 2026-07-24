"""Pure metric formulas. No I/O, no DB. Fully unit-testable.

Every denominator guarded. ACoS is None when sales==0 (treat as worst, never 0).
"""
from __future__ import annotations
from typing import Optional


def ctr(clicks: float, impressions: float) -> Optional[float]:
    return clicks / impressions if impressions else None


def cpc(spend: float, clicks: float) -> Optional[float]:
    return spend / clicks if clicks else None


def cvr(orders: float, clicks: float) -> Optional[float]:
    return orders / clicks if clicks else None


def acos(spend: float, sales: float) -> Optional[float]:
    """spend / sales. None when no sales (undefined / worst case)."""
    return spend / sales if sales else None


def roas(sales: float, spend: float) -> Optional[float]:
    return sales / spend if spend else None


def all_metrics(impressions=0, clicks=0, spend=0.0, sales=0.0, orders=0, units=0) -> dict:
    """Bundle raw counts + derived rates for one entity."""
    return {
        "impressions": impressions, "clicks": clicks, "spend": round(spend, 2),
        "sales": round(sales, 2), "orders": orders, "units": units,
        "ctr": ctr(clicks, impressions), "cpc": cpc(spend, clicks),
        "cvr": cvr(orders, clicks), "acos": acos(spend, sales), "roas": roas(sales, spend),
    }


def target_cpc_bid(clicks: float, sales: float, target_acos: float,
                   current_bid: Optional[float], max_cut: float, max_up: float,
                   floor: float, cap_acos: Optional[float] = None) -> Optional[float]:
    """First-principles optimal bid = the most you can pay per click and still hit
    the target ACoS:  max_cpc = target_acos * (sales / clicks).

    Independent of the current (possibly wrong) bid — unlike target_acos_bid which
    just scales it. Capped by break-even (cap_acos) so a bid never implies a
    money-losing ACoS, and clamped to [max_cut, max_up] of the current bid to keep
    each pass safe. Returns None when there's nothing to compute on.
    """
    if not clicks:
        return None
    rev_per_click = sales / clicks                 # 0 when no sales -> bid floors out
    bid = target_acos * rev_per_click
    if cap_acos:                                   # never exceed the break-even cpc
        bid = min(bid, cap_acos * rev_per_click)
    if current_bid:                                # clamp the swing vs today's bid
        bid = max(current_bid * max_cut, min(current_bid * max_up, bid))
    return max(round(bid, 2), floor)


def safe_bid_cut(bid: Optional[float], cpc: Optional[float], acos: Optional[float],
                 goal_acos: float, strategy: Optional[str],
                 floor: float = 0.15) -> Optional[float]:
    """Bid cut that can NEVER raise. Returns the new bid, or None (no cut needed /
    nothing to cut / cut wouldn't lower).

    Live bug this fixes: 'Dynamic bids - up and down' inflates CPC to ~2x the bid,
    so the CPC-based formula `cpc * goal/acos` can EXCEED the current bid — an
    over-goal target would get a bid RAISE. On up/down, cut from the BID instead;
    on down-only / fixed the CPC-based cut is the correct lever, hard-guarded to
    never exceed the current bid. `acos`/`goal_acos` just need the same unit
    (both fractions or both percents).
    """
    if not bid or bid <= 0:
        return None
    if not acos or acos <= goal_acos:
        return None
    ratio = goal_acos / acos
    if strategy and "up and down" in str(strategy).lower():
        new = bid * ratio
    else:
        new = cpc * ratio if cpc else bid * ratio
        new = min(new, bid)                    # hard never-raise guard
    new = max(round(new, 2), floor)
    if new >= bid:
        return None                            # floor met/crossed — nothing to cut
    return new


def target_acos_bid(current_bid: float, observed_acos: Optional[float], target: float,
                    max_cut: float, max_up: float, floor: float) -> float:
    """Scale a bid toward a target ACoS, capped per pass.

    new = bid * (target / observed_acos), clamped to [max_cut, max_up], floored.
    No sales (observed_acos None) -> treat as loser, cut by max_cut.
    """
    if current_bid is None:
        return floor
    if observed_acos is None or observed_acos <= 0:
        scale = max_cut
    else:
        scale = target / observed_acos
        scale = max(max_cut, min(max_up, scale))
    return max(round(current_bid * scale, 2), floor)
