"""Waterfall Restructure Engine — one uploaded bulk -> a phased restructure plan
(A renames / B loser bid cuts / C creates / D pauses) + day-0 benchmark.

  POST /waterfall/upload      bulk .xlsx -> classify + plan -> new draft run
  GET  /waterfall/run         latest run: boss map, items grouped by phase
  POST /waterfall/bulk        ?phase=A + selected item ids -> bulk .xlsx (ChangeLog + BidLedger)
  POST /waterfall/applied     ?phase=A -> mark that phase applied (in order; unlocks D)
  POST /waterfall/override    {overrides: {"sku|slot": campaign_id}} -> re-elect bosses, rebuild
  GET  /waterfall/benchmark   day-0 vs latest hero benchmark (day-21 verdict)
  GET/PUT /waterfall/settings naming template, goal acos, budget, seeds, heroes,
                              bid floor/ceiling, force-down-only, pause protection
  GET  /waterfall/ledger      pending (unapplied) exported bid changes + stale count
  POST /waterfall/ledger/applied|discard   resolve pending ledger rows

Account-level, cadence-partitioned: the db is the Audit Cadence's own file
(get_account_db). full_month / no cadence resolve to the base project db.
"""
from __future__ import annotations
import tempfile
from fastapi import APIRouter, UploadFile, File, Depends, Query, Body, HTTPException, Response
from sqlalchemy.orm import Session
from ..database import get_account_db as get_base_db, get_project_extra, set_project_extra
from ..pipeline import waterfall as wf, ledger as ledger_stage, changelog as changelog_stage
from .. import models as md

router = APIRouter()

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

SETTINGS_KEY = "waterfall"
SETTINGS_FIELDS = ("naming_template", "budget", "goal_acos", "seed_min_orders",
                   "seed_copies", "hero_n", "heroes", "bid_floor", "bid_ceiling",
                   "force_down_only", "protect_min_orders", "protected_campaign_ids",
                   "slot_bids", "new_strategy")


def _settings(db: Session) -> dict:
    saved = get_project_extra(db.info["store"], db.info["project"], SETTINGS_KEY, {}) or {}
    out = {k: saved.get(k, wf.DEFAULTS.get(k)) for k in SETTINGS_FIELDS}
    # resolve None -> concrete per-slot bid defaults so the UI shows values
    out["slot_bids"] = {**wf.DEFAULT_SLOT_BIDS, **(out.get("slot_bids") or {})}
    out["new_strategy"] = out.get("new_strategy") or "down"
    return out


@router.get("/waterfall/settings")
def get_settings(db: Session = Depends(get_base_db)):
    return _settings(db)


@router.put("/waterfall/settings")
def put_settings(body: dict = Body(...), db: Session = Depends(get_base_db)):
    cur = _settings(db)
    for k in SETTINGS_FIELDS:
        if k in body:
            cur[k] = body[k]
    set_project_extra(db.info["store"], db.info["project"], SETTINGS_KEY, cur)
    return cur


@router.post("/waterfall/upload")
async def upload(file: UploadFile = File(...),
                 engines: str = Query("waterfall", description="fan-out: waterfall,cannibal"),
                 db: Session = Depends(get_base_db)):
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Please upload an Amazon Sponsored Products bulk export "
                                 "(.xlsx/.xlsm) — the full sheet with Campaign / Ad Group / "
                                 "Product Ad / Keyword rows.")
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "That file is empty — please choose a bulk file with data.")
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(blob)
        path = tmp.name
    wanted = {e.strip() for e in engines.split(",") if e.strip()}
    try:
        if "waterfall" in wanted:
            wf.save_bulk(db, blob)          # kept so boss overrides can rebuild
        out = wf.build_run(db, path, _settings(db)) if "waterfall" in wanted else {}
        if "cannibal" in wanted:
            from ..pipeline import cannibal as cn
            goal = float(_settings(db).get("goal_acos") or wf.DEFAULTS["goal_acos"])
            out["cannibal"] = cn.run(db, path, goal)
        if "waterfall" in wanted:
            out["upload_meta"] = _set_meta(db, file.filename or "bulk.xlsx",
                                           (out.get("summary") or {}).get("campaigns") or 0)
        return out
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, "Couldn't read that file — make sure it's a valid Amazon SP "
                                 f"bulk export. ({type(e).__name__})")


# last-uploaded-file meta (app-wide upload pattern). Fixed key — base-db scoped.
_META_KEY = "upload_meta:waterfall"


def _get_meta(db: Session):
    return get_project_extra(db.info.get("store"), db.info.get("project"), _META_KEY)


def _set_meta(db: Session, filename: str, campaigns: int) -> dict:
    from datetime import date
    meta = {"file": filename, "rows": campaigns, "uploaded": date.today().isoformat()}
    set_project_extra(db.info.get("store"), db.info.get("project"), _META_KEY, meta)
    return meta


