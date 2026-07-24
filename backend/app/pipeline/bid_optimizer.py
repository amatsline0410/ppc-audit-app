"""Bid + placement adjustment engine with hard guardrails.

Pure, deterministic, no I/O. Given a list of targets (keyword bids, ad-group
default bids, placement adjustments) it recommends a new value that pulls ACoS
toward goal — but only ever inside strict guardrails:

  1. data threshold   — skip thin targets (not enough clicks/purchases/spend)
  2. compute target   — current * (target_acos / actual_acos)
  3. hard caps        — clamp into an absolute allowed range per target type
  4. step limiter     — never move more than a fixed amount per cycle
  5. round            — bids to cents, placement adjustments to whole percent

The guardrail primitives (`meets_threshold`, `clamp_caps`, `limit_step`,
`normalize_placement`) are reused by the live `bidopt`/`placement` engines so
every bid-changing feature shares one tunable rulebook: `CONFIG`.
"""
from __future__ import annotations
from typing import Optional, TypedDict

# ----------------------------------------------------------------------------
# One config dict for every cap/threshold/step. Tune here, nowhere else.
# ----------------------------------------------------------------------------
CONFIG: dict = {
    # rule 1 — minimum data before we trust the ACoS signal
    "thresholds": {"min_clicks": 20, "min_purchases": 3, "min_spend": 5.00},
    # rule 3 — absolute allowed range, clamped after computing the target
    "caps": {
        "default_bid": (0.30, 3.00),       # $
        "keyword_bid": (0.20, 5.00),       # $
        "placement_adj": {                 # % adjustment, per placement
            "top_of_search": (0.0, 150.0),
            "product_pages": (0.0, 150.0),
            "rest_of_search": (0.0, 200.0),
        },
    },
    # rule 4 — max change allowed in a single cycle
    "max_step": {"default_bid": 0.15, "keyword_bid": 0.20, "placement_adj": 25.0},
    # rule 6 — overbid reset: a bid above the hard-cap max, or several times the
    # observed CPC, is not a meaningful anchor. Cutting it by max_step per pass
    # would take years, so overbid targets bypass the step limiter and reset
    # straight to the computed (hard-capped) target in one pass.
    "overbid": {"cpc_mult": 3.0, "min_gap": 1.00},
}

# raw Amazon placement labels -> the canonical keys used in CONFIG["caps"]
_PLACEMENT_ALIASES: dict[str, str] = {
    "top_of_search": "top_of_search", "placement top": "top_of_search",
    "top of search": "top_of_search", "placementtop": "top_of_search",
    "product_pages": "product_pages", "placement product page": "product_pages",
    "product pages": "product_pages", "product page": "product_pages",
    "rest_of_search": "rest_of_search", "placement rest of search": "rest_of_search",
    "rest of search": "rest_of_search",
}


class TargetRow(TypedDict, total=False):
    """One input target. `placement` only required when target_type='placement_adj'."""
    target_type: str            # default_bid | keyword_bid | placement_adj
    placement: str              # top_of_search | rest_of_search | product_pages
    current: float              # current bid $ or adjustment %
    clicks: int
    purchases: int
    spend: float
    actual_acos: float          # observed ACoS (%)
    target_acos: float          # goal ACoS (%)


class ResultRow(TypedDict):
    """One output recommendation."""
    target_type: str
    current: float
    recommended: float
    delta: float
    reason: str


# ----------------------------------------------------------------------------
# Guardrail primitives (shared with the live bidopt / placement engines)
# ----------------------------------------------------------------------------
def meets_threshold(clicks: int, purchases: int, spend: float) -> bool:
    """True when a target has enough data (rule 1) to act on its ACoS signal."""
    th = CONFIG["thresholds"]
    return (clicks >= th["min_clicks"]
            and purchases >= th["min_purchases"]
            and spend >= th["min_spend"])


def normalize_placement(placement: Optional[str]) -> Optional[str]:
    """Map a raw/Amazon placement label to a canonical CONFIG key, or None."""
    if not placement:
        return None
    return _PLACEMENT_ALIASES.get(str(placement).strip().lower())


def caps_for(target_type: str, placement: Optional[str] = None) -> tuple[float, float]:
    """Return the (min, max) hard-cap range for a target type / placement."""
    caps = CONFIG["caps"]
    if target_type == "placement_adj":
        key = normalize_placement(placement)
        # unknown placement -> use the widest (rest_of_search) range, never crash
        return caps["placement_adj"].get(key, caps["placement_adj"]["rest_of_search"])
    return caps[target_type]


def clamp_caps(value: float, target_type: str, placement: Optional[str] = None) -> float:
    """Clamp a value into its absolute allowed range (rule 3)."""
    lo, hi = caps_for(target_type, placement)
    return max(lo, min(hi, value))


def is_overbid(current: Optional[float], target_type: str,
               cpc: Optional[float] = None, placement: Optional[str] = None) -> bool:
    """True when the current bid is grossly inflated (rule 6): above the hard-cap
    max for its type, or `cpc_mult`x the observed CPC (with an absolute `min_gap`
    so low bids over cheap clicks don't trip it). Overbid targets skip the
    per-pass step limiter — the current bid is noise, not an anchor."""
    if not current or current <= 0:
        return False
    _, hi = caps_for(target_type, placement)
    if current > hi:
        return True
    ob = CONFIG["overbid"]
    return bool(cpc) and current >= cpc * ob["cpc_mult"] and current - cpc >= ob["min_gap"]


