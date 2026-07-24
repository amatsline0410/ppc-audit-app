"""POST /harvest : Search Term Report -> promote/negate candidates.
POST /harvest/bulk : chosen candidates -> SP bulk-upload file.

The account structure (campaigns / ad groups / keywords) must already be loaded
via /upload or the bundled seed — the STR only carries names, so IDs are
re-attached from the loaded dims.

POST /harvest/from-bulk : the PREFERRED path — upload the SP BULK file itself;
its embedded "SP Search Term Report" sheet carries the report's real Campaign /
Ad Group / Keyword / Product Targeting IDs, so nothing is re-attached by name
(reuses the Weekly engine). POST /harvest/from-bulk/file : chosen rows -> SP
bulk that updates/creates/negates by exact ID.
"""
from __future__ import annotations
import tempfile
from types import SimpleNamespace
from fastapi import APIRouter, UploadFile, File, Depends, Query, HTTPException, Body, Response
from sqlalchemy.orm import Session
from ..database import get_db
from ..config import default_thresholds
from .. import models as md
from ..pipeline import harvest as harvest_stage, changelog as changelog_stage
from ..pipeline import ingest as ingest_stage
from ..pipeline import keywords as kw_stage
from ..pipeline import ledger as ledger_stage
from ..pipeline import waterfall as wf
from ..pipeline import weekly as wk
from ..schemas import HarvestCandidate, HarvestBulkRequest

router = APIRouter()


def _project_asins(db: Session, project_id: int) -> set[str]:
    """The keyword project's OWN ASINs (primary + is_primary competitor rows),
    read from the base db (tracker lives there, harvest runs per-cadence)."""
    base = ledger_stage.base_session(db)
    try:
        asins: set[str] = set()
        proj = base.get(md.TrackerProject, project_id)
        if proj and proj.primary_asin:
            asins.add(proj.primary_asin.strip().upper())
        for c in base.query(md.TrackedCompetitor).filter(
                md.TrackedCompetitor.project_id == project_id,
                md.TrackedCompetitor.is_primary == True):  # noqa: E712
            if c.asin:
                asins.add(c.asin.strip().upper())
        return asins
    finally:
        base.close()


def _ag_asin_map(path: str) -> dict[str, set[str]]:
    """ad_group_id -> advertised ASINs, from the bulk's Product Ad rows."""
    ads = wf._frame(ingest_stage.frames(path), "product ad")
    out: dict[str, set[str]] = {}
    if len(ads):
        for _, r in ads.iterrows():
            ag, asin = wf._s(r.get("ad_group_id")), wf._s(r.get("asin")).upper()
            if ag and asin:
                out.setdefault(ag, set()).add(asin)
    return out


@router.post("/harvest", response_model=list[HarvestCandidate])
async def harvest(
    file: UploadFile = File(...),
    target_acos: float | None = Query(None, ge=0.01, le=2.0),
    min_spend: float | None = Query(None, ge=0.0, description="loser spend floor"),
    min_orders: int = Query(1, ge=1, description="winner order floor"),
    db: Session = Depends(get_db),
):
    if not file.filename.lower().endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(400, "upload an Amazon SP Search Term Report .xlsx/.csv")

    suffix = ".csv" if file.filename.lower().endswith(".csv") else ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        path = tmp.name

    try:
        df = harvest_stage.parse_str(path)
    except ValueError as e:
        raise HTTPException(400, str(e))

    th = default_thresholds.merged(target_acos=target_acos, min_spend=min_spend)
    candidates = harvest_stage.harvest(db, df, th, min_orders=min_orders)
    # keyword terms only — ASIN-shaped search terms are hidden in this panel
    candidates = [c for c in candidates if not harvest_stage.is_asin(c.search_term)]
    return [HarvestCandidate(**c.dict()) for c in candidates]


@router.post("/harvest/bulk")
def harvest_bulk(req: HarvestBulkRequest, db: Session = Depends(get_db)):
    rows = [c.model_dump() for c in req.candidates]
    data = harvest_stage.harvest_to_bulk(rows)
    changelog_stage.log(db, changelog_stage.from_harvest(rows), "harvest")
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ppc_harvest_bulk.xlsx"})


