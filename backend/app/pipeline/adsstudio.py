"""Ads Studio — campaign consolidation board for the Product Ads tab.

Pick ASINs in Product Ads, open them here, and merge their scattered campaigns into
one destination per targeting kind. Two data sources, both from the SAME Product Ads
bulk upload, so Studio never reads the audit star schema:

  ProductAdFact         which ASINs each campaign advertises (already parsed)
  AdsStudioTargetFact   that bulk's Keyword / Product Targeting rows + metrics (here)

The consolidation rule is the user's: **a target survives the merge only if it beats
the goal ACoS.** Everything else is paused rather than migrated, so the destination
campaign inherits the winners and nothing else.

Verdicts (`classify`):
  keep    — orders >= 1 and ACoS <= goal            -> migrate into the destination
  drop    — orders >= 1 and ACoS > goal, OR
            0 orders with >= min_clicks clicks      -> pause where it sits
  review  — too thin to judge (0 orders, few clicks) -> left alone, shown for the user

`plan()` turns a set of drag-and-dropped groups into migrate / pause / campaign-pause
lists; `to_bulk()` emits them as one Amazon SP bulk through `bulkfmt`, so the same
validation every other engine uses (exact ID strings, keyword legality, no auto-clause
promotion, in-file dedup) applies here too.
"""
from __future__ import annotations
import io
import pandas as pd
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session
from ..config import Thresholds
from .. import models as md
from .. import metrics as M
from . import bulkfmt, funnel as fn, perftier as pt, productads as pa

BULK_COLS = ["Product", "Entity", "Operation", "Campaign ID", "Ad Group ID",
             "Keyword ID", "Product Targeting ID", "Keyword Text", "Match Type",
             "Product Targeting Expression", "Bid", "State"]

# a target with no bid of its own falls back to this before the goal-ACoS math
_MIN_BID = 0.20


def _ensure_schema(db: Session) -> None:
    """Create the tables in project DBs that predate Ads Studio (SQLite, no Alembic)."""
    bind = db.get_bind()
    insp = sa_inspect(bind)
    for model in (md.AdsStudioAdFact, md.AdsStudioTargetFact, md.AdsStudioPlacementFact):
        if not insp.has_table(model.__tablename__):
            model.__table__.create(bind)


# ---- per-feature settings -----------------------------------------------------
SETTINGS_KEY = "ads_studio"
DEFAULT_TARGET_ACOS = 0.25


def get_settings(db: Session) -> dict:
    """Ads Studio's OWN goal ACoS, deliberately independent of the audit-wide knob:
    consolidation is a structural decision the operator wants to tune on its own."""
    from .. import database as dbmod
    saved = dbmod.get_project_extra(db.info.get("store"), db.info.get("project"),
                                    SETTINGS_KEY) or {}
    return {"target_acos": float(saved.get("target_acos") or DEFAULT_TARGET_ACOS)}


def set_settings(db: Session, target_acos: float) -> dict:
    from .. import database as dbmod
    val = {"target_acos": round(float(target_acos), 4)}
    dbmod.set_project_extra(db.info.get("store"), db.info.get("project"), SETTINGS_KEY, val)
    return get_settings(db)


def thresholds(db: Session, target_acos: float | None = None) -> Thresholds:
    """Studio thresholds — its own saved goal ACoS unless the request overrides it."""
    acos = target_acos if target_acos is not None else get_settings(db)["target_acos"]
    return Thresholds().merged(target_acos=acos)


# ---- parse the bulk's target rows -------------------------------------------
def _resolve(df: pd.DataFrame) -> dict[str, str | None]:
    norm = {str(c).strip().lower(): c for c in df.columns}

    def find(*preds):
        for pred in preds:
            for low, orig in norm.items():
                if pred(low):
                    return orig
        return None

    return {
        "entity": find(lambda s: s == "entity"),
        "campaign_id": find(lambda s: s == "campaign id"),
        "ad_group_id": find(lambda s: s == "ad group id"),
        "keyword_id": find(lambda s: s == "keyword id"),
        "target_id": find(lambda s: s == "product targeting id"),
        # see productads._resolve: the bare Name columns are blank on Keyword /
        # Product Targeting rows, the "(Informational only)" twins are populated.
        "campaign_name": find(lambda s: s == "campaign name (informational only)",
                              lambda s: s.startswith("campaign name")),
        "ad_group_name": find(lambda s: s == "ad group name (informational only)",
                              lambda s: s.startswith("ad group name")),
        "campaign_name_own": find(lambda s: s == "campaign name"),
        "ad_group_name_own": find(lambda s: s == "ad group name"),
        "keyword_text": find(lambda s: s == "keyword text"),
        "match_type": find(lambda s: s == "match type"),
        "expression": find(lambda s: s.startswith("product targeting expression"),
                           lambda s: s == "resolved product targeting expression"),
        "state": find(lambda s: s == "state"),
        "bid": find(lambda s: s == "bid"),
        "impressions": find(lambda s: s == "impressions"),
        "clicks": find(lambda s: s == "clicks"),
        "spend": find(lambda s: s == "spend", lambda s: "spend" in s),
        "sales": find(lambda s: "7 day" in s and "sales" in s, lambda s: s == "sales", lambda s: "sales" in s),
        "orders": find(lambda s: "7 day" in s and "orders" in s, lambda s: s == "orders", lambda s: "orders" in s),
        "units": find(lambda s: "7 day" in s and "units" in s, lambda s: s == "units", lambda s: "units" in s),
    }


