"""Account-level PPC totals (ad spend + ad sales) straight from the bulk.

The Sales report / profit P&L features were removed; what survives here is the
pure-PPC account roll-up used for account ACoS by the Dashboard, Reports, Stores
overview and the cadence engine.
"""
from __future__ import annotations
from sqlalchemy.orm import Session
from sqlalchemy import func
from .. import models as md
from . import audit as audit_stage


def total_ad(db: Session, snapshot=None) -> dict:
    """Account-level PPC spend + sales straight from Entity=campaign rows — each
    campaign counted once (the ASIN rollup double-counts campaigns that advertise
    multiple ASINs). Use this for account KPIs (ad cost, ACoS)."""
    snap = snapshot or audit_stage.active_snapshot(db)
    q = db.query(func.sum(md.FactPerformance.spend), func.sum(md.FactPerformance.sales)) \
          .filter(md.FactPerformance.entity_type == "campaign")
    if snap:
        q = q.filter(md.FactPerformance.snapshot_date == snap)
    sp, sa = q.one()
    return {"spend": round(sp or 0.0, 2), "sales": round(sa or 0.0, 2)}