@router.get("/waterfall/run")
def run(db: Session = Depends(get_base_db)):
    return {**wf.run_state(db), "upload_meta": _get_meta(db)}


@router.delete("/waterfall/data")
def delete_all(db: Session = Depends(get_base_db)):
    """Wipe every waterfall run + items (settings + bid ledger untouched)."""
    out = wf.delete_all(db)
    set_project_extra(db.info.get("store"), db.info.get("project"), _META_KEY, None)
    return out


def _phase_items(db: Session, phase: str, ids: list[int] | None) -> tuple[int, list[dict]]:
    run = wf.latest_run(db)
    if not run:
        raise HTTPException(400, "No waterfall plan yet — upload a bulk first.")
    # straight from the db: run_state only ships a page of each phase, the export
    # must carry every row
    items = wf.phase_items(db, md.WaterfallItem, run.id, phase, ids)
    if not items:
        raise HTTPException(400, "Nothing selected for that phase.")
    return run.id, items


@router.post("/waterfall/bulk")
def bulk(phase: str = Query(..., pattern="^[ABCD]$"), req: dict = Body(default={}),
         db: Session = Depends(get_base_db)):
    state = wf.run_state(db)
    if phase == "D" and state.get("run") and not state.get("d_unlocked"):
        raise HTTPException(400, "Phase D (pauses) is locked until phases A, B and C are "
                                 "marked applied — the transitional overlap protects sales.")
    run_id, items = _phase_items(db, phase, (req or {}).get("ids"))
    data = wf.items_to_bulk(items)
    try:
        changelog_stage.log(db, wf.changelog_entries(items, phase), "waterfall")
    except Exception:
        db.rollback()
    led = wf.ledger_entries(items)
    if led:
        ledger_stage.record(db, led, "waterfall", run_id=run_id)
    return Response(content=data, media_type=XLSX,
        headers={"Content-Disposition":
                 f"attachment; filename=waterfall_phase_{phase}_bulk.xlsx"})


@router.post("/waterfall/applied")
def applied(phase: str = Query(..., pattern="^[ABCD]$"), db: Session = Depends(get_base_db)):
    state = wf.run_state(db)
    if not state.get("run"):
        raise HTTPException(400, "No waterfall plan yet — upload a bulk first.")
    try:
        return wf.mark_phase_applied(db, state["run"]["id"], phase)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/waterfall/select")
def select(req: dict = Body(...), db: Session = Depends(get_base_db)):
    """Persist item selection: {ids: [...], selected: bool}."""
    ids = req.get("ids") or []
    if not ids:
        raise HTTPException(400, "No item ids given.")
    n = db.query(md.WaterfallItem).filter(md.WaterfallItem.id.in_(ids)) \
          .update({md.WaterfallItem.selected: bool(req.get("selected", True))},
                  synchronize_session=False)
    db.commit()
    return {"updated": n}


@router.post("/waterfall/override")
def override(req: dict = Body(...), db: Session = Depends(get_base_db)):
    """Re-elect bosses from the ASIN×slot grid: {overrides: {"sku|slot": campaign_id}}
    rebuilds the plan from the saved bulk. An empty/omitted campaign_id clears that
    slot's override (back to auto-pick)."""
    if not wf.latest_run(db):
        raise HTTPException(400, "No waterfall plan yet — upload a bulk first.")
    forced = {k: v for k, v in (req.get("overrides") or {}).items() if v}
    try:
        return {**wf.rebuild_with_overrides(db, _settings(db), forced),
                "upload_meta": _get_meta(db)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/waterfall/benchmark")
def benchmark(db: Session = Depends(get_base_db)):
    return wf.benchmark_compare(db)


@router.get("/waterfall/benchmark/export")
def benchmark_export(db: Session = Depends(get_base_db)):
    return Response(content=wf.benchmark_xlsx(db), media_type=XLSX,
        headers={"Content-Disposition": "attachment; filename=waterfall_day0_benchmark.xlsx"})


@router.get("/waterfall/ledger")
def ledger_pending(db: Session = Depends(get_base_db)):
    return ledger_stage.pending(db)


@router.post("/waterfall/ledger/applied")
def ledger_applied(req: dict = Body(default={}), db: Session = Depends(get_base_db)):
    return {"applied": ledger_stage.mark_applied(db, source=(req or {}).get("source"),
                                                 ids=(req or {}).get("ids"))}


@router.post("/waterfall/ledger/discard")
def ledger_discard(req: dict = Body(default={}), db: Session = Depends(get_base_db)):
    return {"discarded": ledger_stage.discard(db, source=(req or {}).get("source"),
                                              ids=(req or {}).get("ids"))}
