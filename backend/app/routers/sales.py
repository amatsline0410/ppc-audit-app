"""Dashboard reporting summary (account KPIs + flag/ladder breakdown).

GET  /report               : KPI/flag/ladder summary
GET  /dashboard            : one-shot refresh (asins + flags + report + ASIN forest)
GET  /dashboard/analytics  : cross-feature analytics blocks (Product Ads, catalog,
                             transactions, monitoring, movers, changelog, keywords)
"""
from __future__ import annotations
from collections import Counter
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from .. import database as dbmod
from ..database import get_db, get_base_db
from ..config import default_thresholds
from ..pipeline import sales as sales_stage, audit as audit_stage, report as report_stage
from ..schemas import FlagOut, AsinSummary

router = APIRouter()


def _report_payload(db, th, flags):
    """Assemble the account-KPI/flag/ladder summary from an already-computed flag list."""
    by_flag = Counter(f.flag for f in flags)
    ladder = Counter(f.stage for f in flags if f.flag == "HIGH_ACOS" and f.stage)
    wasted = round(sum(f.observed or 0 for f in flags if f.flag == "WASTED_SPEND"), 2)
    acct = sales_stage.total_ad(db)
    snap = audit_stage.active_snapshot(db)
    # Avg Product ACoS (reporting spec): Σ ad spend ÷ Σ ad revenue across the
    # per-PRODUCT campaign rollups (build_tree, cached). Differs from account
    # ACoS when one campaign advertises several ASINs — the rollup counts that
    # campaign under each of its products.
    p_sp = p_sa = 0.0
    for node in audit_stage.build_tree(db).values():
        for c in node["campaigns"]:
            m = c["metrics"]
            p_sp += m["spend"]; p_sa += m["sales"]
    return {
        "target_acos": th.target_acos,
        "target_roas": round(1 / th.target_acos, 2) if th.target_acos else None,
        "ad_spend": acct["spend"], "ad_sales": acct["sales"],
        "acos": round(acct["spend"] / acct["sales"], 4) if acct["sales"] else None,
        "avg_product_acos": round(p_sp / p_sa, 4) if p_sa else None,
        "snapshot": snap.isoformat() if snap else None,
        "flags": {"total": len(flags), "by_type": dict(by_flag)},
        "ladder": {"reduce": ladder.get("REDUCE", 0), "monitor": ladder.get("MONITOR", 0),
                   "pause": ladder.get("PAUSE", 0)},
        "wasted_spend": wasted, "scale_winners": by_flag.get("SCALE_WINNER", 0),
    }


def _asin_rows(tree, flags):
    """Per-ASIN summary reusing an already-built tree + flag list (no rebuild)."""
    flag_by_asin = Counter(f.asin for f in flags if f.asin)
    rows = []
    for asin, node in tree.items():
        sp = sa = od = 0.0
        for c in node["campaigns"]:
            m = c["metrics"]; sp += m["spend"]; sa += m["sales"]; od += m["orders"]
        rows.append(AsinSummary(asin=asin, spend=round(sp, 2), sales=round(sa, 2),
                    orders=int(od), acos=round(sp / sa, 4) if sa else None,
                    flag_count=flag_by_asin.get(asin, 0)))
    return sorted(rows, key=lambda r: r.spend, reverse=True)


@router.get("/report")
def report(target_acos: float | None = Query(None, ge=0.01, le=2.0),
           store: str = Query(dbmod.DEFAULT_STORE), project: str = Query(dbmod.DEFAULT_PROJECT),
           db: Session = Depends(get_db)):
    th = default_thresholds.merged(target_acos=target_acos)
    return _report_payload(db, th, audit_stage.audit(db, th))


@router.get("/report/summary")
def report_summary(target_acos: float | None = Query(None, ge=0.01, le=2.0),
                   store: str = Query(dbmod.DEFAULT_STORE), project: str = Query(dbmod.DEFAULT_PROJECT),
                   db: Session = Depends(get_db)):
    th = default_thresholds.merged(target_acos=target_acos)
    return report_stage.summary(db, th)


@router.get("/report/export")
def report_export(target_acos: float | None = Query(None, ge=0.01, le=2.0),
                  store: str = Query(dbmod.DEFAULT_STORE), project: str = Query(dbmod.DEFAULT_PROJECT),
                  db: Session = Depends(get_db)):
    th = default_thresholds.merged(target_acos=target_acos)
    data = report_stage.export_xlsx(db, th)
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ppc_report.xlsx"})


@router.get("/dashboard/analytics")
def dashboard_analytics(target_acos: float | None = Query(None, ge=0.01, le=2.0),
                        audit_type: str | None = Query(None, description="cadence preset key"),
                        store: str = Query(dbmod.DEFAULT_STORE), project: str = Query(dbmod.DEFAULT_PROJECT),
                        db: Session = Depends(get_db), bdb: Session = Depends(get_base_db)):
    """Cross-feature analytics for the Main Dashboard — one call rolling up every
    report/data source: Product Ads, Product Benchmark catalog (+break-even join),
    the store transaction ledger, the Monitoring daily tracker (base db), snapshot
    top movers, Change Log and mined keywords. Each block is None when its data
    source has no upload yet, so the UI can hint instead of erroring."""
    from ..pipeline import cadence as cadence_stage, dashboard as dash
    th = cadence_stage.thresholds_for(audit_type, target_acos)
    return dash.analytics(db, bdb, th)


@router.get("/dashboard/export")
def dashboard_export(target_acos: float | None = Query(None, ge=0.01, le=2.0),
                     audit_type: str | None = Query(None, description="cadence preset key"),
                     store: str = Query(dbmod.DEFAULT_STORE), project: str = Query(dbmod.DEFAULT_PROJECT),
                     db: Session = Depends(get_db), bdb: Session = Depends(get_base_db)):
    """Client-ready Dashboard workbook (charts) mirroring the analytics hub."""
    from ..pipeline import cadence as cadence_stage, dashboard as dash
    th = cadence_stage.thresholds_for(audit_type, target_acos)
    data = dash.export_xlsx(db, bdb, th)
    return Response(content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=dashboard_report.xlsx"})


@router.get("/dashboard")
def dashboard(target_acos: float | None = Query(None, ge=0.01, le=2.0),
              audit_type: str | None = Query(None, description="cadence preset key"),
              flag: str | None = None, severity: str | None = None,
              store: str = Query(dbmod.DEFAULT_STORE), project: str = Query(dbmod.DEFAULT_PROJECT),
              db: Session = Depends(get_db)):
    """One call powering a full refresh: asins + flags + report + first-ASIN tree.
    Builds the tree + flags ONCE. The cadence preset (audit_type) re-tunes thresholds."""
    from ..pipeline import cadence as cadence_stage
    th = cadence_stage.thresholds_for(audit_type, target_acos)
    tree = audit_stage.build_tree(db)              # cached
    flags = audit_stage.audit(db, th)
    asins = _asin_rows(tree, flags)
    out_flags = [f for f in flags
                 if (not flag or f.flag == flag) and (not severity or f.severity == severity)]
    # full ASIN-rooted forest, ordered by spend (highest first) so the UI can list
    # every ASIN -> its campaigns -> ad groups -> ads, not just the top ASIN.
    trees = [tree[a.asin] for a in asins if a.asin in tree]
    return {
        "asins": [a.model_dump() for a in asins],
        "flags": [FlagOut(**f.__dict__).model_dump() for f in out_flags],
        "report": _report_payload(db, th, flags),
        "trees": trees,
        "tree": trees[0] if trees else None,   # back-compat: top ASIN
    }
