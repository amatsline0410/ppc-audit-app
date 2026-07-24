"""Store + project management. Hierarchy: store -> project (audit) -> core process.

A store is an Amazon account (own dir); a project is one named audit inside it
(own isolated SQLite db). The core pipeline (upload/audit/harvest/automate) runs
scoped to a single project via ?store=&project=.
"""
from __future__ import annotations
from fastapi import APIRouter, Query, HTTPException, Depends, Response
from sqlalchemy.orm import Session
from .. import database as db
from .. import models as md
from .. import auth
from ..config import default_thresholds
from ..pipeline import (audit as audit_stage, changelog as changelog_stage,
                        checklist as checklist_stage, sales as sales_stage)
from ..schemas import StoreCreate, ProjectCreate, ProjectUpdate, ChecklistAdd, ChecklistToggle

router = APIRouter()

# all data tables, child -> parent order (safe under FK enforcement)
# child rows first so DB-level cascades aren't relied on. Includes the Monitoring
# daily table + the captured cadence runs so a flush leaves nothing data-derived.
# NOTE: FactDaily/MonthSalesOverride (Monitoring) live in the BASE db; a
# base-scoped flush clears them.
_DATA_MODELS = [md.ChangeLog, md.MinedKeyword, md.CadenceTask, md.CadenceRun,
                md.DailyWatchFact, md.WeeklyTermFact, md.MidMonthTermFact, md.FullMonthTermFact,
                md.PauseScaleTermFact, md.ProductAdFact, md.FactDaily, md.MonthSalesOverride,
                md.WaterfallItem, md.WaterfallRun, md.BidLedger, md.OverlapFinding,
                md.SBFact, md.SDFact, md.SPChannelFact,
                md.FactPerformance, md.FactPlacement,
                md.ProductBenchmark,
                md.DimTarget, md.DimAd, md.DimAdGroup, md.DimCampaign, md.DimProduct]


@router.get("/stores")
def get_stores(user: auth.User = Depends(auth.current_user)):
    return {"stores": db.list_stores(user.id), "default": db.DEFAULT_STORE}


@router.get("/stores/overview")
def stores_overview(target_acos: float | None = Query(None, ge=0.01, le=2.0),
                    user: auth.User = Depends(auth.current_user)):
    """KPI roll-up for ALL of the user's stores (default audit, latest snapshot):
    ad spend / ad sales / ACoS / ASINs / open flags — one row per store."""
    th = default_thresholds.merged(target_acos=target_acos)
    out = []
    for s in db.list_stores(user.id):
        sess = db.get_session(db.scoped(user.id, s["id"]), db.DEFAULT_PROJECT)
        try:
            ad = sales_stage.total_ad(sess)
            tree = audit_stage.build_tree(sess)
            flags = audit_stage.audit(sess, th)
        finally:
            sess.close()
        out.append({"id": s["id"], "title": s["title"],
                    "ad_spend": ad["spend"], "ad_sales": ad["sales"],
                    "acos": round(ad["spend"] / ad["sales"], 4) if ad["sales"] else None,
                    "asins": len(tree), "flags": len(flags)})
    out.sort(key=lambda r: r["ad_spend"], reverse=True)
    return {"stores": out}


@router.post("/stores")
def post_store(body: StoreCreate, user: auth.User = Depends(auth.current_user)):
    if not body.title.strip():
        raise HTTPException(400, "store title required")
    return db.create_store(user.id, body.title)


@router.get("/projects")
def get_projects(store: str = Query(db.DEFAULT_STORE), user: auth.User = Depends(auth.current_user)):
    """Audits in a store. Each carries `snapshot` = the latest PPC snapshot date in
    its base db (None until a bulk is uploaded) so the UI can label the audit's month."""
    sid = db.scoped(user.id, store)
    projects = db.list_projects(sid)
    for p in projects:
        sess = db.get_session(sid, p["id"])
        try:
            snap = audit_stage.active_snapshot(sess)
        finally:
            sess.close()
        p["snapshot"] = str(snap) if snap else None
    return {"projects": projects, "default": db.DEFAULT_PROJECT}


@router.post("/projects")
def post_project(body: ProjectCreate, store: str = Query(db.DEFAULT_STORE),
                 user: auth.User = Depends(auth.current_user)):
    if not body.title.strip():
        raise HTTPException(400, "audit title required")
    return db.create_project(db.scoped(user.id, store), body.title)


