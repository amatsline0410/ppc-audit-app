"""Full Month Audit — Sponsored Products, the **full optimization** pass driven
from one SP Search Term Report (single panel, like Mid-Month). It's the superset
of the focused cadences — every action at once:

  bid adjustments   — recompute every keyword / product target's bid (by ID).
  harvest · promote — winners (orders ≤ goal ACoS) → Exact keyword / product target.
  negative · wasted — spent with 0 orders → Negative Exact / Negative Product Targeting.
  negative · bleeders — converted but ACoS ≥ 2× goal (head spend, 2+ orders).

Reuses the shared Weekly engine on its **own** single-snapshot table
(`FullMonthTermFact`), so a Full Month bulk only ever drives the Full Month cadence.
Uses the untuned (30-day) full-month thresholds for the broadest coverage.
"""
from __future__ import annotations
from sqlalchemy.orm import Session
from ..config import Thresholds
from .. import models as md
from . import weekly as wk

BLEEDER_ACOS_MULT = 2.0


_TABLE = "full_month_term_fact"


def ingest(db: Session, path: str, load_star: bool = True) -> dict:
    """Parse + store as the current snapshot, keeping the prior one as 'previous' so
    the panel can compare this upload against the last."""
    rows = wk.parse_str_sheet(path)
    wk.ensure_period_col(db, _TABLE)
    wk.shift_and_insert(db, md.FullMonthTermFact, rows)
    # also load the star schema so Placement / BidOptimizer / AsinTree / Harvest /
    # Ngram populate for the Full Month cadence (tolerant if the bulk lacks those rows)
    if load_star:                   # the suite upload loads the star schema itself
        wk.load_star_schema(db, path)
    return summary(db)


def _facts(db: Session):
    """Current snapshot rows (period 0)."""
    wk.ensure_period_col(db, _TABLE)
    return wk.period_rows(db, md.FullMonthTermFact, 0)


def has_data(db: Session) -> bool:
    return db.query(md.FullMonthTermFact.id).first() is not None


def delete_all(db: Session) -> dict:
    """Wipe all Full Month data: the search-term snapshots (current + previous) AND
    the star schema its uploads fed. NB: Full Month lives in the BASE audit db, so
    this also clears the audit's bulk-derived data (dashboard / flags / optimizer
    panels) — Monitoring, Product Ads, keywords and the benchmark are untouched."""
    n = db.query(md.FullMonthTermFact).delete()
    db.commit()
    return {"terms": n, "star_rows": wk.clear_star_schema(db)}


def has_previous(db: Session) -> bool:
    wk.ensure_period_col(db, _TABLE)
    return wk.has_previous(db, md.FullMonthTermFact)


def summary(db: Session) -> dict:
    return wk.summarize(_facts(db))


def plan(db: Session, t: Thresholds) -> dict:
    rows = _facts(db)
    h = wk.compute_harvest(rows, t, min_orders=1, bleeder_acos_mult=BLEEDER_ACOS_MULT)
    out = {"summary": summary(db), "has_previous": has_previous(db),
           "bid_tweaks": wk.compute_bid_tweaks(rows, t, wk._effective(db)),
           "promotes": h["promotes"], "negates": h["negates"], "bleeders": h["bleeders"],
           "target_acos": round(t.target_acos, 4)}
    # ML overlay (advisory): EB-smoothed CVR + confidences on every row, plus the
    # conversion-propensity model — trained on THIS cadence's own aggregated
    # search terms, surfacing early-promote candidates (high P(convert), still
    # under the harvest order threshold). Quality-gated inside train_term_model.
    from . import ml
    ml.enrich_plan(out, wk.aggregate_targets(rows), t.target_acos)
    if out.get("ml") is not None:
        terms = _aggregate_terms(rows)
        model = ml.train_term_model(terms)
        if model:
            early = [r for r in terms if (r.get("orders") or 0) == 0
                     and (r.get("clicks") or 0) >= 3]
            cands = [c for c in ml.score_terms(model, early)
                     if c["p_convert"] >= 1.5 * model["base_rate"]][:15]
            out["ml"]["model"] = {"auc": model["auc"], "n": model["n"],
                                  "base_rate": model["base_rate"],
                                  "candidates": [{k: c.get(k) for k in
                                                  ("search_term", "campaign_name", "ad_group_name",
                                                   "clicks", "impressions", "spend", "match_type",
                                                   "p_convert")} for c in cands]}
    return out


def _aggregate_terms(rows) -> list[dict]:
    """Aggregate raw STR fact rows per (ad group, search term) — the training set
    for the conversion-propensity model (mirrors compute_harvest's grouping)."""
    agg: dict[tuple, dict] = {}
    for r in rows:
        st = (r.search_term or "").strip()
        if not st or st == "*":
            continue
        key = (r.ad_group_id, st.lower())
        a = agg.get(key)
        if a is None:
            a = agg[key] = dict(search_term=st, campaign_name=r.campaign_name,
                                ad_group_name=r.ad_group_name, match_type=r.match_type,
                                impressions=0, clicks=0, spend=0.0, sales=0.0, orders=0)
        a["impressions"] += r.impressions or 0
        a["clicks"] += r.clicks or 0
        a["spend"] = round(a["spend"] + (r.spend or 0), 2)
        a["sales"] = round(a["sales"] + (r.sales or 0), 2)
        a["orders"] += r.orders or 0
    return list(agg.values())


def compare(db: Session, target_acos: float | None = None) -> dict:
    """Compare the previous upload (period 1) vs the current one (period 0)."""
    wk.ensure_period_col(db, _TABLE)
    prev = wk.period_rows(db, md.FullMonthTermFact, 1)
    cur = wk.period_rows(db, md.FullMonthTermFact, 0)
    if not prev:
        raise ValueError("No previous upload to compare against — upload a second Full Month bulk first.")
    return {"prev_label": "Previous", "cur_label": "Current",
            **wk.compare_rows(prev, cur, target_acos)}


def to_bulk(bid_rows: list[dict], harvest_rows: list[dict]) -> bytes:
    """Chosen bid adjustments + harvest (promotes + negatives + bleeders) → one
    Amazon SP bulk sheet (reuses Weekly's builder)."""
    return wk.to_bulk(bid_rows, harvest_rows)
