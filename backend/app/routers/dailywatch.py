"""Daily Watch: dated bulk uploads + day-over-day anomaly compare + trend."""
from __future__ import annotations
import tempfile
from datetime import date, datetime, timedelta
from fastapi import APIRouter, UploadFile, File, Depends, Query, Body, HTTPException
from sqlalchemy.orm import Session
from ..database import pinned_db
get_db = pinned_db("daily")   # every /daily-watch route is Daily cadence data — pin it
from ..pipeline import dailywatch as dw

router = APIRouter()


def _d(s: str | None, fallback: date) -> date:
    if not s:
        return fallback
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, f"bad date '{s}', expected YYYY-MM-DD")


@router.post("/daily-watch/upload")
async def upload(file: UploadFile = File(...),
                 day: str | None = Query(None, description="YYYY-MM-DD this file represents"),
                 target_acos: float | None = Query(None, ge=0.01, le=2.0),
                 db: Session = Depends(get_db)):
    """Ingest one SP bulk file as the snapshot for `day` (defaults to today).
    Also evaluates the campaign monitor list: watches aligned to the goal ACoS
    on this day auto-clear (returned as `monitor_cleared`)."""
    name = file.filename.lower()
    if not name.endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(400, "upload an Amazon SP bulk .xlsx/.csv")
    d = _d(day, date.today())
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "That file is empty — please choose a bulk file with data.")
    suffix = ".csv" if name.endswith(".csv") else ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(blob)
        path = tmp.name
    try:
        out = dw.ingest_day(db, path, d)
        out["monitor_cleared"] = dw.evaluate_monitors(db, d, target_acos)
        return out
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Couldn't read that file — make sure it's a valid Amazon SP bulk export (.xlsx/.csv). ({type(e).__name__})")


@router.get("/daily-watch/days")
def days(db: Session = Depends(get_db)):
    return {"days": dw.days(db)}


@router.delete("/daily-watch/day")
def delete_day(day: str = Query(..., description="YYYY-MM-DD to remove"),
               db: Session = Depends(get_db)):
    """Delete a day's uploaded data (so its panel stays removed across reloads)."""
    return {"deleted": dw.delete_day(db, _d(day, date.today())), "day": day}


@router.delete("/daily-watch/data")
def delete_all(db: Session = Depends(get_db)):
    """Wipe every uploaded day (clears all Daily Watch data)."""
    return {"deleted": dw.delete_all(db)}


@router.get("/daily-watch/compare")
def compare(yesterday: str | None = Query(None), today: str | None = Query(None),
            target_acos: float | None = Query(None, ge=0.01, le=2.0),
            db: Session = Depends(get_db)):
    """Compare two days. Defaults: today=latest day, yesterday=day before it."""
    avail = dw.days(db)  # newest first
    if not avail:
        raise HTTPException(400, "No daily files uploaded yet — add your Yesterday and Today "
                                 "bulk files in the panels above to compare.")
    cur = _d(today, _d(avail[0] if avail else None, date.today()))
    prev_default = (datetime.strptime(avail[1], "%Y-%m-%d").date() if len(avail) > 1
                    else cur - timedelta(days=1))
    prev = _d(yesterday, prev_default)
    if cur == prev:
        raise HTTPException(400, "Pick two different days to compare (Yesterday and Today can't be "
                                 "the same date).")
    try:
        return dw.compare(db, prev, cur, target_acos)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/daily-watch/monitors")
def monitors(target_acos: float | None = Query(None, ge=0.01, le=2.0),
             db: Session = Depends(get_db)):
    """The isolated monitor area: active watches + recently cleared."""
    return dw.monitors(db, target_acos)


@router.post("/daily-watch/monitor")
def add_monitor(req: dict = Body(...), db: Session = Depends(get_db)):
    """Add a campaign to the watchlist: {campaign_id, name?}."""
    try:
        return dw.monitor(db, req.get("campaign_id"), req.get("name"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/daily-watch/monitor")
def remove_monitor(campaign_id: str = Query(...), db: Session = Depends(get_db)):
    """Remove a campaign's active watch."""
    return {"removed": dw.unmonitor(db, campaign_id)}


@router.get("/daily-watch/anomalies")
def anomalies(db: Session = Depends(get_db)):
    """ML anomaly scan (robust z-scores) over the whole uploaded day series."""
    return dw.anomalies(db)


@router.get("/daily-watch/series")
def series(start: str | None = Query(None), end: str | None = Query(None),
           db: Session = Depends(get_db)):
    s = _d(start, None) if start else None
    e = _d(end, None) if end else None
    return dw.series(db, s, e)
