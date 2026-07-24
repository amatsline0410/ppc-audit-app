"""Cannibalization / Keyword Ownership Detector.

  POST /cannibal/run        bulk .xlsx -> detect + REPLACE findings (idempotent)
  GET  /cannibal/findings   findings (+ ?kind=duplicate_target|cross_product)
  GET  /cannibal/summary    counts + estimated overlap spend
  POST /cannibal/bulk       selected findings -> SP bulk (pauses + negativeExact)

Account-level (base db). The same upload can fan out from Waterfall via
POST /waterfall/upload?engines=waterfall,cannibal.
"""
from __future__ import annotations
import tempfile
from datetime import date
from fastapi import APIRouter, UploadFile, File, Depends, Query, Body, HTTPException, Response
from sqlalchemy.orm import Session
from .. import database as dbmod
from ..database import get_account_db as get_base_db
from ..config import default_thresholds
from ..pipeline import cannibal as cn, changelog as changelog_stage, ledger as ledger_stage

router = APIRouter()
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# last-scanned-file meta (app-wide upload pattern). Fixed key — Cannibalization
# is base-db scoped (cadence-agnostic), like Monitoring.
_META_KEY = "upload_meta:cannibal"


def _get_meta(db: Session) -> dict | None:
    return dbmod.get_project_extra(db.info.get("store"), db.info.get("project"), _META_KEY)


def _set_meta(db: Session, filename: str, findings_n: int) -> dict:
    meta = {"file": filename, "rows": findings_n, "uploaded": date.today().isoformat()}
    dbmod.set_project_extra(db.info.get("store"), db.info.get("project"), _META_KEY, meta)
    return meta


@router.post("/cannibal/run")
async def run(file: UploadFile = File(...),
              target_acos: float | None = Query(None, ge=0.01, le=2.0),
              min_clicks: int = Query(cn.MIN_CLICKS, ge=1, le=1000),
              db: Session = Depends(get_base_db)):
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Please upload an Amazon Sponsored Products bulk export "
                                 "(.xlsx/.xlsm) — ideally including the SP Search Term Report "
                                 "for cross-product detection.")
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "That file is empty — please choose a bulk file with data.")
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(blob)
        path = tmp.name
    goal = target_acos or default_thresholds.target_acos
    try:
        out = cn.run(db, path, goal, min_clicks)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, "Couldn't read that file — make sure it's a valid Amazon SP "
                                 f"bulk export. ({type(e).__name__})")
    out["upload_meta"] = _set_meta(db, file.filename or "bulk.xlsx", out.get("findings", 0))
    return out


@router.get("/cannibal/findings")
def findings(kind: str | None = Query(None, pattern="^(duplicate_target|cross_product)$"),
             db: Session = Depends(get_base_db)):
    return {"summary": cn.summary(db), "findings": cn.findings(db, kind),
            "upload_meta": _get_meta(db)}


@router.delete("/cannibal/data")
def delete_all(db: Session = Depends(get_base_db)):
    """Wipe the stored scan (findings only — nothing else clears)."""
    n = cn.delete_all(db)
    dbmod.set_project_extra(db.info.get("store"), db.info.get("project"), _META_KEY, None)
    return {"deleted": n}


@router.get("/cannibal/summary")
def summary(db: Session = Depends(get_base_db)):
    return cn.summary(db)


@router.post("/cannibal/bulk")
def bulk(req: dict = Body(...), db: Session = Depends(get_base_db)):
    chosen = req.get("findings") or []
    chosen = [f for f in chosen if f.get("verdict") in ("resolve", "coexist") and f.get("actions")]
    if not chosen:
        raise HTTPException(400, "Nothing selected — tick at least one resolvable finding "
                                 "before downloading the bulk file.")
    data = cn.to_bulk(chosen)
    try:
        changelog_stage.log(db, cn.changelog_entries(chosen), "cannibal")
    except Exception:
        db.rollback()
    led = cn.ledger_entries(chosen)
    if led:
        try:
            ledger_stage.record(db, led, "cannibal")
        except Exception:
            pass
    return Response(content=data, media_type=XLSX,
        headers={"Content-Disposition": "attachment; filename=cannibalization_bulk.xlsx"})
