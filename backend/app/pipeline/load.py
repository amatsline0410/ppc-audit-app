"""Stage 4: load into dims + facts. Idempotent.

Upsert dims by PK. Replace facts for (entity_type, entity_id, snapshot_date)
so re-uploading the same file/date never duplicates.
"""
from __future__ import annotations
from datetime import date
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import delete, text
from .. import models as md


class _Dims:
    """Collect dim upserts in memory, then write them in two bulk statements.

    A real bulk export carries ~140k dim rows. Upserting them one at a time costs a
    SELECT and an ORM identity-map entry each — about a minute of the upload. Here
    the rows are merged by primary key (last write wins, same as re-setting the
    attributes did), the existing keys are fetched with one query per table, and the
    split is written with bulk_insert_mappings / bulk_update_mappings.
    """

    def __init__(self):
        self.rows: dict[tuple, dict] = {}          # (model, pk_val) -> attrs
        self.order: list[tuple] = []

    def add(self, model, pk_field: str, pk_val, attrs: dict) -> None:
        if not pk_val:
            return
        key = (model, str(pk_val))
        cur = self.rows.get(key)
        if cur is None:
            self.rows[key] = {pk_field: str(pk_val), **attrs}
            self.order.append(key)
        else:
            cur.update(attrs)

    # Parent-before-child. The ORM used to sort inserts by dependency for us; a bulk
    # insert writes in the order given, and SQLite checks each FK immediately, so a
    # DimAd written before its ad group fails outright.
    ORDER = [md.DimProduct, md.DimCampaign, md.DimAdGroup, md.DimAd, md.DimTarget]

    def flush(self, db: Session) -> None:
        by_model: dict = {}
        for key in self.order:
            by_model.setdefault(key[0], []).append(self.rows[key])
        ordered = ([m for m in self.ORDER if m in by_model]
                   + [m for m in by_model if m not in self.ORDER])
        for model in ordered:
            rows = by_model[model]
            pk_col = list(model.__table__.primary_key.columns)[0]
            pk_name = pk_col.name
            have = {r[0] for r in db.query(pk_col).all()}
            new = [r for r in rows if r[pk_name] not in have]
            upd = [r for r in rows if r[pk_name] in have]
            if new:
                db.bulk_insert_mappings(model, new)
            if upd:
                db.bulk_update_mappings(model, upd)
        db.flush()


