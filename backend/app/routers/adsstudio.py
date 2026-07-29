"""Ads Studio — a standalone consolidation panel with its OWN bulk upload.

One Sponsored Products bulk feeds two of its own tables (`AdsStudioAdFact` +
`AdsStudioTargetFact`), so Studio never reads — or is invalidated by — whatever the
Product Ads tab holds. Its goal ACoS is its own setting too: consolidation is a
structural call the operator tunes separately from the audit-wide knob.

POST   /ads-studio/upload   : bulk -> Studio's product ads + keyword/target rows
GET    /ads-studio/products : the Product-Ads table, off Studio's own upload
GET    /ads-studio/settings : Studio's own goal ACoS   (POST to change it)
DELETE /ads-studio/data     : wipe Studio's snapshot (its tables only)
GET    /ads-studio/board    : campaigns for the picked ASINs + targets judged vs goal ACoS
POST   /ads-studio/plan     : groups -> migrate / pause / campaign-pause / consolidated view
POST   /ads-studio/bulk     : the chosen rows -> one Amazon SP bulk .xlsx (+ Change Log)
"""
from __future__ import annotations
import os
import tempfile
from fastapi import APIRouter, UploadFile, File, Depends, Query, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ..database import get_db
from ..pipeline import adsstudio as studio
from ..pipeline import cadence as cadence_stage
from ..pipeline import changelog

router = APIRouter()


class Group(BaseModel):
    name: str | None = None
    # the boss campaign everything in this group consolidates into
    destination_campaign_id: str
    destination_ad_group_id: str | None = None
    source_campaign_ids: list[str] = Field(default_factory=list)


class PlanReq(BaseModel):
    groups: list[Group] = Field(default_factory=list)


class BulkReq(BaseModel):
    """The rows the user actually ticked — never the whole plan by default, so a
    campaign pause can't ship just because it was computed."""
    migrate: list[dict] = Field(default_factory=list)
    pause_targets: list[dict] = Field(default_factory=list)
    campaign_pauses: list[dict] = Field(default_factory=list)


class SettingsReq(BaseModel):
    target_acos: float = Field(..., ge=0.01, le=2.0)


@router.post("/ads-studio/upload")
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    """Ads Studio's own bulk upload (replaces its snapshot — its tables only)."""
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(400, "Please upload an Amazon Sponsored Products bulk export "
                                 "(.xlsx/.xlsm/.csv) that includes the Product Ads.")
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "That file is empty — please choose a bulk file with data.")
    suffix = ".csv" if name.endswith(".csv") else ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(blob)
        path = tmp.name
    try:
        out = studio.ingest_bulk(db, path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, "Couldn't read that file — make sure it's a valid Amazon SP bulk "
                                 f"export with Product Ads. ({type(e).__name__})")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    out["upload_meta"] = cadence_stage.set_upload_meta(db, file.filename or "bulk.xlsx",
                                                       out.get("product_ads", 0),
                                                       feature="ads_studio")
    return out


@router.get("/ads-studio/products")
def products(db: Session = Depends(get_db)) -> dict:
    """Every product ad (ASIN + SKU) from Studio's own upload — pick ASINs here."""
    return {**studio.products(db),
            "has_targets": studio.has_targets(db),
            "settings": studio.get_settings(db),
            "upload_meta": cadence_stage.get_upload_meta(db, feature="ads_studio")}


@router.get("/ads-studio/settings")
def get_settings(db: Session = Depends(get_db)) -> dict:
    return studio.get_settings(db)


@router.post("/ads-studio/settings")
def set_settings(req: SettingsReq, db: Session = Depends(get_db)) -> dict:
    """Studio's own goal ACoS — applies to this feature only."""
    return studio.set_settings(db, req.target_acos)


@router.delete("/ads-studio/data")
def delete_all(db: Session = Depends(get_db)) -> dict:
    """Wipe Ads Studio's snapshot. Its own tables only — Product Ads is untouched."""
    n = studio.delete_all(db)
    cadence_stage.clear_upload_meta(db, feature="ads_studio")
    return {"deleted": n}


@router.get("/ads-studio/board")
def board(
    asins: str = Query(..., description="comma-separated ASINs picked in the panel"),
    campaign_types: str | None = Query(None, description="auto,manual (blank = both)"),
    tiers: str | None = Query(None, description="HERO,A,B,C,D (blank = all)"),
    target_acos: float | None = Query(None, ge=0.01, le=2.0),
    db: Session = Depends(get_db),
) -> dict:
    """Campaigns advertising the picked ASINs, each target judged keep/drop/review,
    each campaign tiered HERO/A/B/C/D on its own performance."""
    want = [a.strip() for a in asins.split(",") if a.strip()]
    if not want:
        raise HTTPException(400, "Pick at least one product first.")
    if not studio.has_data(db):
        raise HTTPException(400, "Upload a Sponsored Products bulk on the Ads Studio panel first.")
    if not studio.has_targets(db):
        raise HTTPException(400, "That bulk had no keyword or product-target rows, so there's "
                                 "nothing to judge against the goal ACoS. Re-export the bulk with "
                                 "its Keyword / Product Targeting rows included.")
    types = [c.strip() for c in (campaign_types or "").split(",") if c.strip()]
    want_tiers = [c.strip() for c in (tiers or "").split(",") if c.strip()]
    b = studio.board(db, want, studio.thresholds(db, target_acos), types)
    return studio.filter_tiers(b, want_tiers)


