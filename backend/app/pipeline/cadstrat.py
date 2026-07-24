"""Per-cadence Strategy Advisor.

Weekly / Mid-Month / Full-Month / Pause-Scale each drive their OWN strategies,
computed from that cadence's own side-table data (WeeklyTermFact / MidMonthTermFact
/ FullMonthTermFact / PauseScaleTermFact) via the cadence's plan pipeline — NOT the
star-schema FactPerformance the generic `strategy.analyze` reads. Output matches the
generic advisor's shape ({recommendations, playbook, counts}) so the Strategy panel
renders it identically, and each named strategy can emit its cadence's Amazon bulk.
"""
from __future__ import annotations
from sqlalchemy.orm import Session
from ..config import Thresholds
from . import weekly as wk, midmonth as mm, fullmonth as fm, pausescale as ps
from . import changelog as changelog_stage

CADENCE_TYPES = ("weekly", "mid_month", "full_month", "pause_scale")

# short reference text per strategy for the playbook cards
_PB = {
    "Search Term Harvesting": ("Winning search terms (orders ≤ goal ACoS)", "Promote to Exact keyword / product target"),
    "Negative Keyword Sculpting": ("Wasted terms ($-spend, 0 orders)", "Negate as Exact negative"),
    "Bleeder Negation": ("Converting terms ≥ 2× goal ACoS", "Negate the head $-bleeders"),
    "Bid Optimization": ("Targets with enough data off target CPC", "Raise / cut bids toward goal"),
    "Exact Match Scaling": ("Proven winners at/under goal", "Bid up existing targets"),
    "Pause Wasted Targets": ("30+ clicks, 0 orders", "Pause the target"),
    "Pause Wasted Campaigns": ("$-spend, 0 orders across the report", "Pause the whole campaign"),
}


# ---- row -> recommendation mappers (one per cadence row kind) ----------------
def _harvest_action(r) -> str:
    as_ = "product target" if r.get("as") == "product_target" else "keyword"
    return f"Promote → Exact {as_}" if r.get("action") == "promote" else f"Negate → Exact negative {as_}"


def _rec_harvest(name, tool, prio, r):
    return {"strategy": name, "campaign": r.get("campaign_name") or r.get("campaign_id"),
            "asin": None, "criteria": f"'{r['search_term']}' · {r['reason']}",
            "action": _harvest_action(r), "tool": tool, "priority": prio,
            "spend": r.get("spend", 0), "stage": "", "bulk": True}


def _rec_bid(name, tool, prio, r):
    return {"strategy": name, "campaign": r.get("label"), "asin": None,
            "criteria": r["reason"],
            "action": f"{r['direction'].title()} bid ${r['current_bid']:.2f}→${r['suggested_bid']:.2f}",
            "tool": tool, "priority": prio, "spend": r.get("spend", 0), "stage": "", "bulk": True}


def _rec_scale(name, tool, prio, r):
    return {"strategy": name, "campaign": r.get("label"), "asin": None,
            "criteria": r["reason"],
            "action": f"Scale bid ${r['current_bid']:.2f}→${r['suggested_bid']:.2f}",
            "tool": tool, "priority": prio, "spend": r.get("spend", 0), "stage": "Scale", "bulk": True}


def _rec_pause(name, tool, prio, r):
    return {"strategy": name, "campaign": r.get("label"), "asin": None,
            "criteria": r["reason"], "action": "Pause target", "tool": tool,
            "priority": prio, "spend": r.get("spend", 0), "stage": "", "bulk": True}


def _rec_camppause(name, tool, prio, r):
    return {"strategy": name, "campaign": r.get("name") or r.get("campaign_id"), "asin": None,
            "criteria": r["reason"], "action": "Pause whole campaign", "tool": tool,
            "priority": prio, "spend": r.get("spend", 0), "stage": "", "bulk": True}


