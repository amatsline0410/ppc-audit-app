"""Mid-Month Check — Sponsored Products, single-panel: bid adjustments + heavy
negative targeting from the bulk's SP Search Term Report. Per-cadence isolated.

  POST /mid-month/upload   ingest the SP Search Term Report (replaces the snapshot)
  GET  /mid-month/plan     bid adjustments + negatives (wasted) + bleeders
  POST /mid-month/bulk     chosen rows -> SP bulk .xlsx
"""
from __future__ import annotations
import tempfile
from fastapi import APIRouter, UploadFile, File, Depends, Query, Body, HTTPException, Response
from sqlalchemy.orm import Session
from ..database import pinned_db
get_db = pinned_db("mid_month")   # every /mid-month route is Mid-Month cadence data — pin it
from ..pipeline import midmonth as mm, cadence as cadence_stage, changelog as changelog_stage, ledger as ledger_stage

router = APIRouter()


@router.post("/mid-month/upload")
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
        out = mm.ingest(db, path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, "Couldn't read that file — make sure it's a valid Amazon SP bulk "
                                 f"export with the Search Term Report sheet. ({type(e).__name__})")
    out["upload_meta"] = cadence_stage.set_upload_meta(db, file.filename or "bulk.xlsx",
                                                       out.get("terms", 0))
    return out


@router.get("/mid-month/plan")
def plan(target_acos: float | None = Query(None, ge=0.01, le=2.0), db: Session = Depends(get_db)):
    if not mm.has_data(db):
        raise HTTPException(400, "No Mid-Month data yet — upload your Sponsored Products bulk (with the "
                                 "SP Search Term Report) above to build bid adjustments and negatives.")
    t = cadence_stage.thresholds_for("mid_month", target_acos)
    return {**mm.plan(db, t), "upload_meta": cadence_stage.get_upload_meta(db)}


@router.get("/mid-month/compare")
def compare(target_acos: float | None = Query(None, ge=0.01, le=2.0), db: Session = Depends(get_db)):
    """Compare the previous Mid-Month upload vs the current one."""
    try:
        return mm.compare(db, target_acos)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/mid-month/bulk")
def bulk(req: dict = Body(...), db: Session = Depends(get_db)):
    bid_rows = req.get("bid_tweaks") or []
    negate_rows = (req.get("negates") or []) + (req.get("bleeders") or [])
    if not bid_rows and not negate_rows:
        raise HTTPException(400, "Nothing selected — tick at least one bid adjustment or negative row "
                                 "before downloading the bulk file.")
    data = mm.to_bulk(bid_rows, negate_rows)
    try:
        changelog_stage.log(db, changelog_stage.from_weekly(bid_rows, negate_rows), "mid_month")
    except Exception:
        db.rollback()
    # effective-bid ledger: the next export computes from these, not the snapshot
    try:
        ledger_stage.record_from(db, "midmonth", bids=bid_rows)
    except Exception:
        pass
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=mid_month_bulk.xlsx"})


@router.delete("/mid-month/data")
def delete_all(db: Session = Depends(get_db)):
    """Wipe all Mid-Month data: the search-term snapshot(s) AND the star schema its
    uploads fed, so the optimizer sub-panels clear too."""
    out = mm.delete_all(db)
    cadence_stage.clear_upload_meta(db)
    return out