@router.post("/ads-studio/plan")
def plan(
    req: PlanReq,
    target_acos: float | None = Query(None, ge=0.01, le=2.0),
    db: Session = Depends(get_db),
) -> dict:
    """Draft the consolidation: what moves into each boss campaign, what gets paused."""
    if not req.groups:
        raise HTTPException(400, "Put at least one campaign into a consolidation group first.")
    groups = [g.model_dump() for g in req.groups]
    return studio.plan(db, groups, studio.thresholds(db, target_acos))


class FunnelPlanReq(BaseModel):
    asins: list[str] = Field(default_factory=list)
    # tier -> campaign id that owns it (EXACT and PT are the ones that receive)
    bosses: dict[str, str] = Field(default_factory=dict)
    campaign_types: list[str] = Field(default_factory=list)


class FunnelBulkReq(BaseModel):
    promotes: list[dict] = Field(default_factory=list)
    migrates: list[dict] = Field(default_factory=list)
    negatives: list[dict] = Field(default_factory=list)
    pauses: list[dict] = Field(default_factory=list)
    placements: list[dict] = Field(default_factory=list)


@router.get("/ads-studio/funnel")
def funnel_report(
    asins: str = Query(..., description="comma-separated ASINs picked in the panel"),
    campaign_types: str | None = Query(None),
    target_acos: float | None = Query(None, ge=0.01, le=2.0),
    db: Session = Depends(get_db),
) -> dict:
    """Funnel health: tier rollups, Phase-1 budget split, gaps, never-mix violations,
    and the Top-of-Search placement rule."""
    want = [a.strip() for a in asins.split(",") if a.strip()]
    if not want:
        raise HTTPException(400, "Pick at least one product first.")
    if not studio.has_targets(db):
        raise HTTPException(400, "Upload a Sponsored Products bulk with its Keyword / "
                                 "Product Targeting rows first.")
    types = [c.strip() for c in (campaign_types or "").split(",") if c.strip()]
    return studio.funnel_report(db, want, studio.thresholds(db, target_acos), types)


@router.post("/ads-studio/funnel/plan")
def funnel_plan(
    req: FunnelPlanReq,
    target_acos: float | None = Query(None, ge=0.01, le=2.0),
    db: Session = Depends(get_db),
) -> dict:
    """Route winners: discovery -> Exact / PT, with the upstream negatives."""
    if not req.asins:
        raise HTTPException(400, "Pick at least one product first.")
    if not (req.bosses.get("EXACT") or req.bosses.get("PT")):
        raise HTTPException(400, "Choose the Exact (and/or Product Targeting) campaign that "
                                 "winners should graduate into.")
    return studio.funnel_plan(db, req.asins, req.bosses,
                              studio.thresholds(db, target_acos), req.campaign_types)


@router.post("/ads-studio/funnel/bulk")
def funnel_bulk(req: FunnelBulkReq, db: Session = Depends(get_db)):
    """The chosen funnel rows -> one Amazon SP bulk (+ a Placement Adjustments sheet)."""
    if not (req.promotes or req.migrates or req.negatives or req.pauses or req.placements):
        raise HTTPException(400, "Nothing selected — tick at least one row to export.")
    data = studio.funnel_to_bulk(req.promotes, req.migrates, req.negatives,
                                 req.pauses, req.placements)
    changelog.log(db, changelog.from_funnel(req.promotes, req.migrates, req.negatives,
                                            req.pauses, req.placements), source="ads_studio")
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ads_studio_funnel.xlsx"})


@router.post("/ads-studio/bulk")
def bulk(req: BulkReq, db: Session = Depends(get_db)):
    """Chosen rows -> Amazon SP bulk .xlsx, logged to the Change Log."""
    if not (req.migrate or req.pause_targets or req.campaign_pauses):
        raise HTTPException(400, "Nothing selected — tick at least one row to export.")
    data = studio.to_bulk(req.migrate, req.pause_targets, req.campaign_pauses)
    changelog.log(db, changelog.from_adsstudio(req.migrate, req.pause_targets,
                                               req.campaign_pauses), source="ads_studio")
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ads_studio_consolidation.xlsx"})
