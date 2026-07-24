"""Listing Optimizer (Competitor Research / Indexed Keywords / SEO tracker).

Replaces the "Project Snore x Competitor Research" Google Sheet. Base-db scoped
(cadence-agnostic, like Monitoring); per-user + per-store/project via get_base_db.

  GET    /tracker/projects            list projects
  POST   /tracker/projects            create blank project (raw-data flow)
  POST   /tracker/migrate             one-time sheet xlsx import (per MAPPING.md)
  POST   /tracker/import              Cerebro snapshot import (?project_id=&date=&asin=)
  POST   /tracker/xray                raw X-ray export import (?project_id=)
  GET    /tracker/listing             raw copy + computed listing audit (?project_id=&variant=)
  PUT    /tracker/listing             save raw listing copy {project_id, element, text, variant}
  GET    /tracker/matrix              keyword x ASIN coverage grid (?project_id=&date=)
  GET    /tracker/scorecard           per-ASIN SEO scorecards + trend series
  GET    /tracker/movers              rank deltas since previous snapshot
  PATCH  /tracker/cell                manual rank edit (writes a snapshot row)
  POST   /tracker/ppc-suggest         rank-support keywords + competitor PT ASINs
  GET    /tracker/export              coverage matrix xlsx
  DELETE /tracker/projects/{id}       delete a project (cascade)
"""
from __future__ import annotations
import tempfile
from datetime import datetime, date
from fastapi import APIRouter, UploadFile, File, Depends, Query, Body, HTTPException, Response
from sqlalchemy.orm import Session
from ..database import get_base_db as get_db
from ..pipeline import tracker as tk

router = APIRouter()

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")


async def _tmp(file: UploadFile) -> str:
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(400, "upload an .xlsx/.xlsm/.csv export")
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "That file is empty.")
    suffix = ".csv" if name.endswith(".csv") else ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(blob)
        return tmp.name


@router.get("/tracker/projects")
def projects(db: Session = Depends(get_db)):
    return {"projects": tk.list_projects(db)}


