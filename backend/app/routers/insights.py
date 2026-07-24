"""Insight endpoints: POST /ngrams (STR word analysis), GET /trends (period diff)."""
from __future__ import annotations
import tempfile
from fastapi import APIRouter, Body, Depends, UploadFile, File, Query, HTTPException, Response
from sqlalchemy.orm import Session
from ..database import get_db
from ..config import default_thresholds
from ..pipeline import (harvest as harvest_stage, ngrams as ngram_stage, trends as trend_stage,
                        strategy as strategy_stage, changelog as changelog_stage,
                        cadence as cadence_stage, cadstrat as cadstrat_stage,
                        tiers as tier_stage)

router = APIRouter()


# `audit_type` scopes the db file per cadence (via get_db) AND retunes the flag
# thresholds to that cadence's preset. Weekly / Mid-Month / Full-Month / Pause-Scale
# each drive their OWN strategies from their own side-table data (cadstrat); every
# other type falls back to the generic account advisor over FactPerformance.
@router.get("/strategy")
def strategy(target_acos: float | None = Query(None, ge=0.01, le=2.0),
             audit_type: str | None = Query(None),
             db: Session = Depends(get_db)):
    th = cadence_stage.thresholds_for(audit_type, target_acos)
    if audit_type in cadstrat_stage.CADENCE_TYPES:
        return cadstrat_stage.analyze(db, audit_type, th)
    return strategy_stage.analyze(db, th)


# Tier Router: campaign-architecture tier suggested from the store catalog's
# advertisable-unit count (parents + standalone; falls back to distinct DimAd
# ASINs when no catalog is uploaded). Store-level, cadence-agnostic.
@router.get("/strategy/tier")
def strategy_tier(db: Session = Depends(get_db)):
    return tier_stage.suggest(db)