def parse_targets(path: str) -> list[dict]:
    """Positive Keyword + Product Targeting rows of the SP bulk, as dicts.

    Negatives are skipped outright — they carry no metrics and must never be
    migrated as positives. Auto-campaign clause rows are kept (they're real spend)
    but flagged, since Amazon rejects an attempt to create them in a manual campaign.
    """
    df = pa._read_df(path)
    ctypes = pa.classify_campaigns(df)
    cols = _resolve(df)
    if not cols.get("entity"):
        raise ValueError("That sheet has no 'Entity' column — is it the Sponsored Products bulk?")
    camp_names, ag_names = pa.name_maps(df)

    def g(r, key):
        c = cols.get(key)
        return r.get(c) if c else None

    rows: list[dict] = []
    for _, r in df.iterrows():
        ent = pa._str(g(r, "entity")).lower()
        if ent == "keyword":
            entity = "keyword"
        elif ent == "product targeting":
            entity = "product_target"
        else:
            continue        # campaigns, ad groups, product ads, negatives -> not ours
        cid = bulkfmt.idstr(pa._str(g(r, "campaign_id")))
        if not cid:
            continue
        kw = pa._str(g(r, "keyword_text"))
        match = pa._str(g(r, "match_type"))
        expr = pa._str(g(r, "expression"))
        # an auto campaign's clause rows arrive as Product Targeting whose expression
        # (or match type) is one of close-match / loose-match / substitutes / complements
        clause = (expr or match).strip().lower()
        is_clause = clause in bulkfmt.AUTO_CLAUSES
        tid = pa._str(g(r, "keyword_id")) if entity == "keyword" else pa._str(g(r, "target_id"))
        bid = g(r, "bid")
        agid = bulkfmt.idstr(pa._str(g(r, "ad_group_id"))) or None
        rows.append(dict(
            entity=entity,
            target_id=bulkfmt.idstr(tid) or None,
            campaign_id=cid,
            campaign_name=pa._pick_name(r, cols, "campaign_name", camp_names, cid),
            campaign_type=ctypes.get(cid),
            ad_group_id=agid,
            ad_group_name=pa._pick_name(r, cols, "ad_group_name", ag_names, agid),
            keyword_text=kw or None,
            match_type=match or None,
            expression=expr or None,
            is_auto_clause=is_clause,
            state=pa._str(g(r, "state")) or None,
            bid=round(pa._num(bid), 2) if pa._str(bid) else None,
            impressions=int(pa._num(g(r, "impressions"))),
            clicks=int(pa._num(g(r, "clicks"))),
            spend=round(pa._num(g(r, "spend")), 2),
            sales=round(pa._num(g(r, "sales")), 2),
            orders=int(pa._num(g(r, "orders"))),
            units=int(pa._num(g(r, "units"))),
        ))
    return rows


def parse_placements(path: str) -> list[dict]:
    """The bulk's `Bidding Adjustment` rows — current placement multipliers per
    campaign. They carry no metrics (those live in the Placement report), so this is
    only the starting percentage the Top-of-Search rule raises from."""
    df = pa._read_df(path)
    cols = _resolve(df)
    norm = {str(c).strip().lower(): c for c in df.columns}
    c_place = norm.get("placement")
    c_pct = norm.get("percentage")
    if not cols.get("entity") or not c_place:
        return []
    camp_names, _ = pa.name_maps(df)
    rows = []
    for _, r in df.iterrows():
        if pa._str(r.get(cols["entity"])).lower() != "bidding adjustment":
            continue
        cid = bulkfmt.idstr(pa._str(r.get(cols["campaign_id"]))) if cols.get("campaign_id") else ""
        place = pa._str(r.get(c_place))
        if not cid or not place:
            continue
        rows.append(dict(campaign_id=cid,
                         campaign_name=pa._pick_name(r, cols, "campaign_name", camp_names, cid),
                         placement=place,
                         percentage=round(pa._num(r.get(c_pct)) if c_pct else 0.0, 2)))
    return rows


