"""Weekly Optimization — Sponsored Products, driven straight from the bulk's
**SP Search Term Report** sheet.

The Weekly cadence focuses on two actions, both keyed off the *real entity IDs*
the Search Term Report carries (Campaign / Ad Group / Keyword / Product Targeting
ID) — so the bulk file we emit points at exactly the right Amazon rows, instead
of re-matching by name like the generic `harvest` stage does:

  bid tweaks  — aggregate each existing keyword / product target's last-7-day
                performance, recompute its optimal bid (target-CPC, guardrailed),
                emit an Entity=Keyword / Product Targeting **update** keyed by its
                Keyword ID / Product Targeting ID (update-by-ID — safest).
  harvest     — aggregate each customer search term inside its ad group; a winner
                (orders + good ACoS) becomes an Exact keyword / product-target
                **create**, a loser ($ spent, 0 orders) a Negative Exact / Negative
                Product Targeting create.

Careful handling of Targeting / ASINs / Keywords (Amazon rejects the wrong shape):
  * a customer search term that is an ASIN (B0…) is ALWAYS a product target
    (`asin="B0…"`), never a keyword — and vice-versa;
  * an ad group can't mix positive keywords with positive product targets, so a
    promote whose type doesn't match the ad group's existing type is skipped;
  * auto-campaign clauses (loose-/close-match, substitutes, complements) can't be
    promoted (no manual destination) — only negated;
  * IDs are kept as exact strings end-to-end (16-18 digit IDs overflow float64).

Self-contained: never touches FactPerformance / the campaign-rooted dims, so a
bulk uploaded under Weekly only ever drives the Weekly cadence (per-cadence db).
"""
from __future__ import annotations
import io
import re
import pandas as pd
from sqlalchemy.orm import Session
from .. import models as md
from .. import metrics as M
from ..config import Thresholds
from . import bulkfmt, bid_optimizer as bo, ingest as ingest_stage, workbook

AUTO_CLAUSES = bulkfmt.AUTO_CLAUSES   # loose-match / close-match / substitutes / complements