@router.patch("/projects/{project}")
def patch_project(project: str, body: ProjectUpdate, store: str = Query(db.DEFAULT_STORE),
                  user: auth.User = Depends(auth.current_user)):
    """Update a per-audit setting (currently the Goal ACoS)."""
    if not (0.01 <= body.acos_threshold <= 2.0):
        raise HTTPException(400, "acos_threshold out of range")
    return db.set_project_acos(db.scoped(user.id, store), project, body.acos_threshold)


@router.get("/changelog")
def get_changelog(limit: int = Query(500, ge=1, le=2000), source: str | None = None,
                  store: str = Query(db.DEFAULT_STORE), project: str = Query(db.DEFAULT_PROJECT),
                  session: Session = Depends(db.get_db)):
    return {"entries": changelog_stage.recent(session, limit=limit, source=source)}


@router.get("/changelog/export")
def export_changelog(source: str | None = None,
                     store: str = Query(db.DEFAULT_STORE), project: str = Query(db.DEFAULT_PROJECT),
                     session: Session = Depends(db.get_db)):
    """Change Log as a downloadable .xlsx (client report attachment)."""
    data = changelog_stage.export_xlsx(session, source=source)
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ppc_change_log.xlsx"})


@router.delete("/changelog")
def clear_changelog(source: str | None = None,
                    store: str = Query(db.DEFAULT_STORE), project: str = Query(db.DEFAULT_PROJECT),
                    session: Session = Depends(db.get_db)):
    """Wipe the change log for this audit (optionally one source only)."""
    return {"deleted": changelog_stage.clear(session, source=source)}


@router.get("/changelog/report")
def report_changelog(source: str | None = None,
                     store: str = Query(db.DEFAULT_STORE), project: str = Query(db.DEFAULT_PROJECT),
                     session: Session = Depends(db.get_db)):
    """Copy-paste client report message summarizing the changes."""
    return {"text": changelog_stage.report_text(session, source=source)}


@router.delete("/stores/{store}")
def delete_store(store: str, user: auth.User = Depends(auth.current_user)):
    """STORE-level delete: store + ALL its audits/data. Blocks the last store."""
    ids = {s["id"] for s in db.list_stores(user.id)}
    if store not in ids:
        raise HTTPException(404, "store not found")
    if len(ids) <= 1:
        raise HTTPException(400, "cannot delete the only store")
    return db.delete_store(db.scoped(user.id, store))


@router.delete("/projects/{project}")
def delete_project(project: str, store: str = Query(db.DEFAULT_STORE),
                   user: auth.User = Depends(auth.current_user)):
    """AUDIT-level delete: just this audit. Blocks the last audit in a store."""
    sid = db.scoped(user.id, store)
    pids = {p["id"] for p in db.list_projects(sid)}
    if project not in pids:
        raise HTTPException(404, "audit not found")
    if len(pids) <= 1:
        raise HTTPException(400, "cannot delete the only audit — flush it instead")
    return db.delete_project(sid, project)


@router.get("/checklist")
def get_checklist(store: str = Query(db.DEFAULT_STORE), project: str = Query(db.DEFAULT_PROJECT),
                  session: Session = Depends(db.get_db)):
    return checklist_stage.status(session, db.get_project_meta(session.info["store"], session.info["project"]))


@router.post("/checklist")
def add_checklist(body: ChecklistAdd, store: str = Query(db.DEFAULT_STORE),
                  project: str = Query(db.DEFAULT_PROJECT), session: Session = Depends(db.get_db)):
    if not body.text.strip():
        raise HTTPException(400, "task text required")
    return checklist_stage.add(session, body.text)


@router.patch("/checklist/{item_id}")
def toggle_checklist(item_id: int, body: ChecklistToggle, session: Session = Depends(db.get_db)):
    if not checklist_stage.toggle(session, item_id, body.done):
        raise HTTPException(404, "task not found")
    return {"id": item_id, "done": body.done}


@router.delete("/checklist/{item_id}")
def delete_checklist(item_id: int, session: Session = Depends(db.get_db)):
    if not checklist_stage.remove(session, item_id):
        raise HTTPException(404, "task not found")
    return {"deleted": item_id}


@router.post("/flush")
def flush(store: str = Query(db.DEFAULT_STORE), project: str = Query(db.DEFAULT_PROJECT),
          session: Session = Depends(db.get_db)):
    """Wipe ALL data in one audit (bulk, sales, costs, benchmark, placements).
    Keeps the audit itself + its title/Goal ACoS. Irreversible."""
    counts = {}
    for model in _DATA_MODELS:
        counts[model.__tablename__] = session.query(model).delete()
    session.commit()
    audit_stage.invalidate_tree_cache()
    return {"flushed": True, "store": store, "project": project,
            "rows_deleted": sum(counts.values())}