@router.post("/tracker/projects")
def create_project(req: dict = Body(...), db: Session = Depends(get_db)):
    """Blank project for the raw-data flow: {name, primary_asin?}."""
    try:
        return tk.create_project(db, str(req.get("name") or ""), req.get("primary_asin"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/tracker/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    from .. import models as md
    p = db.get(md.TrackerProject, project_id)
    if not p:
        raise HTTPException(404, "Unknown tracker project.")
    tk.purge_project(db, p)
    db.commit()
    return {"deleted": project_id}


@router.post("/tracker/migrate")
async def migrate(file: UploadFile = File(...),
                  name: str | None = Query(None, description="Project name (defaults to filename)"),
                  snapshot_date: str | None = Query(None, description="YYYY-MM-DD label for the sheet's ranks"),
                  db: Session = Depends(get_db)):
    """One-time import of the competitor-research sheet (all tabs, per MAPPING.md)."""
    path = await _tmp(file)
    pname = name or (file.filename or "Imported project").rsplit(".", 1)[0][:80]
    try:
        return tk.migrate(db, path, pname, _date(snapshot_date))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, "Couldn't read that file — export the Google Sheet as .xlsx "
                                 f"with all tabs. ({type(e).__name__})")


@router.post("/tracker/import")
async def import_snapshot(file: UploadFile = File(...),
                          project_id: int = Query(...),
                          checked_at: str | None = Query(None, description="YYYY-MM-DD (default today)"),
                          asin: str | None = Query(None, description="target ASIN for single-ASIN Cerebro exports"),
                          db: Session = Depends(get_db)):
    """Ongoing Cerebro snapshot import (single- or multi-ASIN export)."""
    path = await _tmp(file)
    try:
        return tk.import_cerebro(db, project_id, path, _date(checked_at), asin)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Couldn't read that file as a Cerebro export. ({type(e).__name__})")


@router.post("/tracker/xray")
async def import_xray(file: UploadFile = File(...), project_id: int = Query(...),
                      db: Session = Depends(get_db)):
    """Raw X-ray export -> competitor upsert (manual audit fields preserved)."""
    path = await _tmp(file)
    try:
        return tk.import_xray(db, project_id, path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Couldn't read that file as an X-ray export. ({type(e).__name__})")


@router.get("/tracker/listing")
def listing(project_id: int = Query(...), variant: str = Query("current"),
            db: Session = Depends(get_db)):
    """Raw copy blocks + the computed listing-audit analysis."""
    try:
        return tk.listing_audit(db, project_id, variant)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/tracker/listing")
def set_listing(req: dict = Body(...), db: Session = Depends(get_db)):
    """Save raw listing copy: {project_id, element, text, variant?, asin?}.
    asin set = that competitor's copy (manual paste, no search_terms)."""
    if not req.get("project_id") or not req.get("element"):
        raise HTTPException(400, "project_id and element required")
    try:
        return tk.set_listing_copy(db, int(req["project_id"]), str(req["element"]),
                                   req.get("text"), str(req.get("variant") or "current"),
                                   req.get("asin") or None)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/tracker/listing/from-catalog")
def listing_from_catalog(req: dict = Body(...), db: Session = Depends(get_db)):
    """Perform Listing Audit on a Product Benchmark catalog product: pull its
    title / bullets / description / search terms out of the store catalog and
    prefill this project's OWN listing copy. Body: {project_id, sku}."""
    if not req.get("project_id") or not req.get("sku"):
        raise HTTPException(400, "project_id and sku required")
    from ..pipeline import catalog as catmod
    product = (catmod.read_catalog(db.info.get("store")).get("products") or {}) \
        .get(str(req["sku"]))
    if product is None:
        raise HTTPException(404, f"SKU {req['sku']!r} is not in this store's "
                                 "Product Benchmark catalog.")
    try:
        return tk.import_catalog_copy(db, int(req["project_id"]), product)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/tracker/banned")
def banned(db: Session = Depends(get_db)):
    """The Amazon banned-keyword list (shared across tracker projects)."""
    return {"phrases": tk.get_banned(db)}


@router.put("/tracker/banned")
def set_banned(req: dict = Body(...), db: Session = Depends(get_db)):
    """Replace the banned-keyword list: {text} — newline/comma separated."""
    return tk.set_banned(db, req.get("text"))


@router.get("/tracker/sanitize")
def sanitize(project_id: int = Query(...), variant: str = Query("current"),
             db: Session = Depends(get_db)):
    """Banned-keyword check over OUR OWN listing copy only."""
    try:
        return tk.sanitize(db, project_id, variant)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/tracker/competitors")
def competitors(project_id: int = Query(...), db: Session = Depends(get_db)):
    """The sheet's Main-tab competitor matrix data (attributes per ASIN + KPIs)."""
    try:
        return tk.competitors(db, project_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/tracker/competitor")
def competitor_field(req: dict = Body(...), db: Session = Depends(get_db)):
    """Manual audit edit: {id, field, value} (Yes/None rows + listing health score)."""
    if not req.get("id") or not req.get("field"):
        raise HTTPException(400, "id and field required")
    try:
        return tk.set_competitor_field(db, int(req["id"]), str(req["field"]), req.get("value"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/tracker/matrix")
def matrix(project_id: int = Query(...), date_: str | None = Query(None, alias="date"),
           db: Session = Depends(get_db)):
    try:
        return tk.matrix(db, project_id, _date(date_))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/tracker/scorecard")
def scorecard(project_id: int = Query(...), db: Session = Depends(get_db)):
    try:
        return tk.scorecard(db, project_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/tracker/movers")
def movers(project_id: int = Query(...), top: int = Query(25, ge=1, le=200),
           db: Session = Depends(get_db)):
    try:
        return tk.movers(db, project_id, top)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/tracker/cell")
def cell(req: dict = Body(...), db: Session = Depends(get_db)):
    """Manual grid edit: {keyword_id, asin, rank|null, date?}. Writes a snapshot row."""
    kid, asin = req.get("keyword_id"), req.get("asin")
    if not kid or not asin:
        raise HTTPException(400, "keyword_id and asin required")
    try:
        return tk.set_cell(db, int(kid), str(asin), req.get("rank"),
                           _date(req.get("date")))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/tracker/report/export")
def report_export(project_id: int = Query(...), db: Session = Depends(get_db)):
    """Client-ready Product Optimization report: one xlsx with native Excel charts
    mirroring the Overview / SEO / Listing Audit / Product Overview views."""
    try:
        data = tk.report_xlsx(db, project_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=product_optimization_report.xlsx"})


@router.get("/tracker/seo-recommend")
def seo_recommend(project_id: int = Query(...), variant: str = Query("current"),
                  db: Session = Depends(get_db)):
    """SEO recommendations + a ready-to-paste backend search-term line, computed
    from the Listing Audit copy vs the project's tracked keywords."""
    if variant not in ("current", "proposed"):
        raise HTTPException(400, "variant must be 'current' or 'proposed'")
    try:
        return tk.seo_recommend(db, project_id, variant)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/tracker/ppc-suggest")
def ppc_suggest(project_id: int = Query(...), max_page: int = Query(3, ge=2, le=10),
                min_sv: int = Query(500, ge=0), db: Session = Depends(get_db)):
    try:
        return tk.suggest(db, project_id, max_page, min_sv)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/tracker/export")
def export(project_id: int = Query(...), date_: str | None = Query(None, alias="date"),
           db: Session = Depends(get_db)):
    try:
        data = tk.export_matrix(db, project_id, _date(date_))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(content=data, media_type=XLSX_MIME,
                    headers={"Content-Disposition": "attachment; filename=listing_optimizer_matrix.xlsx"})


@router.post("/tracker/keywords/bulk")
def add_keywords(req: dict = Body(...), db: Session = Depends(get_db)):
    """Merge keywords into a project (from harvest / n-gram / manual paste).
    body: {project_id, source?, keywords: [{keyword, search_volume?, source?}]}
    Response carries seo_before/seo_after (primary ASIN indexed % / page 1 /
    avg rank) so the indexed-% impact of the push is visible immediately."""
    pid = int(req.get("project_id") or 0)
    try:
        before = tk.primary_seo(db, pid)
        out = tk.add_keywords(db, pid, req.get("keywords") or [],
                              source=str(req.get("source") or "manual"))
        out["seo_before"], out["seo_after"] = before, tk.primary_seo(db, pid)
        return out
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/tracker/relevancy-prompt")
def relevancy_prompt(project_id: int = Query(...), db: Session = Depends(get_db)):
    """Copyable AI prompt: keyword relevancy vs the CURRENT and PROPOSED listing."""
    try:
        return tk.relevancy_prompt(db, project_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
