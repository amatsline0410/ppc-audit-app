"""Channels — Sponsored Brands + Sponsored Display ingestion & report (v1 =
audit visibility, NOT bulk generation — the SB bulk format differs enough that
emitting updates is v2).

One upload (the full Amazon bulk workbook) fans into three own tables:
  SPChannelFact — SP campaign totals (same file, so the mix compares like-for-like)
  SBFact        — from **SB Multi Ad Group Campaigns** ONLY. The legacy
                  'Sponsored Brands Campaigns' sheet duplicates the SAME campaigns
                  (verified on a real export — identical spend/sales); reading
                  both double-counts. + 'SB Search Term Report' rows (entity='str').
  SDFact        — from 'Sponsored Display Campaigns'.

Report (pure):
  * channel mix — SP vs SB vs SD spend/sales/ACoS side by side
  * SB keyword table with HIGH_ACOS / WASTED_SPEND flags (cadence thresholds)
  * brand vs non-brand split from a configurable per-store brand-term list
    (store _meta.json, e.g. ["pro ice", "proice"]) — the defense-vs-growth ratio
  * SD targeting table + dormant-channel banner when spend == 0
  * SB STR harvest suggestions (read-only) via the model-agnostic Weekly engine.

Never touches FactPerformance / active_snapshot. IDs stay exact strings.
"""
from __future__ import annotations
import re
from types import SimpleNamespace
import pandas as pd
from sqlalchemy.orm import Session
from .. import models as md
from .. import metrics as M
from ..config import Thresholds
from . import bulkfmt, workbook
from . import weekly as wk

SB_SHEET = "SB Multi Ad Group Campaigns"
SB_LEGACY_SHEET = "Sponsored Brands Campaigns"     # duplicate of SB_SHEET — never ingest
SD_SHEET = "Sponsored Display Campaigns"
SP_SHEET = "Sponsored Products Campaigns"
SB_STR_SHEET = "SB Search Term Report"

SB_ENTITIES = {"campaign", "ad group", "keyword", "video ad", "product collection ad",
               "store spotlight ad", "product targeting", "bidding adjustment by placement"}
SD_ENTITIES = {"campaign", "ad group", "product ad", "contextual targeting",
               "audience targeting", "negative product targeting"}
AD_FORMAT = {"video ad": "video", "product collection ad": "product_collection",
             "store spotlight ad": "store_spotlight"}


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


