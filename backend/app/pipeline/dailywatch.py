"""Daily Watch — day-over-day anomaly tracking for the Daily cadence.

Daily Watch keeps its OWN table (`DailyWatchFact`), deliberately separate from
the audit's `FactPerformance`: daily spike-tracking must never shift the 'latest
snapshot' that the Weekly/Mid/Full/Pause cadences read. Each upload parses an SP
bulk file's campaign rows and upserts them for the chosen day (one row per
campaign per day, replacing that day on re-upload), so days accumulate as an
independent time series. `compare()` diffs two days at the account + per-campaign
level and raises spike/anomaly flags (spend spike, ACoS spike, sales drop,
zero-order spend). `series()` returns the accumulated daily totals for the trend
chart. No structural changes are emitted — Daily Watch is watch-only.
"""
from __future__ import annotations
from datetime import date, datetime
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import models as md
from . import ingest as ingest_stage, clean as clean_stage

# anomaly thresholds (account + per-campaign)
SPEND_SPIKE_MULT = 1.5      # today spend > yesterday * this -> spike
SPEND_SPIKE_FLOOR = 20.0    # ...and absolute delta >= $ this (ignore noise)
ACOS_SPIKE_PP = 10.0        # ACoS up by >= this many points
SALES_DROP_MULT = 0.5       # today sales < yesterday * this (with spend holding)
ZERO_ORDER_SPEND = 25.0     # campaign spent >= $ this today, 0 orders


# ---- ingest one day (into Daily Watch's own table) --------------------------
def _i(v):
    try: return int(float(v or 0))
    except (TypeError, ValueError): return 0


def _f(v):
    try: return round(float(v or 0), 2)
    except (TypeError, ValueError): return 0.0


def ingest_day(db: Session, path: str, day: date) -> dict:
    """Parse a bulk file's campaign rows and store them as `day` in DailyWatchFact
    (replacing that day). Returns the day's account totals so the UI can confirm."""
    frames = ingest_stage.frames(path)
    camp = frames.get("campaign")
    if camp is None or not len(camp):
        raise ValueError("No campaign rows found in that file — Daily Watch needs the "
                         "Sponsored Products bulk export (with the Campaigns sheet).")

    rows, seen = [], set()
    for _, r in camp.iterrows():
        cid = r.get("campaign_id")
        if not cid or str(cid) in seen:
            continue
        seen.add(str(cid))
        rows.append(dict(date=day, campaign_id=str(cid),
            name=r.get("campaign_name") or r.get("campaign_name_info"),
            impressions=_i(r.get("impressions")), clicks=_i(r.get("clicks")),
            spend=_f(r.get("spend")), sales=_f(r.get("sales")),
            orders=_i(r.get("orders")), units=_i(r.get("units"))))
    if not rows:
        raise ValueError("That file had no usable campaign rows (missing Campaign IDs).")

    # replace the day (idempotent re-upload)
    db.query(md.DailyWatchFact).filter(md.DailyWatchFact.date == day).delete()
    db.bulk_insert_mappings(md.DailyWatchFact, rows)
    db.commit()
    return {"date": day.isoformat(), "campaigns": len(rows), "totals": _acct(db, day)}


# ---- account + per-campaign totals for one day ------------------------------
def _acct(db: Session, day: date) -> dict:
    row = db.query(
        func.sum(md.DailyWatchFact.spend), func.sum(md.DailyWatchFact.sales),
        func.sum(md.DailyWatchFact.clicks), func.sum(md.DailyWatchFact.impressions),
        func.sum(md.DailyWatchFact.orders),
    ).filter(md.DailyWatchFact.date == day).one()
    sp, sa, cl, im, od = (x or 0 for x in row)
    return _kpis(sp, sa, cl, im, od)


