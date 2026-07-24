"""Change Log / Audit Trail. Every action written to a bulk export is recorded
here with old -> new value + reason, so the operator and the weekly report can
see exactly what changed. One row per entity action.
"""
from __future__ import annotations
import io
from datetime import datetime
import pandas as pd
from sqlalchemy.orm import Session
from .. import models as md

# human label per export source — used in the client report message
SOURCE_LABEL = {
    "audit_bulk": "PPC Audit", "bid_optimizer": "Bid Optimization",
    "placement": "Placement Adjustment", "harvest": "Search-Term Harvest",
    "strategy": "Strategy", "automate": "Automation",
}
# human label per action verb
ACTION_LABEL = {
    "pause+negate": "Paused + added negative", "promote": "Promoted to exact keyword",
    "negate": "Added negative keyword", "placement": "Adjusted placement bid",
    "reduce": "Reduced bid", "raise": "Raised bid", "monitor": "Flagged to monitor",
    "pause": "Paused", "lower": "Lowered bid",
    "cut": "Cut bid (wasted spend)", "scale_winner": "Scaled up winner",
}


def log(db: Session, entries: list[dict], source: str) -> int:
    for e in entries:
        db.add(md.ChangeLog(source=source, **e))
    db.commit()
    return len(entries)


def clear(db: Session, source: str | None = None) -> int:
    """Wipe the audit trail (optionally one source's entries only). Irreversible —
    the log is the record of what was exported to Amazon."""
    q = db.query(md.ChangeLog)
    if source:
        q = q.filter(md.ChangeLog.source == source)
    n = q.delete()
    db.commit()
    return n


def recent(db: Session, limit: int = 500, source: str | None = None) -> list[dict]:
    q = db.query(md.ChangeLog).order_by(md.ChangeLog.ts.desc())
    if source:
        q = q.filter(md.ChangeLog.source == source)
    return [{"id": c.id, "ts": c.ts.isoformat() if c.ts else None, "asin": c.asin,
             "campaign_id": c.campaign_id, "entity_type": c.entity_type,
             "label": c.label, "field": c.field, "old_value": c.old_value,
             "new_value": c.new_value, "action": c.action, "reason": c.reason,
             "source": c.source, "status": c.status} for c in q.limit(limit).all()]


# ---- entry builders: turn each engine's exported rows into log entries --------
def from_flags(db: Session, flags: list[dict]) -> list[dict]:
    """Audit-center bulk: bid updates + pauses + negates."""
    targets = {t.target_id: t for t in db.query(md.DimTarget).all()}
    out = []
    for f in flags:
        t = targets.get(f.get("entity_id"))
        if not t:
            continue
        flag, stage = f.get("flag"), f.get("stage")
        if flag == "WASTED_SPEND" or (flag == "HIGH_ACOS" and stage == "PAUSE"):
            field, new, action = "state", "paused", "pause+negate"
            old = t.state
        elif f.get("new_bid") is not None:
            field, old, new, action = "bid", t.bid, f["new_bid"], (stage or flag).lower()
        else:
            continue
        out.append(dict(asin=f.get("asin"), entity_type=t.target_type, entity_id=t.target_id,
                        label=t.keyword_text or t.expression, field=field,
                        old_value=str(old), new_value=str(new), action=action,
                        reason=f.get("suggested_action")))
    return out


def from_bidopt(rows: list[dict]) -> list[dict]:
    return [dict(asin=r.get("asin"), campaign_id=r.get("campaign_id"),
                 entity_type=r.get("target_type"), entity_id=r.get("target_id"),
                 label=r.get("label"), field="bid",
                 old_value=str(r.get("current_bid")), new_value=str(r.get("suggested_bid")),
                 action=r.get("direction"), reason=r.get("reason")) for r in rows]


def from_placement(rows: list[dict]) -> list[dict]:
    return [dict(campaign_id=r.get("campaign_id"), entity_type="placement",
                 label=r.get("placement"), field="percentage",
                 old_value=str(r.get("current_pct")), new_value=str(r.get("suggested_pct")),
                 action="placement", reason=r.get("reason")) for r in rows]


def from_weekly(bid_rows: list[dict], harvest_rows: list[dict]) -> list[dict]:
    """Weekly Optimization bulk: keyword/PT bid updates + search-term harvest."""
    out = []
    for b in bid_rows or []:
        out.append(dict(campaign_id=b.get("campaign_id"), entity_type=b.get("kind"),
                        entity_id=b.get("id"), label=b.get("label"), field="bid",
                        old_value=str(b.get("current_bid")), new_value=str(b.get("suggested_bid")),
                        action=b.get("direction"), reason=b.get("reason")))
    for h in harvest_rows or []:
        promote = h.get("action") == "promote"
        out.append(dict(campaign_id=h.get("campaign_id"),
                        entity_type=("keyword" if h.get("as") == "keyword" else "product_target")
                        if promote else "negative",
                        label=h.get("search_term"), field="create",
                        old_value=None, new_value="exact" if promote else "negative exact",
                        action="promote" if promote else "negate", reason=h.get("reason")))
    return out


