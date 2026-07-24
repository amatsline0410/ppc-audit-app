"""Per-ASIN break-even Benchmark (upload + view)."""
from __future__ import annotations
import tempfile
from fastapi import APIRouter, Depends, Query, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from .. import database as dbmod
from ..database import get_db
from ..pipeline import benchmark as bench_stage

router = APIRouter()


@router.get("/benchmark")
def get_benchmark(store: str = Query(dbmod.DEFAULT_STORE), project: str = Query(dbmod.DEFAULT_PROJECT),
                  db: Session = Depends(get_db)):
    return bench_stage.benchmark_view(db, dbmod.get_project_econ(db.info["store"], db.info["project"]))


@router.post("/benchmark/upload")
async def upload_benchmark(file: UploadFile = File(...),
                           store: str = Query(dbmod.DEFAULT_STORE), project: str = Query(dbmod.DEFAULT_PROJECT),
                           db: Session = Depends(get_db)):
    if not file.filename.lower().endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(400, "upload a Product Benchmark .xlsx/.csv")
    suffix = ".csv" if file.filename.lower().endswith(".csv") else ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        path = tmp.name
    try:
        df = bench_stage.parse_benchmark(path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    n = bench_stage.load_benchmark(db, df)
    return {"loaded": n, **bench_stage.benchmark_view(db, dbmod.get_project_econ(db.info["store"], db.info["project"]))}