def _campaigns(db: Session, day: date) -> dict[str, dict]:
    """campaign_id -> {name, spend, sales, ...} for one day."""
    out = {}
    for r in db.query(md.DailyWatchFact).filter(md.DailyWatchFact.date == day).all():
        out[r.campaign_id] = {"campaign_id": r.campaign_id, "name": r.name or r.campaign_id,
                              **_kpis(r.spend, r.sales, r.clicks, r.impressions, r.orders)}
    return out


def _kpis(sp, sa, cl, im, od) -> dict:
    sp, sa, cl, im, od = float(sp), float(sa), float(cl), float(im), float(od)
    return {
        "spend": round(sp, 2), "sales": round(sa, 2), "clicks": int(cl),
        "impressions": int(im), "orders": int(od),
        "acos": round(sp / sa * 100, 2) if sa else None,        # %
        "roas": round(sa / sp, 2) if sp else None,              # x
        "cvr": round(od / cl * 100, 2) if cl else None,         # %  (orders/clicks)
        "ctr": round(cl / im * 100, 2) if im else None,         # %
        "cpc": round(sp / cl, 2) if cl else None,               # $
    }


# ---- available days ---------------------------------------------------------
def days(db: Session) -> list[str]:
    rows = db.query(md.DailyWatchFact.date).distinct() \
             .order_by(md.DailyWatchFact.date.desc()).all()
    return [r[0].isoformat() for r in rows if r[0]]


def delete_day(db: Session, day: date) -> int:
    """Remove all rows for `day` so the panel doesn't re-seed on remount."""
    n = db.query(md.DailyWatchFact).filter(md.DailyWatchFact.date == day).delete()
    db.commit()
    return n


def delete_all(db: Session) -> int:
    """Wipe every uploaded day (clears all Daily Watch data). Watch-only cadence —
    its uploads never fed the star schema, so nothing else to clear."""
    n = db.query(md.DailyWatchFact).delete()
    db.commit()
    return n


# ---- compare two days -------------------------------------------------------
def _delta(prev, cur):
    if prev is None or cur is None:
        return None
    return round(cur - prev, 2)


def _pct_change(prev, cur):
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def _has_day(db: Session, day: date) -> bool:
    return db.query(md.DailyWatchFact.id) \
             .filter(md.DailyWatchFact.date == day).first() is not None