def placement_map(db: Session) -> dict[str, dict]:
    """campaign_id -> {placement: percentage}, for the funnel's Top-of-Search rule."""
    _ensure_schema(db)
    out: dict[str, dict] = {}
    for p in db.query(md.AdsStudioPlacementFact).all():
        out.setdefault(p.campaign_id, {})[p.placement] = p.percentage or 0.0
    return out


def ingest(db: Session, path: str) -> int:
    """Replace the target snapshot only (used when another panel owns the ad rows)."""
    _ensure_schema(db)
    rows = parse_targets(path)
    db.query(md.AdsStudioTargetFact).delete()
    if rows:
        db.bulk_insert_mappings(md.AdsStudioTargetFact, rows)
    db.commit()
    return len(rows)


def ingest_bulk(db: Session, path: str) -> dict:
    """Ads Studio's OWN upload: one SP bulk -> its Product Ad rows AND its Keyword /
    Product Targeting rows, replacing both snapshots together.

    A bulk with no target rows is still accepted (an all-auto account has no keyword
    lines) — Studio then reports zero targets instead of rejecting the upload.
    """
    _ensure_schema(db)
    ads = pa.parse_product_ads(path)          # raises with a friendly message if none
    targets = parse_targets(path)
    places = parse_placements(path)
    db.query(md.AdsStudioAdFact).delete()
    db.query(md.AdsStudioTargetFact).delete()
    db.query(md.AdsStudioPlacementFact).delete()
    db.bulk_insert_mappings(md.AdsStudioAdFact, ads)
    if targets:
        db.bulk_insert_mappings(md.AdsStudioTargetFact, targets)
    if places:
        db.bulk_insert_mappings(md.AdsStudioPlacementFact, places)
    db.commit()
    return {"product_ads": len(ads), "targets": len(targets), "placements": len(places),
            "asins": len({a["asin"] for a in ads if a["asin"]})}


def products(db: Session) -> dict:
    """The Product-Ads table, rendered off Ads Studio's own upload, with each
    product tiered HERO/A/B/C/D against the others in the same upload."""
    _ensure_schema(db)
    out = pa.summary(db, model=md.AdsStudioAdFact)
    goal = get_settings(db)["target_acos"]
    # the summary rows carry metrics flat; perftier wants them under `metrics`
    wrapped = [{**r, "metrics": r} for r in out.get("rows") or []]
    tiered = pt.assign(wrapped, goal)
    out["rows"] = [{**{k: v for k, v in r.items() if k != "metrics"}}
                   for r in tiered["rows"]]
    out["tiering"] = {"method": tiered["method"], "breaks": tiered["breaks"],
                      "counts": tiered["counts"], "target_acos": goal}
    return out


def has_data(db: Session) -> bool:
    _ensure_schema(db)
    return db.query(md.AdsStudioAdFact.id).first() is not None


def has_targets(db: Session) -> bool:
    _ensure_schema(db)
    return db.query(md.AdsStudioTargetFact.id).first() is not None


def delete_all(db: Session) -> int:
    _ensure_schema(db)
    n = db.query(md.AdsStudioTargetFact).delete()
    n += db.query(md.AdsStudioAdFact).delete()
    db.query(md.AdsStudioPlacementFact).delete()
    db.commit()
    return n


# ---- verdicts ----------------------------------------------------------------
def classify(m: dict, target_acos: float, min_clicks: int) -> tuple[str, str]:
    """(verdict, human reason) for one target's metrics. Pure — easy to test."""
    orders = m.get("orders") or 0
    clicks = m.get("clicks") or 0
    acos = m.get("acos")
    if orders >= 1:
        if acos is not None and acos <= target_acos:
            return "keep", f"{orders} order(s) at {acos * 100:.0f}% ACoS — at or under goal"
        return "drop", f"{orders} order(s) at {acos * 100:.0f}% ACoS — over goal" if acos is not None \
            else f"{orders} order(s), no spend recorded"
    if clicks >= min_clicks:
        return "drop", f"{clicks} clicks, no orders"
    return "review", f"only {clicks} click(s) — too thin to judge"


def _metrics(o) -> dict:
    return M.all_metrics(impressions=o.impressions or 0, clicks=o.clicks or 0,
                         spend=o.spend or 0.0, sales=o.sales or 0.0,
                         orders=o.orders or 0, units=o.units or 0)


