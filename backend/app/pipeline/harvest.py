"""Search-Term-Report harvesting.

Amazon's SP Search Term Report carries *customer search terms* — the actual
queries shoppers typed — which the bulk file never exposes. Harvesting turns
them into two kinds of action:

  winner  (orders + good ACoS)  -> create an Exact keyword  (promote)
  loser   (spend, zero orders)  -> create a Negative Exact  (negate)

The STR has campaign/ad-group **names only** (no IDs), so we re-attach IDs by
matching names against the dims already loaded from the bulk file. A search
term with no matching ad group, or one that already exists as a keyword in that
ad group, is skipped.
"""
from __future__ import annotations
import io
import re
from dataclasses import dataclass, asdict
from typing import Optional
import pandas as pd

# Amazon product ASIN: 10 chars, "B0" + 8 alphanumerics. A search term matching
# this is a product, not a keyword — it must be targeted as (negative) product
# targeting with an `asin="..."` expression, never as a keyword.
_ASIN_RE = re.compile(r"^b0[a-z0-9]{8}$", re.IGNORECASE)


def is_asin(term: str) -> bool:
    return bool(_ASIN_RE.match(term.strip()))
from sqlalchemy.orm import Session
from .. import models as md
from .. import metrics as M
from ..config import Thresholds
from . import bulkfmt


@dataclass
class HarvestCandidate:
    action: str                       # promote | negate
    search_term: str
    campaign_id: str
    ad_group_id: str
    campaign_name: Optional[str]
    ad_group_name: Optional[str]
    match_type: Optional[str]         # source targeting match type (informational)
    impressions: int
    clicks: int
    spend: float
    sales: float
    orders: int
    acos: Optional[float]
    cvr: Optional[float]
    suggested_bid: Optional[float]
    reason: str
    break_even: Optional[float] = None   # the ad group's product break-even ACoS

    def dict(self) -> dict:
        return asdict(self)


def ag_break_even_map(db: Session) -> dict[str, float]:
    """ad_group_id -> the product's break-even ACoS (benchmark upload wins, else
    catalog listing price + per-SKU COGS + real Transactions-ledger fees; ASIN
    match, normalized-SKU fallback) via the ad group's product ad."""
    from .. import database as dbmod
    from . import benchmark as bench_stage
    from . import catalog as cat
    be_map = bench_stage.break_even_map(db)
    sku_be = cat.be_by_sku(db.info.get("store"),
                           dbmod.get_project_econ(db.info.get("store"), db.info.get("project")))
    out: dict[str, float] = {}
    for ad in db.query(md.DimAd).all():
        if ad.ad_group_id in out:
            continue
        be = be_map.get(ad.asin)
        if be is None and ad.sku:
            be = sku_be.get(cat.norm_sku(ad.sku))
        if be is not None:
            out[str(ad.ad_group_id)] = be
    return out


def _resolve_columns(df: pd.DataFrame) -> dict[str, str]:
    """Map normalized STR headers -> canonical keys. Tolerant of the report's
    7/14-day attribution-window column-name drift."""
    norm = {str(c).strip().lower(): c for c in df.columns}
    out: dict[str, str] = {}

    def find(*preds) -> Optional[str]:
        for pred in preds:
            for low, orig in norm.items():
                if pred(low):
                    return orig
        return None

    out["search_term"] = find(lambda s: s == "customer search term",
                               lambda s: "search term" in s)
    out["campaign_name"] = find(lambda s: s == "campaign name", lambda s: "campaign" in s and "name" in s)
    out["ad_group_name"] = find(lambda s: s == "ad group name", lambda s: "ad group" in s and "name" in s)
    out["match_type"] = find(lambda s: s == "match type")
    out["impressions"] = find(lambda s: s == "impressions")
    out["clicks"] = find(lambda s: s == "clicks")
    out["spend"] = find(lambda s: s == "spend", lambda s: "spend" in s)
    # prefer the 7-day window; fall back to any sales/orders column
    out["sales"] = find(lambda s: "7 day" in s and "sales" in s,
                        lambda s: "total sales" in s, lambda s: "sales" in s)
    out["orders"] = find(lambda s: "7 day" in s and "orders" in s,
                         lambda s: "total orders" in s, lambda s: "orders" in s)
    return out


