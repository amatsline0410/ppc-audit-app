"""Stage 5: audit. Build the ASIN-rooted tree and apply flag rules.

Store campaign-rooted, view ASIN-rooted: we re-root at query time by walking
ad -> ad_group -> campaign and grouping by the ad's ASIN.
"""
from __future__ import annotations
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import func
from .. import models as md
from ..config import Thresholds
from .. import metrics as M
from ..rules import run_target_rules, Flag


def active_snapshot(db: Session):
    """Latest PPC snapshot = the 'current period'. Point-in-time views default
    here so they never silently sum lifetime across multiple uploads."""
    return db.query(func.max(md.FactPerformance.snapshot_date)).scalar()


# --- build_tree cache: the tree is a pure function of (db, snapshot, fact rows).
# Re-summing dims+facts in Python is the hot path; cache it across requests and
# invalidate via max(perf_id), which changes whenever fact rows are (re)written.
_tree_cache: dict = {}


def _fact_version(db: Session):
    return db.query(func.max(md.FactPerformance.perf_id)).scalar()


def invalidate_tree_cache():
    _tree_cache.clear()


def _fact_map(db: Session, snapshot=None) -> dict:
    """Aggregate fact rows -> {(entity_type, entity_id): summed metrics}.
    snapshot None = lifetime (all dates); pass a date to pin one period."""
    q = db.query(
        md.FactPerformance.entity_type, md.FactPerformance.entity_id,
        func.sum(md.FactPerformance.impressions), func.sum(md.FactPerformance.clicks),
        func.sum(md.FactPerformance.spend), func.sum(md.FactPerformance.sales),
        func.sum(md.FactPerformance.orders), func.sum(md.FactPerformance.units))
    if snapshot:
        q = q.filter(md.FactPerformance.snapshot_date == snapshot)
    q = q.group_by(md.FactPerformance.entity_type, md.FactPerformance.entity_id)
    out = {}
    for et, eid, im, cl, sp, sa, od, un in q.all():
        out[(et, eid)] = M.all_metrics(im or 0, cl or 0, sp or 0, sa or 0, od or 0, un or 0)
    return out


def build_tree(db: Session, snapshot=None) -> dict:
    """ASIN -> campaigns -> ad_groups -> {ads, targets}, metrics on each node.
    Defaults to the active (latest) snapshot for a consistent current-period view.
    Cached per (db, snapshot, fact-version); read-only — callers must not mutate."""
    snap = snapshot or active_snapshot(db)
    key = (str(db.get_bind().url), snap.isoformat() if snap else None, _fact_version(db))
    hit = _tree_cache.get(key)
    if hit is not None:
        return hit

    fm = _fact_map(db, snap)
    # column tuples, not ORM entities — dim tables run to 300k+ rows and
    # instance materialization (not the SQL) is what made cold builds slow
    ads = db.query(md.DimAd.ad_id, md.DimAd.ad_group_id, md.DimAd.asin,
                   md.DimAd.sku, md.DimAd.state).all()
    groups = {gid: (cid, name, state) for gid, cid, name, state in
              db.query(md.DimAdGroup.ad_group_id, md.DimAdGroup.campaign_id,
                       md.DimAdGroup.name, md.DimAdGroup.state)}
    camps = {cid: (name, state) for cid, name, state in
             db.query(md.DimCampaign.campaign_id, md.DimCampaign.name,
                      md.DimCampaign.state)}
    targets_by_ag = defaultdict(list)
    # stored negatives excluded in SQL — they're not biddable targets
    for row in db.query(md.DimTarget.target_id, md.DimTarget.ad_group_id,
                        md.DimTarget.target_type, md.DimTarget.keyword_text,
                        md.DimTarget.expression, md.DimTarget.match_type,
                        md.DimTarget.bid, md.DimTarget.state) \
            .filter(md.DimTarget.target_type.in_(("keyword", "product_target"))).all():
        targets_by_ag[row[1]].append(row)

    # one shared zero-metrics dict for the (many) no-fact nodes; the tree is
    # documented read-only, so aliasing is safe and skips 100k+ dict builds
    empty = M.all_metrics()
    tree = defaultdict(lambda: {"asin": None, "campaigns": {}})
    for ad_id, gid, ad_asin, sku, ad_state in ads:
        asin = ad_asin or "UNKNOWN"
        g = groups.get(gid)
        if not g:
            continue
        cid, g_name, g_state = g
        camp = camps.get(cid)
        node = tree[asin]; node["asin"] = asin
        cnode = node["campaigns"].setdefault(cid, {
            "campaign_id": cid, "name": camp[0] if camp else None,
            "state": camp[1] if camp else None,
            "metrics": fm.get(("campaign", cid), empty),
            "ad_groups": {}})
        agnode = cnode["ad_groups"].get(gid)
        if agnode is None:
            # fill the group's targets once at node creation — a second ad in the
            # same group must not duplicate (or rescan) the target list
            agnode = cnode["ad_groups"][gid] = {
                "ad_group_id": gid, "name": g_name, "state": g_state,
                "metrics": fm.get(("ad_group", gid), empty),
                "ads": [],
                "targets": [{
                    "target_id": tid, "type": ttype, "label": kw or expr,
                    "match_type": mt, "bid": bid, "state": st,
                    "metrics": fm.get(("target", tid), empty)}
                    for tid, _gid, ttype, kw, expr, mt, bid, st in targets_by_ag.get(gid, ())]}
        agnode["ads"].append({"ad_id": ad_id, "asin": ad_asin, "sku": sku,
                              "state": ad_state, "metrics": fm.get(("ad", ad_id), empty)})
    # collapse dict->list for JSON
    result = {}
    for asin, node in tree.items():
        camps_list = []
        for c in node["campaigns"].values():
            c["ad_groups"] = list(c["ad_groups"].values())
            camps_list.append(c)
        result[asin] = {"asin": asin, "campaigns": camps_list}
    if len(_tree_cache) > 64:
        _tree_cache.clear()
    _tree_cache[key] = result
    return result


