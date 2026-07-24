"""Daily SALES & PPC Tracker (Monitoring panel).

POST /monitoring/upload : ingest a Business Report or SP campaign report (auto-
detected), accumulating one row per day. GET /monitoring?start=&end= : the
consolidated tracker + all features for a date range. Auth-gated + per-user
scoped via get_db, like every other pipeline router.
"""
from __future__ import annotations
import tempfile
from datetime import date, datetime
from fastapi import APIRouter, UploadFile, File, Depends, Query, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .. import database as dbmod
from ..database import get_base_db as get_db
from ..pipeline import monitoring as mon

router = APIRouter()

# Monitoring is cadence-agnostic (base db), so its upload meta uses a FIXED key —
# unlike the per-cadence panels — and keeps a rolling list of the last few files
# (daily reports accumulate; one single-file line would under-tell the story).
_META_KEY = "upload_meta:monitoring"
_META_FILES = 6


def _get_meta(db: Session) -> dict | None:
    return dbmod.get_project_extra(db.info.get("store"), db.info.get("project"), _META_KEY)


def _record_upload(db: Session, filename: str, out: dict) -> dict:
    meta = _get_meta(db) or {}
    files = [f for f in meta.get("files", []) if f.get("name") != filename]
    files.append({"name": filename, "days": out.get("days", 0), "kind": out.get("kind"),
                  "uploaded": date.today().isoformat()})
    meta = {"files": files[-_META_FILES:], "updated": date.today().isoformat()}
    dbmod.set_project_extra(db.info.get("store"), db.info.get("project"), _META_KEY, meta)
    return meta


class MonthSales(BaseModel):
    year: int
    month: int
    sales: float | None = None   # None clears the override


@router.post("/monitoring/upload")
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    name = file.filename.lower()
    if not name.endswith((".csv", ".xlsx", ".xlsm")):
        raise HTTPException(400, "upload a Business Report or SP campaign report (.csv/.xlsx)")
    suffix = ".csv" if name.endswith(".csv") else ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        path = tmp.name
    try:
        out = mon.ingest(db, path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Couldn't read that file — make sure it's a Business Report or SP campaign report (.csv/.xlsx). ({type(e).__name__})")
    out["upload_meta"] = _record_upload(db, file.filename or "report", out)
    return out


def _d(s: str | None, fallback: date) -> date:
    if not s:
        return fallback
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, f"bad date '{s}', expected YYYY-MM-DD")


@router.get("/monitoring")
def monitoring(start: str | None = Query(None), end: str | None = Query(None),
               target: float = Query(mon.TARGET_TACOS, ge=0, le=100),
               db: Session = Depends(get_db)):
    """Tracker for [start, end]. Defaults to the current month. `target` = TACOS goal %."""
    today = date.today()
    s = _d(start, today.replace(day=1))
    e = _d(end, today)
    if e < s:
        raise HTTPException(400, "end date is before start date")
    return {**mon.summary(db, s, e, target_tacos=target), "upload_meta": _get_meta(db)}


@router.delete("/monitoring/data")
def delete_all(db: Session = Depends(get_db)):
    """Wipe every uploaded tracker day. Manual month-sales overrides survive
    (hand-typed, not upload-derived)."""
    n = mon.delete_all(db)
    dbmod.set_project_extra(db.info.get("store"), db.info.get("project"), _META_KEY, None)
    return {"deleted": n}


@router.get("/monitoring/export")
def export(start: str | None = Query(None), end: str | None = Query(None),
           target: float = Query(mon.TARGET_TACOS, ge=0, le=100),
           db: Session = Depends(get_db)):
    """Tracker workbook with charts: Overview (KPIs, alerts, recommendations,
    weekday/weekend bar, B2B pie) + the per-day Daily Tracker sheet + line chart."""
    today = date.today()
    s = _d(start, today.replace(day=1))
    e = _d(end, today)
    if e < s:
        raise HTTPException(400, "end date is before start date")
    data = mon.export_xlsx(db, s, e, target_tacos=target)
    fname = f"daily_tracker_{s.isoformat()}_{e.isoformat()}.xlsx"
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"})


@router.post("/monitoring/month-sales")
def month_sales(body: MonthSales, db: Session = Depends(get_db)):
    """Set (or clear, sales=null) a manual total-sales figure for a month used by
    the overview's vs-last-month / vs-last-year comparison."""
    if not (1 <= body.month <= 12):
        raise HTTPException(400, "month must be 1-12")
    return mon.set_month_sales(db, body.year, body.month, body.sales)
