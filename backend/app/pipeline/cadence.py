"""Audit cadence presets — "Best Audit Cadence Strategy".

Each Audit Type bundles: a lookback label, the action level, threshold overrides
that re-tune the flag engine for that cadence, and the SOP effort checklist. The
selected month/year is a *label* for the run — the audit still reads the latest
uploaded bulk snapshot; the preset decides how aggressively it flags.
"""
from __future__ import annotations
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..config import Thresholds, default_thresholds
from .. import models as md

# key -> preset. `thresholds` overrides feed Thresholds.merged(**overrides).
# `focus` = the flag types each cadence's OWN table shows (its unique feature),
# so every cadence renders a distinct, bulk-derived view ([] = all flags).
PRESETS: dict[str, dict] = {
    "daily": {
        "label": "Daily Watch", "range": "Today + Yesterday", "action_level": "Anomaly alert only",
        "thresholds": {},
        "focus": [], "feature": "watch",   # not flag-based — day-over-day spike tracker
        "table_title": "Daily Watch — spike & anomaly tracker",
        "sop": ["Scan for anomalies (spend/sales/ACoS spikes)",
                "Note any campaign that went out-of-budget",
                "No structural changes — watch only"],
    },
    "weekly": {
        "label": "Weekly Optimization", "range": "Last 7 days", "action_level": "Bid tweaks, harvest",
        "thresholds": {"min_clicks": 10},
        "focus": ["HIGH_ACOS", "OVERBID"], "feature": "weekly",
        "table_title": "Weekly — bid tweaks + search-term harvest (SP Search Term Report)",
        "sop": ["Harvest search terms with 1+ orders",
                "Lower bids on 10+ clicks, 0 orders",
                "Flag budget-capped campaigns"],
    },
    "mid_month": {
        "label": "Mid-Month Check", "range": "Last 14 days", "action_level": "Bid adjust, add negatives",
        "thresholds": {"min_spend": 10.0, "low_ctr": 0.001},
        "focus": ["WASTED_SPEND", "HIGH_ACOS", "LOW_CTR"], "feature": "mid_month",
        "table_title": "Mid-Month — bid adjustments + heavy negative targeting (SP Search Term Report)",
        "sop": ["Bid adjust ±15% based on ACoS vs target",
                "Add negatives for $10+ spend, 0 orders",
                "Check CTR < 0.1% targets"],
    },
    "full_month": {
        "label": "Full Month Audit", "range": "Last 30 days", "action_level": "Full optimization",
        "thresholds": {},
        "focus": [], "feature": "full_month",   # own dedicated full-optimization panel
        "table_title": "Full Month — full optimization (bids + harvest + negatives, SP Search Term Report)",
        "sop": ["Full bid optimization pass",
                "Harvest + promote to exact match",
                "Budget reallocation across campaigns"],
    },
    "pause_scale": {
        "label": "Pause/Scale Audit", "range": "Last 60 days", "action_level": "Pause, kill, scale",
        "thresholds": {"min_clicks": 30, "min_spend": 50.0, "scale_min_orders": 10},
        "focus": ["BLEEDING", "WASTED_SPEND", "SCALE_WINNER"], "feature": "pause_scale",
        "table_title": "Pause / Scale — pause dead targets & campaigns, scale winners (SP Search Term Report)",
        "sop": ["Pause targets: 30+ clicks, 0 orders",
                "Pause campaigns: $50+ spend, 0 orders",
                "Scale winners: ACoS < target, 10+ orders"],
    },
}

ORDER = ["daily", "weekly", "mid_month", "full_month", "pause_scale"]
DEFAULT_TYPE = "full_month"


def list_presets() -> list[dict]:
    return [{"key": k, **{x: PRESETS[k][x] for x in
             ("label", "range", "action_level", "sop", "focus", "feature", "table_title")}}
            for k in ORDER]


def thresholds_for(audit_type: str | None, target_acos: float | None = None) -> Thresholds:
    """Default thresholds tuned by the audit-type preset (+ optional goal ACoS)."""
    p = PRESETS.get(audit_type or DEFAULT_TYPE, PRESETS[DEFAULT_TYPE])
    overrides = dict(p["thresholds"])
    if target_acos is not None:
        overrides["target_acos"] = target_acos
    return default_thresholds.merged(**overrides)


def sop_for(audit_type: str | None) -> list[str]:
    return list(PRESETS.get(audit_type or DEFAULT_TYPE, PRESETS[DEFAULT_TYPE])["sop"])