@router.post("/harvest/from-bulk")
async def harvest_from_bulk(
    file: UploadFile = File(...),
    target_acos: float | None = Query(None, ge=0.01, le=2.0),
    min_spend: float | None = Query(None, ge=0.0, description="loser spend floor"),
    min_orders: int = Query(1, ge=1, description="winner order floor"),
    project_id: int | None = Query(None, description="keyword project — scope to its ASINs"),
    db: Session = Depends(get_db),
):
    """Harvest from the SP BULK file's embedded 'SP Search Term Report' sheet —
    every candidate carries the report's real entity IDs (no name mapping).
    Keyword terms only (ASIN-shaped search terms are dropped — this panel mines
    keywords). With ?project_id=, only terms from ad groups advertising the
    keyword project's ASIN(s) are kept (matched via the bulk's Product Ad rows)."""
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
        # the weekly engine is model-agnostic but reads rows by ATTRIBUTE
        # (it normally gets WeeklyTermFact instances) — wrap the parsed dicts
        rows = [SimpleNamespace(**r) for r in wk.parse_str_sheet(path)]
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, "Couldn't read that file — make sure it's a valid Amazon SP bulk "
                                 f"export with the Search Term Report sheet. ({type(e).__name__})")
    th = default_thresholds.merged(target_acos=target_acos, min_spend=min_spend)
    h = wk.compute_harvest(rows, th, min_orders=min_orders)

    # keyword terms only: ASIN-shaped customer search terms are product hits,
    # not keywords — this panel mines keywords for the project
    before = len(h["promotes"]) + len(h["negates"])
    h["promotes"] = [r for r in h["promotes"] if not harvest_stage.is_asin(str(r.get("search_term") or ""))]
    h["negates"] = [r for r in h["negates"] if not harvest_stage.is_asin(str(r.get("search_term") or ""))]
    asin_terms_hidden = before - len(h["promotes"]) - len(h["negates"])

    # scope to the keyword project's ASIN(s): keep only terms whose ad group
    # advertises one of them (Product Ad rows in the same bulk carry the mapping)
    scope = None
    if project_id:
        asins = _project_asins(db, project_id)
        if asins:
            ag_map = _ag_asin_map(path)
            keep = lambda r: bool(ag_map.get(str(r.get("ad_group_id") or ""), set()) & asins)  # noqa: E731
            b2 = len(h["promotes"]) + len(h["negates"])
            h["promotes"] = [r for r in h["promotes"] if keep(r)]
            h["negates"] = [r for r in h["negates"] if keep(r)]
            scope = {"asins": sorted(asins),
                     "hidden": b2 - len(h["promotes"]) - len(h["negates"])}
        else:
            scope = {"asins": [], "hidden": 0,
                     "note": "Keyword project has no primary ASIN — showing all ad groups."}

    # merge the STR's keyword terms into the mined pool as a third source
    # ("STR"): impressions feed the Impression Share metric (impressions ÷
    # search volume × 100) in the SEO scorecard preview. Same scoping as the
    # table: keyword terms only, project-ASIN ad groups only when scoped.
    agg: dict[str, dict] = {}
    scoped_ags = None
    if scope and scope.get("asins"):
        scoped_ags = {ag for ag, asins in _ag_asin_map(path).items()
                      if asins & set(scope["asins"])}
    for r in rows:
        term = str(getattr(r, "search_term", "") or "").strip()
        if not term or harvest_stage.is_asin(term):
            continue
        if scoped_ags is not None and str(getattr(r, "ad_group_id", "")) not in scoped_ags:
            continue
        a = agg.setdefault(term.lower(), {"keyword": term, "impressions": 0, "clicks": 0, "orders": 0})
        a["impressions"] += int(getattr(r, "impressions", 0) or 0)
        a["clicks"] += int(getattr(r, "clicks", 0) or 0)
        a["orders"] += int(getattr(r, "orders", 0) or 0)
    pool_merged = kw_stage.merge_str_terms(db, list(agg.values())) if agg else None

    # stamp each candidate with its ad group's product break-even ACoS (from the
    # loaded account's ads + the catalog's real-fee economics)
    ag_be = harvest_stage.ag_break_even_map(db)
    for r in h["promotes"] + h["negates"]:
        r["break_even"] = ag_be.get(str(r.get("ad_group_id")))
    return {"file": file.filename, "summary": wk.summarize(rows),
            "promotes": h["promotes"], "negates": h["negates"],
            "asin_terms_hidden": asin_terms_hidden, "scope": scope,
            "pool_merged": pool_merged,
            "target_acos": round(th.target_acos, 4)}


@router.post("/harvest/from-bulk/file")
def harvest_from_bulk_file(req: dict = Body(...), db: Session = Depends(get_db)):
    """Chosen bulk-harvest rows -> one validated SP bulk (creates + negatives by
    the exact IDs the report carried)."""
    harvest_rows = (req.get("promotes") or []) + (req.get("negates") or [])
    if not harvest_rows:
        raise HTTPException(400, "Nothing selected — tick at least one promote or negate row "
                                 "before downloading the bulk file.")
    data = wk.to_bulk([], harvest_rows)
    try:
        changelog_stage.log(db, changelog_stage.from_weekly([], harvest_rows), "harvest")
    except Exception:
        db.rollback()
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ppc_harvest_bulk.xlsx"})