# ---- parse the SP Search Term Report sheet ----------------------------------
def _num(v) -> float:
    if v is None:
        return 0.0
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    if not s or s.lower() == "nan":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _str(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def _find_sheet(path: str) -> str | None:
    """Pick the Sponsored Products Search Term Report sheet by name, else any
    sheet carrying a 'customer search term' column."""
    names = workbook.sheet_names(path)
    # exact-ish SP search term report
    for sn in names:
        low = str(sn).strip().lower()
        if "search term" in low and ("sp " in low or low.startswith("sp") or "sponsored product" in low):
            return sn
    # any sheet with a customer-search-term header
    for sn in names:
        if any("customer search term" in str(c).strip().lower()
               for c in workbook.columns(path, sn)):
            return sn
    return None


def _resolve(df: pd.DataFrame) -> dict[str, str]:
    norm = {str(c).strip().lower(): c for c in df.columns}

    def find(*preds):
        for pred in preds:
            for low, orig in norm.items():
                if pred(low):
                    return orig
        return None

    return {
        "campaign_id": find(lambda s: s == "campaign id"),
        "ad_group_id": find(lambda s: s == "ad group id"),
        "keyword_id": find(lambda s: s == "keyword id"),
        "product_targeting_id": find(lambda s: s == "product targeting id"),
        "campaign_name": find(lambda s: s.startswith("campaign name")),
        "ad_group_name": find(lambda s: s.startswith("ad group name")),
        "state": find(lambda s: s == "state"),
        "bid": find(lambda s: s == "bid"),
        "keyword_text": find(lambda s: s == "keyword text"),
        "match_type": find(lambda s: s == "match type"),
        "expression": find(lambda s: s == "product targeting expression"),
        "search_term": find(lambda s: s == "customer search term", lambda s: "search term" in s),
        "impressions": find(lambda s: s == "impressions"),
        "clicks": find(lambda s: s == "clicks"),
        "spend": find(lambda s: s == "spend", lambda s: "spend" in s),
        "sales": find(lambda s: "7 day" in s and "sales" in s, lambda s: s == "sales", lambda s: "sales" in s),
        "orders": find(lambda s: "7 day" in s and "orders" in s, lambda s: s == "orders", lambda s: "orders" in s),
        "units": find(lambda s: "7 day" in s and "units" in s, lambda s: s == "units", lambda s: "units" in s),
    }


_STR_CACHE: dict[tuple, list[dict]] = {}


def clear_cache() -> None:
    _STR_CACHE.clear()


def parse_str_sheet(path: str) -> list[dict]:
    """Read the SP Search Term Report into normalized row dicts (IDs kept as exact
    strings). Raises ValueError with a friendly message if the sheet is missing.

    Cached per file (see ingest._stamp): a suite upload feeds the same report to
    Weekly / Mid-Month / Full-Month / Pause-Scale / Cannibalization, and parsing it
    once instead of five times is most of that upload's wall clock. Rows are copied
    out, since callers stamp fields (e.g. `week`) onto them."""
    key = ingest_stage._stamp(path, "__str__")
    hit = _STR_CACHE.get(key)
    if hit is not None:
        return [dict(r) for r in hit]
    rows = _parse_str_sheet(path)
    _STR_CACHE[key] = rows
    return [dict(r) for r in rows]


def _parse_str_sheet(path: str) -> list[dict]:
    if path.lower().endswith(".csv"):
        df = workbook.read_str(path)
    else:
        sheet = _find_sheet(path)
        if sheet is None:
            raise ValueError("No 'SP Search Term Report' sheet found in that file — Weekly "
                             "Optimization needs the Sponsored Products bulk export that includes "
                             "the Search Term Report.")
        df = workbook.read_str(path, sheet)
    cols = _resolve(df)
    if not cols.get("search_term"):
        raise ValueError("That sheet has no 'Customer Search Term' column — is it the SP Search "
                         "Term Report?")
    if not cols.get("campaign_id") or not cols.get("ad_group_id"):
        raise ValueError("The Search Term Report is missing Campaign ID / Ad Group ID columns — "
                         "those IDs are required to build the bulk file.")

    rows = []
    for _, r in df.iterrows():
        st = _str(r.get(cols["search_term"]))
        cid = bulkfmt.idstr(_str(r.get(cols["campaign_id"])))
        agid = bulkfmt.idstr(_str(r.get(cols["ad_group_id"])))
        if not st or st == "*" or not cid or not agid:
            continue
        kid = bulkfmt.idstr(_str(r.get(cols["keyword_id"]))) if cols.get("keyword_id") else ""
        ptid = bulkfmt.idstr(_str(r.get(cols["product_targeting_id"]))) if cols.get("product_targeting_id") else ""
        expr = _str(r.get(cols["expression"])) if cols.get("expression") else ""
        bid = _num(r.get(cols["bid"])) if cols.get("bid") else 0.0
        rows.append(dict(
            campaign_id=cid, ad_group_id=agid, keyword_id=kid or None,
            product_targeting_id=ptid or None,
            campaign_name=_str(r.get(cols["campaign_name"])) if cols.get("campaign_name") else None,
            ad_group_name=_str(r.get(cols["ad_group_name"])) if cols.get("ad_group_name") else None,
            state=(_str(r.get(cols["state"])) if cols.get("state") else "") or None,
            bid=bid or None,
            keyword_text=(_str(r.get(cols["keyword_text"])) if cols.get("keyword_text") else "") or None,
            match_type=(_str(r.get(cols["match_type"])) if cols.get("match_type") else "") or None,
            expression=expr or None,
            is_auto=expr.strip().lower() in AUTO_CLAUSES,
            search_term=st,
            impressions=int(_num(r.get(cols["impressions"])) if cols.get("impressions") else 0),
            clicks=int(_num(r.get(cols["clicks"])) if cols.get("clicks") else 0),
            spend=round(_num(r.get(cols["spend"])) if cols.get("spend") else 0.0, 2),
            sales=round(_num(r.get(cols["sales"])) if cols.get("sales") else 0.0, 2),
            orders=int(_num(r.get(cols["orders"])) if cols.get("orders") else 0),
            units=int(_num(r.get(cols["units"])) if cols.get("units") else 0),
        ))
    if not rows:
        raise ValueError("The Search Term Report had no usable rows (no Sponsored Products search "
                         "terms with Campaign / Ad Group IDs).")
    return rows


def _ensure_schema(db: Session) -> None:
    """Defensive: a weekly_term_fact table created before the per-week change won't
    have the `week` column. Add it once so old single-snapshot data keeps working
    (everything that exists is treated as Week 1)."""
    from sqlalchemy import text
    cols = [r[1] for r in db.execute(text("PRAGMA table_info(weekly_term_fact)")).fetchall()]
    if cols and "week" not in cols:
        db.execute(text("ALTER TABLE weekly_term_fact ADD COLUMN week INTEGER NOT NULL DEFAULT 1"))
        db.commit()


def load_star_schema(db: Session, path: str, snapshot=None) -> dict | None:
    """ALSO feed the star schema (FactPerformance + FactPlacement + dims) from the same
    full SP bulk, so the generic optimizer panels (Placement / BidOptimizer / AsinTree /
    Harvest / Ngram) light up for this cadence's db. Tolerant: a Search-Term-Report-only
    file with no campaign / 'Bidding Adjustment' rows just leaves the star schema alone.
    Returns the load counts, or None if the file carried nothing loadable."""
    from datetime import date
    from . import load as load_stage
    try:
        return load_stage.load(db, ingest_stage.frames(path), snapshot or date.today())
    except Exception:
        db.rollback()
        return None


def ingest(db: Session, path: str, week: int = 1, load_star: bool = True) -> dict:
    """Parse + store the report as the snapshot for `week` (replaces that week).
    Weeks accumulate; re-uploading a week overwrites just that week."""
    _ensure_schema(db)
    week = max(1, int(week))
    rows = parse_str_sheet(path)
    for r in rows:
        r["week"] = week
    db.query(md.WeeklyTermFact).filter(md.WeeklyTermFact.week == week).delete()
    db.bulk_insert_mappings(md.WeeklyTermFact, rows)
    db.commit()
    if load_star:                # the suite upload loads the star schema itself
        load_star_schema(db, path)   # Placement / BidOpt / AsinTree / Harvest / Ngram
    return {"week": week, **summary(db, week)}


def has_data(db: Session) -> bool:
    _ensure_schema(db)
    return db.query(md.WeeklyTermFact.id).first() is not None


def weeks(db: Session) -> list[int]:
    """Uploaded week numbers, ascending."""
    _ensure_schema(db)
    rows = db.query(md.WeeklyTermFact.week).distinct().all()
    return sorted(int(r[0]) for r in rows if r[0] is not None)


def delete_week(db: Session, week: int) -> int:
    """Remove a week's data so its panel doesn't re-seed on remount."""
    _ensure_schema(db)
    n = db.query(md.WeeklyTermFact).filter(md.WeeklyTermFact.week == int(week)).delete()
    db.commit()
    return n


def delete_all(db: Session) -> int:
    """Wipe every uploaded week (clears all Weekly Optimization data)."""
    _ensure_schema(db)
    n = db.query(md.WeeklyTermFact).delete()
    db.commit()
    return n


def clear_star_schema(db: Session) -> int:
    """Wipe the star schema this cadence's uploads fed (`load_star_schema`), so the
    generic optimizer sub-panels (Placement / BidOptimizer / AsinTree / Harvest /
    Ngram) clear with the cadence. Child tables first (FK-safe). Shared by every
    cadence's clear — each cadence db only holds its own cadence's data."""
    from . import audit as audit_stage
    n = 0
    for model in (md.FactPerformance, md.FactPlacement, md.DimTarget, md.DimAd,
                  md.DimAdGroup, md.DimCampaign, md.DimProduct):
        n += db.query(model).delete()
    db.commit()
    audit_stage.invalidate_tree_cache()
    return n


def _latest_week(db: Session) -> int | None:
    ws = weeks(db)
    return ws[-1] if ws else None


def _resolve_week(db: Session, week: int | None) -> int | None:
    """Pick the requested week if it has data, else the latest uploaded week."""
    ws = weeks(db)
    if not ws:
        return None
    if week and int(week) in ws:
        return int(week)
    return ws[-1]


def summarize(rows) -> dict:
    """Account snapshot for a list of STR fact rows (model-agnostic)."""
    sp = sum(r.spend or 0 for r in rows)
    sa = sum(r.sales or 0 for r in rows)
    return {
        "terms": len(rows),
        "campaigns": len({r.campaign_id for r in rows}),
        "ad_groups": len({r.ad_group_id for r in rows}),
        "spend": round(sp, 2), "sales": round(sa, 2),
        "acos": round(sp / sa * 100, 2) if sa else None,
    }


def summary(db: Session, week: int | None = None) -> dict:
    rows = db.query(md.WeeklyTermFact).filter(md.WeeklyTermFact.week == week).all() \
        if week is not None else db.query(md.WeeklyTermFact).all()
    return summarize(rows)


def _kpis(sp, sa, cl, im, od) -> dict:
    sp, sa, cl, im, od = float(sp), float(sa), float(cl), float(im), float(od)
    return {
        "spend": round(sp, 2), "sales": round(sa, 2), "clicks": int(cl),
        "impressions": int(im), "orders": int(od),
        "acos": round(sp / sa * 100, 2) if sa else None,       # %
        "roas": round(sa / sp, 2) if sp else None,             # ×
        "cvr": round(od / cl * 100, 2) if cl else None,        # %
        "ctr": round(cl / im * 100, 2) if im else None,        # %
        "cpc": round(sp / cl, 2) if cl else None,              # $
    }


def series(db: Session) -> dict:
    """Per-week account totals for the trend chart (oldest→newest week)."""
    out = []
    for w in weeks(db):
        rows = db.query(md.WeeklyTermFact).filter(md.WeeklyTermFact.week == w).all()
        sp = sum(r.spend or 0 for r in rows); sa = sum(r.sales or 0 for r in rows)
        cl = sum(r.clicks or 0 for r in rows); im = sum(r.impressions or 0 for r in rows)
        od = sum(r.orders or 0 for r in rows)
        out.append({"week": w, "label": f"Week {w}", **_kpis(sp, sa, cl, im, od)})
    return {"weeks": out}


# ---- week-over-week compare (mirrors Daily Watch's day compare) --------------
SPEND_SPIKE_MULT = 1.5      # cur spend > prev * this -> spike
SPEND_SPIKE_FLOOR = 20.0    # ...and absolute delta >= $ this
ACOS_SPIKE_PP = 10.0        # ACoS up by >= this many points
SALES_DROP_MULT = 0.5       # cur sales < prev * this (with spend holding)
ZERO_ORDER_SPEND = 25.0     # campaign spent >= $ this, 0 orders


def _delta(prev, cur):
    if prev is None or cur is None:
        return None
    return round(cur - prev, 2)


def _pct_change(prev, cur):
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def _acct_of(rows) -> dict:
    sp = sum(r.spend or 0 for r in rows); sa = sum(r.sales or 0 for r in rows)
    cl = sum(r.clicks or 0 for r in rows); im = sum(r.impressions or 0 for r in rows)
    od = sum(r.orders or 0 for r in rows)
    return _kpis(sp, sa, cl, im, od)


def _campaigns_of(rows) -> dict[str, dict]:
    agg: dict[str, dict] = {}
    for r in rows:
        c = agg.get(r.campaign_id)
        if c is None:
            c = agg[r.campaign_id] = {"name": r.campaign_name or r.campaign_id,
                                      "spend": 0.0, "sales": 0.0, "clicks": 0, "impressions": 0, "orders": 0}
        c["spend"] += r.spend or 0; c["sales"] += r.sales or 0; c["clicks"] += r.clicks or 0
        c["impressions"] += r.impressions or 0; c["orders"] += r.orders or 0
    return {cid: {"campaign_id": cid, "name": c["name"],
                  **_kpis(c["spend"], c["sales"], c["clicks"], c["impressions"], c["orders"])}
            for cid, c in agg.items()}


def _flag(kind, severity, campaign, message, cid):
    return {"kind": kind, "severity": severity, "campaign": campaign, "message": message, "campaign_id": cid}


def compare_rows(prev_rows, cur_rows, target_acos: float | None = None) -> dict:
    """Model-agnostic period-over-period compare: account deltas + per-campaign movers
    + spike flags, from two lists of *_term_fact rows. Shared by Weekly (week vs week),
    Mid-Month and Full Month (previous upload vs current)."""
    a_prev, a_cur = _acct_of(prev_rows), _acct_of(cur_rows)
    target = (target_acos or 0) * 100 if target_acos and target_acos <= 2 else (target_acos or 0)

    account = {}
    for k in ("spend", "sales", "clicks", "impressions", "orders", "acos"):
        account[k] = {"prev": a_prev[k], "cur": a_cur[k],
                      "delta": _delta(a_prev[k], a_cur[k]), "pct": _pct_change(a_prev[k], a_cur[k])}

    cp, cc = _campaigns_of(prev_rows), _campaigns_of(cur_rows)
    flags, rows = [], []
    for cid in set(cp) | set(cc):
        p, c = cp.get(cid), cc.get(cid)
        name = (c or p)["name"]
        ps, cs = (p["spend"] if p else 0.0), (c["spend"] if c else 0.0)
        psa, csa = (p["sales"] if p else 0.0), (c["sales"] if c else 0.0)
        pac, cac = (p["acos"] if p else None), (c["acos"] if c else None)
        rows.append({
            "campaign_id": cid, "name": name,
            "spend_prev": ps, "spend_cur": cs, "spend_delta": round(cs - ps, 2), "spend_pct": _pct_change(ps, cs),
            "sales_prev": psa, "sales_cur": csa, "sales_delta": round(csa - psa, 2),
            "acos_prev": pac, "acos_cur": cac, "orders_cur": c["orders"] if c else 0,
        })
        if cs >= ps * SPEND_SPIKE_MULT and (cs - ps) >= SPEND_SPIKE_FLOOR:
            pcs = _pct_change(ps, cs)
            tail = f"(+{pcs:.0f}%)" if pcs is not None else "(new spend)"
            flags.append(_flag("spend_spike", "high", name, f"Ad spend spiked ${ps:.0f} → ${cs:.0f} {tail}", cid))
        if pac is not None and cac is not None and (cac - pac) >= ACOS_SPIKE_PP and (not target or cac > target):
            flags.append(_flag("acos_spike", "high", name, f"ACoS jumped {pac:.0f}% → {cac:.0f}% (+{cac - pac:.0f}pp)", cid))
        if psa > 0 and csa < psa * SALES_DROP_MULT and cs >= ps * 0.8:
            flags.append(_flag("sales_drop", "med", name, f"Sales fell ${psa:.0f} → ${csa:.0f} with spend holding", cid))
        if c and c["spend"] >= ZERO_ORDER_SPEND and c["orders"] == 0:
            flags.append(_flag("zero_order_spend", "med", name, f"Spent ${c['spend']:.0f} with 0 orders", cid))

    rows.sort(key=lambda r: abs(r["spend_delta"]), reverse=True)
    sev = {"high": 0, "med": 1, "low": 2}
    flags.sort(key=lambda f: sev.get(f["severity"], 9))
    return {"account": account, "campaigns": rows, "flags": flags}


def compare(db: Session, prev_week: int, cur_week: int, target_acos: float | None = None) -> dict:
    """Diff two uploaded weeks (account deltas + per-campaign movers + spike flags)."""
    avail = weeks(db)
    missing = [w for w in (prev_week, cur_week) if w not in avail]
    if missing:
        hint = f" Uploaded weeks: {', '.join(f'Week {w}' for w in avail)}." if avail else " No weeks uploaded yet."
        raise ValueError("No data for " + ", ".join(f"Week {w}" for w in missing) +
                         " — upload that week's bulk first." + hint)
    if prev_week == cur_week:
        raise ValueError("Pick two different weeks to compare.")
    return {"prev_week": prev_week, "cur_week": cur_week,
            **compare_rows(_facts(db, prev_week), _facts(db, cur_week), target_acos)}


# ---- single-snapshot history (current=0 / previous=1) — shared by Mid/Full ----
def ensure_period_col(db: Session, table: str) -> None:
    """Defensive: add the `period` column to a single-snapshot term table created
    before the compare feature (everything existing becomes the current snapshot, 0)."""
    from sqlalchemy import text
    cols = [r[1] for r in db.execute(text(f"PRAGMA table_info({table})")).fetchall()]
    if cols and "period" not in cols:
        db.execute(text(f"ALTER TABLE {table} ADD COLUMN period INTEGER NOT NULL DEFAULT 0"))
        db.commit()


def shift_and_insert(db: Session, Model, rows: list[dict]) -> None:
    """Keep two snapshots: drop the old previous, shift current(0)→previous(1), insert
    the new rows as current(0). Lets a single-panel cadence compare upload-vs-previous."""
    db.query(Model).filter(Model.period == 1).delete()
    db.query(Model).filter(Model.period == 0).update({Model.period: 1})
    for r in rows:
        r["period"] = 0
    db.bulk_insert_mappings(Model, rows)
    db.commit()


def period_rows(db: Session, Model, period: int) -> list:
    return db.query(Model).filter(Model.period == period).all()


def has_previous(db: Session, Model) -> bool:
    return db.query(Model.id).filter(Model.period == 1).first() is not None


# ---- bid tweaks (aggregate each existing target, recompute its bid) ----------
def _facts(db: Session, week: int | None):
    q = db.query(md.WeeklyTermFact)
    return q.filter(md.WeeklyTermFact.week == week).all() if week is not None else q.all()


def aggregate_targets(rows) -> list[dict]:
    """Aggregate STR rows into per-target totals (keyword / product target), keyed by
    Keyword ID / Product Targeting ID, keeping each target's state + current bid.
    Model-agnostic — shared by bid tweaks (Weekly/Mid/Full) and pause/scale."""
    agg: dict[tuple, dict] = {}
    for r in rows:
        if r.keyword_id:
            key, kind, tid = ("kw", r.keyword_id), "keyword", r.keyword_id
        elif r.product_targeting_id:
            key, kind, tid = ("pt", r.product_targeting_id), "product_target", r.product_targeting_id
        else:
            continue
        a = agg.get(key)
        if a is None:
            a = agg[key] = dict(id=tid, kind=kind, campaign_id=r.campaign_id,
                                ad_group_id=r.ad_group_id, is_auto=r.is_auto,
                                label=(r.keyword_text or r.expression or tid),
                                match_type=r.match_type, expression=r.expression,
                                state=(r.state or "enabled"), current_bid=r.bid,
                                impressions=0, clicks=0, spend=0.0, sales=0.0, orders=0)
        if a["current_bid"] is None and r.bid:
            a["current_bid"] = r.bid
        a["impressions"] += r.impressions or 0
        a["clicks"] += r.clicks or 0
        a["spend"] = round(a["spend"] + (r.spend or 0), 2)
        a["sales"] = round(a["sales"] + (r.sales or 0), 2)
        a["orders"] += r.orders or 0
    return list(agg.values())


def compute_bid_tweaks(rows, t: Thresholds, effective: dict[str, dict] | None = None) -> list[dict]:
    """One recommendation per existing keyword / product target with enough data,
    from a list of STR fact rows (model-agnostic — shared by Weekly + Mid-Month).
    Keyed by the target's Keyword ID / Product Targeting ID (update-by-ID).

    `effective` (target_id -> {'bid','state'}) is the BidLedger overlay: bids
    already exported land there, so a second export computes from them instead of
    the stale snapshot (never double-applies)."""
    th = bo.CONFIG["thresholds"]
    min_clicks = max(t.min_clicks, 1)
    effective = effective or {}
    out = []
    for a in aggregate_targets(rows):
        eff = effective.get(str(a["id"]), {})
        st = (eff.get("state") or a["state"] or "enabled").strip().lower()
        if st not in ("enabled", "ok", ""):
            continue
        cur = eff.get("bid") if eff.get("bid") is not None else a["current_bid"]
        if cur is None or cur <= 0:
            continue
        if a["clicks"] < min_clicks or a["spend"] < t.min_spend:
            continue
        m0 = M.all_metrics(a["impressions"], a["clicks"], a["spend"], a["sales"], a["orders"], 0)
        # overbid (bid over the hard cap, or way above what clicks actually cost):
        # the current bid is noise — skip the per-pass cut cap + step limiter and
        # reset straight to the computed, hard-capped target in one pass.
        overbid = bo.is_overbid(cur, "keyword_bid", m0["cpc"])
        if m0["acos"] is not None and m0["acos"] > t.target_acos:
            # over goal -> CUT path. safe_bid_cut can never raise — the target-CPC
            # formula can EXCEED the current bid on up/down campaigns (CPC ~2x bid).
            new = M.safe_bid_cut(cur, m0["cpc"], m0["acos"], t.target_acos, None,
                                 floor=t.bid_floor)
            if new is None:
                continue
            if not overbid:
                new = max(new, round(cur * t.max_bid_cut, 2))   # keep the per-pass cut cap
        else:
            new = M.target_cpc_bid(a["clicks"], a["sales"], t.target_acos, cur,
                                   t.max_bid_cut, t.max_bid_up, t.bid_floor)
        if new is None:
            continue
        new = bo.clamp_caps(new, "keyword_bid")
        if not overbid:
            new = round(bo.limit_step(cur, new, "keyword_bid"), 2)
        if abs(new - cur) < 0.01:
            continue
        direction = "raise" if new > cur else "cut"
        if m0["acos"] is not None and m0["acos"] > t.target_acos and direction == "raise":
            continue                                        # belt-and-braces: never raise over goal
        # don't raise on thin conversion evidence
        if direction == "raise" and a["orders"] < th["min_purchases"]:
            continue
        m = M.all_metrics(a["impressions"], a["clicks"], a["spend"], a["sales"], a["orders"], 0)
        acos = m["acos"]
        if overbid and direction == "cut":
            cpc_txt = f" vs ${m['cpc']:.2f} CPC" if m["cpc"] else ""
            reason = f"overbid ${cur:.2f}{cpc_txt} — reset to ${new:.2f} in one pass"
        elif a["orders"] == 0:
            reason = f"{a['clicks']} clicks, 0 orders — pull bid back"
        elif direction == "raise":
            reason = f"profitable @ {acos:.0%} — bid up toward goal {t.target_acos:.0%}"
        else:
            reason = f"{acos:.0%} ACoS over goal {t.target_acos:.0%} — bid down to target CPC"
        out.append({
            "id": a["id"], "kind": a["kind"], "campaign_id": a["campaign_id"],
            "ad_group_id": a["ad_group_id"], "label": a["label"],
            "match_type": a["match_type"], "expression": a["expression"],
            "current_bid": round(cur, 2), "suggested_bid": new, "delta": round(new - cur, 2),
            "direction": direction, "overbid": overbid, "clicks": a["clicks"], "orders": a["orders"],
            "spend": a["spend"], "sales": a["sales"],
            "acos": round(acos, 4) if acos is not None else None, "reason": reason,
        })
    out.sort(key=lambda r: r["spend"], reverse=True)
    return out


def _effective(db: Session) -> dict[str, dict]:
    """BidLedger overlay from the BASE project db (account-level, shared across
    cadences) — already-exported bids/states that the snapshot doesn't show yet."""
    from . import ledger as ledger_stage
    base = ledger_stage.base_session(db)
    try:
        return ledger_stage.effective_map(base)
    finally:
        base.close()


def bid_tweaks(db: Session, t: Thresholds, week: int | None = None) -> list[dict]:
    return compute_bid_tweaks(_facts(db, week), t, _effective(db))


# ---- search-term harvest (winners promote, losers negate) -------------------
def compute_ag_types(rows) -> tuple[set[str], set[str], set[str]]:
    """From the report rows, classify each ad group: has positive keywords / has
    positive product targets / is an auto campaign clause group."""
    ag_kw, ag_pt, ag_auto = set(), set(), set()
    for r in rows:
        if r.is_auto:
            ag_auto.add(r.ad_group_id)
        elif r.keyword_id:
            ag_kw.add(r.ad_group_id)
        elif r.product_targeting_id:
            ag_pt.add(r.ad_group_id)
    return ag_kw, ag_pt, ag_auto


def compute_harvest(rows, t: Thresholds, min_orders: int = 1,
                    bleeder_acos_mult: float | None = None,
                    bleeder_min_orders: int = 2, bleeder_spend_mult: float = 2.0) -> dict:
    """Aggregate every customer search term inside its ad group, classify as a
    promote (winner) / negate (zero-order loser), with Amazon-safe targeting shape.
    If `bleeder_acos_mult` is set, also surface **bleeders** — terms that DID convert
    but at ACoS ≥ mult × goal (converting-but-unprofitable) as an extra, separate
    negate list for heavier negative targeting (Mid-Month). Bleeders are pre-filtered
    to the ones worth acting on: ≥ `bleeder_min_orders` orders (one order's ACoS is
    statistical noise) AND spend ≥ `bleeder_spend_mult` × the loser floor (head
    $-bleeders only, not the long tail). Model-agnostic."""
    ag_kw, ag_pt, ag_auto = compute_ag_types(rows)
    agg: dict[tuple, dict] = {}
    for r in rows:
        st = r.search_term.strip()
        if not st or st == "*":
            continue
        key = (r.ad_group_id, st.lower())
        a = agg.get(key)
        if a is None:
            a = agg[key] = dict(search_term=st, campaign_id=r.campaign_id,
                                ad_group_id=r.ad_group_id, campaign_name=r.campaign_name,
                                ad_group_name=r.ad_group_name, match_type=r.match_type,
                                impressions=0, clicks=0, spend=0.0, sales=0.0, orders=0)
        a["impressions"] += r.impressions or 0
        a["clicks"] += r.clicks or 0
        a["spend"] = round(a["spend"] + (r.spend or 0), 2)
        a["sales"] = round(a["sales"] + (r.sales or 0), 2)
        a["orders"] += r.orders or 0

    # reserve in-run promotes so we never mix kw+pt in one ad group across the file
    res_kw, res_pt = set(ag_kw), set(ag_pt)
    promotes, negates, bleeders = [], [], []
    for a in agg.values():
        term, agid = a["search_term"], a["ad_group_id"]
        m = M.all_metrics(a["impressions"], a["clicks"], a["spend"], a["sales"], a["orders"], 0)
        acos = m["acos"]
        term_is_asin = bulkfmt.is_asin(term)
        winner = a["orders"] >= min_orders and acos is not None and acos <= t.target_acos
        loser = a["orders"] == 0 and a["spend"] >= t.min_spend
        # bleeder: converted, but ACoS ≥ mult × goal (Mid-Month). Pre-filtered to
        # ≥ bleeder_min_orders (one order's ACoS is noise) and head spend only.
        # acos here is a fraction (e.g. 0.80); compare against the fraction goal × mult.
        bleeder = (bleeder_acos_mult and a["orders"] >= bleeder_min_orders and acos is not None
                   and acos >= bleeder_acos_mult * t.target_acos
                   and a["spend"] >= bleeder_spend_mult * t.min_spend)

        if winner and agid not in ag_auto:
            # type must match the ad group (no kw+pt mix); ASIN->PT, text->keyword
            if term_is_asin:
                if agid in res_kw:
                    continue                     # keyword ad group can't take a product target
                res_pt.add(agid)
            else:
                if agid in res_pt:
                    continue                     # PT ad group can't take a keyword
                if not bulkfmt.valid_keyword(term):
                    continue
                res_kw.add(agid)
            cpc = m["cpc"] or t.bid_floor
            bid = M.target_acos_bid(cpc, acos, t.target_acos, t.max_bid_cut, t.max_bid_up, t.bid_floor)
            bid = bo.clamp_caps(bid, "keyword_bid")   # new keyword bid never born over the hard cap
            promotes.append({
                "action": "promote", "as": "product_target" if term_is_asin else "keyword",
                "search_term": term, "campaign_id": a["campaign_id"], "ad_group_id": agid,
                "campaign_name": a["campaign_name"], "ad_group_name": a["ad_group_name"],
                "impressions": a["impressions"], "clicks": a["clicks"], "spend": a["spend"],
                "sales": a["sales"], "orders": a["orders"], "acos": round(acos, 4),
                "suggested_bid": bid, "reason": f"{a['orders']} orders @ {acos:.0%} ACoS — promote to Exact",
            })
        elif loser:
            if not term_is_asin and not bulkfmt.valid_keyword(term):
                continue                          # invalid as a negative keyword
            negates.append({
                "action": "negate", "as": "product_target" if term_is_asin else "keyword",
                "search_term": term, "campaign_id": a["campaign_id"], "ad_group_id": agid,
                "campaign_name": a["campaign_name"], "ad_group_name": a["ad_group_name"],
                "impressions": a["impressions"], "clicks": a["clicks"], "spend": a["spend"],
                "sales": a["sales"], "orders": a["orders"], "acos": None,
                "suggested_bid": None, "reason": f"${a['spend']:.2f} spend, 0 orders — negate Exact",
            })
        elif bleeder:
            if not term_is_asin and not bulkfmt.valid_keyword(term):
                continue
            bleeders.append({
                "action": "negate", "as": "product_target" if term_is_asin else "keyword",
                "search_term": term, "campaign_id": a["campaign_id"], "ad_group_id": agid,
                "campaign_name": a["campaign_name"], "ad_group_name": a["ad_group_name"],
                "impressions": a["impressions"], "clicks": a["clicks"], "spend": a["spend"],
                "sales": a["sales"], "orders": a["orders"], "acos": round(acos, 4),
                "suggested_bid": None,
                "reason": (f"${a['spend']:.0f} / {a['orders']} ord @ {acos:.0%} ACoS "
                           f"(≥ {bleeder_acos_mult:g}× goal {t.target_acos:.0%}) — bleeding, negate"),
            })
    promotes.sort(key=lambda r: r["sales"], reverse=True)
    negates.sort(key=lambda r: r["spend"], reverse=True)
    bleeders.sort(key=lambda r: r["spend"], reverse=True)
    return {"promotes": promotes, "negates": negates, "bleeders": bleeders}


def harvest(db: Session, t: Thresholds, week: int | None = None, min_orders: int = 1) -> dict:
    return compute_harvest(_facts(db, week), t, min_orders)


def plan(db: Session, t: Thresholds, week: int | None = None) -> dict:
    wk = _resolve_week(db, week)
    h = harvest(db, t, wk)
    out = {"week": wk, "weeks": weeks(db), "summary": summary(db, wk),
           "bid_tweaks": bid_tweaks(db, t, wk),
           "promotes": h["promotes"], "negates": h["negates"],
           "target_acos": round(t.target_acos, 4)}
    # stamp each row with its ad group's product break-even ACoS (benchmark
    # upload wins, else catalog listing + real Transactions-ledger fees) — the
    # cadence db carries the bulk's star schema, so the ad-group join works here
    from . import harvest as hv
    ag_be = hv.ag_break_even_map(db)
    for r in out["bid_tweaks"] + out["promotes"] + out["negates"]:
        r["break_even"] = ag_be.get(str(r.get("ad_group_id")))
    # ML overlay (advisory): empirical-Bayes CVR shrinkage + confidences on every
    # row, plus a next-week Holt forecast from the accumulated weeks series.
    from . import ml
    ml.enrich_plan(out, aggregate_targets(_facts(db, wk)), t.target_acos)
    if out.get("ml") is not None:
        ser = series(db)["weeks"]
        if len(ser) >= 3:
            out["ml"]["forecast"] = {k: ml.holt_forecast([w.get(k) for w in ser])
                                     for k in ("spend", "sales", "acos")}
    return out


# ---- bulk file --------------------------------------------------------------
BULK_COLS = ["Product", "Entity", "Operation", "Campaign ID", "Ad Group ID",
             "Keyword ID", "Product Targeting ID", "Keyword Text", "Match Type",
             "Product Targeting Expression", "Bid", "State"]


def _blank() -> dict:
    return {c: None for c in BULK_COLS}


def to_bulk(bid_rows: list[dict], harvest_rows: list[dict]) -> bytes:
    """Chosen bid-tweak + harvest rows -> one Amazon SP bulk sheet (xlsx bytes).
    De-duplicated so Amazon never rejects on Duplicate Id / already exists."""
    rows, seen = [], set()

    # 1) bid updates — keyed by Keyword ID / Product Targeting ID (update-by-ID)
    for b in bid_rows or []:
        tid = bulkfmt.idstr(b.get("id"))
        if not tid:
            continue
        is_kw = b.get("kind") == "keyword"
        sig = ("u", "kw" if is_kw else "pt", tid)
        if sig in seen:
            continue
        seen.add(sig)
        row = _blank()
        row.update({"Product": "Sponsored Products",
                    "Entity": "Keyword" if is_kw else "Product Targeting",
                    "Operation": "update",
                    "Campaign ID": bulkfmt.idstr(b.get("campaign_id")),
                    "Ad Group ID": bulkfmt.idstr(b.get("ad_group_id")),
                    "Bid": b.get("suggested_bid"), "State": "enabled"})
        if is_kw:
            row["Keyword ID"] = tid
        else:
            row["Product Targeting ID"] = tid
        rows.append(row)

    # 2) harvest creates — promote (Exact keyword / product target) or negate
    for h in harvest_rows or []:
        term = str(h.get("search_term", "")).strip()
        if not term:
            continue
        as_pt = h.get("as") == "product_target" or bulkfmt.is_asin(term)
        if not as_pt and not bulkfmt.valid_keyword(term):
            continue
        agid = bulkfmt.idstr(h.get("ad_group_id"))
        row = _blank()
        row.update({"Product": "Sponsored Products", "Operation": "create",
                    "Campaign ID": bulkfmt.idstr(h.get("campaign_id")),
                    "Ad Group ID": agid, "State": "enabled"})
        if as_pt:
            expr = f'asin="{term.upper()}"' if bulkfmt.is_asin(term) else term
            row["Product Targeting Expression"] = expr
            if h.get("action") == "promote":
                row.update({"Entity": "Product Targeting", "Bid": h.get("suggested_bid")})
            else:
                row["Entity"] = "Negative Product Targeting"
            sig = ("c", row["Entity"], agid, expr.lower())
        else:
            row["Keyword Text"] = term
            if h.get("action") == "promote":
                row.update({"Entity": "Keyword", "Match Type": "Exact", "Bid": h.get("suggested_bid")})
            else:
                row.update({"Entity": "Negative Keyword", "Match Type": "Negative Exact"})
            sig = ("c", row["Entity"], agid, term.lower())
        if sig in seen:
            continue
        seen.add(sig)
        rows.append(row)

    df = pd.DataFrame(rows, columns=BULK_COLS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Sponsored Products Campaigns")
    return buf.getvalue()