def _label(t) -> str:
    if t.entity == "keyword":
        return t.keyword_text or "(keyword)"
    return t.expression or "(product target)"


# ---- the board ---------------------------------------------------------------
# the campaign-type chooser: 'auto' | 'manual' (which covers keyword + product targeting)
TYPE_GROUPS = {"auto": {"auto"}, "manual": {"keyword", "product", "manual"}}


def _wanted_types(campaign_types: list[str] | None) -> set[str] | None:
    """Expand the UI's Automatic / Manual choice into concrete campaign_type values.
    None (or nothing chosen) = no filter."""
    if not campaign_types:
        return None
    out: set[str] = set()
    for c in campaign_types:
        out |= TYPE_GROUPS.get(c, {c})
    return out or None


def filter_tiers(b: dict, tiers: list[str] | None) -> dict:
    """Narrow an already-built board to the chosen performance tiers.

    Applied AFTER tiering, never before: the tiers are relative to the whole
    selection, so filtering first would re-rank the survivors and a campaign could
    be promoted to HERO purely because its betters were hidden.
    """
    keep = {str(x).strip().upper() for x in (tiers or []) if str(x).strip()}
    if not keep:
        return b
    kept = [c for c in b["campaigns"] if (c.get("tier") or "") in keep]
    counts = {"keep": 0, "drop": 0, "review": 0}
    tot = dict(impressions=0, clicks=0, spend=0.0, sales=0.0, orders=0, units=0)
    for c in kept:
        for k in counts:
            counts[k] += c["counts"][k]
        m = c["metrics"]
        for k in tot:
            tot[k] += m.get(k) or 0
    return {**b, "campaigns": kept, "counts": counts, "totals": M.all_metrics(**tot),
            "tier_filter": sorted(keep)}


def board(db: Session, asins: list[str], t: Thresholds,
          campaign_types: list[str] | None = None) -> dict:
    """Every campaign advertising the selected ASINs, with its targets judged
    against the goal ACoS. This is what the Studio board renders.

    `campaign_types` is the panel's Automatic / Manual chooser — 'auto' keeps
    automatic campaigns, 'manual' keeps keyword- and product-targeting ones.
    """
    _ensure_schema(db)
    want = {a.strip().upper() for a in asins if a and a.strip()}
    keep_types = _wanted_types(campaign_types)
    empty = {"asins": sorted(want), "campaigns": [], "target_acos": t.target_acos,
             "min_clicks": t.min_clicks, "totals": {},
             "counts": {"keep": 0, "drop": 0, "review": 0}}
    if not want:
        return {**empty, "asins": []}

    # campaign -> the selected ASINs it advertises (from Ads Studio's own upload)
    ads = db.query(md.AdsStudioAdFact).all()
    camp_asins: dict[str, set[str]] = {}
    camp_meta: dict[str, dict] = {}
    for a in ads:
        if not a.campaign_id or not a.asin or a.asin.upper() not in want:
            continue
        if keep_types is not None and (a.campaign_type or "manual") not in keep_types:
            continue
        camp_asins.setdefault(a.campaign_id, set()).add(a.asin.upper())
        camp_meta.setdefault(a.campaign_id, {
            "campaign_name": a.campaign_name, "campaign_type": a.campaign_type,
            "state": a.state,
        })

    if not camp_asins:
        return empty

    targets = (db.query(md.AdsStudioTargetFact)
                 .filter(md.AdsStudioTargetFact.campaign_id.in_(list(camp_asins)))
                 .all())
    by_camp: dict[str, list] = {}
    for tg in targets:
        by_camp.setdefault(tg.campaign_id, []).append(tg)

    counts = {"keep": 0, "drop": 0, "review": 0}
    tot = dict(impressions=0, clicks=0, spend=0.0, sales=0.0, orders=0, units=0)
    campaigns = []
    for cid, asin_set in camp_asins.items():
        meta = camp_meta.get(cid, {})
        rows, groups, c_counts = [], {}, {"keep": 0, "drop": 0, "review": 0}
        c_tot = dict(impressions=0, clicks=0, spend=0.0, sales=0.0, orders=0, units=0)
        for tg in by_camp.get(cid, []):
            m = _metrics(tg)
            verdict, reason = classify(m, t.target_acos, t.min_clicks)
            c_counts[verdict] += 1
            for k in c_tot:
                c_tot[k] += getattr(tg, k) or 0
            if tg.ad_group_id:
                groups.setdefault(tg.ad_group_id, tg.ad_group_name)
            rows.append({
                "id": tg.target_id, "entity": tg.entity, "label": _label(tg),
                "keyword_text": tg.keyword_text, "match_type": tg.match_type,
                "expression": tg.expression, "is_auto_clause": bool(tg.is_auto_clause),
                "state": tg.state, "bid": tg.bid,
                "campaign_id": tg.campaign_id, "ad_group_id": tg.ad_group_id,
                "ad_group_name": tg.ad_group_name,
                "metrics": m, "verdict": verdict, "reason": reason,
            })
        for k in counts:
            counts[k] += c_counts[k]
        for k in tot:
            tot[k] += c_tot[k]
        rows.sort(key=lambda r: (r["metrics"].get("spend") or 0), reverse=True)
        # the Product Ad row is the primary source of the name; fall back to what the
        # campaign's own target rows carry before giving up and showing the raw ID
        name = meta.get("campaign_name") or next(
            (t.campaign_name for t in by_camp.get(cid, []) if t.campaign_name), None)
        campaigns.append({
            "campaign_id": cid,
            "campaign_name": name or cid,
            "has_name": bool(name),
            "campaign_type": meta.get("campaign_type") or "manual",
            "state": meta.get("state"),
            "asins": sorted(asin_set),
            "ad_groups": [{"ad_group_id": g, "ad_group_name": n} for g, n in groups.items()],
            "targets": rows,
            "counts": c_counts,
            "metrics": M.all_metrics(**c_tot),
        })
    campaigns.sort(key=lambda c: (c["metrics"].get("spend") or 0), reverse=True)
    # HERO / A / B / C / D, clustered on this selection's own performance
    tiered = pt.assign(campaigns, t.target_acos)
    campaigns = tiered["rows"]
    return {
        "asins": sorted(want),
        "target_acos": t.target_acos,
        "min_clicks": t.min_clicks,
        "campaigns": campaigns,
        "counts": counts,
        "totals": M.all_metrics(**tot),
        "tiering": {"method": tiered["method"], "breaks": tiered["breaks"],
                    "counts": tiered["counts"]},
    }


