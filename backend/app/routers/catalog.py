"""Product Benchmark catalog — Amazon Category Listings Report per STORE.

Store-level (never overlaps another store; store dirs are per-user namespaced).
Amazon exports one file per category, so POST /catalog/upload MERGES by SKU —
upload each category file and they accumulate into one catalog.

POST   /catalog/upload : parse a Category Listings Report (.xlsm/.xlsx/.csv), upsert by SKU.
GET    /catalog        : light product rows + stats + upload history.
GET    /catalog/item   : full detail for one SKU (description, bullets, images, variation family).
DELETE /catalog        : clear the store's catalog.

SKU-level transactions (Payments Date Range report, store-level like the catalog):
POST   /catalog/transactions/upload : parse + merge a transaction report (.csv/.xlsx).
GET    /catalog/transactions        : date-filtered SKU rollup + transaction drill-down.
DELETE /catalog/transactions        : clear the store's transaction ledger.
"""
from __future__ import annotations
import os
import tempfile
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session
from .. import database as dbmod
from ..database import get_db
from ..pipeline import benchmark as bench_stage
from ..pipeline import catalog as cat
from ..pipeline import fbafees as fba
from ..pipeline import productads as pa
from ..pipeline import transactions as txn

router = APIRouter()


def _store(db: Session) -> str:
    sid = db.info.get("store")
    if not sid:
        raise HTTPException(400, "No store selected.")
    return sid


def _view(db: Session, data: dict) -> dict:
    """Overview joined to the selected audit's Product Ads (campaigns per ASIN)
    + break-even economics (store benchmark / catalog price + per-SKU COGS)."""
    ads = pa.by_asin(db) if pa.has_data(db) else None
    sid = db.info.get("store")
    econ = dbmod.get_project_econ(sid, db.info.get("project"))
    bench = bench_stage._read_store(sid)
    return cat.enrich(cat.overview(data), ads, bench, econ,
                      cat.read_cogs(sid), cat.fees_by_sku(sid))


