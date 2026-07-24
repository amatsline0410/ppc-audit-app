"""Pause/Scale Audit — Sponsored Products, last-60-day cut/scale decisions from one
SP Search Term Report (single panel). Unlike Weekly/Mid/Full (which harvest customer
search terms), Pause/Scale acts on the **existing entities** the report carries:

  pause targets   — keyword / product target with 30+ clicks and 0 orders → state=paused
  pause campaigns — campaigns with $50+ spend and 0 orders                → state=paused
  scale winners   — keyword / product target with 10+ orders at/under goal → bid UP (scale)

Reuses the shared Weekly engine (`aggregate_targets` / `parse_str_sheet` / `summarize`)
on its **own** single-snapshot table (`PauseScaleTermFact`). Thresholds come from the
`pause_scale` cadence preset (min_clicks=30, min_spend=50, scale_min_orders=10).
"""
from __future__ import annotations
import io
import pandas as pd
from sqlalchemy.orm import Session
from ..config import Thresholds
from .. import models as md
from .. import metrics as M
from . import weekly as wk, bulkfmt, bid_optimizer as bo


def ingest(db: Session, path: str, load_star: bool = True) -> dict:
    """Parse + store the report as the Pause/Scale snapshot (replaces any prior one)."""
    rows = wk.parse_str_sheet(path)
    db.query(md.PauseScaleTermFact).delete()
    db.bulk_insert_mappings(md.PauseScaleTermFact, rows)
    db.commit()
    if load_star:                   # the suite upload loads the star schema itself
        wk.load_star_schema(db, path)
    return summary(db)


def _facts(db: Session):
    return db.query(md.PauseScaleTermFact).all()


def has_data(db: Session) -> bool:
    return db.query(md.PauseScaleTermFact.id).first() is not None


def delete_all(db: Session) -> dict:
    """Wipe all Pause/Scale data: the search-term snapshot AND the star schema its
    uploads fed, so the optimizer sub-panels clear too."""
    n = db.query(md.PauseScaleTermFact).delete()
    db.commit()
    return {"terms": n, "star_rows": wk.clear_star_schema(db)}


def summary(db: Session) -> dict:
    return wk.summarize(_facts(db))


