"""Keyword mining: upload SQP / Cerebro separately, consolidate (deduped),
recommend generic keywords.

POST /keywords/upload?source=sqp|cerebro   : merge a research file into the pool
GET  /keywords                              : consolidated deduped list + stats
GET  /keywords/recommend                    : generic keyword recommendations
DELETE /keywords                            : clear the pool
"""
from __future__ import annotations
import tempfile
from datetime import date
from fastapi import APIRouter, Body, Depends, UploadFile, File, Query, HTTPException, Response
from sqlalchemy.orm import Session
from .. import database as dbmod
from .. import models as md
from ..database import get_db
from ..pipeline import keywords as kw_stage
from ..pipeline import ledger as ledger_stage
from ..pipeline import tracker as tracker_stage

router = APIRouter()

# Rolling list of the last few uploaded research files (SQP + Cerebro accumulate
# into one pool), shown in the panel header like the app-wide upload pattern.
# Keyed per cadence — MinedKeyword lives in the per-cadence db.
_META_FILES = 6


def _meta_key(db: Session) -> str:
    return f"upload_meta:keywords:{db.info.get('cadence')}"


def _get_meta(db: Session) -> dict | None:
    return dbmod.get_project_extra(db.info.get("store"), db.info.get("project"), _meta_key(db))


def _record_upload(db: Session, filename: str, source: str, stats: dict) -> dict:
    meta = _get_meta(db) or {}
    files = [f for f in meta.get("files", []) if f.get("name") != filename]
    files.append({"name": filename, "source": source, "rows": stats.get("rows", 0),
                  "uploaded": date.today().isoformat()})
    meta = {"files": files[-_META_FILES:], "updated": date.today().isoformat()}
    dbmod.set_project_extra(db.info.get("store"), db.info.get("project"), _meta_key(db), meta)
    return meta