# ---- the consolidation plan --------------------------------------------------
def _dest_bid(row: dict, target_acos: float) -> float:
    """Bid to open the migrated target at: its own bid, else goal-ACoS CPC math."""
    if row.get("bid"):
        return round(float(row["bid"]), 2)
    m = row.get("metrics") or {}
    suggested = M.target_cpc_bid(m.get("clicks") or 0, m.get("sales") or 0.0, target_acos,
                                 None, fn.PROMOTE_MAX_CUT, fn.PROMOTE_MAX_UP, _MIN_BID)
    return round(max(suggested or _MIN_BID, _MIN_BID), 2)


def _sig(row: dict) -> tuple:
    """In-destination identity of a target — Amazon rejects a duplicate of either."""
    if row["entity"] == "keyword":
        return ("kw", (row.get("keyword_text") or "").strip().lower(),
                (row.get("match_type") or "").strip().lower())
    return ("pt", (row.get("expression") or "").strip().lower())


def plan(db: Session, groups: list[dict], t: Thresholds) -> dict:
    """Turn the board's drag-and-dropped groups into an actionable plan.

    Each group is `{name, destination_campaign_id, destination_ad_group_id,
    source_campaign_ids: [...]}`. For every group:

      migrate         keep-verdict targets from the sources, created in the destination
      pause_targets   drop-verdict targets anywhere in the group (destination included)
      skipped         keep-verdict targets that CAN'T migrate, each with the reason
      campaign_pauses the drained source campaigns (never pre-selected — the caller
                      decides, since pausing a campaign stops its sales immediately)
    """
    all_ids = [cid for g in groups for cid in
               ([g.get("destination_campaign_id")] + list(g.get("source_campaign_ids") or []))
               if cid]
    b = board(db, _asins_for(db, all_ids), t)
    by_id = {c["campaign_id"]: c for c in b["campaigns"]}

    out_groups = []
    n_mig = n_pause = n_skip = 0
    for g in groups:
        dest_id = bulkfmt.idstr(g.get("destination_campaign_id") or "")
        dest = by_id.get(dest_id)
        if not dest:
            continue
        dest_ag = bulkfmt.idstr(g.get("destination_ad_group_id") or "") or \
            (dest["ad_groups"][0]["ad_group_id"] if dest["ad_groups"] else None)
        sources = [by_id[c] for c in (g.get("source_campaign_ids") or [])
                   if c in by_id and c != dest_id]

        # what the destination already carries -> never re-create it (Duplicate Keyword)
        seen = {_sig(r) for r in dest["targets"]}
        migrate, skipped, pauses = [], [], []

        # drop-verdict targets are paused wherever they live, destination included
        for camp in [dest] + sources:
            for r in camp["targets"]:
                if r["verdict"] == "drop" and r["id"]:
                    pauses.append({**r, "campaign_name": camp["campaign_name"]})

        for camp in sources:
            for r in camp["targets"]:
                if r["verdict"] != "keep":
                    continue
                reason = None
                if r["is_auto_clause"]:
                    reason = "auto-campaign clause — Amazon can't create it in a manual campaign"
                elif r["entity"] == "keyword" and not bulkfmt.valid_keyword(r.get("keyword_text")):
                    reason = "keyword text Amazon would reject (length / characters)"
                elif r["entity"] == "product_target" and not (r.get("expression") or "").strip():
                    reason = "product target has no expression to copy"
                elif not dest_ag:
                    reason = "destination campaign has no ad group to receive it"
                elif _sig(r) in seen:
                    reason = "destination already has this target"
                if reason:
                    skipped.append({**r, "campaign_name": camp["campaign_name"], "skip_reason": reason})
                    continue
                seen.add(_sig(r))
                migrate.append({
                    **r,
                    "from_campaign_id": camp["campaign_id"],
                    "from_campaign_name": camp["campaign_name"],
                    "to_campaign_id": dest_id,
                    "to_ad_group_id": dest_ag,
                    "new_bid": _dest_bid(r, t.target_acos),
                })

        campaign_pauses = [{
            "campaign_id": c["campaign_id"], "campaign_name": c["campaign_name"],
            "campaign_type": c["campaign_type"], "metrics": c["metrics"],
            "migrated": sum(1 for m in migrate if m["from_campaign_id"] == c["campaign_id"]),
        } for c in sources]

        n_mig += len(migrate); n_pause += len(pauses); n_skip += len(skipped)
        out_groups.append({
            "name": g.get("name") or dest["campaign_name"],
            # "destination" == the boss campaign everything is consolidated into
            "destination": {"campaign_id": dest_id, "campaign_name": dest["campaign_name"],
                            "campaign_type": dest["campaign_type"], "ad_group_id": dest_ag},
            "sources": [{"campaign_id": c["campaign_id"], "campaign_name": c["campaign_name"],
                         "campaign_type": c["campaign_type"]} for c in sources],
            "migrate": migrate, "pause_targets": pauses, "skipped": skipped,
            "campaign_pauses": campaign_pauses,
            "consolidated": _consolidated(dest, sources, migrate, pauses),
        })

    return {"groups": out_groups, "target_acos": t.target_acos,
            "counts": {"migrate": n_mig, "pause_targets": n_pause, "skipped": n_skip},
            "consolidated": [g["consolidated"] for g in out_groups]}


