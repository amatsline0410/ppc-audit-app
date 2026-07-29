"""FastAPI app: wire routers, CORS, init DB, optional seed on startup."""
from __future__ import annotations
import os
import logging
from datetime import date
from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .database import (init_db, get_session, ensure_store, ensure_project,
                       DEFAULT_STORE, DEFAULT_PROJECT)
from . import auth
from .routers import (upload, audit, consult, automate, harvest, stores, insights, sales, costs, bids,
                      templates, keywords, productads, adsstudio, monitoring, cadence, dailywatch, weekly,
                      midmonth, fullmonth, pausescale, waterfall, cannibal,
                      channels, tracker, catalog, auth as auth_router)

app = FastAPI(title="PPC Audit API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                   allow_methods=["*"], allow_headers=["*"])

_log = logging.getLogger("ppc")


# Any unhandled error -> a readable {detail} (the full trace is logged server-side),
# so the UI never shows a bare "Internal Server Error" / 500.
@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    _log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500,
        content={"detail": "Something went wrong while processing that request. "
                           "Please try again — if it keeps happening, check the file or data and retry."})

# auth endpoints are public (they self-gate); every data router requires a valid
# session token (Authorization: Bearer ...) via the current_user dependency.
app.include_router(auth_router.router)
_PROTECTED = [Depends(auth.current_user)]

app.include_router(stores.router, tags=["stores"], dependencies=_PROTECTED)
app.include_router(upload.router, tags=["pipeline"], dependencies=_PROTECTED)
app.include_router(audit.router, tags=["audit"], dependencies=_PROTECTED)
app.include_router(automate.router, tags=["automate"], dependencies=_PROTECTED)
app.include_router(harvest.router, tags=["harvest"], dependencies=_PROTECTED)
app.include_router(insights.router, tags=["insights"], dependencies=_PROTECTED)
app.include_router(sales.router, tags=["sales"], dependencies=_PROTECTED)
app.include_router(costs.router, tags=["costs"], dependencies=_PROTECTED)
app.include_router(bids.router, tags=["bids"], dependencies=_PROTECTED)
app.include_router(templates.router, tags=["templates"], dependencies=_PROTECTED)
app.include_router(keywords.router, tags=["keywords"], dependencies=_PROTECTED)
app.include_router(productads.router, tags=["productads"], dependencies=_PROTECTED)
app.include_router(adsstudio.router, tags=["adsstudio"], dependencies=_PROTECTED)
app.include_router(monitoring.router, tags=["monitoring"], dependencies=_PROTECTED)
app.include_router(cadence.router, tags=["cadence"], dependencies=_PROTECTED)
app.include_router(dailywatch.router, tags=["dailywatch"], dependencies=_PROTECTED)
app.include_router(weekly.router, tags=["weekly"], dependencies=_PROTECTED)
app.include_router(midmonth.router, tags=["midmonth"], dependencies=_PROTECTED)
app.include_router(fullmonth.router, tags=["fullmonth"], dependencies=_PROTECTED)
app.include_router(pausescale.router, tags=["pausescale"], dependencies=_PROTECTED)
app.include_router(waterfall.router, tags=["waterfall"], dependencies=_PROTECTED)
app.include_router(consult.router, tags=["consult"], dependencies=_PROTECTED)
app.include_router(cannibal.router, tags=["cannibal"], dependencies=_PROTECTED)
app.include_router(channels.router, tags=["channels"], dependencies=_PROTECTED)
app.include_router(tracker.router, tags=["tracker"], dependencies=_PROTECTED)
app.include_router(catalog.router, tags=["catalog"], dependencies=_PROTECTED)


@app.on_event("startup")
def startup():
    auth.init_auth()   # creates auth.db + seeds the superuser; user stores auto-create per user


@app.get("/health")
def health():
    return {"ok": True}


def seed(store: str = DEFAULT_STORE, project: str = DEFAULT_PROJECT):
    """Load the bundled ZValves file into the SUPERUSER's workspace on first run."""
    from .pipeline import ingest, clean, load
    from .database import scoped
    if not os.path.exists(settings.seed_file):
        print(f"seed file not found: {settings.seed_file}")
        return
    auth.init_auth()
    su = auth.authenticate(*auth._SUPERUSER)
    if not su:
        print("superuser not found; cannot seed"); return
    sid = scoped(su.id, store)        # seed belongs to SAdmin, isolated like any user
    ensure_store(sid, "ZValves")
    ensure_project(sid, project, "Seed Audit")
    init_db(sid, project)
    db = get_session(sid, project)
    try:
        df = ingest.ingest(settings.seed_file)
        frames = clean.clean(ingest.split(df))
        counts = load.load(db, frames, date(2026, 6, 6))
        print("seeded:", {k: v for k, v in counts.items() if isinstance(v, int)})
    finally:
        db.close()


if __name__ == "__main__":
    seed()