def _over_periods(db: Session, target_acos: float) -> dict:
    """Per (entity_type, entity_id): count of trailing consecutive snapshots that
    were over goal ACoS *with sales*. Drives the reduce->monitor->pause ladder."""
    rows = (db.query(md.FactPerformance.entity_type, md.FactPerformance.entity_id,
                     md.FactPerformance.snapshot_date,
                     func.sum(md.FactPerformance.spend), func.sum(md.FactPerformance.sales),
                     func.sum(md.FactPerformance.orders))
            .group_by(md.FactPerformance.entity_type, md.FactPerformance.entity_id,
                      md.FactPerformance.snapshot_date).all())
    hist = defaultdict(list)
    for et, eid, snap, sp, sa, od in rows:
        hist[(et, eid)].append((snap, sp or 0, sa or 0, od or 0))
    out = {}
    for key, lst in hist.items():
        lst.sort(key=lambda x: x[0])
        cnt = 0
        for snap, sp, sa, od in reversed(lst):
            acos = sp / sa if sa else None
            if od > 0 and acos is not None and acos > target_acos:
                cnt += 1
            else:
                break
        out[key] = cnt
    return out


def audit(db: Session, thresholds: Thresholds, snapshot=None) -> list[Flag]:
    """Run flag rules over every target (and enabled-only is handled by caller filter)."""
    from . import benchmark as bench
    snap = snapshot or active_snapshot(db)        # current period, not lifetime
    fm = _fact_map(db, snap)
    over_map = _over_periods(db, thresholds.target_acos)
    be_map = bench.break_even_map(db)             # asin -> break-even ACoS
    goal_map = bench.goal_map(db)                 # asin -> per-ASIN goal ACoS override
    # map ad_group -> asin / sku via its ads. SKU is the break-even fallback:
    # when the ad's ASIN isn't in the benchmark/catalog map, match the catalog
    # LISTING by normalized SKU (same join Product Ads uses).
    from .. import database as dbmod
    from . import catalog as cat
    sku_be = cat.be_by_sku(db.info.get("store"),
                           dbmod.get_project_econ(db.info.get("store"), db.info.get("project")))
    ag_asin, ag_sku = {}, {}
    for gid, asin, sku in db.query(md.DimAd.ad_group_id, md.DimAd.asin, md.DimAd.sku):
        ag_asin.setdefault(gid, asin)
        if sku:
            ag_sku.setdefault(gid, sku)

    # column tuples + only targets that actually have fact rows: the dim table can
    # be 100x the fact table (negatives + long-tail), so ORM-loading every DimTarget
    # dominated audit time while the loop skipped almost all of them
    fact_ids = (db.query(md.FactPerformance.entity_id)
                .filter(md.FactPerformance.entity_type == "target").distinct())
    rows = (db.query(md.DimTarget.target_id, md.DimTarget.ad_group_id,
                     md.DimTarget.keyword_text, md.DimTarget.expression, md.DimTarget.bid)
            .filter(md.DimTarget.target_id.in_(fact_ids)).all())

    flags: list[Flag] = []
    for tid, gid, kw, expr, bid in rows:
        m = fm.get(("target", tid))
        if not m:
            continue
        asin = ag_asin.get(gid)
        # per-ASIN goal override from the benchmark file wins over the global goal
        eff = thresholds.merged(target_acos=goal_map[asin]) if goal_map.get(asin) else thresholds
        be = be_map.get(asin)
        if be is None:
            be = sku_be.get(cat.norm_sku(ag_sku.get(gid)))
        ctx = {"entity_type": "target", "entity_id": tid,
               "asin": asin, "bid": bid,
               "label": kw or expr,
               "over_periods": max(1, over_map.get(("target", tid), 1)),
               "break_even_acos": be}
        new = run_target_rules(m, eff, ctx)
        for f in new:                       # stamp the ASIN's break-even on every flag
            f.break_even = ctx["break_even_acos"]
        flags.extend(new)
    return flags
