"""Bid optimization: full-portfolio Bid Optimizer + Placement optimizer.

GET  /bids/optimize       : optimal-bid plan for every eligible target
POST /bids/optimize/bulk  : chosen rows -> Amazon bid-update sheet
GET  /placements          : placement (ToS/PP/Rest) analysis + recommended %
POST /placements/bulk     : chosen rows -> Amazon Bidding-Adjustment sheet
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, Body, HTTPException, Response
from sqlalchemy.orm import Session
from ..database import get_db
from ..config import default_thresholds
from ..pipeline import bidopt as bidopt_stage, placement as placement_stage, changelog as changelog_stage, ledger as ledger_stage
from ..schemas import RowsRequest

router = APIRouter()
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/bids/optimize")
def bids_optimize(target_acos: float | None = Query(None, ge=0.01, le=2.0),
                  db: Session = Depends(get_db)):
    th = default_thresholds.merged(target_acos=target_acos)
    return bidopt_stage.optimize(db, th)


@router.post("/bids/optimize/bulk")
def bids_optimize_bulk(req: RowsRequest, db: Session = Depends(get_db)):
    data = bidopt_stage.to_bulk(db, req.rows)
    changelog_stage.log(db, changelog_stage.from_bidopt(req.rows), "bid_optimizer")
    # effective-bid ledger: the next export computes from these, not the snapshot
    try:
        ledger_stage.record_from(db, "bidopt", bids=req.rows)
    except Exception:
        pass
    return Response(content=data, media_type=_XLSX,
        headers={"Content-Disposition": "attachment; filename=ppc_bid_optimizer.xlsx"})


@router.get("/placements")
def placements(target_acos: float | None = Query(None, ge=0.01, le=2.0),
               db: Session = Depends(get_db)):
    th = default_thresholds.merged(target_acos=target_acos)
    return placement_stage.analyze(db, th)


@router.post("/placements/bulk")
def placements_bulk(req: dict = Body(...), db: Session = Depends(get_db)):
    rows = req.get("rows") or []
    companions = req.get("companions") or []          # base-bid cuts (PP bleeding at +0%)
    if not rows and not companions:
        raise HTTPException(400, "Nothing selected — tick at least one placement row first.")
    data = placement_stage.to_bulk(rows, companions)
    changelog_stage.log(db, changelog_stage.from_placement(rows), "placement")
    if companions:
        try:
            changelog_stage.log(db, changelog_stage.from_bidopt(companions), "placement")
        except Exception:
            db.rollback()
        try:
            ledger_stage.record_from(db, "placement", bids=companions)
        except Exception:
            pass
    return Response(content=data, media_type=_XLSX,
        headers={"Content-Disposition": "attachment; filename=ppc_placements.xlsx"})