def _consolidated(dest: dict, sources: list[dict], migrate: list[dict],
                  pauses: list[dict]) -> dict:
    """What the boss campaign looks like once the plan is applied — the panel's
    bottom section. Metrics are the trailing numbers of the targets that SURVIVE
    (the boss's own keepers + everything migrated in), so it reads as the campaign's
    performance had it been consolidated all along. It is not a forecast."""
    paused_ids = {p["id"] for p in pauses if p.get("id")}
    survivors = [r for r in dest["targets"]
                 if r["verdict"] != "drop" and r["id"] not in paused_ids]
    tot = dict(impressions=0, clicks=0, spend=0.0, sales=0.0, orders=0, units=0)
    for r in survivors + migrate:
        m = r.get("metrics") or {}
        for k in tot:
            tot[k] += m.get(k) or 0
    # spend switched off by this plan: the paused targets plus the drained campaigns
    off = round(sum((p.get("metrics") or {}).get("spend") or 0 for p in pauses), 2)
    asins = sorted({a for c in [dest] + sources for a in (c.get("asins") or [])})
    return {
        "campaign_id": dest["campaign_id"],
        "campaign_name": dest["campaign_name"],
        "campaign_type": dest["campaign_type"],
        "ad_group_id": (dest["ad_groups"][0]["ad_group_id"] if dest["ad_groups"] else None),
        "asins": asins,
        "scope": "multi" if len(asins) > 1 else "single",
        "campaigns_absorbed": len(sources),
        "targets_kept": len(survivors),
        "targets_migrated": len(migrate),
        "targets_total": len(survivors) + len(migrate),
        "spend_switched_off": off,
        "metrics": M.all_metrics(**tot),
    }