def parse_str(path: str, sheet: Optional[str] = None) -> pd.DataFrame:
    """Read the Search Term Report into a frame with canonical columns.
    Accepts .csv (single sheet) as well as .xlsx/.xlsm."""
    if path.lower().endswith(".csv"):
        df = pd.read_csv(path)
    else:
        from . import workbook
        # close the handle before returning: Windows can't unlink a file the
        # process still holds open, and callers unlink the temp upload after us.
        with pd.ExcelFile(path, engine=workbook.excel_engine()) as xls:
            # pick the STR sheet: explicit, else first sheet carrying a search-term column
            target_sheet = sheet
            if target_sheet is None:
                for sn in xls.sheet_names:
                    head = pd.read_excel(xls, sheet_name=sn, nrows=0)
                    if any("search term" in str(c).strip().lower() for c in head.columns):
                        target_sheet = sn
                        break
                target_sheet = target_sheet or xls.sheet_names[0]
            df = pd.read_excel(xls, sheet_name=target_sheet)
    cols = _resolve_columns(df)
    if not cols.get("search_term"):
        raise ValueError("file has no 'Customer Search Term' column — is this a Search Term Report?")

    out = pd.DataFrame()
    out["search_term"] = df[cols["search_term"]].astype(str).str.strip()
    out["campaign_name"] = df[cols["campaign_name"]].astype(str).str.strip() if cols.get("campaign_name") else ""
    out["ad_group_name"] = df[cols["ad_group_name"]].astype(str).str.strip() if cols.get("ad_group_name") else ""
    out["match_type"] = df[cols["match_type"]].astype(str).str.strip() if cols.get("match_type") else ""
    for k in ("impressions", "clicks", "spend", "sales", "orders"):
        out[k] = pd.to_numeric(df[cols[k]], errors="coerce").fillna(0) if cols.get(k) else 0
    return out


@dataclass
class _AcctIndex:
    # (campaign_name, ad_group_name) -> (campaign_id, ad_group_id), names lowercased
    name_map: dict[tuple[str, str], tuple[str, str]]
    is_auto: dict[str, bool]            # campaign_id -> auto-targeting campaign?
    existing_kw: dict[str, set[str]]    # ad_group_id -> {keyword_text}
    ag_has_kw: set[str]                 # ad groups holding ≥1 positive keyword
    ag_has_pt: set[str]                 # ad groups holding ≥1 positive product target
    existing_pt: dict[str, set[str]]    # ad_group_id -> {existing positive PT expression}
    neg_kw: dict[str, set[str]]         # ad_group_id -> {existing negative keyword text}
    neg_pt: dict[str, set[str]]         # ad_group_id -> {existing negative PT expression}


def _account_index(db: Session) -> _AcctIndex:
    """Build name->id maps + per-campaign/ad-group targeting facts from loaded dims.

    These enforce Amazon's create rules during harvest: auto campaigns accept only
    negatives, and an ad group can't mix positive keywords with positive product
    targets.
    """
    camps = {c.campaign_id: c for c in db.query(md.DimCampaign).all()}
    is_auto = {cid: (c.targeting_type or "").strip().lower() == "auto"
               for cid, c in camps.items()}
    groups = db.query(md.DimAdGroup).all()
    name_map: dict[tuple[str, str], tuple[str, str]] = {}
    for g in groups:
        camp = camps.get(g.campaign_id)
        cn = (camp.name or "").strip().lower() if camp else ""
        an = (g.name or "").strip().lower()
        name_map[(cn, an)] = (g.campaign_id, g.ad_group_id)

    existing_kw: dict[str, set[str]] = {}
    existing_pt: dict[str, set[str]] = {}
    ag_has_kw: set[str] = set()
    ag_has_pt: set[str] = set()
    for t in db.query(md.DimTarget).all():
        if t.target_type == "keyword":
            ag_has_kw.add(t.ad_group_id)
            if t.keyword_text:
                existing_kw.setdefault(t.ad_group_id, set()).add(t.keyword_text.strip().lower())
        elif t.target_type == "product_target":
            ag_has_pt.add(t.ad_group_id)
            if t.expression:
                existing_pt.setdefault(t.ad_group_id, set()).add(t.expression.strip().lower())
    neg_kw, neg_pt = bulkfmt.existing_negatives(db)
    return _AcctIndex(name_map, is_auto, existing_kw, ag_has_kw, ag_has_pt,
                      existing_pt, neg_kw, neg_pt)


