"""POST /upload : run stages 1-5, return summary. target_acos overridable."""
from __future__ import annotations
import tempfile
from datetime import date, datetime
from fastapi import APIRouter, UploadFile, File, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..config import default_thresholds
from ..pipeline import ingest, clean, load, audit, harvest as harvest_stage
from ..schemas import UploadSummary

router = APIRouter()


@router.post("/upload", response_model=UploadSummary)
async def upload(
    file: UploadFile = File(...),
    snapshot_date: str | None = Query(None, description="YYYY-MM-DD; defaults to today"),
    target_acos: float | None = Query(None, ge=0.01, le=2.0),
    db: Session = Depends(get_db),
):
    if not file.filename.lower().endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(400, "upload an Amazon SP bulk .xlsx/.csv")
    snap = datetime.strptime(snapshot_date, "%Y-%m-%d").date() if snapshot_date else date.today()

    suffix = ".csv" if file.filename.lower().endswith(".csv") else ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        path = tmp.name

    try:
        df = ingest.ingest(path)
        frames = clean.clean(ingest.split(df))
        counts = load.load(db, frames, snap)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Couldn't read that file — make sure it's a valid Amazon SP bulk export (.xlsx/.csv). ({type(e).__name__})")

    th = default_thresholds.merged(target_acos=target_acos)
    flags = audit.audit(db, th, snapshot=snap)
    tree = audit.build_tree(db, snapshot=snap)

    # OPTIONAL: many SP bulk exports carry an 'SP Search Term Report' sheet.
    # If present, harvest it through the normal STR process; if absent, skip.
    str_found, candidates = False, []
    try:
        str_df = harvest_stage.parse_str(path)
        if len(str_df):
            str_found = True
            candidates = [c.dict() for c in harvest_stage.harvest(db, str_df, th)]
    except ValueError:
        pass   # no search-term sheet in this bulk -> process bulk only

    return UploadSummary(snapshot_date=snap.isoformat(),
                         entity_counts={k: v for k, v in counts.items() if isinstance(v, int)},
                         asins=len(tree), flags=len(flags),
                         str_found=str_found, harvest_candidates=candidates)