def _s(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def _col(df: pd.DataFrame, *names) -> str | None:
    low = {str(c).strip().lower(): c for c in df.columns}
    for n in names:
        if n in low:
            return low[n]
    return None


def _metrics_of(r, df_cols) -> dict:
    g = lambda n: _num(r.get(df_cols.get(n))) if df_cols.get(n) else 0.0
    return dict(impressions=int(g("impressions")), clicks=int(g("clicks")),
                spend=round(g("spend"), 2), sales=round(g("sales"), 2),
                orders=int(g("orders")), units=int(g("units")))


def _cols_map(df) -> dict:
    return {n: _col(df, n) for n in ("impressions", "clicks", "spend", "sales", "orders", "units")}


# ---- parse -----------------------------------------------------------------------
def parse_sb(path: str) -> list[dict]:
    """SB rows from the Multi-Ad-Group sheet ONLY (legacy sheet = duplicates)."""
    try:
        df = workbook.read_str(path, SB_SHEET)
    except ValueError:
        return []
    ent_c = _col(df, "entity")
    if not ent_c:
        return []
    mc = _cols_map(df)
    out = []
    for _, r in df.iterrows():
        ent = _s(r.get(ent_c)).lower()
        if ent not in SB_ENTITIES:
            continue
        out.append(dict(
            entity=ent,
            campaign_id=bulkfmt.idstr(_s(r.get(_col(df, "campaign id")))) or None,
            ad_group_id=bulkfmt.idstr(_s(r.get(_col(df, "ad group id")))) or None,
            keyword_id=bulkfmt.idstr(_s(r.get(_col(df, "keyword id")))) or None,
            campaign_name=_s(r.get(_col(df, "campaign name", "campaign name (informational only)"))) or None,
            ad_group_name=_s(r.get(_col(df, "ad group name", "ad group name (informational only)"))) or None,
            state=_s(r.get(_col(df, "state"))).lower() or None,
            ad_format=AD_FORMAT.get(ent),
            keyword_text=_s(r.get(_col(df, "keyword text"))) or None,
            match_type=_s(r.get(_col(df, "match type"))) or None,
            expression=_s(r.get(_col(df, "product targeting expression"))) or None,
            bid=_num(r.get(_col(df, "bid"))) or None,
            budget=_num(r.get(_col(df, "budget"))) or None,
            **_metrics_of(r, mc)))
    return out


def parse_sb_str(path: str) -> list[dict]:
    """SB Search Term Report lines -> entity='str' rows (read-only harvest)."""
    try:
        df = workbook.read_str(path, SB_STR_SHEET)
    except ValueError:
        return []
    st_c = _col(df, "customer search term")
    if not st_c:
        return []
    mc = _cols_map(df)
    out = []
    for _, r in df.iterrows():
        term = _s(r.get(st_c))
        if not term or term == "*":
            continue
        out.append(dict(
            entity="str",
            campaign_id=bulkfmt.idstr(_s(r.get(_col(df, "campaign id")))) or None,
            ad_group_id=bulkfmt.idstr(_s(r.get(_col(df, "ad group id")))) or None,
            keyword_id=bulkfmt.idstr(_s(r.get(_col(df, "keyword id")))) or None,
            campaign_name=_s(r.get(_col(df, "campaign name", "campaign name (informational only)"))) or None,
            ad_group_name=_s(r.get(_col(df, "ad group name", "ad group name (informational only)"))) or None,
            state=_s(r.get(_col(df, "state"))).lower() or None,
            keyword_text=_s(r.get(_col(df, "keyword text"))) or None,
            match_type=_s(r.get(_col(df, "match type"))) or None,
            search_term=term,
            bid=_num(r.get(_col(df, "bid"))) or None,
            **_metrics_of(r, mc)))
    return out


def parse_sd(path: str) -> list[dict]:
    try:
        df = workbook.read_str(path, SD_SHEET)
    except ValueError:
        return []
    ent_c = _col(df, "entity")
    if not ent_c:
        return []
    mc = _cols_map(df)
    out = []
    for _, r in df.iterrows():
        ent = _s(r.get(ent_c)).lower()
        if ent not in SD_ENTITIES:
            continue
        out.append(dict(
            entity=ent,
            campaign_id=bulkfmt.idstr(_s(r.get(_col(df, "campaign id")))) or None,
            ad_group_id=bulkfmt.idstr(_s(r.get(_col(df, "ad group id")))) or None,
            targeting_id=bulkfmt.idstr(_s(r.get(_col(df, "targeting id")))) or None,
            campaign_name=_s(r.get(_col(df, "campaign name", "campaign name (informational only)"))) or None,
            ad_group_name=_s(r.get(_col(df, "ad group name", "ad group name (informational only)"))) or None,
            state=_s(r.get(_col(df, "state"))).lower() or None,
            tactic=_s(r.get(_col(df, "tactic"))) or None,
            sku=_s(r.get(_col(df, "sku"))) or None,
            asin=_s(r.get(_col(df, "asin (informational only)", "asin"))) or None,
            expression=_s(r.get(_col(df, "targeting expression"))) or None,
            bid=_num(r.get(_col(df, "bid"))) or None,
            budget=_num(r.get(_col(df, "budget"))) or None,
            **_metrics_of(r, mc)))
    return out


def parse_sp_campaigns(path: str) -> list[dict]:
    """SP campaign totals from the same workbook (mix card baseline)."""
    try:
        df = workbook.read_str(path, SP_SHEET)
    except ValueError:
        return []
    ent_c = _col(df, "entity")
    if not ent_c:
        return []
    mc = _cols_map(df)
    out = []
    for _, r in df.iterrows():
        if _s(r.get(ent_c)).lower() != "campaign":
            continue
        m = _metrics_of(r, mc)
        m.pop("units", None)
        out.append(dict(
            campaign_id=bulkfmt.idstr(_s(r.get(_col(df, "campaign id")))) or None,
            campaign_name=_s(r.get(_col(df, "campaign name"))) or None,
            state=_s(r.get(_col(df, "state"))).lower() or None, **m))
    return out


def ingest(db: Session, path: str) -> dict:
    """Parse SP + SB + SD (+ SB STR) from one workbook; replace all snapshots."""
    sb = parse_sb(path) + parse_sb_str(path)
    sd = parse_sd(path)
    sp = parse_sp_campaigns(path)
    if not sb and not sd:
        raise ValueError("No Sponsored Brands / Sponsored Display sheets found — upload the "
                         "full Amazon bulk workbook ('SB Multi Ad Group Campaigns' and/or "
                         "'Sponsored Display Campaigns' sheets).")
    db.query(md.SBFact).delete()
    db.query(md.SDFact).delete()
    db.query(md.SPChannelFact).delete()
    if sb:
        db.bulk_insert_mappings(md.SBFact, sb)
    if sd:
        db.bulk_insert_mappings(md.SDFact, sd)
    if sp:
        db.bulk_insert_mappings(md.SPChannelFact, sp)
    db.commit()
    return summary(db, brand_terms=[])["mix"] | {"sb_rows": len(sb), "sd_rows": len(sd),
                                                 "sp_campaigns": len(sp)}


def has_data(db: Session) -> bool:
    return (db.query(md.SBFact.id).first() is not None
            or db.query(md.SDFact.id).first() is not None)


def delete_all(db: Session) -> int:
    """Wipe the SB/SD/SP channel snapshots (Clear button). Own tables only —
    brand terms (store settings) survive."""
    n = db.query(md.SBFact).delete()
    n += db.query(md.SDFact).delete()
    n += db.query(md.SPChannelFact).delete()
    db.commit()
    return n


# ---- brand classifier (pure) --------------------------------------------------
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def is_brand(term: str, brand_terms: list[str]) -> bool:
    """True when the term contains any configured brand phrase — matched on the
    normalized string AND its space-less form ('pro ice' also catches 'proice')."""
    t = _norm(term)
    t_nospace = t.replace(" ", "")
    for b in brand_terms or []:
        bb = _norm(b)
        if not bb:
            continue
        if bb in t or bb.replace(" ", "") in t_nospace:
            return True
    return False


# ---- report --------------------------------------------------------------------
def _kpis(rows) -> dict:
    sp = sum(r.spend or 0 for r in rows)
    sa = sum(r.sales or 0 for r in rows)
    cl = sum(r.clicks or 0 for r in rows)
    im = sum(r.impressions or 0 for r in rows)
    od = sum(r.orders or 0 for r in rows)
    return {"spend": round(sp, 2), "sales": round(sa, 2), "clicks": cl,
            "impressions": im, "orders": od,
            "acos": round(sp / sa, 4) if sa else None,
            "roas": round(sa / sp, 2) if sp else None}


def summary(db: Session, brand_terms: list[str], t: Thresholds | None = None) -> dict:
    sp_rows = db.query(md.SPChannelFact).all()
    sb_camp = db.query(md.SBFact).filter(md.SBFact.entity == "campaign").all()
    sd_camp = db.query(md.SDFact).filter(md.SDFact.entity == "campaign").all()

    mix = {"SP": _kpis(sp_rows), "SB": _kpis(sb_camp), "SD": _kpis(sd_camp)}
    total_spend = sum(m["spend"] for m in mix.values())
    total_sales = sum(m["sales"] for m in mix.values())
    for m in mix.values():
        m["spend_share"] = round(m["spend"] / total_spend, 4) if total_spend else None
        m["sales_share"] = round(m["sales"] / total_sales, 4) if total_sales else None

    # brand vs non-brand across SB keywords + SB search terms (defense vs growth)
    kw_rows = db.query(md.SBFact).filter(md.SBFact.entity == "keyword").all()
    str_rows = db.query(md.SBFact).filter(md.SBFact.entity == "str").all()
    split = {"brand": {"spend": 0.0, "sales": 0.0}, "nonbrand": {"spend": 0.0, "sales": 0.0}}
    base = str_rows if str_rows else kw_rows          # STR terms are the truer signal
    for r in base:
        label = "brand" if is_brand(r.search_term or r.keyword_text or "", brand_terms) else "nonbrand"
        split[label]["spend"] += r.spend or 0
        split[label]["sales"] += r.sales or 0
    tot_b = split["brand"]["spend"] + split["nonbrand"]["spend"]
    brand_pct = round(split["brand"]["spend"] / tot_b, 4) if tot_b else None
    for v in split.values():
        v["spend"] = round(v["spend"], 2)
        v["sales"] = round(v["sales"], 2)
        v["acos"] = round(v["spend"] / v["sales"], 4) if v["sales"] else None

    return {"has_data": has_data(db), "mix": {"channels": mix,
                                              "total_spend": round(total_spend, 2),
                                              "total_sales": round(total_sales, 2)},
            "brand_split": {"terms": brand_terms, "brand_spend_share": brand_pct, **split,
                            "source": "search_terms" if str_rows else "keywords"},
            "sd_dormant": bool(sd_camp) and mix["SD"]["spend"] == 0,
            "sb_present": bool(sb_camp), "sd_present": bool(sd_camp)}


def sb_keywords(db: Session, t: Thresholds, brand_terms: list[str]) -> list[dict]:
    """SB keyword table: keyword | match | ad format | metrics | flag."""
    fmt_by_ag: dict[str, str] = {}
    for r in db.query(md.SBFact).filter(md.SBFact.ad_format.isnot(None)).all():
        if r.ad_group_id:
            fmt_by_ag.setdefault(r.ad_group_id, r.ad_format)
    out = []
    for r in db.query(md.SBFact).filter(md.SBFact.entity == "keyword").all():
        if r.state and r.state not in ("enabled", "ok"):
            continue
        m = M.all_metrics(r.impressions, r.clicks, r.spend, r.sales, r.orders, r.units)
        flag = None
        if (r.spend or 0) >= t.min_spend and (r.orders or 0) == 0:
            flag = "WASTED_SPEND"
        elif m["acos"] is not None and m["acos"] > t.target_acos:
            flag = "HIGH_ACOS"
        out.append({"keyword_id": r.keyword_id, "keyword": r.keyword_text,
                    "match_type": r.match_type, "campaign": r.campaign_name,
                    "ad_format": fmt_by_ag.get(r.ad_group_id),
                    "brand": is_brand(r.keyword_text or "", brand_terms),
                    "impressions": r.impressions, "clicks": r.clicks,
                    "spend": round(r.spend or 0, 2), "sales": round(r.sales or 0, 2),
                    "orders": r.orders, "acos": m["acos"], "flag": flag})
    out.sort(key=lambda r: r["spend"], reverse=True)
    return out


def sd_targets(db: Session, t: Thresholds) -> list[dict]:
    out = []
    for r in db.query(md.SDFact).filter(
            md.SDFact.entity.in_(("contextual targeting", "audience targeting"))).all():
        if r.state and r.state not in ("enabled", "ok"):
            continue
        m = M.all_metrics(r.impressions, r.clicks, r.spend, r.sales, r.orders, r.units)
        flag = None
        if (r.spend or 0) >= t.min_spend and (r.orders or 0) == 0:
            flag = "WASTED_SPEND"
        elif m["acos"] is not None and m["acos"] > t.target_acos:
            flag = "HIGH_ACOS"
        out.append({"targeting_id": r.targeting_id, "expression": r.expression,
                    "kind": r.entity, "tactic": r.tactic, "campaign": r.campaign_name,
                    "impressions": r.impressions, "clicks": r.clicks,
                    "spend": round(r.spend or 0, 2), "sales": round(r.sales or 0, 2),
                    "orders": r.orders, "acos": m["acos"], "flag": flag})
    out.sort(key=lambda r: r["spend"], reverse=True)
    return out


def sb_harvest(db: Session, t: Thresholds) -> dict:
    """Read-only harvest suggestions from the SB STR via the model-agnostic Weekly
    engine (promotes/negates displayed — SB bulk emission is v2)."""
    rows = [SimpleNamespace(is_auto=False, product_targeting_id=None,
                            keyword_id=r.keyword_id, campaign_id=r.campaign_id,
                            ad_group_id=r.ad_group_id or "", campaign_name=r.campaign_name,
                            ad_group_name=r.ad_group_name, match_type=r.match_type,
                            search_term=r.search_term or "", impressions=r.impressions,
                            clicks=r.clicks, spend=r.spend, sales=r.sales, orders=r.orders)
            for r in db.query(md.SBFact).filter(md.SBFact.entity == "str").all()]
    if not rows:
        return {"promotes": [], "negates": [], "terms": 0}
    h = wk.compute_harvest(rows, t)
    return {"promotes": h["promotes"], "negates": h["negates"], "terms": len(rows)}