def _asins_for(db: Session, campaign_ids: list[str]) -> list[str]:
    """The ASINs advertised by these campaigns — lets plan() rebuild the same board."""
    if not campaign_ids:
        return []
    rows = (db.query(md.AdsStudioAdFact.asin)
              .filter(md.AdsStudioAdFact.campaign_id.in_(list(set(campaign_ids))))
              .distinct().all())
    return [r[0] for r in rows if r[0]]


# ---- the funnel strategy ------------------------------------------------------
def funnel_report(db: Session, asins: list[str], t: Thresholds,
                  campaign_types: list[str] | None = None) -> dict:
    """Funnel health for the selected products: tier rollups, the Phase-1 budget
    split, structural gaps, never-mix violations, and the Top-of-Search rule."""
    b = board(db, asins, t, campaign_types)
    rep = fn.report(b["campaigns"], t.target_acos)
    rep["placements"] = fn.placement_recommendations(
        b["campaigns"], placement_map(db), t.target_acos)
    # what the board already knows, so the panel renders both from one call
    rep["campaigns"] = [{**c, "tier": fn.campaign_tier(c)} for c in b["campaigns"]]
    rep["asins"] = b["asins"]
    rep["counts"] = b["counts"]
    rep["totals"] = b["totals"]
    return rep


def funnel_plan(db: Session, asins: list[str], bosses: dict[str, str], t: Thresholds,
                campaign_types: list[str] | None = None) -> dict:
    """Route every winner to the tier the funnel says it belongs in."""
    b = board(db, asins, t, campaign_types)
    out = fn.plan(b["campaigns"], bosses, t.target_acos, min_bid=_MIN_BID)
    out["target_acos"] = t.target_acos
    out["placements"] = fn.placement_recommendations(
        b["campaigns"], placement_map(db), t.target_acos)
    return out


PLACEMENT_COLS = ["Product", "Entity", "Operation", "Campaign ID", "Placement",
                  "Percentage"]


def funnel_to_bulk(promotes: list[dict], migrates: list[dict], negatives: list[dict],
                   pauses: list[dict], placements: list[dict] | None = None) -> bytes:
    """The funnel plan -> one Amazon SP bulk.

    Row order is the funnel's own order and matters: creates land first so the money
    tier owns the term, then the upstream negatives, then the pauses. Placement
    adjustments ride in a second sheet — Amazon accepts `Bidding Adjustment` rows in
    the campaigns sheet, but keeping them separate makes the file easy to eyeball.
    """
    rows, seen = [], set()

    def add_create(m: dict):
        cid = bulkfmt.idstr(m.get("to_campaign_id"))
        ag = bulkfmt.idstr(m.get("to_ad_group_id"))
        if not cid or not ag:
            return
        row = _blank()
        row.update({"Product": "Sponsored Products", "Operation": "create",
                    "Campaign ID": cid, "Ad Group ID": ag,
                    "Bid": m.get("new_bid"), "State": "enabled"})
        if m.get("entity") == "keyword":
            text = (m.get("keyword_text") or "").strip()
            if not bulkfmt.valid_keyword(text):
                return
            sig = ("c", "kw", cid, ag, text.lower())
            row.update({"Entity": "Keyword", "Keyword Text": text, "Match Type": "Exact"})
        else:
            expr = bulkfmt.neg_pt_expression(m.get("expression"))   # same ASIN-only rule
            if not expr:
                return
            sig = ("c", "pt", cid, ag, expr.lower())
            row.update({"Entity": "Product Targeting", "Product Targeting Expression": expr})
        if sig in seen:
            return
        seen.add(sig)
        rows.append(row)

    for m in (promotes or []) + (migrates or []):
        add_create(m)

    for n in negatives or []:
        cid = bulkfmt.idstr(n.get("campaign_id"))
        if not cid:
            continue
        # Prefer an ad-group negative (surgical). With no ad group to hang it on, fall
        # back to a campaign-level negative rather than dropping the sculpt entirely —
        # a promotion with no upstream negative means paying for the term twice.
        ag = bulkfmt.idstr(n.get("ad_group_id"))
        row = _blank()
        row.update({"Product": "Sponsored Products", "Operation": "create",
                    "Campaign ID": cid, "Ad Group ID": ag or None, "State": "enabled"})
        if n.get("entity") == "keyword":
            text = (n.get("keyword_text") or "").strip()
            if not bulkfmt.valid_keyword(text):
                continue
            sig = ("n", "kw", ag or cid, text.lower())
            row.update({"Entity": "Negative Keyword" if ag else "Campaign Negative Keyword",
                        "Keyword Text": text, "Match Type": "Negative Exact"})
        else:
            expr = bulkfmt.neg_pt_expression(n.get("expression"))
            if not expr:
                continue
            if not ag:
                continue        # SP has no campaign-level negative product targeting
            sig = ("n", "pt", ag, expr.lower())
            row.update({"Entity": "Negative Product Targeting",
                        "Product Targeting Expression": expr})
        if sig in seen:
            continue
        seen.add(sig)
        rows.append(row)

    for p in pauses or []:
        tid = bulkfmt.idstr(p.get("id"))
        cid = bulkfmt.idstr(p.get("campaign_id"))
        if not tid or not cid:
            continue
        is_kw = p.get("entity") == "keyword"
        sig = ("u", "kw" if is_kw else "pt", tid)
        if sig in seen:
            continue
        seen.add(sig)
        row = _blank()
        row.update({"Product": "Sponsored Products",
                    "Entity": "Keyword" if is_kw else "Product Targeting",
                    "Operation": "update", "Campaign ID": cid,
                    "Ad Group ID": bulkfmt.idstr(p.get("ad_group_id")), "State": "paused"})
        row["Keyword ID" if is_kw else "Product Targeting ID"] = tid
        rows.append(row)

    place_rows = []
    for p in placements or []:
        cid = bulkfmt.idstr(p.get("campaign_id"))
        if not cid:
            continue
        place_rows.append({"Product": "Sponsored Products", "Entity": "Bidding Adjustment",
                           "Operation": "update", "Campaign ID": cid,
                           "Placement": p.get("placement_raw") or "Placement Top",
                           "Percentage": p.get("new_pct")})

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame(rows, columns=BULK_COLS).to_excel(
            w, index=False, sheet_name="Sponsored Products Campaigns")
        if place_rows:
            pd.DataFrame(place_rows, columns=PLACEMENT_COLS).to_excel(
                w, index=False, sheet_name="Placement Adjustments")
    return buf.getvalue()


