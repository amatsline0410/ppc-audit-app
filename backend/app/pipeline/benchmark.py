"""Product Benchmark = per-ASIN break-even data for PPC.

break_even_acos is the ACoS at which an incremental ad sale yields zero profit
(= gross margin before ads ÷ price). Goal ACoS should sit *below* it; an entity
running above it is losing money on every ad-driven sale.

Either uploaded directly (Product Benchmark file: ASIN + break-even ACoS/ROAS,
optional sale price) or derived from sale price + the econ referral default.
"""
from __future__ import annotations
import json
import os
from typing import Optional
import pandas as pd
from sqlalchemy.orm import Session
from .. import models as md
from .. import database as dbmod


# ---- store-scoped benchmark file -------------------------------------------
# One _benchmark.json per STORE: upload once, every audit in that store matches
# its ASINs against it. (Per-audit ProductBenchmark rows still merge on top.)
def _store_path(store_id: str) -> str:
    return os.path.join(dbmod._store_dir(store_id), "_benchmark.json")


def _read_store(store_id: Optional[str]) -> dict:
    if not store_id:
        return {}
    p = _store_path(store_id)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _write_store(store_id: str, data: dict) -> None:
    with open(_store_path(store_id), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _session_store(db: Session) -> Optional[str]:
    return db.info.get("store")


def _frac(x) -> Optional[float]:
    """Normalize a percent-or-fraction cell to a fraction. '35%' -> 0.35,
    42 -> 0.42, 0.42 -> 0.42."""
    try:
        v = float(str(x).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return v / 100.0 if v > 1.0 else v


def _money(x) -> Optional[float]:
    try:
        return float(str(x).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _resolve(df: pd.DataFrame) -> dict:
    norm = {str(c).strip().lower(): c for c in df.columns}

    def find(*preds):
        for pred in preds:
            for low, orig in norm.items():
                if pred(low):
                    return orig
        return None

    return {
        "asin": find(lambda s: s == "asin", lambda s: "asin" in s),
        "price": find(lambda s: "sale price" in s, lambda s: "price" in s),
        "be_acos": find(lambda s: "break" in s and "acos" in s, lambda s: "breakeven acos" in s,
                        lambda s: "be acos" in s),
        "be_roas": find(lambda s: "break" in s and "roas" in s, lambda s: "be roas" in s),
        "target": find(lambda s: "target acos" in s, lambda s: "goal acos" in s),
    }


def parse_benchmark(path: str, sheet: Optional[str] = None) -> pd.DataFrame:
    if path.lower().endswith(".csv"):
        df = pd.read_csv(path)
    else:
        from . import workbook
        # close the handle before returning: Windows can't unlink a file the
        # process still holds open, and callers unlink the temp upload after us.
        with pd.ExcelFile(path, engine=workbook.excel_engine()) as xls:
            target = sheet
            if target is None:
                for sn in xls.sheet_names:
                    head = pd.read_excel(xls, sheet_name=sn, nrows=0)
                    if any("asin" in str(c).strip().lower() for c in head.columns):
                        target = sn
                        break
                target = target or xls.sheet_names[0]
            df = pd.read_excel(xls, sheet_name=target)
    col = _resolve(df)
    if not col["asin"] or not (col["be_acos"] or col["be_roas"] or col["price"]):
        raise ValueError("Benchmark file needs ASIN + break-even ACoS/ROAS (or sale price)")

    out = pd.DataFrame()
    out["asin"] = df[col["asin"]].astype(str).str.strip().str.upper()
    out["sale_price"] = df[col["price"]].map(_money) if col["price"] else None
    if col["be_acos"]:
        out["break_even_acos"] = df[col["be_acos"]].map(_frac)
    elif col["be_roas"]:
        out["break_even_acos"] = df[col["be_roas"]].map(lambda r: (1.0 / float(r)) if _money(r) else None)
    else:
        out["break_even_acos"] = None
    out["target_acos"] = df[col["target"]].map(_frac) if col["target"] else None
    return out[out["asin"].str.len() > 0]


def load_benchmark(db: Session, df: pd.DataFrame) -> int:
    """Upsert benchmark rows at STORE scope (shared by all audits in the store).
    Falls back to the per-audit table only if the session has no store info."""
    store = _session_store(db)
    if store:
        data = _read_store(store)
        n = 0
        for _, r in df.iterrows():
            row = data.setdefault(r["asin"], {})
            for k in ("sale_price", "break_even_acos", "target_acos"):
                if r.get(k) is not None:
                    row[k] = r[k]
            n += 1
        _write_store(store, data)
        return n
    n = 0
    for _, r in df.iterrows():
        b = db.get(md.ProductBenchmark, r["asin"])
        if b is None:
            b = md.ProductBenchmark(asin=r["asin"]); db.add(b)
        if r.get("sale_price") is not None:
            b.sale_price = r["sale_price"]
        if r.get("break_even_acos") is not None:
            b.break_even_acos = r["break_even_acos"]
        if r.get("target_acos") is not None:
            b.target_acos = r["target_acos"]
        n += 1
    db.commit()
    return n


def _merged_rows(db: Session) -> dict[str, dict]:
    """Store-level benchmark + per-audit table rows. Audit rows win (more specific)."""
    out = {a: dict(v) for a, v in _read_store(_session_store(db)).items()}
    for b in db.query(md.ProductBenchmark).all():
        row = out.setdefault(b.asin, {})
        if b.sale_price is not None:
            row["sale_price"] = b.sale_price
        if b.break_even_acos is not None:
            row["break_even_acos"] = b.break_even_acos
        if b.target_acos is not None:
            row["target_acos"] = b.target_acos
    return out


def effective_unit_cost(unit_cost, sale_price, default_cogs_pct) -> float:
    """Unit COGS, with a percent-of-price fallback when it's blank/0."""
    if unit_cost and unit_cost > 0:
        return float(unit_cost)
    if sale_price and default_cogs_pct:
        return round(sale_price * default_cogs_pct, 2)
    return 0.0


def _unit_economics(price, cost, default_ref: float, default_cogs_pct: float):
    """Per-unit breakdown: (cogs, amazon_fee, profit_per_unit). Amazon fee =
    the fee report's TOTAL FEES per unit (base fulfillment + referral, exact $)
    when it has them, else referral % of price + FBA + misc.
    profit/unit = price - (cogs + amazon_fee)."""
    if not price or price <= 0:
        return None, None, None
    ref = cost.referral_pct if cost else default_ref
    fba = cost.fba_fee if cost else 0.0
    misc = cost.misc_fee if cost else 0.0
    total = getattr(cost, "total_fee", None) if cost else None
    # a total quoted at a different price no longer applies — the referral part
    # is a % of the actual sale price, so fall back to rate x price + FBA
    fee_price = getattr(cost, "fee_price", None) if cost else None
    if total is not None and ref and fee_price and abs(fee_price - price) > 0.01:
        total = None
    cogs = effective_unit_cost(cost.unit_cost if cost else 0.0, price, default_cogs_pct)
    amazon_fee = round(total + misc, 2) if total else round(price * ref + fba + misc, 2)
    profit = round(price - (cogs + amazon_fee), 2)
    return round(cogs, 2), amazon_fee, profit


def _derive_be(price, cost, default_ref, default_cogs_pct=0.0) -> Optional[float]:
    """break-even ACoS = margin-before-ads ÷ price (uses effective COGS)."""
    cogs, amazon_fee, profit = _unit_economics(price, cost, default_ref, default_cogs_pct)
    if profit is None:
        return None
    be = profit / price
    return round(be, 4) if be > 0 else None


def cost_map(db: Session, default_ref: float = 0.15) -> dict:
    """asin -> cost object. Manual product-cost entry was removed; what's left is
    the store's REAL per-unit fees — the base fulfillment fee per unit from the
    FBA Fee Preview upload (else the Transactions-ledger observed FBA fee) and
    the ledger referral %. Keyed by CHILD/standalone ASIN only (a parent ASIN is
    not a purchasable unit and has no fulfillment fee), so a benchmark row's
    break-even accounts for fulfillment instead of pricing it at $0."""
    from types import SimpleNamespace
    from . import fbafees as fba
    from . import catalog as cat
    sid = db.info.get("store")
    fees = fba.by_asin(sid)                     # ASIN -> Fee Preview row (children only)
    ledger = cat.fees_by_sku(sid)               # normalized SKU -> observed fees
    prods = (cat.read_catalog(sid) or {}).get("products", {})
    out: dict = {}
    for sku, p in prods.items():
        asin = (p.get("asin") or "").upper()
        if not asin or p.get("parentage") == "parent":
            continue
        led = ledger.get(cat.norm_sku(sku)) or {}
        f = fees.get(asin) or {}
        fee, src = f.get("fulfillment_fee"), "report"
        if fee is None:
            fee, src = led.get("fba_fee"), led.get("fba_source")
        ref = f.get("referral_pct") or led.get("referral_pct")   # report rate wins
        if fee is None and ref is None:
            continue
        out[asin] = SimpleNamespace(referral_pct=ref if ref is not None else default_ref,
                                    fba_fee=fee or 0.0, misc_fee=0.0, unit_cost=0.0,
                                    total_fee=f.get("total_fee"),
                                    referral_fee=f.get("referral_fee"),
                                    fee_price=f.get("price"),
                                    fba_source=src if fee is not None else None)
    # SKUs not in the catalog: the report's own ASIN column still maps them
    # (a referral-only row — merchant-fulfilled, no FBA fee — still counts)
    for asin, f in fees.items():
        if asin in out or (f.get("fulfillment_fee") is None
                           and f.get("referral_pct") is None):
            continue
        out[asin] = SimpleNamespace(
            referral_pct=f.get("referral_pct") if f.get("referral_pct") is not None else default_ref,
            fba_fee=f.get("fulfillment_fee") or 0.0, misc_fee=0.0, unit_cost=0.0,
            total_fee=f.get("total_fee"), referral_fee=f.get("referral_fee"),
            fee_price=f.get("price"),
            fba_source="report" if f.get("fulfillment_fee") else None)
    return out


def break_even_map(db: Session, default_ref: float = 0.15, default_cogs_pct: float = 0.0) -> dict:
    """asin -> break-even ACoS. An uploaded benchmark value wins; ASINs not in
    the benchmark fall back to the store CATALOG (Product Benchmark tab): selling
    price + per-SKU COGS override (default 40% of price) + referral %. So every
    catalog product benchmarks its ads/campaigns in the PPC Audit (BLEEDING
    flags, BidOptimizer caps) without a separate benchmark upload."""
    costs = cost_map(db, default_ref)
    out: dict[str, float] = {}
    for asin, row in _merged_rows(db).items():
        be = row.get("break_even_acos")
        if be is None:
            be = _derive_be(row.get("sale_price"), costs.get(asin), default_ref, default_cogs_pct)
        if be is not None:
            out[asin] = be
    # catalog fallback — lazy import (catalog imports this module at top level).
    # Uses each listing's per-SKU COGS + real Transactions-ledger fees, so the
    # derived break-even is price-dependent, not a constant.
    from . import catalog as cat
    sid = db.info.get("store")
    data = cat.read_catalog(sid)
    if data:
        cogs = cat.read_cogs(sid)
        fees = cat.fees_by_sku(sid)
        econ = {"default_referral_pct": default_ref, "default_cogs_pct": default_cogs_pct}
        for p in data.get("products", {}).values():
            asin = p.get("asin")
            if not asin or asin in out:
                continue
            b = cat.be_metrics(p, None, econ, cogs.get(p.get("sku")),
                               fees.get(cat.norm_sku(p.get("sku"))))
            if b and b.get("break_even_acos") is not None:
                out[asin] = b["break_even_acos"]
    return out


def goal_map(db: Session) -> dict:
    """asin -> per-ASIN goal ACoS override (store-wide benchmark, merged)."""
    return {a: r["target_acos"] for a, r in _merged_rows(db).items() if r.get("target_acos")}


def benchmark_view(db: Session, econ: dict) -> dict:
    default_ref = econ.get("default_referral_pct", 0.15) or 0.15
    default_cogs_pct = econ.get("default_cogs_pct", 0.0) or 0.0
    costs = cost_map(db, default_ref)
    known = {a.asin for a in db.query(md.DimProduct).all() if a.asin}
    rows = []
    for asin, r in _merged_rows(db).items():
        price = r.get("sale_price")
        uploaded = r.get("break_even_acos")
        derived = _derive_be(price, costs.get(asin), default_ref, default_cogs_pct)
        be = uploaded if uploaded is not None else derived
        cogs, amazon_fee, profit_unit = _unit_economics(price, costs.get(asin), default_ref, default_cogs_pct)
        cogs_default = bool(price) and not (costs.get(asin) and (costs[asin].unit_cost or 0) > 0) and default_cogs_pct > 0
        c = costs.get(asin)
        rows.append({"asin": asin, "sale_price": price,
                     "cogs": cogs, "cogs_default": cogs_default,
                     "amazon_fee": amazon_fee, "profit_per_unit": profit_unit,
                     # amazon_fee broken out: fulfillment + referral per unit
                     "fba_fee": (c.fba_fee if c else 0.0) or 0.0,
                     "fba_source": c.fba_source if c else None,
                     "total_fee": getattr(c, "total_fee", None) if c else None,
                     "referral_pct": (c.referral_pct if c else default_ref),
                     "referral_fee": (getattr(c, "referral_fee", None) if c else None)
                                     or (round(price * (c.referral_pct if c else default_ref), 2)
                                         if price else None),
                     "break_even_acos": be, "break_even_roas": round(1 / be, 2) if be else None,
                     "target_acos": r.get("target_acos"),
                     "in_audit": asin in known,
                     "source": "uploaded" if uploaded is not None else ("derived" if derived else None)})
    rows.sort(key=lambda r: (not r["in_audit"], r["break_even_acos"] or 0))
    return {"rows": rows, "count": len(rows), "scope": "store",
            "matched": sum(1 for r in rows if r["in_audit"])}
