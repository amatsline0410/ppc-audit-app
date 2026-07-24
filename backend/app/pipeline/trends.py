"""Period-over-period trends from snapshot history.

Each upload stamps fact rows with snapshot_date. With >=2 snapshots we diff the
two most recent: account totals + per-campaign movers (what's degrading or
accelerating). Needs no extra data — just more than one upload.
"""
from __future__ import annotations
from sqlalchemy.orm import Session
from sqlalchemy import func
from .. import models as md
from .. import metrics as M


def list_snapshots(db: Session) -> list:
    rows = db.query(md.FactPerformance.snapshot_date).distinct().all()
    return sorted({r[0] for r in rows if r[0] is not None})


def _campaign_metrics(db: Session, snap) -> dict[str, dict]:
    """campaign_id -> summed metrics for one snapshot."""
    q = (db.query(md.FactPerformance.entity_id,
                  func.sum(md.FactPerformance.impressions), func.sum(md.FactPerformance.clicks),
                  func.sum(md.FactPerformance.spend), func.sum(md.FactPerformance.sales),
                  func.sum(md.FactPerformance.orders), func.sum(md.FactPerformance.units))
         .filter(md.FactPerformance.entity_type == "campaign",
                 md.FactPerformance.snapshot_date == snap)
         .group_by(md.FactPerformance.entity_id))
    out = {}
    for eid, im, cl, sp, sa, od, un in q.all():
        out[eid] = M.all_metrics(im or 0, cl or 0, sp or 0, sa or 0, od or 0, un or 0)
    return out


def _totals(cmap: dict[str, dict]) -> dict:
    sp = sum(m["spend"] for m in cmap.values())
    sa = sum(m["sales"] for m in cmap.values())
    od = sum(m["orders"] for m in cmap.values())
    cl = sum(m["clicks"] for m in cmap.values())
    return {"spend": round(sp, 2), "sales": round(sa, 2), "orders": od,
            "clicks": cl, "acos": round(sp / sa, 4) if sa else None}


def _delta(cur: float | None, prev: float | None):
    if cur is None or prev is None:
        return None
    return round(cur - prev, 4)


def compare(db: Session, top: int = 15) -> dict:
    snaps = list_snapshots(db)
    iso = [s.isoformat() for s in snaps]
    if len(snaps) < 2:
        return {"snapshots": iso, "have_history": False}

    prev_s, cur_s = snaps[-2], snaps[-1]
    cur, prev = _campaign_metrics(db, cur_s), _campaign_metrics(db, prev_s)
    names = {c.campaign_id: c.name for c in db.query(md.DimCampaign).all()}

    ct, pt = _totals(cur), _totals(prev)
    totals = {"current": ct, "previous": pt, "delta": {
        "spend": _delta(ct["spend"], pt["spend"]), "sales": _delta(ct["sales"], pt["sales"]),
        "orders": _delta(ct["orders"], pt["orders"]), "acos": _delta(ct["acos"], pt["acos"])}}

    movers = []
    for cid in set(cur) | set(prev):
        c = cur.get(cid, M.all_metrics()); p = prev.get(cid, M.all_metrics())
        movers.append({
            "campaign_id": cid, "name": names.get(cid),
            "spend_cur": c["spend"], "spend_prev": p["spend"],
            "spend_delta": round(c["spend"] - p["spend"], 2),
            "sales_cur": c["sales"], "sales_prev": p["sales"],
            "orders_delta": c["orders"] - p["orders"],
            "acos_cur": c["acos"], "acos_prev": p["acos"],
            "acos_delta": _delta(c["acos"], p["acos"])})
    movers.sort(key=lambda x: abs(x["spend_delta"]), reverse=True)

    return {"snapshots": iso, "have_history": True,
            "current": cur_s.isoformat(), "previous": prev_s.isoformat(),
            "totals": totals, "movers": movers[:top]}
