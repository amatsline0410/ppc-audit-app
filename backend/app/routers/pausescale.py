"""Pause/Scale Audit — Sponsored Products, single-panel cut/scale decisions from
the bulk's SP Search Term Report. Per-cadence isolated.

  POST /pause-scale/upload   ingest the SP Search Term Report (replaces the snapshot)
  GET  /pause-scale/plan     scale winners + pause targets + pause campaigns
  POST /pause-scale/bulk     chosen rows -> SP bulk .xlsx
"""
from __future__ import annotations
import tempfile
from fastapi import APIRouter, UploadFile, File, Depends, Query, Body, HTTPException, Response
from sqlalchemy.orm import Session
from ..database import pinned_db
get_db = pinned_db("pause_scale")   # every /pause-scale route is Pause/Scale cadence data — pin it
from ..pipeline import pausescale as ps, cadence as cadence_stage, changelog as changelog_stage, ledger as ledger_stage

router = APIRouter()


@router.post("/pause-scale/upload")
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
        out = ps.ingest(db, path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, "Couldn't read that file — make sure it's a valid Amazon SP bulk "
                                 f"export with the Search Term Report sheet. ({type(e).__name__})")
    out["upload_meta"] = cadence_stage.set_upload_meta(db, file.filename or "bulk.xlsx",
                                                       out.get("terms", 0))
    return out


@router.get("/pause-scale/plan")
def plan(target_acos: float | None = Query(None, ge=0.01, le=2.0), db: Session = Depends(get_db)):
    if not ps.has_data(db):
        raise HTTPException(400, "No Pause/Scale data yet — upload your Sponsored Products bulk (with "
                                 "the SP Search Term Report) above to build the cut/scale plan.")
    t = cadence_stage.thresholds_for("pause_scale", target_acos)
    return {**ps.plan(db, t), "upload_meta": cadence_stage.get_upload_meta(db)}


@router.post("/pause-scale/bulk")
def bulk(req: dict = Body(...), db: Session = Depends(get_db)):
    scale_rows = req.get("scales") or []
    pause_rows = req.get("pauses") or []
    campaign_rows = req.get("campaign_pauses") or []
    if not scale_rows and not pause_rows and not campaign_rows:
        raise HTTPException(400, "Nothing selected — tick at least one scale or pause row before "
                                 "downloading the bulk file.")
    data = ps.to_bulk(scale_rows, pause_rows, campaign_rows)
    try:
        changelog_stage.log(db, changelog_stage.from_pausescale(scale_rows, pause_rows, campaign_rows), "pause_scale")
    except Exception:
        db.rollback()
    # effective-bid ledger: the next export computes from these, not the snapshot
    try:
        ledger_stage.record_from(db, "pausescale", bids=scale_rows, pauses=pause_rows)
    except Exception:
        pass
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=pause_scale_bulk.xlsx"})


@router.delete("/pause-scale/data")
def delete_all(db: Session = Depends(get_db)):
    """Wipe all Pause/Scale data: the search-term snapshot(s) AND the star schema its
    uploads fed, so the optimizer sub-panels clear too."""
    out = ps.delete_all(db)
    cadence_stage.clear_upload_meta(db)
    return out
