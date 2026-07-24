"""Audit cadence: presets + saved monthly runs (the rhythm tracker)."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..pipeline import cadence as cadence_stage

router = APIRouter()


class RunCreate(BaseModel):
    year: int
    month: int
    audit_type: str
    target_acos: float | None = None
    refresh: bool = False   # explicit re-audit: recompute the captured numbers at the current goal


class TaskToggle(BaseModel):
    done: bool


@router.get("/cadence/presets")
def presets():
    return {"presets": cadence_stage.list_presets(), "default": cadence_stage.DEFAULT_TYPE}


@router.get("/cadence/runs")
def runs(db: Session = Depends(get_db)):
    return {"runs": cadence_stage.list_runs(db)}


@router.post("/cadence/runs")
def create_run(body: RunCreate, db: Session = Depends(get_db)):
    if not (1 <= body.month <= 12):
        raise HTTPException(400, "month must be 1-12")
    if body.audit_type not in cadence_stage.PRESETS:
        raise HTTPException(400, "unknown audit type")
    return cadence_stage.get_or_create_run(db, body.year, body.month, body.audit_type,
                                           body.target_acos, refresh=body.refresh)


@router.patch("/cadence/tasks/{task_id}")
def toggle(task_id: int, body: TaskToggle, db: Session = Depends(get_db)):
    if not cadence_stage.toggle_task(db, task_id, body.done):
        raise HTTPException(404, "task not found")
    return {"id": task_id, "done": body.done}


@router.delete("/cadence/runs/{run_id}")
def delete(run_id: int, db: Session = Depends(get_db)):
    if not cadence_stage.delete_run(db, run_id):
        raise HTTPException(404, "run not found")
    return {"deleted": run_id}
