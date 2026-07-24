"""POST /automate -> bulk file. POST /narrate -> LLM text. GET /config."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from ..database import get_db
from ..config import settings, default_thresholds
from ..pipeline import automate as automate_stage, changelog as changelog_stage
from ..llm.narrate import narrate as narrate_fn
from ..llm.providers import get_provider
from ..schemas import AutomateRequest, NarrateRequest, NarrateResponse

router = APIRouter()


@router.post("/automate")
def automate(req: AutomateRequest, db: Session = Depends(get_db)):
    flags = [f.model_dump() for f in req.flags]
    data = automate_stage.flags_to_bulk(db, flags)
    changelog_stage.log(db, changelog_stage.from_flags(db, flags), "audit_bulk")
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ppc_automation_bulk.xlsx"})


@router.post("/narrate", response_model=NarrateResponse)
def narrate(req: NarrateRequest):
    res = narrate_fn([f.model_dump() for f in req.flags], req.target_acos, req.mode)
    return NarrateResponse(**res)


@router.get("/config")
def get_config():
    p = get_provider()
    return {
        "default_target_acos": default_thresholds.target_acos,
        "thresholds": {"min_spend": default_thresholds.min_spend,
                       "min_clicks": default_thresholds.min_clicks},
        "llm": {"provider": settings.llm_provider, "model": settings.llm_model,
                "use_langchain": settings.llm_use_langchain, "available": p.available()},
    }
