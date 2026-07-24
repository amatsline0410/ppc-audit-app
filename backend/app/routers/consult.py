"""Consultation — right campaign structure for the ASIN count.

  POST /consult/upload    SP bulk .xlsx -> tier route + tier-tuned problem scan
  GET  /consult/run       stored result (tier card + problems + resolutions)
  GET  /consult/tiers     the 7-tier ladder (for the UI)
  DELETE /consult/data    wipe the stored result

Account-level, cadence-partitioned like Waterfall / Structure Redesign
(get_account_db); result JSON persists per project via _meta.json extras.
"""
from __future__ import annotations
import tempfile
from datetime import date

from fastapi import APIRouter, UploadFile, File, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from ..database import get_account_db, get_project_extra, set_project_extra
from ..pipeline import consult as ct

router = APIRouter()

_KEY = "consult"


def _store_key(db: Session) -> tuple[str, str]:
    return db.info["store"], db.info["project"]


@router.get("/consult/tiers")
def tiers():
    return {"tiers": [{k: v for k, v in t.items() if k != "resolutions"} for t in ct.TIERS]}


@router.post("/consult/upload")
async def upload(file: UploadFile = File(...),
                 target_acos: float | None = Query(None, ge=0.01, le=2.0),
                 tier: int | None = Query(None, ge=1, le=7, description="optional tier override"),
                 db: Session = Depends(get_account_db)):
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(400, "Please upload an Amazon Sponsored Products bulk export (.xlsx/.xlsm/.csv).")
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "That file is empty — please choose a bulk file with data.")
    suffix = ".csv" if name.endswith(".csv") else ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(blob)
        path = tmp.name
    try:
        result = ct.analyze(path, target_acos or 0.30, tier_override=tier)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, "Couldn't read that file — make sure it's a valid Amazon SP bulk "
                                 f"export. ({type(e).__name__})")
    result["upload_meta"] = {"file": file.filename or "bulk.xlsx",
                             "rows": result["campaigns"], "uploaded": date.today().isoformat()}
    s, p = _store_key(db)
    set_project_extra(s, p, _KEY, result)
    return result


@router.get("/consult/run")
def run(db: Session = Depends(get_account_db)):
    s, p = _store_key(db)
    out = get_project_extra(s, p, _KEY)
    if not out:
        raise HTTPException(404, "No consultation yet — upload your Sponsored Products bulk above.")
    return out


@router.delete("/consult/data")
def clear(db: Session = Depends(get_account_db)):
    s, p = _store_key(db)
    set_project_extra(s, p, _KEY, None)
    return {"deleted": True}
