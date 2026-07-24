"""GET /asins, /asins/{asin}/tree, /audit — all accept target_acos override."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..pipeline import audit as audit_stage, cadence as cadence_stage
from ..schemas import FlagOut, AsinSummary

router = APIRouter()


def _flags(db, target_acos, audit_type=None):
    # the audit-cadence preset re-tunes the thresholds (e.g. Pause/Scale = 30 clicks)
    th = cadence_stage.thresholds_for(audit_type, target_acos)
    return audit_stage.audit(db, th)


@router.get("/audit", response_model=list[FlagOut])
def get_audit(
    target_acos: float | None = Query(None, ge=0.01, le=2.0),
    audit_type: str | None = Query(None, description="cadence preset key"),
    flag: str | None = None,
    severity: str | None = None,
    db: Session = Depends(get_db),
):
    flags = _flags(db, target_acos, audit_type)
    out = [f for f in flags if (not flag or f.flag == flag) and (not severity or f.severity == severity)]
    return [FlagOut(**f.__dict__) for f in out]


@router.get("/asins", response_model=list[AsinSummary])
def list_asins(target_acos: float | None = Query(None, ge=0.01, le=2.0),
               audit_type: str | None = Query(None), db: Session = Depends(get_db)):
    tree = audit_stage.build_tree(db)
    flags = _flags(db, target_acos, audit_type)
    flag_by_asin = {}
    for f in flags:
        flag_by_asin[f.asin] = flag_by_asin.get(f.asin, 0) + 1
    rows = []
    for asin, node in tree.items():
        sp = sa = od = 0.0
        for c in node["campaigns"]:
            m = c["metrics"]; sp += m["spend"]; sa += m["sales"]; od += m["orders"]
        rows.append(AsinSummary(asin=asin, spend=round(sp, 2), sales=round(sa, 2),
                    orders=int(od), acos=round(sp / sa, 4) if sa else None,
                    flag_count=flag_by_asin.get(asin, 0)))
    return sorted(rows, key=lambda r: r.spend, reverse=True)


@router.get("/asins/{asin}/tree")
def asin_tree(asin: str, db: Session = Depends(get_db)):
    tree = audit_stage.build_tree(db)
    node = tree.get(asin.upper()) or tree.get(asin)
    if not node:
        raise HTTPException(404, f"ASIN {asin} not found")
    return node
