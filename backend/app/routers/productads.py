"""Product Ad performance — its own dedicated bulk upload + own table
(`ProductAdFact`), separate from the PPC Audit star schema.

POST /product-ads/upload : ingest the bulk's Product Ad rows (replaces the snapshot).
GET  /product-ads        : consolidated per-Product-Ad metrics + account total.
GET  /product-ads/detail : ads + per-campaign rollups for the selected ASIN(s).
"""
from __future__ import annotations
import tempfile
from fastapi import APIRouter, UploadFile, File, Depends, Query, HTTPException, Response
from sqlalchemy.orm import Session
from ..database import get_db
from ..pipeline import cadence as cadence_stage
from ..pipeline import productads as productads_stage

router = APIRouter()


@router.post("/product-ads/upload")
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    """Ingest a Sponsored Products bulk's Product Ad rows into Product Ads' own table."""
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(400, "Please upload an Amazon Sponsored Products bulk export "
                                 "(.xlsx/.xlsm/.csv) that includes the Product Ads.")
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "That file is empty — please choose a bulk file with data.")
    suffix = ".csv" if name.endswith(".csv") else ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(blob)
        path = tmp.name
    try:
        out = productads_stage.ingest(db, path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, "Couldn't read that file — make sure it's a valid Amazon SP bulk "
                                 f"export with Product Ads. ({type(e).__name__})")
    out["upload_meta"] = cadence_stage.set_upload_meta(db, file.filename or "bulk.xlsx",
                                                       out.get("product_ads", 0),
                                                       feature="product_ads")
    return out


@router.get("/product-ads")
def product_ads(db: Session = Depends(get_db)) -> dict:
    """Per-Product-Ad metrics + total, from Product Ads' own uploaded data."""
    return {**productads_stage.summary(db),
            "upload_meta": cadence_stage.get_upload_meta(db, feature="product_ads")}


@router.get("/product-ads/export")
def report_export(db: Session = Depends(get_db)):
    """Client-ready Product Ads workbook with native Excel charts."""
    try:
        data = productads_stage.report_xlsx(db)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=product_ads_report.xlsx"})


@router.delete("/product-ads/data")
def delete_all(db: Session = Depends(get_db)) -> dict:
    """Wipe the Product Ads snapshot (own table only — nothing else clears).
    The Product Benchmark tab's campaigns/ACoS join for this audit empties too."""
    n = productads_stage.delete_all(db)
    cadence_stage.clear_upload_meta(db, feature="product_ads")
    return {"deleted": n}


@router.get("/product-ads/detail")
def product_ads_detail(
    asins: str = Query(..., description="comma-separated ASINs to drill into"),
    db: Session = Depends(get_db),
) -> dict:
    """Ads + per-campaign rollups for the selected ASIN(s)."""
    want = [a.strip() for a in asins.split(",") if a.strip()]
    return productads_stage.detail(db, want)