def harvest(db: Session, df: pd.DataFrame, t: Thresholds, min_orders: int = 1) -> list[HarvestCandidate]:
    """Classify each search-term row into a promote/negate candidate.

    winner: orders >= min_orders and ACoS <= target  -> promote to Exact keyword
    loser : spend >= min_spend and orders == 0        -> add Negative Exact
    """
    idx = _account_index(db)
    out: list[HarvestCandidate] = []

    for _, r in df.iterrows():
        term = str(r["search_term"]).strip()
        if not term or term.lower() in ("nan", "*"):
            continue
        cn, an = str(r["campaign_name"]).strip().lower(), str(r["ad_group_name"]).strip().lower()
        ids = idx.name_map.get((cn, an))
        if not ids:
            continue  # search term's ad group isn't in the loaded account -> can't target it
        campaign_id, ad_group_id = ids

        impressions, clicks = int(r["impressions"]), int(r["clicks"])
        spend, sales, orders = float(r["spend"]), float(r["sales"]), int(r["orders"])
        m = M.all_metrics(impressions, clicks, spend, sales, orders, 0)
        acos, cvr = m["acos"], m["cvr"]

        is_winner = orders >= min_orders and acos is not None and acos <= t.target_acos
        is_loser = orders == 0 and spend >= t.min_spend

        if is_winner:
            # A positive harvest (keyword OR product target) can't go into an auto
            # campaign, and an ad group can't mix positive keywords with positive
            # product targets. Skip rather than emit a row Amazon will reject.
            if idx.is_auto.get(campaign_id):
                continue
            term_is_asin = is_asin(term)
            if term_is_asin and ad_group_id in idx.ag_has_kw:
                continue   # ad group already keyword-typed -> no product target
            if not term_is_asin and ad_group_id in idx.ag_has_pt:
                continue   # ad group already product-target-typed -> no keyword
            if term_is_asin:
                if f'asin="{term.upper()}"'.lower() in idx.existing_pt.get(ad_group_id, set()):
                    continue  # this ASIN is already targeted here -> "already exists"
            else:
                if not bulkfmt.valid_keyword(term):
                    continue  # Amazon would reject it as "Keyword is invalid"
                if term.lower() in idx.existing_kw.get(ad_group_id, set()):
                    continue  # already a keyword in this ad group -> nothing to harvest
            # reserve the ad group's positive-target type so later promotes in this
            # same run don't create a keyword/product-target mix
            (idx.ag_has_pt if term_is_asin else idx.ag_has_kw).add(ad_group_id)
            cpc = m["cpc"] or t.bid_floor
            bid = M.target_acos_bid(cpc, acos, t.target_acos, t.max_bid_cut, t.max_bid_up, t.bid_floor)
            out.append(HarvestCandidate(
                "promote", term, campaign_id, ad_group_id,
                str(r["campaign_name"]), str(r["ad_group_name"]), str(r["match_type"]),
                impressions, clicks, round(spend, 2), round(sales, 2), orders,
                round(acos, 4) if acos is not None else None,
                round(cvr, 4) if cvr is not None else None,
                bid, f"{orders} orders @ {acos:.0%} ACoS — promote to Exact"))
        elif is_loser:
            # don't re-negate something already negated in this ad group (Amazon
            # rejects it as "already exists"). ASIN terms negate as product targets.
            if is_asin(term):
                if f'asin="{term.upper()}"'.lower() in idx.neg_pt.get(ad_group_id, set()):
                    continue
            else:
                if not bulkfmt.valid_keyword(term):
                    continue  # invalid as a negative keyword too
                if term.lower() in idx.neg_kw.get(ad_group_id, set()):
                    continue
            out.append(HarvestCandidate(
                "negate", term, campaign_id, ad_group_id,
                str(r["campaign_name"]), str(r["ad_group_name"]), str(r["match_type"]),
                impressions, clicks, round(spend, 2), round(sales, 2), orders,
                None, round(cvr, 4) if cvr is not None else None,
                None, f"${spend:.2f} spend, 0 orders — negate Exact"))

    # spend desc within each action so the worst losers / best winners surface first
    out.sort(key=lambda c: (c.action, -c.spend))
    # stamp each candidate with its ad group's product break-even ACoS
    ag_be = ag_break_even_map(db)
    for c in out:
        c.break_even = ag_be.get(str(c.ad_group_id))
    return out


# bulk columns Amazon accepts for keyword + product-targeting creates
BULK_COLS = ["Product", "Entity", "Operation", "Campaign ID", "Ad Group ID",
             "Keyword Text", "Match Type", "Product Targeting Expression", "Bid", "State"]


def harvest_to_bulk(candidates: list[dict]) -> bytes:
    """Turn chosen harvest candidates into an SP bulk-upload sheet (xlsx bytes).

    A search term that is an ASIN is emitted as (Negative) Product Targeting with
    an `asin="..."` expression; everything else as a (Negative) Exact keyword.
    Rows are de-duplicated so Amazon doesn't reject the file on Duplicate errors.
    """
    rows = []
    seen: set[tuple] = set()
    for c in candidates:
        term = str(c["search_term"]).strip()
        # final guard: a non-ASIN term must be a valid Amazon keyword
        if not is_asin(term) and not bulkfmt.valid_keyword(term):
            continue
        base = {k: None for k in BULK_COLS}
        base.update({"Product": "Sponsored Products", "Operation": "create",
                     "Campaign ID": bulkfmt.idstr(c["campaign_id"]),
                     "Ad Group ID": bulkfmt.idstr(c["ad_group_id"]),
                     "State": "enabled"})
        if is_asin(term):
            expr = f'asin="{term.upper()}"'
            base["Product Targeting Expression"] = expr
            if c["action"] == "promote":
                base.update({"Entity": "Product Targeting", "Bid": c.get("suggested_bid")})
            else:  # negate (negative product targeting takes no bid)
                base["Entity"] = "Negative Product Targeting"
            key = (c["ad_group_id"], base["Entity"], expr)
        else:
            base["Keyword Text"] = term
            if c["action"] == "promote":
                base.update({"Entity": "Keyword", "Match Type": "Exact",
                             "Bid": c.get("suggested_bid")})
            else:  # negate
                base.update({"Entity": "Negative Keyword", "Match Type": "Negative Exact"})
            key = (c["ad_group_id"], base["Entity"], term.lower())
        if key in seen:
            continue  # collapse duplicate negatives/promotes for the same target
        seen.add(key)
        rows.append(base)

    df = pd.DataFrame(rows, columns=BULK_COLS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Sponsored Products Campaigns")
    return buf.getvalue()