# ---- bulk emit ---------------------------------------------------------------
def _blank() -> dict:
    return {c: None for c in BULK_COLS}


def to_bulk(migrate: list[dict], pause_targets: list[dict],
            campaign_pauses: list[dict]) -> bytes:
    """Chosen migrations + target pauses + campaign pauses → one Amazon SP bulk.

    Order matters: creates land before pauses so the destination owns the winners
    before their old homes go dark. De-duplicated so Amazon never rejects on
    Duplicate Id / Duplicate Keyword Text / already exists.
    """
    rows, seen = [], set()

    for m in migrate or []:
        cid = bulkfmt.idstr(m.get("to_campaign_id"))
        ag = bulkfmt.idstr(m.get("to_ad_group_id"))
        if not cid or not ag:
            continue
        is_kw = m.get("entity") == "keyword"
        if is_kw:
            text = (m.get("keyword_text") or "").strip()
            if not bulkfmt.valid_keyword(text):
                continue
            sig = ("c", cid, ag, "kw", text.lower(), (m.get("match_type") or "").lower())
        else:
            expr = (m.get("expression") or "").strip()
            if not expr or expr.lower() in bulkfmt.AUTO_CLAUSES:
                continue
            sig = ("c", cid, ag, "pt", expr.lower())
        if sig in seen:
            continue
        seen.add(sig)
        row = _blank()
        row.update({"Product": "Sponsored Products",
                    "Entity": "Keyword" if is_kw else "Product Targeting",
                    "Operation": "create", "Campaign ID": cid, "Ad Group ID": ag,
                    "Bid": m.get("new_bid"), "State": "enabled"})
        if is_kw:
            row.update({"Keyword Text": (m.get("keyword_text") or "").strip(),
                        "Match Type": (m.get("match_type") or "exact").lower()})
        else:
            row["Product Targeting Expression"] = (m.get("expression") or "").strip()
        rows.append(row)

    for p in pause_targets or []:
        tid = bulkfmt.idstr(p.get("id"))
        cid = bulkfmt.idstr(p.get("campaign_id"))
        if not tid or not cid:
            continue
        is_kw = p.get("entity") == "keyword"
        sig = ("u", "kw" if is_kw else "pt", tid)
        if sig in seen:
            continue
        seen.add(sig)
        row = _blank()
        row.update({"Product": "Sponsored Products",
                    "Entity": "Keyword" if is_kw else "Product Targeting",
                    "Operation": "update", "Campaign ID": cid,
                    "Ad Group ID": bulkfmt.idstr(p.get("ad_group_id")),
                    "State": "paused"})
        row["Keyword ID" if is_kw else "Product Targeting ID"] = tid
        rows.append(row)

    for c in campaign_pauses or []:
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