# ---- saved runs (persist the monthly rhythm) --------------------------------
def _run_dict(db: Session, run: "md.CadenceRun") -> dict:
    tasks = db.query(md.CadenceTask).filter(md.CadenceTask.run_id == run.id) \
              .order_by(md.CadenceTask.id).all()
    p = PRESETS.get(run.audit_type, {})
    done = sum(1 for t in tasks if t.done)
    return {
        "id": run.id, "year": run.year, "month": run.month, "audit_type": run.audit_type,
        "label": p.get("label", run.audit_type), "range": p.get("range"),
        "action_level": p.get("action_level"),
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "flags": run.flags, "ad_spend": run.ad_spend, "ad_sales": run.ad_sales,
        "acos": round(run.ad_spend / run.ad_sales, 4) if run.ad_sales else None,
        "note": run.note, "done": done, "total": len(tasks),
        "tasks": [{"id": t.id, "text": t.text, "done": t.done} for t in tasks],
    }


def get_or_create_run(db: Session, year: int, month: int, audit_type: str,
                      target_acos: float | None = None, refresh: bool = False) -> dict:
    """Open (or first-time create) the run for (year, month, audit_type). On create,
    capture the headline numbers + seed the SOP checklist from the preset.
    `refresh=True` (an explicit re-audit, e.g. the tile's audit button) recomputes
    the captured numbers at the CURRENT Goal ACoS instead of returning the stored
    snapshot — otherwise changing the goal would keep showing the old flag count."""
    from . import sales as sales_stage, audit as audit_stage
    run = db.query(md.CadenceRun).filter_by(year=year, month=month, audit_type=audit_type).first()
    # No bulk data loaded (never uploaded, or flushed) -> nothing to capture. Drop
    # any stale run so the UI doesn't show numbers from deleted data.
    if audit_stage.active_snapshot(db) is None:
        if run is not None:
            db.delete(run); db.commit()
        return None
    if run is not None and refresh:
        th = thresholds_for(audit_type, target_acos)
        run.flags = len(audit_stage.audit(db, th))
        ad = sales_stage.total_ad(db)
        run.ad_spend, run.ad_sales = ad["spend"], ad["sales"]
        db.commit()
    if run is None:
        th = thresholds_for(audit_type, target_acos)
        flags = len(audit_stage.audit(db, th))
        ad = sales_stage.total_ad(db)
        run = md.CadenceRun(year=year, month=month, audit_type=audit_type,
                            flags=flags, ad_spend=ad["spend"], ad_sales=ad["sales"])
        try:
            db.add(run); db.flush()
            for text in sop_for(audit_type):
                db.add(md.CadenceTask(run_id=run.id, text=text, done=False))
            db.commit()
        except IntegrityError:
            # two concurrent opens raced past the SELECT (the flag audit above is
            # slow) and both tried to insert the same (year, month, audit_type) —
            # UNIQUE keeps one; drop ours and return the winner's row.
            db.rollback()
            run = db.query(md.CadenceRun).filter_by(
                year=year, month=month, audit_type=audit_type).first()
            if run is None:   # not the duplicate-row race — surface it
                raise
    return _run_dict(db, run)


def list_runs(db: Session) -> list[dict]:
    runs = db.query(md.CadenceRun).order_by(
        md.CadenceRun.year.desc(), md.CadenceRun.month.desc(), md.CadenceRun.id.desc()).all()
    return [_run_dict(db, r) for r in runs]


def toggle_task(db: Session, task_id: int, done: bool) -> bool:
    t = db.get(md.CadenceTask, task_id)
    if not t:
        return False
    t.done = done
    db.commit()
    return True


def delete_run(db: Session, run_id: int) -> bool:
    r = db.get(md.CadenceRun, run_id)
    if not r:
        return False
    db.delete(r)
    db.commit()
    return True


# ---- per-cadence upload meta -------------------------------------------------
# Last uploaded file per cadence (name / rows / date), shown in the cadence panel
# header like the Product Benchmark upload pattern. Stored on the BASE project's
# meta (_meta.json) keyed by cadence, so it survives restarts and clears with the
# cadence's Clear action. `database` import is local: database never imports this
# module (cycle-safe the other way is not guaranteed).
def _upload_meta_key(db: Session, feature: str | None = None) -> str:
    """`feature` namespaces a non-cadence upload (e.g. Product Ads) so it never
    collides with the cadence's own upload meta in the same audit + cadence."""
    cad = db.info.get("cadence")
    return f"upload_meta:{feature}:{cad}" if feature else f"upload_meta:{cad}"


def set_upload_meta(db: Session, filename: str, rows: int,
                    feature: str | None = None) -> dict:
    from datetime import date
    from .. import database as dbmod
    meta = {"file": filename, "rows": rows, "uploaded": date.today().isoformat()}
    dbmod.set_project_extra(db.info.get("store"), db.info.get("project"),
                            _upload_meta_key(db, feature), meta)
    return meta


def get_upload_meta(db: Session, feature: str | None = None) -> dict | None:
    from .. import database as dbmod
    return dbmod.get_project_extra(db.info.get("store"), db.info.get("project"),
                                   _upload_meta_key(db, feature))


def clear_upload_meta(db: Session, feature: str | None = None) -> None:
    from .. import database as dbmod
    dbmod.set_project_extra(db.info.get("store"), db.info.get("project"),
                            _upload_meta_key(db, feature), None)