@router.post("/catalog/upload")
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    name = file.filename or "catalog.xlsm"
    if not name.lower().endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(400, "Please upload an Amazon Category Listings Report "
                                 "(.xlsm/.xlsx/.csv) from Seller Central > Reports.")
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "That file is empty — please choose a report with data.")
    suffix = ".csv" if name.lower().endswith(".csv") else os.path.splitext(name)[1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(blob)
        path = tmp.name
    try:
        products = cat.parse_clr(path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, "Couldn't read that file — make sure it's a valid Category "
                                 f"Listings Report. ({type(e).__name__})")
    finally:
        os.unlink(path)
    sid = _store(db)
    data, added, updated = cat.merge(cat.read_catalog(sid), products, name)
    cat.write_catalog(sid, data)
    # NB: overview() carries an "updated" timestamp — keep the upsert count under
    # a distinct key ("replaced") so the spread can't clobber it.
    return {**_view(db, data), "file": name, "rows": len(products),
            "added": added, "replaced": updated}


@router.get("/catalog")
def catalog_overview(db: Session = Depends(get_db)) -> dict:
    return _view(db, cat.read_catalog(_store(db)))


@router.get("/catalog/item")
def catalog_item(sku: str = Query(...), db: Session = Depends(get_db)) -> dict:
    sid = _store(db)
    try:
        out = cat.item(cat.read_catalog(sid), sku)
    except ValueError as e:
        raise HTTPException(404, str(e))
    # catalog-level SEO check (no tracker project needed)
    out["seo"] = cat.seo_check(out)
    # join to the selected audit's Product Ads + break-even economics
    econ = dbmod.get_project_econ(db.info.get("store"), db.info.get("project"))
    bench = bench_stage._read_store(sid)
    out["be"] = cat.be_metrics(out, bench.get(out.get("asin")), econ,
                               cat.read_cogs(sid).get(out.get("sku")),
                               cat.fees_by_sku(sid).get(cat.norm_sku(out.get("sku"))))
    out["ads_connected"] = pa.has_data(db)
    out["ads"] = None
    if out["ads_connected"] and out.get("asin"):
        per = pa.by_asin(db)["asins"].get(out["asin"])
        if per:
            d = pa.detail(db, [out["asin"]])["rows"]
            out["ads"] = {**per, "campaign_rows": d[0]["campaigns"] if d else []}
    out["be_status"] = cat._be_status(out["ads"], out["be"])
    return out


@router.get("/catalog/export")
def catalog_export(db: Session = Depends(get_db)):
    """Client-ready Product Benchmark workbook with native Excel charts."""
    data = cat.read_catalog(_store(db))
    try:
        out = cat.report_xlsx(data, _view(db, data))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(content=out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=product_benchmark_report.xlsx"})


@router.delete("/catalog")
def catalog_clear(db: Session = Depends(get_db)) -> dict:
    sid = _store(db)
    p = cat._store_path(sid)
    if os.path.exists(p):
        os.unlink(p)
    return {"cleared": True}


# ---- per-SKU COGS override (% of selling price, default 40%) ------------------

@router.put("/catalog/cogs")
def set_cogs(payload: dict, db: Session = Depends(get_db)) -> dict:
    """Set/clear one product's COGS override. Accepts a decimal (`0.35`) or a
    percent (`35` / `35%`); empty/null clears back to the 40% default. Returns
    the product's recomputed break-even block."""
    sid = _store(db)
    sku = (payload.get("sku") or "").strip()
    if not sku:
        raise HTTPException(400, "sku is required")
    data = cat.read_catalog(sid)
    p = (data.get("products") or {}).get(sku)
    if not p:
        raise HTTPException(404, f"SKU {sku} not in the catalog")
    try:
        pct = cat.parse_cogs(payload.get("value"))
    except ValueError:
        raise HTTPException(400, "COGS must be a number — a decimal like 0.35 or a percent like 35%.")
    cogs = cat.read_cogs(sid)
    if pct is None:
        cogs.pop(sku, None)
    else:
        cogs[sku] = pct
    cat.write_cogs(sid, cogs)
    econ = dbmod.get_project_econ(sid, db.info.get("project"))
    bench = bench_stage._read_store(sid)
    return {"sku": sku, "cogs_pct": pct,
            "be": cat.be_metrics(p, bench.get(p.get("asin")), econ, pct,
                                 cat.fees_by_sku(sid).get(cat.norm_sku(sku)))}


# ---- base fulfillment fee per unit (FBA Fee Preview report) ------------------

@router.post("/catalog/fba-fees/upload")
async def fba_fees_upload(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    """Upload a Selling economics (SKU Economics) or FBA Fee Preview report —
    base fulfillment fee + referral fee per unit. Merges by SKU (or ASIN when the
    report has no MSKU); the fees feed every break-even ACoS / profit-per-unit in
    the Product Benchmark tab (and the PPC audit through break_even_map)."""
    name = file.filename or "selling_economics.csv"
    if not name.lower().endswith((".csv", ".txt", ".tsv", ".xlsx", ".xlsm")):
        raise HTTPException(400, "Please upload an Amazon Selling economics report "
                                 "(Reports > Business > Selling economics) or an FBA Fee "
                                 "Preview (Reports > Fulfilment) — .csv/.txt/.xlsx.")
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "That file is empty — please choose a report with data.")
    suffix = os.path.splitext(name)[1] or ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(blob)
        path = tmp.name
    try:
        rows = fba.parse_fees(path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, "Couldn't read that file — make sure it's a valid Selling "
                                 f"economics or FBA Fee Preview report. ({type(e).__name__})")
    finally:
        os.unlink(path)
    sid = _store(db)
    data, added, updated = fba.merge(fba.read_fba(sid), rows, name)
    fba.write_fba(sid, data)
    return {**fba.stats(sid), "file": name, "rows": len(rows),
            "added": added, "replaced": updated,
            "matched_asins": len(fba.by_asin(sid))}


@router.get("/catalog/fba-fees")
def fba_fees_view(db: Session = Depends(get_db)) -> dict:
    """Coverage + the per-SKU fee rows behind the fulfillment column."""
    sid = _store(db)
    data = fba.read_fba(sid)
    return {**fba.stats(sid), "rows": list((data.get("skus") or {}).values()),
            "matched_asins": len(fba.by_asin(sid))}


@router.delete("/catalog/fba-fees")
def fba_fees_clear(db: Session = Depends(get_db)) -> dict:
    fba.delete_all(_store(db))
    return {"cleared": True}


# ---- SKU-level transactions (Payments Date Range report) ---------------------

@router.post("/catalog/transactions/upload")
async def transactions_upload(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    name = file.filename or "transaction_report.csv"
    if not name.lower().endswith((".csv", ".xlsx", ".xlsm")):
        raise HTTPException(400, "Please upload an Amazon transaction report (.csv/.xlsx) "
                                 "from Seller Central > Payments > Reports Repository "
                                 "(Date Range report, transaction view).")
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "That file is empty — please choose a report with data.")
    suffix = ".csv" if name.lower().endswith(".csv") else os.path.splitext(name)[1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(blob)
        path = tmp.name
    try:
        rows = txn.parse_txn(path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, "Couldn't read that file — make sure it's a valid "
                                 f"transaction report. ({type(e).__name__})")
    finally:
        os.unlink(path)
    sid = _store(db)
    data, added, updated, dupes = txn.merge(txn.read_txn(sid), rows, name)
    txn.write_txn(sid, data)
    return {**txn.summary(data), "file": name, "rows": len(rows),
            "added": added, "updated": updated, "duplicates": dupes}


@router.get("/catalog/transactions")
def transactions_view(start: str | None = Query(None), end: str | None = Query(None),
                      sku: str | None = Query(None), db: Session = Depends(get_db)) -> dict:
    return txn.summary(txn.read_txn(_store(db)), start, end, sku)


@router.get("/catalog/transactions/export")
def transactions_export(start: str | None = Query(None), end: str | None = Query(None),
                        db: Session = Depends(get_db)):
    """Client-ready SKU Transactions workbook (charts) for the selected date window."""
    try:
        out = txn.report_xlsx(txn.read_txn(_store(db)), start, end)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(content=out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=sku_transactions_report.xlsx"})


@router.delete("/catalog/transactions")
def transactions_clear(db: Session = Depends(get_db)) -> dict:
    txn.delete_all(_store(db))
    return {"cleared": True}