def compare(db: Session, prev_day: date, cur_day: date, target_acos: float | None = None) -> dict:
    """Diff `prev_day` (Yesterday) vs `cur_day` (Today): account + per-campaign
    deltas and the anomaly flags. Both days must have an uploaded bulk file."""
    missing = [d.isoformat() for d in (prev_day, cur_day) if not _has_day(db, d)]
    if missing:
        avail = days(db)
        hint = f" Days you've uploaded: {', '.join(avail)}." if avail else \
               " You haven't uploaded any daily files yet."
        raise ValueError(f"No bulk data for {', '.join(missing)} — upload that day's file in the "
                         f"Yesterday / Today panel first.{hint}")
    a_prev, a_cur = _acct(db, prev_day), _acct(db, cur_day)
    target = (target_acos or 0) * 100 if target_acos and target_acos <= 2 else (target_acos or 0)

    account = {}
    for k in ("spend", "sales", "clicks", "impressions", "orders", "acos"):
        account[k] = {"prev": a_prev[k], "cur": a_cur[k],
                      "delta": _delta(a_prev[k], a_cur[k]),
                      "pct": _pct_change(a_prev[k], a_cur[k])}

    cp, cc = _campaigns(db, prev_day), _campaigns(db, cur_day)
    flags, rows = [], []
    for cid in set(cp) | set(cc):
        p, c = cp.get(cid), cc.get(cid)
        name = (c or p)["name"]
        ps, cs = (p["spend"] if p else 0.0), (c["spend"] if c else 0.0)
        psa, csa = (p["sales"] if p else 0.0), (c["sales"] if c else 0.0)
        pac, cac = (p["acos"] if p else None), (c["acos"] if c else None)
        rows.append({
            "campaign_id": cid, "name": name,
            "spend_prev": ps, "spend_cur": cs, "spend_delta": round(cs - ps, 2),
            "spend_pct": _pct_change(ps, cs),
            "sales_prev": psa, "sales_cur": csa, "sales_delta": round(csa - psa, 2),
            "acos_prev": pac, "acos_cur": cac,
            "orders_cur": c["orders"] if c else 0,
        })
        # spend spike (pct is None when prev spend was 0 -> brand-new spend)
        if cs >= ps * SPEND_SPIKE_MULT and (cs - ps) >= SPEND_SPIKE_FLOOR:
            pcs = _pct_change(ps, cs)
            tail = f"(+{pcs:.0f}%)" if pcs is not None else "(new spend)"
            flags.append(_flag("spend_spike", "high", name,
                f"Ad spend spiked ${ps:.0f} → ${cs:.0f} {tail}", cid))
        # ACoS spike (and over goal)
        if pac is not None and cac is not None and (cac - pac) >= ACOS_SPIKE_PP and (not target or cac > target):
            flags.append(_flag("acos_spike", "high", name,
                f"ACoS jumped {pac:.0f}% → {cac:.0f}% (+{cac - pac:.0f}pp)", cid))
        # sales drop while spend holds
        if psa > 0 and csa < psa * SALES_DROP_MULT and cs >= ps * 0.8:
            flags.append(_flag("sales_drop", "med", name,
                f"Sales fell ${psa:.0f} → ${csa:.0f} with spend holding", cid))
        # zero-order spend today
        if c and c["spend"] >= ZERO_ORDER_SPEND and c["orders"] == 0:
            flags.append(_flag("zero_order_spend", "med", name,
                f"Spent ${c['spend']:.0f} today with 0 orders", cid))

    rows.sort(key=lambda r: abs(r["spend_delta"]), reverse=True)
    sev = {"high": 0, "med": 1, "low": 2}
    flags.sort(key=lambda f: sev.get(f["severity"], 9))
    return {"prev_day": prev_day.isoformat(), "cur_day": cur_day.isoformat(),
            "account": account, "campaigns": rows, "flags": flags}


def _flag(kind, severity, campaign, message, cid):
    return {"kind": kind, "severity": severity, "campaign": campaign,
            "message": message, "campaign_id": cid}


# ---- campaign monitor (isolated watchlist, auto-cleared on alignment) --------
def _target_pct(target_acos: float | None) -> float:
    """Normalize the goal to a % number (0.25 -> 25.0), matching _kpis acos."""
    t = target_acos if target_acos is not None else 0.25
    return t * 100 if t <= 2 else t


def _latest_day(db: Session) -> date | None:
    d = days(db)
    return datetime.strptime(d[0], "%Y-%m-%d").date() if d else None


def monitor(db: Session, campaign_id: str, name: str | None = None) -> dict:
    """Add a campaign to the watchlist (idempotent while an active row exists).
    Captures the latest uploaded day's ACoS as the starting point."""
    cid = str(campaign_id or "").strip()
    if not cid:
        raise ValueError("No campaign id given.")
    existing = db.query(md.WatchedCampaign) \
                 .filter(md.WatchedCampaign.campaign_id == cid,
                         md.WatchedCampaign.status == "active").first()
    if existing:
        return {"added": False, "campaign_id": cid}
    latest = _latest_day(db)
    row = db.query(md.DailyWatchFact) \
            .filter(md.DailyWatchFact.date == latest,
                    md.DailyWatchFact.campaign_id == cid).first() if latest else None
    k = _kpis(row.spend, row.sales, row.clicks, row.impressions, row.orders) if row else None
    db.add(md.WatchedCampaign(campaign_id=cid, name=name or (row.name if row else cid),
                              status="active", added_date=latest,
                              added_acos=k["acos"] if k else None))
    db.commit()
    return {"added": True, "campaign_id": cid}


