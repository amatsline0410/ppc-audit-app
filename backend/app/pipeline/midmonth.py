"""Mid-Month Check — Sponsored Products, driven from the bulk's SP Search Term
Report, like Weekly but **single-panel** (one snapshot) and focused on two actions:

  bid adjustments   — recompute every keyword / product target's bid (target-CPC,
                      guardrailed), updated by ID.
  negative targeting (HEAVY) — the mid-month emphasis. Two tiers:
      * wasted   — spent with 0 orders (≥ $ floor)  → Negative Exact / Negative PT
      * bleeders — DID convert but ACoS ≥ 2× goal   → optional extra negatives

Reuses the Weekly engine (`weekly.compute_bid_tweaks` / `compute_harvest` /
`to_bulk` / `parse_str_sheet`) on its **own** single-snapshot table
(`MidMonthTermFact`), so a Mid-Month bulk only ever drives the Mid-Month cadence.
"""
from __future__ import annotations
from sqlalchemy.orm import Session
from ..config import Thresholds
from .. import models as md
from . import weekly as wk

# converting-but-unprofitable threshold: ACoS ≥ this × goal → a bleeder to negate
BLEEDER_ACOS_MULT = 2.0


_TABLE = "mid_month_term_fact"


def ingest(db: Session, path: str, load_star: bool = True) -> dict:
    """Parse + store as the current snapshot, keeping the prior one as 'previous' so
    the panel can compare this upload against the last."""
    rows = wk.parse_str_sheet(path)
    wk.ensure_period_col(db, _TABLE)
    wk.shift_and_insert(db, md.MidMonthTermFact, rows)
    if load_star:                   # the suite upload loads the star schema itself
        wk.load_star_schema(db, path)
    return summary(db)


def _facts(db: Session):
    """Current snapshot rows (period 0)."""
    wk.ensure_period_col(db, _TABLE)
    return wk.period_rows(db, md.MidMonthTermFact, 0)


def has_data(db: Session) -> bool:
    return db.query(md.MidMonthTermFact.id).first() is not None


def delete_all(db: Session) -> dict:
    """Wipe all Mid-Month data: the search-term snapshots (current + previous) AND
    the star schema its uploads fed, so the optimizer sub-panels clear too."""
    n = db.query(md.MidMonthTermFact).delete()
    db.commit()
    return {"terms": n, "star_rows": wk.clear_star_schema(db)}


def has_previous(db: Session) -> bool:
    wk.ensure_period_col(db, _TABLE)
    return wk.has_previous(db, md.MidMonthTermFact)


def summary(db: Session) -> dict:
    return wk.summarize(_facts(db))


def plan(db: Session, t: Thresholds) -> dict:
    rows = _facts(db)
    h = wk.compute_harvest(rows, t, min_orders=1, bleeder_acos_mult=BLEEDER_ACOS_MULT)
    out = {"summary": summary(db), "has_previous": has_previous(db),
           "bid_tweaks": wk.compute_bid_tweaks(rows, t, wk._effective(db)),
           "negates": h["negates"], "bleeders": h["bleeders"],
           "target_acos": round(t.target_acos, 4)}
    # stamp each row with its ad group's product break-even ACoS (benchmark
    # upload wins, else catalog listing + real Transactions-ledger fees)
    from . import harvest as hv
    ag_be = hv.ag_break_even_map(db)
    for r in out["bid_tweaks"] + out["negates"] + out["bleeders"]:
        r["break_even"] = ag_be.get(str(r.get("ad_group_id")))
    # ML overlay (advisory): EB-smoothed CVR + negation confidence per row
    from . import ml
    ml.enrich_plan(out, wk.aggregate_targets(rows), t.target_acos)
    return out


def compare(db: Session, target_acos: float | None = None) -> dict:
    """Compare the previous upload (period 1) vs the current one (period 0)."""
    wk.ensure_period_col(db, _TABLE)
    prev = wk.period_rows(db, md.MidMonthTermFact, 1)
    cur = wk.period_rows(db, md.MidMonthTermFact, 0)
    if not prev:
        raise ValueError("No previous upload to compare against — upload a second Mid-Month bulk first.")
    return {"prev_label": "Previous", "cur_label": "Current",
            **wk.compare_rows(prev, cur, target_acos)}


def to_bulk(bid_rows: list[dict], negate_rows: list[dict]) -> bytes:
    """Chosen bid adjustments + negatives → one Amazon SP bulk sheet (reuses Weekly's
    builder; every negate row carries action='negate')."""
    return wk.to_bulk(bid_rows, negate_rows)
