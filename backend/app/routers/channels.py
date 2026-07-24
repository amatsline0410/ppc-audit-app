"""Channels — SB/SD ingestion + channel-mix report (v1 read-only, no SB/SD bulk).

  POST /channels/upload        full bulk workbook -> SPChannelFact + SBFact + SDFact
  GET  /channels/summary       mix cards + brand split + dormant-SD banner
  GET  /channels/sb-keywords   SB keyword table with HIGH_ACOS / WASTED_SPEND flags
  GET  /channels/sd-targets    SD targeting table
  GET  /channels/sb-harvest    read-only SB STR harvest suggestions
  GET/PUT /channels/brand-terms  per-store brand-term list (_meta.json)
"""
from __future__ import annotations
import tempfile
from datetime import date
from fastapi import APIRouter, UploadFile, File, Depends, Query, Body, HTTPException
from sqlalchemy.orm import Session
from ..database import (get_account_db as get_base_db, get_store_extra, set_store_extra,
                        get_project_extra, set_project_extra)
from ..config import default_thresholds
from ..pipeline import channels as ch

router = APIRouter()

# last-uploaded-file meta (app-wide upload pattern). Fixed key — base-db scoped.
_META_KEY = "upload_meta:channels"


def _get_meta(db: Session):
    return get_project_extra(db.info.get("store"), db.info.get("project"), _META_KEY)


def _set_meta(db: Session, filename: str, rows: int) -> dict:
    meta = {"file": filename, "rows": rows, "uploaded": date.today().isoformat()}
    set_project_extra(db.info.get("store"), db.info.get("project"), _META_KEY, meta)
    return meta


def _brand_terms(db: Session) -> list[str]:
    return get_store_extra(db.info["store"], "brand_terms", []) or []


@router.post("/channels/upload")
async def upload(file: UploadFile = File(...), db: Session = Depends(get_base_db)):
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Please upload the full Amazon bulk workbook (.xlsx/.xlsm) "
                                 "with the SB Multi Ad Group / Sponsored Display sheets.")
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "That file is empty — please choose a bulk file with data.")
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(blob)
        path = tmp.name
    try:
        out = ch.ingest(db, path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, "Couldn't read that file — make sure it's a valid Amazon "
                                 f"bulk workbook. ({type(e).__name__})")
    out["upload_meta"] = _set_meta(db, file.filename or "bulk.xlsx",
                                   (out.get("sb_rows") or 0) + (out.get("sd_rows") or 0))
    return out


@router.get("/channels/summary")
def summary(target_acos: float | None = Query(None, ge=0.01, le=2.0),
            db: Session = Depends(get_base_db)):
    t = default_thresholds.merged(target_acos=target_acos)
    return {**ch.summary(db, _brand_terms(db), t), "upload_meta": _get_meta(db)}


@router.delete("/channels/data")
def delete_all(db: Session = Depends(get_base_db)):
    """Wipe the SB/SD/SP channel snapshots (brand terms survive)."""
    n = ch.delete_all(db)
    set_project_extra(db.info.get("store"), db.info.get("project"), _META_KEY, None)
    return {"deleted": n}


@router.get("/channels/sb-keywords")
def sb_keywords(target_acos: float | None = Query(None, ge=0.01, le=2.0),
                db: Session = Depends(get_base_db)):
    t = default_thresholds.merged(target_acos=target_acos)
    return {"rows": ch.sb_keywords(db, t, _brand_terms(db))}


@router.get("/channels/sd-targets")
def sd_targets(target_acos: float | None = Query(None, ge=0.01, le=2.0),
               db: Session = Depends(get_base_db)):
    t = default_thresholds.merged(target_acos=target_acos)
    return {"rows": ch.sd_targets(db, t)}


@router.get("/channels/sb-harvest")
def sb_harvest(target_acos: float | None = Query(None, ge=0.01, le=2.0),
               db: Session = Depends(get_base_db)):
    t = default_thresholds.merged(target_acos=target_acos)
    return ch.sb_harvest(db, t)


@router.get("/channels/brand-terms")
def get_brand_terms(db: Session = Depends(get_base_db)):
    return {"terms": _brand_terms(db)}


@router.put("/channels/brand-terms")
def put_brand_terms(body: dict = Body(...), db: Session = Depends(get_base_db)):
    terms = [str(x).strip() for x in (body.get("terms") or []) if str(x).strip()]
    set_store_extra(db.info["store"], "brand_terms", terms)
    return {"terms": terms}