def limit_step(current: float, target: float, target_type: str) -> float:
    """Clamp `target` so |target - current| <= the per-cycle max step (rule 4)."""
    step = CONFIG["max_step"][target_type]
    if target - current > step:
        return current + step
    if current - target > step:
        return current - step
    return target


def round_value(value: float, target_type: str) -> float:
    """Round per rule 5 — bids to 2 decimals, placement adjustments to whole %."""
    return round(value) if target_type == "placement_adj" else round(value, 2)


# ----------------------------------------------------------------------------
# Compute (no printing) — one row, then the batch
# ----------------------------------------------------------------------------
def _skip(row: TargetRow, reason: str) -> ResultRow:
    """Build a no-change result row for a skipped target."""
    cur = float(row.get("current", 0.0))
    return {"target_type": row["target_type"], "current": cur,
            "recommended": cur, "delta": 0.0, "reason": reason}


def optimize_row(row: TargetRow) -> ResultRow:
    """Apply the 5 guardrail rules, in order, to a single target.

    Returns a recommendation with current, recommended, delta and a plain-English
    reason (or a 'skip - ...' reason when no change is made).
    """
    tt = row["target_type"]
    current = float(row["current"])

    # rule 1 — data threshold
    if not meets_threshold(int(row.get("clicks", 0)),
                           int(row.get("purchases", 0)),
                           float(row.get("spend", 0.0))):
        return _skip(row, "skip - low data")

    # rule 2 — compute target value (no ACoS signal -> skip)
    actual = float(row.get("actual_acos", 0.0))
    target_acos = float(row.get("target_acos", 0.0))
    if actual == 0:
        return _skip(row, "skip - no ACOS signal")
    raw_target = current * (target_acos / actual)

    # rule 3 — hard caps
    placement = row.get("placement")
    capped = clamp_caps(raw_target, tt, placement)

    # rule 4 — step limiter (most conservative: never exceed max step) — unless
    # the current bid is overbid (rule 6): then it is noise, reset straight to
    # the capped target instead of crawling down max_step per cycle.
    clicks = int(row.get("clicks", 0))
    cpc = (float(row.get("spend", 0.0)) / clicks) if clicks else None
    overbid = is_overbid(current, tt, cpc, placement)
    stepped = capped if overbid else limit_step(current, capped, tt)

    # rule 5 — round
    recommended = round_value(stepped, tt)
    delta = round_value(recommended - current, tt)

    # plain-English reason, noting which guardrail bound the move
    unit = "%" if tt == "placement_adj" else "$"
    if delta == 0:
        reason = f"already optimal — ACoS {actual:g}% vs target {target_acos:g}%"
    else:
        direction = "raise" if delta > 0 else "lower"
        note = ""
        if overbid:
            note = " (overbid — reset to cap)"
        elif abs(capped - raw_target) > 1e-9:
            note = " (hit hard cap)"
        elif abs(stepped - capped) > 1e-9:
            note = " (step-limited)"
        reason = (f"ACoS {actual:g}% vs target {target_acos:g}% -> {direction} "
                  f"{unit}{abs(delta):g}{note}")
    return {"target_type": tt, "current": current, "recommended": recommended,
            "delta": delta, "reason": reason}


def optimize(rows: list[TargetRow]) -> list[ResultRow]:
    """Run `optimize_row` over a batch of targets. Pure — safe to unit-test."""
    return [optimize_row(r) for r in rows]


# ----------------------------------------------------------------------------
# Presentation (kept separate from compute)
# ----------------------------------------------------------------------------
def render_table(results: list[ResultRow]) -> str:
    """Format results as a fixed-width table string: current -> recommended -> delta -> reason."""
    header = f"{'target_type':<14}{'current':>10}{'recommended':>14}{'delta':>10}  reason"
    lines = [header, "-" * len(header)]
    for r in results:
        lines.append(f"{r['target_type']:<14}{r['current']:>10.2f}"
                     f"{r['recommended']:>14.2f}{r['delta']:>+10.2f}  {r['reason']}")
    return "\n".join(lines)


def print_table(results: list[ResultRow]) -> None:
    """Print the rendered results table to stdout."""
    print(render_table(results))


if __name__ == "__main__":
    samples: list[TargetRow] = [
        # keyword_bid: ACoS double the target -> bid down, but step-limited to 0.20
        {"target_type": "keyword_bid", "current": 1.20, "clicks": 60, "purchases": 4,
         "spend": 30.0, "actual_acos": 50.0, "target_acos": 25.0},
        # default_bid: profitable (ACoS under target) -> bid up, hard-capped/stepped
        {"target_type": "default_bid", "current": 0.80, "clicks": 40, "purchases": 6,
         "spend": 12.0, "actual_acos": 18.0, "target_acos": 25.0},
        # placement_adj (top_of_search): too few purchases -> skip, low data
        {"target_type": "placement_adj", "placement": "top_of_search", "current": 40.0,
         "clicks": 25, "purchases": 1, "spend": 9.0, "actual_acos": 60.0, "target_acos": 25.0},
    ]
    print_table(optimize(samples))