def unmonitor(db: Session, campaign_id: str) -> int:
    """Remove a campaign's ACTIVE watch (cleared history rows stay)."""
    n = db.query(md.WatchedCampaign) \
          .filter(md.WatchedCampaign.campaign_id == str(campaign_id),
                  md.WatchedCampaign.status == "active").delete()
    db.commit()
    return n


def monitors(db: Session, target_acos: float | None = None) -> dict:
    """The isolated area: active watches with latest-day metrics + aligned flag,
    plus recently cleared history (newest first, capped)."""
    target = _target_pct(target_acos)
    latest = _latest_day(db)
    cur = _campaigns(db, latest) if latest else {}
    active, cleared = [], []
    q = db.query(md.WatchedCampaign).order_by(md.WatchedCampaign.id.desc()).all()
    for w in q:
        base = {"campaign_id": w.campaign_id, "name": w.name or w.campaign_id,
                "added_date": w.added_date.isoformat() if w.added_date else None,
                "added_acos": w.added_acos}
        if w.status == "active":
            k = cur.get(w.campaign_id)
            days_watched = None
            if w.added_date and latest:
                days_watched = (latest - w.added_date).days
            active.append({**base, **({k2: k[k2] for k2 in ("spend", "sales", "orders", "acos")}
                                      if k else {"spend": None, "sales": None, "orders": None, "acos": None}),
                           "days_watched": days_watched,
                           "aligned": bool(k and k["acos"] is not None and k["acos"] <= target)})
        elif len(cleared) < 15:
            cleared.append({**base, "cleared_date": w.cleared_date.isoformat() if w.cleared_date else None,
                            "cleared_acos": w.cleared_acos})
    return {"active": active, "cleared": cleared,
            "target_acos": round(target, 2), "latest_day": latest.isoformat() if latest else None}


def evaluate_monitors(db: Session, day: date, target_acos: float | None = None) -> list[dict]:
    """After a day's upload: clear every active watch whose ACoS that day is
    at/under the goal (converted sales required — no-sales days never clear).
    Returns the cleared watches."""
    target = _target_pct(target_acos)
    cur = _campaigns(db, day)
    out = []
    for w in db.query(md.WatchedCampaign).filter(md.WatchedCampaign.status == "active").all():
        k = cur.get(w.campaign_id)
        if not k or k["acos"] is None or k["acos"] > target:
            continue
        w.status = "cleared"
        w.cleared_date = day
        w.cleared_acos = k["acos"]
        out.append({"campaign_id": w.campaign_id, "name": w.name or w.campaign_id,
                    "acos": k["acos"], "target": round(target, 2)})
    if out:
        db.commit()
    return out


# ---- trend series -----------------------------------------------------------
def anomalies(db: Session) -> dict:
    """ML anomaly scan over the accumulated day series: robust (median/MAD)
    z-scores per account KPI, direction-aware severity. Catches slow drifts and
    multi-day outliers the pairwise Yesterday/Today compare can't see. Needs ≥5
    uploaded days; below that returns an empty list with the day count."""
    from . import ml
    ds = series(db)["days"]
    return {"days": len(ds),
            "anomalies": ml.robust_anomalies(ds, ["spend", "sales", "orders", "clicks", "acos"])
                         if len(ds) >= 5 else []}


def series(db: Session, start: date | None = None, end: date | None = None) -> dict:
    """Accumulated daily account totals (for the trend chart), oldest→newest."""
    q = db.query(md.DailyWatchFact.date).distinct()
    if start:
        q = q.filter(md.DailyWatchFact.date >= start)
    if end:
        q = q.filter(md.DailyWatchFact.date <= end)
    ds = sorted(r[0] for r in q.all() if r[0])
    return {"days": [{"date": d.isoformat(), **_acct(db, d)} for d in ds]}
