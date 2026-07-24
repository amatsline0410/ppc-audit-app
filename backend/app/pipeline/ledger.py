"""Effective-bid ledger — the overlay that keeps consecutive exports consistent.

Problem: the user exports bulk #1 (bid changes), then generates bulk #2 from the
SAME uploaded snapshot. #2 is computed from stale bids, so it double-applies or
overwrites #1's changes. Fix: every module that emits a bulk with bid/state
changes also inserts BidLedger rows; every subsequent bid computation reads the
*effective* value = latest ledger row if one exists, else the snapshot value.

The ledger lives in the BASE project db (account-level truth, shared across
cadences) — per-cadence routers reach it through `base_session(db)`.

Lifecycle per row: exported (applied=False) -> the user uploads the file to
Amazon and clicks "Mark applied" (applied=True), or a NEW bulk upload shows the
exported value landed (auto-reconcile). "Discard" deletes the rows instead.
Unapplied rows older than STALE_DAYS are surfaced as a warning.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .. import models as md

STALE_DAYS = 7


def base_session(db: Session) -> Session:
    """Open a session on the BASE project db for a (possibly per-cadence) session.
    Caller closes. If `db` already is the base session, still returns a fresh one —
    same file, so reads/writes are consistent."""
    from ..database import get_session
    return get_session(db.info.get("store", ""), db.info.get("project", ""))


def record(db: Session, entries: list[dict], source: str, run_id: int | None = None) -> int:
    """Insert one ledger row per exported bid/state change.
    entries: [{target_id, campaign_id?, bid?, state?}] — target_id required."""
    n = 0
    for e in entries:
        tid = str(e.get("target_id") or "").strip()
        if not tid:
            continue
        db.add(md.BidLedger(target_id=tid, campaign_id=e.get("campaign_id"),
                            exported_bid=e.get("bid"), exported_state=e.get("state"),
                            run_id=run_id, source=source))
        n += 1
    db.commit()
    return n


def record_from(db: Session, source: str, bids: list[dict] | None = None,
                pauses: list[dict] | None = None) -> int:
    """Convenience for the cadence/bidopt routers: record exported bid rows
    ({id|target_id, campaign_id, suggested_bid}) and pause rows into the BASE db,
    whatever session (per-cadence or base) the router holds."""
    entries = []
    for r in bids or []:
        entries.append({"target_id": r.get("id") or r.get("target_id"),
                        "campaign_id": r.get("campaign_id"),
                        "bid": r.get("suggested_bid"), "state": "enabled"})
    for r in pauses or []:
        entries.append({"target_id": r.get("id") or r.get("target_id"),
                        "campaign_id": r.get("campaign_id"), "state": "paused"})
    base = base_session(db)
    try:
        return record(base, entries, source)
    finally:
        base.close()


def effective_map(db: Session) -> dict[str, dict]:
    """target_id -> {'bid': latest exported bid, 'state': latest exported state}.
    Latest ledger row wins (applied or not — an exported change is the operator's
    intent either way). Missing targets simply aren't in the map (use snapshot)."""
    out: dict[str, dict] = {}
    for r in db.query(md.BidLedger).order_by(md.BidLedger.exported_at.asc(),
                                             md.BidLedger.id.asc()).all():
        e = out.setdefault(r.target_id, {"bid": None, "state": None})
        if r.exported_bid is not None:
            e["bid"] = r.exported_bid
        if r.exported_state is not None:
            e["state"] = r.exported_state
    return out


def effective_bid(db: Session, target_id: str, snapshot_bid: float | None) -> float | None:
    e = effective_map(db).get(str(target_id))
    return e["bid"] if e and e["bid"] is not None else snapshot_bid


def pending(db: Session) -> dict:
    """Unapplied exports, plus which of them have gone stale (> STALE_DAYS old)."""
    rows = db.query(md.BidLedger).filter(md.BidLedger.applied.is_(False)) \
             .order_by(md.BidLedger.exported_at.desc()).all()
    cutoff = datetime.utcnow() - timedelta(days=STALE_DAYS)
    return {
        "count": len(rows),
        "stale": sum(1 for r in rows if r.exported_at and r.exported_at < cutoff),
        "by_source": _counts(rows),
        "rows": [{"id": r.id, "target_id": r.target_id, "campaign_id": r.campaign_id,
                  "bid": r.exported_bid, "state": r.exported_state, "source": r.source,
                  "run_id": r.run_id,
                  "exported_at": r.exported_at.isoformat() if r.exported_at else None,
                  "stale": bool(r.exported_at and r.exported_at < cutoff)} for r in rows[:500]],
    }


def _counts(rows) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r.source] = out.get(r.source, 0) + 1
    return out


def mark_applied(db: Session, source: str | None = None, run_id: int | None = None,
                 ids: list[int] | None = None) -> int:
    """Flip exports to applied (after the user uploads the file to Amazon)."""
    q = db.query(md.BidLedger).filter(md.BidLedger.applied.is_(False))
    if source:
        q = q.filter(md.BidLedger.source == source)
    if run_id is not None:
        q = q.filter(md.BidLedger.run_id == run_id)
    if ids:
        q = q.filter(md.BidLedger.id.in_(ids))
    n = q.update({md.BidLedger.applied: True, md.BidLedger.applied_at: datetime.utcnow()},
                 synchronize_session=False)
    db.commit()
    return n


def discard(db: Session, source: str | None = None, run_id: int | None = None,
            ids: list[int] | None = None) -> int:
    """Delete unapplied exports (the user threw the file away)."""
    q = db.query(md.BidLedger).filter(md.BidLedger.applied.is_(False))
    if source:
        q = q.filter(md.BidLedger.source == source)
    if run_id is not None:
        q = q.filter(md.BidLedger.run_id == run_id)
    if ids:
        q = q.filter(md.BidLedger.id.in_(ids))
    n = q.delete(synchronize_session=False)
    db.commit()
    return n


def reconcile(db: Session, snapshot: dict[str, dict]) -> dict:
    """On a new bulk upload: ledger rows whose exported value now matches the
    snapshot auto-flip applied; unapplied mismatches are returned as drift.
    snapshot: target_id -> {'bid': float|None, 'state': str|None}."""
    applied, drift = 0, []
    for r in db.query(md.BidLedger).filter(md.BidLedger.applied.is_(False)).all():
        snap = snapshot.get(r.target_id)
        if snap is None:
            continue                                    # target not in this upload
        bid_ok = r.exported_bid is None or (
            snap.get("bid") is not None and abs(snap["bid"] - r.exported_bid) < 0.005)
        state_ok = r.exported_state is None or (
            (snap.get("state") or "").strip().lower() == r.exported_state.strip().lower())
        if bid_ok and state_ok:
            r.applied = True
            r.applied_at = datetime.utcnow()
            applied += 1
        else:
            drift.append({"target_id": r.target_id, "source": r.source,
                          "exported_bid": r.exported_bid, "snapshot_bid": snap.get("bid"),
                          "exported_state": r.exported_state, "snapshot_state": snap.get("state")})
    db.commit()
    return {"auto_applied": applied, "drift": drift}