def from_pausescale(scale_rows, pause_rows, campaign_rows) -> list[dict]:
    """Pause/Scale bulk: scale (bid up) + pause target + pause campaign."""
    out = []
    for r in scale_rows or []:
        out.append(dict(campaign_id=r.get("campaign_id"), entity_type=r.get("kind"),
                        entity_id=r.get("id"), label=r.get("label"), field="bid",
                        old_value=str(r.get("current_bid")), new_value=str(r.get("suggested_bid")),
                        action="scale", reason=r.get("reason")))
    for r in pause_rows or []:
        out.append(dict(campaign_id=r.get("campaign_id"), entity_type=r.get("kind"),
                        entity_id=r.get("id"), label=r.get("label"), field="state",
                        old_value="enabled", new_value="paused", action="pause",
                        reason=r.get("reason")))
    for c in campaign_rows or []:
        out.append(dict(campaign_id=c.get("campaign_id"), entity_type="campaign",
                        label=c.get("name"), field="state", old_value="enabled",
                        new_value="paused", action="pause", reason=c.get("reason")))
    return out


def from_harvest(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        promote = r.get("action") == "promote"
        out.append(dict(campaign_id=r.get("campaign_id"),
                        entity_type="keyword" if promote else "negative",
                        label=r.get("search_term"), field="create",
                        old_value=None, new_value="exact" if promote else "negative exact",
                        action="promote" if promote else "negate", reason=r.get("reason")))
    return out


# ---- downloadable client report ----------------------------------------------
def export_xlsx(db: Session, limit: int = 2000, source: str | None = None) -> bytes:
    """Change Log as an .xlsx the operator can attach to a client report.

    Sheet 1 'Summary' = action counts; sheet 2 'Change Log' = the full trail.
    """
    rows = recent(db, limit=limit, source=source)
    log_cols = [("ts", "When"), ("source", "Source"), ("action", "Action"),
                ("asin", "ASIN"), ("label", "Entity"), ("entity_type", "Type"),
                ("field", "Field"), ("old_value", "Old"), ("new_value", "New"),
                ("reason", "Reason")]
    log_df = pd.DataFrame([{lbl: (r.get(k) or "") for k, lbl in log_cols} for r in rows])

    counts: dict[str, int] = {}
    for r in rows:
        a = r.get("action") or "other"
        counts[a] = counts.get(a, 0) + 1
    summary_rows = [{"Action": ACTION_LABEL.get(a, a), "Changes": n}
                    for a, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    summary_rows.insert(0, {"Action": "TOTAL CHANGES", "Changes": len(rows)})
    summary_df = pd.DataFrame(summary_rows)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        summary_df.to_excel(w, index=False, sheet_name="Summary")
        log_df.to_excel(w, index=False, sheet_name="Change Log")
    return buf.getvalue()


def report_text(db: Session, limit: int = 2000, source: str | None = None) -> str:
    """A copy-paste client message summarizing what changed and why.

    Plain text, grouped by engine source -> action, newest period. The operator
    pastes this into an email / chat to the client.
    """
    rows = recent(db, limit=limit, source=source)
    today = datetime.now().strftime("%b %d, %Y")
    if not rows:
        return f"PPC Optimization Report — {today}\n\nNo changes recorded this period."

    counts: dict[str, int] = {}
    for r in rows:
        a = r.get("action") or "other"
        counts[a] = counts.get(a, 0) + 1

    lines = [f"PPC Optimization Report — {today}",
             f"{len(rows)} optimization{'s' if len(rows) != 1 else ''} applied this period.", ""]
    lines.append("Summary of changes:")
    for a, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"  • {ACTION_LABEL.get(a, a)}: {n}")
    lines.append("")

    # group detail by source
    by_src: dict[str, list[dict]] = {}
    for r in rows:
        by_src.setdefault(r.get("source") or "other", []).append(r)
    lines.append("What we did:")
    for src, items in by_src.items():
        lines.append(f"\n{SOURCE_LABEL.get(src, src)} ({len(items)}):")
        for r in items[:25]:
            label = r.get("label") or r.get("entity_type") or "—"
            act = ACTION_LABEL.get(r.get("action"), r.get("action") or "")
            chg = ""
            if r.get("old_value") and r.get("new_value"):
                chg = f" {r['old_value']} → {r['new_value']}"
            elif r.get("new_value"):
                chg = f" → {r['new_value']}"
            lines.append(f"  - {act}: {label}{chg}")
        if len(items) > 25:
            lines.append(f"  …and {len(items) - 25} more")
    lines.append("\nEvery change above is implemented in the Amazon bulk files we uploaded.")
    return "\n".join(lines)