@router.post("/strategy/bulk")
def strategy_bulk(name: str = Query(..., description="strategy name from the playbook"),
                  target_acos: float | None = Query(None, ge=0.01, le=2.0),
                  audit_type: str | None = Query(None),
                  db: Session = Depends(get_db)):
    """One-click: generate the Amazon bulk file for a strategy + log the actions."""
    th = cadence_stage.thresholds_for(audit_type, target_acos)
    try:
        if audit_type in cadstrat_stage.CADENCE_TYPES:
            data, entries, n = cadstrat_stage.build_bulk(db, audit_type, th, name)
        else:
            data, entries, n = strategy_stage.build_bulk(db, th, name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if n == 0:
        raise HTTPException(404, f"no rows qualify for '{name}' right now")
    changelog_stage.log(db, entries, "strategy")
    fname = "ppc_" + "".join(ch if ch.isalnum() else "_" for ch in name.lower()) + ".xlsx"
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"})


@router.post("/ngrams")
async def ngrams(
    file: UploadFile = File(...),
    target_acos: float | None = Query(None, ge=0.01, le=2.0),
    min_clicks: int = Query(2, ge=1),
    n_max: int = Query(3, ge=1, le=3),
    project_id: int | None = Query(None, description="keyword project — scope to its ASINs"),
    db: Session = Depends(get_db),   # keeps the ?store=&project= scope consistent
):
    if not file.filename.lower().endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(400, "upload a Search Term Report .xlsx/.csv")
    suffix = ".csv" if file.filename.lower().endswith(".csv") else ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        path = tmp.name
    try:
        # tolerant: picks the STR sheet whether this is the SP BULK export
        # (embedded 'SP Search Term Report' sheet) or a standalone STR file
        df = harvest_stage.parse_str(path)
    except ValueError as e:
        raise HTTPException(400, f"{e} — upload the Sponsored Products bulk export that "
                                 "includes the 'SP Search Term Report' sheet, or a "
                                 "standalone Search Term Report.")

    # scope to the keyword project's ASIN(s): keep only rows whose ad group
    # advertises one of them (needs the BULK file — its Product Ad rows carry
    # the mapping; a standalone STR can't be scoped)
    scope = None
    if project_id:
        from .harvest import _ag_asin_map, _project_asins
        asins = _project_asins(db, project_id)
        if asins:
            try:
                from ..pipeline import weekly as wk
                id_rows = wk.parse_str_sheet(path)
                ag_map = _ag_asin_map(path)
                keep_ags = {ag for ag, a in ag_map.items() if a & asins}
                keep_pairs = {(str(r["campaign_name"] or "").strip().lower(),
                               str(r["ad_group_name"] or "").strip().lower())
                              for r in id_rows if str(r["ad_group_id"]) in keep_ags}
                before = len(df)
                mask = df.apply(lambda r: (str(r["campaign_name"]).strip().lower(),
                                           str(r["ad_group_name"]).strip().lower()) in keep_pairs, axis=1)
                df = df[mask]
                scope = {"asins": sorted(asins), "hidden_rows": int(before - len(df))}
            except ValueError:
                scope = {"asins": sorted(asins), "hidden_rows": 0,
                         "note": "Standalone STR has no Product Ad rows — can't map ad groups "
                                 "to ASINs; showing all rows."}
        else:
            scope = {"asins": [], "hidden_rows": 0,
                     "note": "Keyword project has no primary ASIN — showing all rows."}

    # keywords only: ASIN-shaped customer search terms are product hits, not
    # words — they'd pollute the gram stats with "b0xxxxxxxx" tokens
    before_asin = len(df)
    df = df[~df["search_term"].apply(harvest_stage.is_asin)]
    asin_terms_hidden = int(before_asin - len(df))

    th = default_thresholds.merged(target_acos=target_acos)
    # per-row break-even via the loaded account (campaign + ad-group NAME ->
    # ad group -> product ad -> catalog listing w/ real ledger fees); mine()
    # rolls it up spend-weighted per gram
    try:
        idx = harvest_stage._account_index(db)
        ag_be = harvest_stage.ag_break_even_map(db)
        if idx.name_map and ag_be:
            def _row_be(r):
                ids = idx.name_map.get((str(r["campaign_name"]).strip().lower(),
                                        str(r["ad_group_name"]).strip().lower()))
                return ag_be.get(str(ids[1])) if ids else None
            df["_be"] = df.apply(_row_be, axis=1)
    except Exception:
        pass                                # BE is decoration — never block mining
    grams = ngram_stage.mine(df, th, n_max=n_max, min_clicks=min_clicks)
    spend = float(df["spend"].sum()); sales = float(df["sales"].sum())
    summary = {"terms": int(len(df)), "impressions": int(df["impressions"].sum()),
               "clicks": int(df["clicks"].sum()), "spend": round(spend, 2),
               "sales": round(sales, 2), "orders": int(df["orders"].sum()),
               "acos": round(spend / sales, 4) if sales else None,
               "winners": sum(1 for g in grams if g.verdict == "winner"),
               "wasters": sum(1 for g in grams if g.verdict == "waster")}
    return {"target_acos": th.target_acos, "count": len(grams),
            "scope": scope, "summary": summary, "asin_terms_hidden": asin_terms_hidden,
            "grams": [g.dict() for g in grams]}


@router.post("/ngrams/export")
def ngrams_export(req: dict = Body(...)):
    """Selected (or all) grams + the run summary -> downloadable .xlsx report."""
    import io
    import pandas as pd
    grams = req.get("grams") or []
    if not grams:
        raise HTTPException(400, "Nothing to export — run the miner first.")
    cols = ["gram", "n", "verdict", "terms", "impressions", "clicks", "orders",
            "spend", "sales", "acos", "cvr", "roas", "break_even"]
    gdf = pd.DataFrame(grams)
    gdf = gdf[[c for c in cols if c in gdf.columns]]
    sdf = pd.DataFrame([req.get("summary") or {}])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        sdf.to_excel(xw, sheet_name="Summary", index=False)
        gdf.to_excel(xw, sheet_name="N-Grams", index=False)
    return Response(content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ppc_ngram_report.xlsx"})


@router.get("/trends")
def trends(db: Session = Depends(get_db)):
    return trend_stage.compare(db)