# per-cadence groups: (strategy name, plan key, priority, tool, row->rec mapper)
GROUPS: dict[str, list[tuple]] = {
    "weekly": [
        ("Search Term Harvesting", "promotes", "high", "harvest", _rec_harvest),
        ("Negative Keyword Sculpting", "negates", "high", "harvest", _rec_harvest),
        ("Bid Optimization", "bid_tweaks", "med", "bidopt", _rec_bid),
    ],
    "mid_month": [
        ("Negative Keyword Sculpting", "negates", "high", "harvest", _rec_harvest),
        ("Bleeder Negation", "bleeders", "high", "harvest", _rec_harvest),
        ("Bid Optimization", "bid_tweaks", "med", "bidopt", _rec_bid),
    ],
    "full_month": [
        ("Search Term Harvesting", "promotes", "high", "harvest", _rec_harvest),
        ("Negative Keyword Sculpting", "negates", "high", "harvest", _rec_harvest),
        ("Bleeder Negation", "bleeders", "med", "harvest", _rec_harvest),
        ("Bid Optimization", "bid_tweaks", "med", "bidopt", _rec_bid),
    ],
    "pause_scale": [
        ("Exact Match Scaling", "scales", "high", "bidopt", _rec_scale),
        ("Pause Wasted Targets", "pauses", "high", "manual", _rec_pause),
        ("Pause Wasted Campaigns", "campaign_pauses", "high", "manual", _rec_camppause),
    ],
}

_PRIO = {"high": 0, "med": 1, "low": 2}


def _plan(db: Session, audit_type: str, t: Thresholds) -> dict:
    return {"weekly": wk.plan, "mid_month": mm.plan,
            "full_month": fm.plan, "pause_scale": ps.plan}[audit_type](db, t)


def analyze(db: Session, audit_type: str, t: Thresholds) -> dict:
    """Recommendations + playbook for one cadence, from its own data."""
    plan = _plan(db, audit_type, t)
    recs, playbook = [], []
    for name, key, prio, tool, mapper in GROUPS[audit_type]:
        rows = plan.get(key) or []
        for r in rows:
            recs.append(mapper(name, tool, prio, r))
        criteria, action = _PB.get(name, ("", ""))
        playbook.append({"strategy": name, "criteria": criteria, "action": action,
                         "recommendation": "", "tool": tool,
                         "status": "active" if rows else "available",
                         "bulk": True, "count": len(rows)})
    recs.sort(key=lambda r: (_PRIO.get(r["priority"], 3), -(r.get("spend") or 0)))
    counts = {k: sum(1 for r in recs if r["priority"] == k) for k in ("high", "med", "low")}
    # the methodology map's four-state account read — the cadence db carries the
    # bulk's star schema, so the per-campaign classifier works per cadence too
    from . import strategy as strategy_stage
    return {"has_portfolio": False, "counts": counts, "cadence": audit_type,
            "states": strategy_stage.account_states(db, t),
            "recommendations": recs, "playbook": playbook}


def build_bulk(db: Session, audit_type: str, t: Thresholds, name: str):
    """Amazon bulk (+ changelog entries) for one cadence strategy → (bytes, entries, n)."""
    plan = _plan(db, audit_type, t)
    group = next((g for g in GROUPS[audit_type] if g[0] == name), None)
    if group is None:
        raise ValueError(f"'{name}' is not a strategy for the {audit_type} cadence")
    key = group[1]
    rows = plan.get(key) or []
    if audit_type == "pause_scale":
        scale = rows if key == "scales" else []
        pause = rows if key == "pauses" else []
        camp = rows if key == "campaign_pauses" else []
        data = ps.to_bulk(scale, pause, camp)
        entries = changelog_stage.from_pausescale(scale, pause, camp)
    else:
        bid_rows, harvest_rows = (rows, []) if key == "bid_tweaks" else ([], rows)
        data = wk.to_bulk(bid_rows, harvest_rows)
        entries = changelog_stage.from_weekly(bid_rows, harvest_rows)
    return data, entries, len(rows)