def load(db: Session, frames: dict[str, pd.DataFrame], snapshot: date) -> dict:
    counts = {}
    dims = _Dims()
    # FKs now enforce ON DELETE CASCADE; defer checks to COMMIT so dims can be
    # inserted in any order (all parents present by commit).
    db.execute(text("PRAGMA defer_foreign_keys=ON"))

    # ---- dims ----
    for _, r in frames.get("product ad", pd.DataFrame()).iterrows():
        asin = r.get("asin")
        if asin:
            dims.add(md.DimProduct, "asin", asin, {"sku": r.get("sku")})
        dims.add(md.DimAd, "ad_id", r.get("ad_id"),
                 {"ad_group_id": r.get("ad_group_id"), "asin": asin,
                  "sku": r.get("sku"), "state": r.get("state")})

    for _, r in frames.get("campaign", pd.DataFrame()).iterrows():
        dims.add(md.DimCampaign, "campaign_id", r.get("campaign_id"),
                 {"name": r.get("campaign_name") or r.get("campaign_name_info"),
                  "targeting_type": r.get("targeting_type"), "state": r.get("state"),
                  "daily_budget": r.get("daily_budget"), "portfolio_id": r.get("portfolio_id") or None})

    for _, r in frames.get("ad group", pd.DataFrame()).iterrows():
        dims.add(md.DimAdGroup, "ad_group_id", r.get("ad_group_id"),
                 {"campaign_id": r.get("campaign_id"), "name": r.get("ad_group_name"),
                  "default_bid": r.get("ad_group_default_bid"), "state": r.get("state")})

    for _, r in frames.get("keyword", pd.DataFrame()).iterrows():
        dims.add(md.DimTarget, "target_id", r.get("keyword_id"),
                 {"ad_group_id": r.get("ad_group_id"), "target_type": "keyword",
                  "keyword_text": r.get("keyword_text"), "match_type": r.get("match_type"),
                  "bid": r.get("bid"), "state": r.get("state")})

    for _, r in frames.get("product targeting", pd.DataFrame()).iterrows():
        dims.add(md.DimTarget, "target_id", r.get("product_targeting_id"),
                 {"ad_group_id": r.get("ad_group_id"), "target_type": "product_target",
                  "expression": r.get("expression"), "bid": r.get("bid"), "state": r.get("state")})

    # existing negatives — stored so bulk generators never re-create a negative the
    # account already has ("already exists"). They carry no facts and are excluded
    # from audit/bidopt/tree (which key off positive target_types / fact rows).
    for _, r in frames.get("negative keyword", pd.DataFrame()).iterrows():
        dims.add(md.DimTarget, "target_id", r.get("keyword_id"),
                 {"ad_group_id": r.get("ad_group_id"), "target_type": "negative_keyword",
                  "keyword_text": r.get("keyword_text"), "match_type": r.get("match_type"),
                  "state": r.get("state")})

    for _, r in frames.get("negative product targeting", pd.DataFrame()).iterrows():
        dims.add(md.DimTarget, "target_id", r.get("product_targeting_id"),
                 {"ad_group_id": r.get("ad_group_id"), "target_type": "negative_product_target",
                  "expression": r.get("expression"), "state": r.get("state")})

    dims.flush(db)

    # ---- facts (replace this snapshot for touched entities) ----
    fact_rows = []
    def add_facts(frame, etype, id_col):
        for _, r in frame.iterrows():
            eid = r.get(id_col)
            if not eid:
                continue
            if (r.get("impressions", 0) or r.get("clicks", 0) or r.get("spend", 0)
                    or r.get("sales", 0) or r.get("orders", 0)):
                fact_rows.append(dict(entity_type=etype, entity_id=eid, snapshot_date=snapshot,
                    impressions=int(r.get("impressions", 0)), clicks=int(r.get("clicks", 0)),
                    spend=float(r.get("spend", 0)), sales=float(r.get("sales", 0)),
                    orders=int(r.get("orders", 0)), units=int(r.get("units", 0))))

    add_facts(frames.get("campaign", pd.DataFrame()), "campaign", "campaign_id")
    add_facts(frames.get("ad group", pd.DataFrame()), "ad_group", "ad_group_id")
    add_facts(frames.get("product ad", pd.DataFrame()), "ad", "ad_id")
    add_facts(frames.get("keyword", pd.DataFrame()), "target", "keyword_id")
    add_facts(frames.get("product targeting", pd.DataFrame()), "target", "product_targeting_id")

    # idempotent: clear existing facts for these (type,id,date) then insert
    keys = {(f["entity_type"], f["entity_id"]) for f in fact_rows}
    for etype, eid in keys:
        db.execute(delete(md.FactPerformance).where(
            md.FactPerformance.entity_type == etype,
            md.FactPerformance.entity_id == eid,
            md.FactPerformance.snapshot_date == snapshot))
    db.bulk_insert_mappings(md.FactPerformance, fact_rows)

    # ---- placement facts (bulk 'Bidding Adjustment' rows), replace this snapshot ----
    pl = frames.get("bidding adjustment", pd.DataFrame())
    db.execute(delete(md.FactPlacement).where(md.FactPlacement.snapshot_date == snapshot))
    pl_rows = []
    for _, r in pl.iterrows():
        cid, place = r.get("campaign_id"), r.get("placement")
        if not cid or not place:
            continue
        strat = str(r.get("bidding strategy") or "").strip()
        pl_rows.append(dict(campaign_id=cid, placement=str(place), snapshot_date=snapshot,
            percentage=float(r.get("percentage", 0) or 0),
            strategy=(strat if strat.lower() not in ("", "nan") else None),
            impressions=int(r.get("impressions", 0)),
            clicks=int(r.get("clicks", 0)), spend=float(r.get("spend", 0)),
            sales=float(r.get("sales", 0)), orders=int(r.get("orders", 0))))
    if pl_rows:
        db.bulk_insert_mappings(md.FactPlacement, pl_rows)
    db.commit()

    counts = {k: len(v) for k, v in frames.items()}
    counts["fact_rows"] = len(fact_rows)
    counts["placement_rows"] = len(pl_rows)
    counts["snapshot_date"] = snapshot.isoformat()
    return counts
