"""Full Month Audit — Sponsored Products, single-panel full optimization (bid
adjustments + harvest promote + negatives + bleeders) from the bulk's SP Search
Term Report. Per-cadence isolated (lands in the base / Full-Month db).

  POST /full-month/upload   ingest the SP Search Term Report (replaces the snapshot)
  GET  /full-month/plan     bid tweaks + promotes + negates + bleeders
  POST /full-month/bulk     chosen rows -> SP bulk .xlsx
"""
from __future__ import annotations
import tempfile
from fastapi import APIRouter, UploadFile, File, Depends, Query, Body, HTTPException, Response
from sqlalchemy.orm import Session
from ..database import pinned_db
get_db = pinned_db("full_month")   # every /full-month route is Full Month (base db) data — pin it
from ..pipeline import fullmonth as fm, cadence as cadence_stage, changelog as changelog_stage, ledger as ledger_stage

router = APIRouter()


@router.post("/full-month/upload")
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Ingest the Sponsored Products bulk (with its Search Term Report sheet)."""
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(400, "Please upload an Amazon Sponsored Products bulk export "
                                 "(.xlsx/.xlsm/.csv) that includes the SP Search Term Report.")
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "That file is empty — please choose a bulk file with data.")
    suffix = ".csv" if name.endswith(".csv") else ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(blob)
        path = tmp.name
    try:
        out = fm.ingest(db, path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, "Couldn't read that file — make sure it's a valid Amazon SP bulk "
                                 f"export with the Search Term Report sheet. ({type(e).__name__})")
    out["upload_meta"] = cadence_stage.set_upload_meta(db, file.filename or "bulk.xlsx",
                                                       out.get("terms", 0))
    return out


@router.get("/full-month/plan")
def plan(target_acos: float | None = Query(None, ge=0.01, le=2.0), db: Session = Depends(get_db)):
    if not fm.has_data(db):
        raise HTTPException(400, "No Full Month data yet — upload your Sponsored Products bulk (with "
                                 "the SP Search Term Report) above to build the full optimization plan.")
    t = cadence_stage.thresholds_for("full_month", target_acos)
    return {**fm.plan(db, t), "upload_meta": cadence_stage.get_upload_meta(db)}


@router.get("/full-month/compare")
def compare(target_acos: float | None = Query(None, ge=0.01, le=2.0), db: Session = Depends(get_db)):
    """Compare the previous Full Month upload vs the current one."""
    try:
        return fm.compare(db, target_acos)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/full-month/bulk")
def bulk(req: dict = Body(...), db: Session = Depends(get_db)):
    bid_rows = req.get("bid_tweaks") or []
    harvest_rows = (req.get("promotes") or []) + (req.get("negates") or []) + (req.get("bleeders") or [])
    if not bid_rows and not harvest_rows:
        raise HTTPException(400, "Nothing selected — tick at least one bid adjustment or harvest row "
                                 "before downloading the bulk file.")
    data = fm.to_bulk(bid_rows, harvest_rows)
    try:
        changelog_stage.log(db, changelog_stage.from_weekly(bid_rows, harvest_rows), "full_month")
    except Exception:
        db.rollback()
    # effective-bid ledger: the next export computes from these, not the snapshot
    try:
        ledger_stage.record_from(db, "fullmonth", bids=bid_rows)
    except Exception:
        pass
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=full_month_bulk.xlsx"})


@router.delete("/full-month/data")
def delete_all(db: Session = Depends(get_db)):
    """Wipe all Full Month data: the search-term snapshot(s) AND the star schema its
    uploads fed, so the optimizer sub-panels clear too. Full Month lives in the BASE
    audit db — this also clears the audit's bulk-derived data (dashboard/flags)."""
    out = fm.delete_all(db)
    cadence_stage.clear_upload_meta(db)
    return out
