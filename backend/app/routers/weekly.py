"""Weekly Optimization — Sponsored Products, driven by the bulk's SP Search Term
Report. Upload the bulk → bid tweaks + search-term harvest → download the bulk
file to re-upload to Amazon. Per-cadence isolated (lands in the Weekly db).

  POST /weekly/upload   ingest the SP Search Term Report (replaces the snapshot)
  GET  /weekly/plan     bid tweaks + promote/negate candidates
  POST /weekly/bulk     chosen rows -> SP bulk .xlsx
"""
from __future__ import annotations
import tempfile
from fastapi import APIRouter, UploadFile, File, Depends, Query, Body, HTTPException, Response
from sqlalchemy.orm import Session
from ..database import pinned_db
get_db = pinned_db("weekly")   # every /weekly route is Weekly cadence data — pin it
from ..pipeline import weekly as wk, cadence as cadence_stage, changelog as changelog_stage, ledger as ledger_stage

router = APIRouter()


@router.post("/weekly/upload")
async def upload(file: UploadFile = File(...),
                 week: int = Query(1, ge=1, le=53, description="Week number this file represents"),
                 db: Session = Depends(get_db)):
    """Ingest the Sponsored Products bulk (with its Search Term Report sheet) as the
    snapshot for `week` (Week 1..N panels — re-uploading a week replaces it)."""
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
        return wk.ingest(db, path, week)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, "Couldn't read that file — make sure it's a valid Amazon SP bulk "
                                 f"export with the Search Term Report sheet. ({type(e).__name__})")


@router.get("/weekly/weeks")
def weeks(db: Session = Depends(get_db)):
    return {"weeks": wk.weeks(db)}


@router.delete("/weekly/week")
def delete_week(week: int = Query(..., ge=1, le=53), db: Session = Depends(get_db)):
    """Delete a week's uploaded data (so its panel stays removed across reloads)."""
    return {"deleted": wk.delete_week(db, week), "week": week}


@router.delete("/weekly/data")
def delete_all(db: Session = Depends(get_db)):
    """Wipe all Weekly Optimization data (every uploaded week) AND the star schema
    its uploads fed, so the optimizer sub-panels clear too."""
    return {"deleted": wk.delete_all(db), "star_rows": wk.clear_star_schema(db)}


@router.get("/weekly/series")
def series(db: Session = Depends(get_db)):
    return wk.series(db)


@router.get("/weekly/compare")
def compare(prev: int = Query(..., ge=1, le=53), cur: int = Query(..., ge=1, le=53),
            target_acos: float | None = Query(None, ge=0.01, le=2.0),
            db: Session = Depends(get_db)):
    """Compare two uploaded weeks (account deltas + per-campaign movers + spike flags)."""
    try:
        return wk.compare(db, prev, cur, target_acos)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/weekly/plan")
def plan(week: int | None = Query(None, ge=1, le=53),
         target_acos: float | None = Query(None, ge=0.01, le=2.0), db: Session = Depends(get_db)):
    if not wk.has_data(db):
        raise HTTPException(400, "No Weekly data yet — upload a week's Sponsored Products bulk (with "
                                 "the SP Search Term Report) in a Week panel above to build bid tweaks "
                                 "and harvest.")
    t = cadence_stage.thresholds_for("weekly", target_acos)
    return wk.plan(db, t, week)


@router.post("/weekly/bulk")
def bulk(req: dict = Body(...), db: Session = Depends(get_db)):
    bid_rows = req.get("bid_tweaks") or []
    harvest_rows = (req.get("promotes") or []) + (req.get("negates") or [])
    if not bid_rows and not harvest_rows:
        raise HTTPException(400, "Nothing selected — tick at least one bid tweak or harvest row "
                                 "before downloading the bulk file.")
    data = wk.to_bulk(bid_rows, harvest_rows)
    # log to the change log so the action is auditable
    try:
        changelog_stage.log(db, changelog_stage.from_weekly(bid_rows, harvest_rows), "weekly")
    except Exception:
        db.rollback()
    # effective-bid ledger: the next export computes from these, not the snapshot
    try:
        ledger_stage.record_from(db, "weekly", bids=bid_rows)
    except Exception:
        pass
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=weekly_optimization_bulk.xlsx"})