@router.post("/keywords/upload")
async def upload_keywords(
    file: UploadFile = File(...),
    source: str = Query(..., description="sqp | cerebro"),
    db: Session = Depends(get_db),
):
    if source not in ("sqp", "cerebro"):
        raise HTTPException(400, "source must be 'sqp' or 'cerebro'")
    if not file.filename.lower().endswith((".xlsx", ".xlsm", ".csv")):
        raise HTTPException(400, "upload a .xlsx/.csv research file")
    suffix = ".csv" if file.filename.lower().endswith(".csv") else ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        path = tmp.name
    try:
        rows = kw_stage.parse_sqp(path) if source == "sqp" else kw_stage.parse_cerebro(path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    stats = kw_stage.load_keywords(db, rows, source)
    return {**stats, "consolidated": kw_stage.consolidated(db)["count"],
            "upload_meta": _record_upload(db, file.filename or "research", source, stats)}


@router.get("/keywords")
def get_keywords(project_id: int | None = Query(None), db: Session = Depends(get_db)):
    """Consolidated pool. With ?project_id=, every row gets `indexed`:
    'ranked' (Cerebro organic rank for the ASIN — definitely indexed),
    'listing' (all the keyword's words appear in the project's CURRENT listing
    copy — indexed by visible copy), or None."""
    out = {**kw_stage.consolidated(db), "upload_meta": _get_meta(db)}
    if project_id:
        copy_words: set[str] = set()
        base = ledger_stage.base_session(db)
        try:
            for r in base.query(md.ListingCopy).filter(
                    md.ListingCopy.project_id == project_id,
                    md.ListingCopy.variant == "current",
                    md.ListingCopy.asin.is_(None)):
                copy_words |= set((r.text or "").lower().split())
        finally:
            base.close()
        for row in out.get("rows", []):
            if row.get("organic_rank"):
                row["indexed"] = "ranked"
            else:
                words = str(row.get("keyword") or "").lower().split()
                row["indexed"] = "listing" if (words and copy_words
                                               and all(w in copy_words for w in words)) else None
        out["has_listing_copy"] = bool(copy_words)
    return out


@router.get("/keywords/recommend")
def recommend(db: Session = Depends(get_db)):
    return kw_stage.recommend(db)


@router.delete("/keywords")
def clear_keywords(db: Session = Depends(get_db)):
    n = kw_stage.clear(db)
    dbmod.set_project_extra(db.info.get("store"), db.info.get("project"), _meta_key(db), None)
    return {"deleted": n}


def _selected_rows(db: Session, req: dict) -> list:
    """Mined pool, optionally narrowed to the request's selected keywords
    (body `keywords`: list of phrases, matched by normalized text)."""
    rows = db.query(md.MinedKeyword).all()
    only = req.get("keywords")
    if only is not None:   # [] = explicit empty selection -> no rows (forecast = current)
        keys = {str(k).strip().lower() for k in only if str(k).strip()}
        rows = [r for r in rows
                if (r.display or r.keyword or "").strip().lower() in keys
                or (r.keyword or "").strip().lower() in keys]
    return rows


@router.post("/keywords/to-project")
def to_project(req: dict = Body(...), db: Session = Depends(get_db)):
    """Push mined keywords (Brand Analytics SQP + Cerebro) into a Listing
    Optimizer project's tracked-keyword list — ALL of them, or only the body's
    `keywords` selection. Mined keywords live in this audit's db; tracker
    projects live in the BASE db (base_session)."""
    project_id = int(req.get("project_id") or 0)
    rows = _selected_rows(db, req)
    if not rows:
        raise HTTPException(400, "No mined keywords matched — upload SQP or Cerebro above first "
                                 "(or adjust the selection).")
    payload = [{"keyword": r.display or r.keyword, "search_volume": r.search_volume or None,
                "source": "cerebro" if r.src_cerebro else "sqp"} for r in rows]
    base = ledger_stage.base_session(db)
    try:
        before = tracker_stage.primary_seo(base, project_id)
        out = tracker_stage.add_keywords(base, project_id, payload, source="mined")
        out["seo_before"], out["seo_after"] = before, tracker_stage.primary_seo(base, project_id)
        return out
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        base.close()


@router.get("/keywords/project-preview")
def project_preview_all(project_id: int = Query(...), db: Session = Depends(get_db)):
    return _project_preview(db, project_id, db.query(md.MinedKeyword).all())


@router.post("/keywords/project-preview")
def project_preview_selected(req: dict = Body(...), db: Session = Depends(get_db)):
    """Same what-if scorecard, computed over the body's `keywords` selection only.
    With an EMPTY selection the forecast equals current, but the insight blocks
    (mined-pool scorecard, impression share) still cover the whole pool."""
    return _project_preview(db, int(req.get("project_id") or 0), _selected_rows(db, req),
                            insight_rows=db.query(md.MinedKeyword).all())


def _project_preview(db: Session, project_id: int, rows: list, insight_rows: list | None = None):
    """What-if SEO scorecard: CURRENT primary-ASIN card vs the PROJECTED card if
    the given mined rows were pushed into the project. New keywords count into
    the tracked denominator; the ones carrying a Cerebro organic rank also
    project into ranked / page-1 / top-10 / avg rank (that rank lands with the
    next snapshot import)."""
    base = ledger_stage.base_session(db)
    try:
        proj = base.get(md.TrackerProject, project_id)
        if not proj:
            raise HTTPException(400, "Unknown tracker project.")
        current = tracker_stage.primary_seo(base, project_id)
        tracked = {(k.keyword or "").strip().lower()
                   for k in base.query(md.TrackedKeyword)
                   .filter(md.TrackedKeyword.project_id == project_id)}
        # OUR-listing copy, both variants: current drives coverage/indexed flags,
        # proposed drives the listing-indexed forecast
        copy_rows = base.query(md.ListingCopy).filter(
            md.ListingCopy.project_id == project_id,
            md.ListingCopy.variant == "current",
            md.ListingCopy.asin.is_(None)).all()
        proposed_rows = base.query(md.ListingCopy).filter(
            md.ListingCopy.project_id == project_id,
            md.ListingCopy.variant == "proposed",
            md.ListingCopy.asin.is_(None)).all()
    finally:
        base.close()
    if current is None:   # no snapshot/competitor yet — still show the pool math
        current = {"asin": proj.primary_asin, "indexed": None, "page1": 0, "top10": 0,
                   "avg_rank": None, "tracked": len(tracked), "ranked": 0}

    new = [r for r in rows if (r.display or r.keyword or "").strip().lower() not in tracked]
    ranked_new = [r for r in new if r.cerebro_organic_rank]
    page1_new = sum(1 for r in ranked_new if r.cerebro_organic_rank <= 48)
    top10_new = sum(1 for r in ranked_new if r.cerebro_organic_rank <= 10)

    t2 = current["tracked"] + len(new)
    r2 = current["ranked"] + len(ranked_new)
    cnt = current["ranked"] + len(ranked_new)
    tot = (current["avg_rank"] or 0) * current["ranked"] \
        + sum(r.cerebro_organic_rank for r in ranked_new)
    projected = {
        "asin": current["asin"], "tracked": t2, "ranked": r2,
        "indexed": round(r2 / t2, 4) if t2 else None,
        "page1": current["page1"] + page1_new,
        "top10": current["top10"] + top10_new,
        "avg_rank": round(tot / cnt, 1) if cnt else None,
    }
    # ---- mined-pool scorecard: is the BA/Cerebro research ALREADY indexed for
    # this ASIN (Cerebro organic rank = ranked) and already covered by the
    # CURRENT listing copy (all of the keyword's words appear in the copy)?
    def _card(sub):
        ranked = [r for r in sub if r.cerebro_organic_rank]
        return {"total": len(sub), "ranked": len(ranked),
                "indexed": round(len(ranked) / len(sub), 4) if sub else None,
                "page1": sum(1 for r in ranked if r.cerebro_organic_rank <= 48),
                "top10": sum(1 for r in ranked if r.cerebro_organic_rank <= 10),
                "avg_rank": (round(sum(r.cerebro_organic_rank for r in ranked) / len(ranked), 1)
                             if ranked else None)}
    copy_text = " ".join((r.text or "") for r in copy_rows).lower()
    copy_words = set(copy_text.split())

    def _covered(r) -> bool:
        words = (r.display or r.keyword or "").lower().split()
        return bool(words and copy_words and all(w in copy_words for w in words))

    # insight blocks fall back to the whole pool when the selection is empty —
    # the forecast above stays selection-scoped (empty = current), but "already
    # indexed for this ASIN" and Impression Share keep showing pool-wide insight
    insight = rows if rows else (insight_rows if insight_rows is not None else rows)
    covered = sum(1 for r in insight if _covered(r))
    not_indexed = sum(1 for r in insight if not r.cerebro_organic_rank and not _covered(r))
    pool_scorecard = {
        **_card(insight),
        "not_indexed": not_indexed,
        "scope": "selection" if rows else "pool",
        "by_source": {"sqp": _card([r for r in insight if r.src_sqp]),
                      "cerebro": _card([r for r in insight if r.src_cerebro])},
        "listing": {"covered": covered,
                    "coverage": round(covered / len(insight), 4) if insight else None,
                    "has_copy": bool(copy_text.strip())},
    }

    # ---- Impression Share: keywords present in BOTH the mined research and the
    # Search Term Report harvest. Formula: STR impressions ÷ total search volume
    # × 100 — how much of the keyword's search demand your ads actually saw.
    overlap = [r for r in insight if r.src_str and (r.search_volume or 0) > 0]
    imp = sum(r.str_impressions or 0 for r in overlap)
    vol = sum(r.search_volume or 0 for r in overlap)
    impression_share = {"keywords": len(overlap),
                        "impressions": imp, "search_volume": vol,
                        "share": round(imp / vol * 100, 2) if vol else None,
                        "scope": "selection" if rows else "pool",
                        "str_only": sum(1 for r in insight if r.src_str and not (r.search_volume or 0))}

    # ---- listing-indexed forecast over the FORECAST set (the selection): how
    # many of these keywords the CURRENT copy already covers vs how many the
    # PROPOSED copy would cover. No proposed copy pasted -> 0 (nothing planned).
    prop_text = " ".join((r.text or "") for r in proposed_rows).lower()
    prop_words = set(prop_text.split())

    def _covered_by(words_set, r) -> bool:
        words = (r.display or r.keyword or "").lower().split()
        return bool(words and words_set and all(w in words_set for w in words))

    cur_cov = sum(1 for r in rows if _covered_by(copy_words, r))
    pro_cov = sum(1 for r in rows if _covered_by(prop_words, r)) if prop_words else 0
    listing_forecast = {"current_covered": cur_cov, "proposed_covered": pro_cov,
                        "gain": pro_cov - cur_cov if prop_words else 0,
                        "has_proposed": bool(prop_words), "keywords": len(rows)}

    # ---- listing demand comparison: the demand the CURRENT listing already
    # covers (pool keywords whose words all appear in the current copy) vs the
    # forecast = current + the SELECTED keywords it doesn't cover yet. Every
    # metric adds the same way: current total + selection's contribution.
    def _sums(rs) -> dict:
        return {"search_volume": sum(r.search_volume or 0 for r in rs),
                "sqp_impressions": sum(r.sqp_impressions or 0 for r in rs),
                "sqp_purchases": sum(r.sqp_purchases or 0 for r in rs),
                "str_impressions": sum(r.str_impressions or 0 for r in rs),
                "str_orders": sum(r.str_orders or 0 for r in rs)}
    all_rows = insight_rows if insight_rows is not None else rows
    cur_rows = [r for r in all_rows if _covered(r)]
    add_rows = [r for r in rows if not _covered(r)]
    cur_sums, add_sums = _sums(cur_rows), _sums(add_rows)
    listing_demand = {
        "current": cur_sums, "added": add_sums,
        "projected": {k: cur_sums[k] + add_sums[k] for k in cur_sums},
        "current_keywords": len(cur_rows), "added_keywords": len(add_rows),
        "has_copy": bool(copy_words),
    }

    return {"current": current, "projected": projected,
            "listing_forecast": listing_forecast, "listing_demand": listing_demand,
            "pool_scorecard": pool_scorecard, "impression_share": impression_share,
            "pool": {"total": len(rows), "new": len(new),
                     "already_tracked": len(rows) - len(new),
                     "with_cerebro_rank": len(ranked_new),
                     "page1_candidates": page1_new}}


@router.post("/keywords/export")
def export_report(req: dict = Body(...)):
    """Everything on the Keywords tab -> one .xlsx: Summary (project, forecast
    current vs projected, pool scorecard, impression share), Mined Keywords,
    Recommendations, Harvest and N-Grams. The frontend sends exactly what it
    shows (harvest/n-gram results are ephemeral panel state)."""
    import io
    import pandas as pd

    def kv_rows(title: str, obj) -> list[dict]:
        out = [{"section": title, "metric": "", "value": ""}]
        for k, v in (obj or {}).items():
            if isinstance(v, (dict, list)):
                continue
            out.append({"section": "", "metric": k, "value": v})
        return out

    summary_rows: list[dict] = []
    proj = req.get("project") or {}
    if proj:
        summary_rows += kv_rows("Keyword Project", proj)
    fc = req.get("forecast") or {}
    if fc.get("current") or fc.get("projected"):
        summary_rows.append({"section": "Forecast SEO Scorecard", "metric": "", "value": ""})
        cur, pro = fc.get("current") or {}, fc.get("projected") or {}
        for k in ("indexed", "page1", "top10", "avg_rank", "tracked", "ranked"):
            summary_rows.append({"section": "", "metric": k,
                                 "value": f"{cur.get(k)} -> {pro.get(k)}"})
    for title, key in (("Mined Pool Scorecard", "pool_scorecard"),
                       ("Impression Share", "impression_share"),
                       ("N-Gram Summary", "ngram_summary")):
        if req.get(key):
            summary_rows += kv_rows(title, req[key])

    sheets: list[tuple[str, pd.DataFrame]] = []
    if summary_rows:
        sheets.append(("Summary", pd.DataFrame(summary_rows)))
    for name, key in (("Mined Keywords", "mined"), ("Recommendations", "recommend"),
                      ("Harvest", "harvest"), ("N-Grams", "ngrams")):
        rows = req.get(key) or []
        if rows:
            df = pd.DataFrame(rows)
            # lists (e.g. sources) -> readable strings
            for c in df.columns:
                if df[c].map(lambda v: isinstance(v, (list, dict))).any():
                    df[c] = df[c].map(lambda v: ", ".join(map(str, v)) if isinstance(v, list) else str(v))
            sheets.append((name, df))
    if not sheets:
        raise HTTPException(400, "Nothing to export yet — upload research files first.")

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets:
            df.to_excel(xw, sheet_name=name[:31], index=False)
    return Response(content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ppc_keywords_report.xlsx"})


@router.get("/keywords/backend-terms")
def backend_terms(project_id: int = Query(...),
                  limit_bytes: int = Query(243, ge=50, le=249),
                  basis: str = Query("volume", description="volume | harvest"),
                  db: Session = Depends(get_db)):
    """Backend Search Terms recommendation for the listing. Two bases:
    - volume: highest-search-volume pool keywords first (research demand)
    - harvest: Search-Term-Report keywords first, ordered by PPC proof
      (orders, then impressions) — customers already bought through these terms.
    Either way: only words NOT already in the CURRENT visible copy (those are
    indexed — repeating them wastes the byte budget), deduped, byte-capped."""
    import re as _re
    if basis not in ("volume", "harvest"):
        raise HTTPException(400, "basis must be 'volume' or 'harvest'")
    if basis == "harvest":
        rows = (db.query(md.MinedKeyword)
                .filter(md.MinedKeyword.src_str == True)  # noqa: E712
                .order_by(md.MinedKeyword.str_orders.desc().nullslast(),
                          md.MinedKeyword.str_impressions.desc().nullslast()).all())
        if not rows:
            raise HTTPException(400, "No harvest keywords yet — upload a bulk in the "
                                     "Search-Term Harvest below first (its STR terms feed this).")
    else:
        rows = db.query(md.MinedKeyword).order_by(
            md.MinedKeyword.search_volume.desc().nullslast()).all()
        if not rows:
            raise HTTPException(400, "No mined keywords yet — upload SQP or Cerebro above first.")
    copy_words: set[str] = set()
    base = ledger_stage.base_session(db)
    try:
        proj = base.get(md.TrackerProject, project_id)
        if not proj:
            raise HTTPException(400, "Unknown tracker project.")
        for r in base.query(md.ListingCopy).filter(
                md.ListingCopy.project_id == project_id,
                md.ListingCopy.variant == "current",
                md.ListingCopy.asin.is_(None)):
            copy_words |= set(_re.sub(r"[^a-z0-9 ]", " ", (r.text or "").lower()).split())
    finally:
        base.close()

    picked: list[str] = []
    used = set(copy_words)
    from_keywords = 0
    for r in rows:
        kw = (r.display or r.keyword or "").lower()
        if kw_stage._ASIN_RE.match(kw.replace(" ", "")):
            continue
        words = [w for w in _re.sub(r"[^a-z0-9 ]", " ", kw).split()
                 if len(w) > 1 and w not in used]
        if not words:
            continue
        candidate = picked + words
        if len(" ".join(candidate).encode("utf-8")) > limit_bytes:
            continue
        picked = candidate
        used |= set(words)
        from_keywords += 1

    line = " ".join(picked)
    return {"line": line, "bytes": len(line.encode("utf-8")), "limit": limit_bytes,
            "words": len(picked), "from_keywords": from_keywords, "basis": basis,
            "has_copy": bool(copy_words),
            "note": (None if copy_words else
                     "No current listing copy pasted in the project — words may duplicate your visible copy.")}