def plan(db: Session, t: Thresholds) -> dict:
    rows = _facts(db)
    effective = wk._effective(db)                 # BidLedger overlay (already-exported changes)
    pauses, scales = [], []
    for a in wk.aggregate_targets(rows):
        eff = effective.get(str(a["id"]), {})
        st = (eff.get("state") or a["state"] or "enabled").strip().lower()
        if st not in ("enabled", "ok", ""):
            continue                              # already paused / archived
        cur = eff.get("bid") if eff.get("bid") is not None else a["current_bid"]
        m = M.all_metrics(a["impressions"], a["clicks"], a["spend"], a["sales"], a["orders"], 0)
        acos = m["acos"]
        base = {"id": a["id"], "kind": a["kind"], "campaign_id": a["campaign_id"],
                "ad_group_id": a["ad_group_id"], "label": a["label"],
                "match_type": a["match_type"], "expression": a["expression"],
                "clicks": a["clicks"], "orders": a["orders"], "spend": a["spend"],
                "sales": a["sales"], "acos": round(acos, 4) if acos is not None else None}
        # pause: enough clicks to judge, zero conversions
        if a["clicks"] >= t.min_clicks and a["orders"] == 0:
            pauses.append({**base, "action": "pause",
                           "reason": f"{a['clicks']} clicks · ${a['spend']:.0f} spend · 0 orders — pause"})
        # scale: proven winner at/under goal -> bid up
        elif (a["orders"] >= t.scale_min_orders and acos is not None
              and acos <= t.target_acos and cur):
            new = M.target_cpc_bid(a["clicks"], a["sales"], t.target_acos, cur,
                                   t.max_bid_cut, t.max_bid_up, t.bid_floor)
            # hard cap the scale-up — never push a bid over the allowed range,
            # and never scale an already-overbid target even higher
            if new is not None:
                new = bo.clamp_caps(new, "keyword_bid")
            if new and new > cur + 0.01:
                scales.append({**base, "action": "scale", "current_bid": round(cur, 2),
                               "suggested_bid": new, "delta": round(new - cur, 2),
                               "reason": f"{a['orders']} orders @ {acos:.0%} ACoS (≤ goal {t.target_acos:.0%}) — scale up"})

    # campaign pauses: $50+ spend, 0 orders across the report
    camp: dict[str, dict] = {}
    for r in rows:
        c = camp.get(r.campaign_id)
        if c is None:
            c = camp[r.campaign_id] = {"campaign_id": r.campaign_id, "name": r.campaign_name or r.campaign_id,
                                       "spend": 0.0, "sales": 0.0, "clicks": 0, "orders": 0}
        c["spend"] = round(c["spend"] + (r.spend or 0), 2)
        c["sales"] = round(c["sales"] + (r.sales or 0), 2)
        c["clicks"] += r.clicks or 0
        c["orders"] += r.orders or 0
    campaign_pauses = [{**c, "action": "pause_campaign",
                        "reason": f"${c['spend']:.0f} spend · {c['clicks']} clicks · 0 orders — pause campaign"}
                       for c in camp.values() if c["spend"] >= t.min_spend and c["orders"] == 0]

    pauses.sort(key=lambda r: r["spend"], reverse=True)
    scales.sort(key=lambda r: r["orders"], reverse=True)
    campaign_pauses.sort(key=lambda r: r["spend"], reverse=True)
    out = {"summary": summary(db), "scales": scales, "pauses": pauses,
           "campaign_pauses": campaign_pauses, "target_acos": round(t.target_acos, 4)}
    # ML overlay (advisory): Bayesian pause/scale confidence — P(true CVR really
    # is below break-even) for pauses, P(above) for scales. A 0-order target with
    # 8 clicks is NOT the same evidence as one with 80; the confidence says so.
    from . import ml
    ml.enrich_plan(out, wk.aggregate_targets(rows), t.target_acos)
    return out


# ---- bulk file --------------------------------------------------------------
BULK_COLS = wk.BULK_COLS


def _blank() -> dict:
    return {c: None for c in BULK_COLS}


def to_bulk(scale_rows: list[dict], pause_rows: list[dict],
            campaign_rows: list[dict]) -> bytes:
    """Chosen scale (bid up) + pause (target) + pause (campaign) rows → one Amazon SP
    bulk sheet. Dedup so Amazon never rejects on Duplicate Id."""
    rows, seen = [], set()

    def add_target(r, *, paused):
        tid = bulkfmt.idstr(r.get("id"))
        if not tid:
            return
        is_kw = r.get("kind") == "keyword"
        sig = ("u", "kw" if is_kw else "pt", tid)
        if sig in seen:
            return
        seen.add(sig)
        row = _blank()
        row.update({"Product": "Sponsored Products",
                    "Entity": "Keyword" if is_kw else "Product Targeting",
                    "Operation": "update",
                    "Campaign ID": bulkfmt.idstr(r.get("campaign_id")),
                    "Ad Group ID": bulkfmt.idstr(r.get("ad_group_id"))})
        if is_kw:
            row["Keyword ID"] = tid
        else:
            row["Product Targeting ID"] = tid
        if paused:
            row["State"] = "paused"
        else:
            row.update({"Bid": r.get("suggested_bid"), "State": "enabled"})
        rows.append(row)

    for r in scale_rows or []:
        add_target(r, paused=False)
    for r in pause_rows or []:
        add_target(r, paused=True)
    for c in campaign_rows or []:
        cid = bulkfmt.idstr(c.get("campaign_id"))
        sig = ("u", "campaign", cid)
        if not cid or sig in seen:
            continue
        seen.add(sig)
        row = _blank()
        row.update({"Product": "Sponsored Products", "Entity": "Campaign",
                    "Operation": "update", "Campaign ID": cid, "State": "paused"})
        rows.append(row)

    df = pd.DataFrame(rows, columns=BULK_COLS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Sponsored Products Campaigns")
    return buf.getvalue()
