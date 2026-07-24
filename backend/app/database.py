"""DB engines + sessions. Three-level isolation:

    store (Amazon account)  ->  project (one named audit)  ->  cadence  ->  process

On disk:  data/stores/<store_id>/<project_id>[__<cadence>].db — one SQLite file
per (project, cadence), fully isolated. The PPC bulk + everything derived from it
(flags, bid/placement optimizer, harvest, n-gram, negatives, pause/kill/scale)
splits per **Audit Cadence** so uploading a bulk under "Weekly" only audits there
— no overlap with the other cadences. `full_month` (and no cadence) map to the
BASE `<project_id>.db` file (back-compat: existing data = the Full-Month set).

Shared across all cadences of a project: the Goal ACoS + econ (in _meta.json),
the Product Benchmark (_benchmark.json), and the Product Costs (_costs.json) —
store/project-level so they don't have to be re-entered per cadence. Monitoring
(the daily-report tracker) uses the BASE db via `get_base_db`.

store_id / project_id / audit_type flow in from the API as ?store=&project=&audit_type=;
engines are created + cached lazily.
"""
from __future__ import annotations
import os
import re
import json
import shutil
import threading
from datetime import date
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from fastapi import Query, Depends
from .auth import current_user as _current_user

Base = declarative_base()

DEFAULT_STORE = "zvalves"
DEFAULT_PROJECT = "default"
STORES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "stores"))

# the Audit Cadence keys that get their own isolated db file. `full_month` (and
# None/unknown) map to the base <project>.db so existing data stays the Full-Month
# set. Hardcoded here (not imported from pipeline.cadence) to avoid an import cycle.
CADENCE_KEYS = {"daily", "weekly", "mid_month", "pause_scale"}

_engines: dict[tuple[str, str], tuple] = {}   # (store_id, data_project_id) -> (engine, SessionLocal)


def _data_pid(pid: str, cadence: str | None) -> str:
    """Project id used for the on-disk db file. A real (non-full-month) cadence
    gets a `<pid>__<cadence>` file of its own; everything else uses the base file."""
    c = slug(cadence or "", "")
    return f"{pid}__{c}" if c in CADENCE_KEYS else pid


def slug(s: str, fallback: str) -> str:
    """Sanitize an id to a safe filename slug (blocks path traversal)."""
    out = re.sub(r"[^a-z0-9_-]", "", (s or "").strip().lower().replace(" ", "-"))
    return out or fallback


# ---- per-user isolation -----------------------------------------------------
# Each user owns their stores: the on-disk store dir is namespaced by the owner's
# numeric user id (`u<id>__<store>`). The public store id the API/UI uses is the
# un-prefixed slug; translation happens at the request boundary (get_db + the
# stores router). Two users can both have a "zvalves" store without ever sharing.
def _prefix(owner_id) -> str:
    return f"u{owner_id}__"


def scoped(owner_id, store: str) -> str:
    """Public store id -> the owner's internal (namespaced) store id."""
    return _prefix(owner_id) + slug(store, DEFAULT_STORE)


def unscope(owner_id, sid: str) -> str:
    pre = _prefix(owner_id)
    return sid[len(pre):] if sid.startswith(pre) else sid


def _store_dir(store_id: str) -> str:
    d = os.path.join(STORES_DIR, store_id)
    os.makedirs(d, exist_ok=True)
    return d


def _meta_path(store_id: str) -> str:
    return os.path.join(_store_dir(store_id), "_meta.json")


def _db_path(store_id: str, project_id: str) -> str:
    return os.path.join(_store_dir(store_id), f"{project_id}.db")


def _read_meta(store_id: str) -> dict:
    p = _meta_path(store_id)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _write_meta(store_id: str, meta: dict) -> None:
    with open(_meta_path(store_id), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


def _uniquify(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    i = 2
    while f"{base}-{i}" in taken:
        i += 1
    return f"{base}-{i}"


def ensure_store(store_id: str, title: str | None = None) -> dict:
    meta = _read_meta(store_id)
    if not meta:
        meta = {"title": title or store_id, "created": date.today().isoformat(), "projects": {}}
        _write_meta(store_id, meta)
    elif title and meta.get("title") != title:
        meta["title"] = title
        _write_meta(store_id, meta)
    return meta


def ensure_project(store_id: str, project_id: str, title: str | None = None) -> dict:
    meta = ensure_store(store_id)
    projects = meta.setdefault("projects", {})
    if project_id not in projects:
        projects[project_id] = {"title": title or project_id, "created": date.today().isoformat()}
        _write_meta(store_id, meta)
    elif title and projects[project_id].get("title") != title:
        projects[project_id]["title"] = title
        _write_meta(store_id, meta)
    return projects[project_id]


def get_project_meta(store: str, project: str) -> dict:
    """Project info dict ({title, created, acos_threshold?}) or {} if unknown."""
    sid, pid = slug(store, DEFAULT_STORE), slug(project, DEFAULT_PROJECT)
    return _read_meta(sid).get("projects", {}).get(pid, {})


def set_project_acos(store: str, project: str, acos: float) -> dict:
    """Persist a per-audit Goal ACoS on the project. Returns the project info."""
    sid, pid = slug(store, DEFAULT_STORE), slug(project, DEFAULT_PROJECT)
    meta = ensure_store(sid)
    proj = meta.setdefault("projects", {}).setdefault(
        pid, {"title": pid, "created": date.today().isoformat()})
    proj["acos_threshold"] = acos
    _write_meta(sid, meta)
    return {"id": pid, **proj}


def get_project_econ(store: str, project: str) -> dict:
    """Account-level economics defaults (referral / COGS %) used by the Benchmark
    break-even derivation. Manual cost entry was removed, so these stay at defaults."""
    m = get_project_meta(store, project)
    return {"refund_rate": m.get("refund_rate", 0.0),
            "default_referral_pct": m.get("default_referral_pct", 0.15),
            "default_cogs_pct": m.get("default_cogs_pct", 0.0)}   # COGS fallback = % of price


def get_store_extra(store: str, key: str, default=None):
    """Read a store-level settings blob from _meta.json (e.g. 'brand_terms')."""
    return _read_meta(slug(store, DEFAULT_STORE)).get(key, default)


def set_store_extra(store: str, key: str, value):
    """Persist a store-level settings blob in _meta.json."""
    sid = slug(store, DEFAULT_STORE)
    meta = ensure_store(sid)
    meta[key] = value
    _write_meta(sid, meta)
    return value


def get_project_extra(store: str, project: str, key: str, default=None):
    """Read a named settings blob stored on the project meta (e.g. 'waterfall')."""
    return get_project_meta(store, project).get(key, default)


def set_project_extra(store: str, project: str, key: str, value) -> dict:
    """Persist a named settings blob on the project meta. Returns the blob."""
    sid, pid = slug(store, DEFAULT_STORE), slug(project, DEFAULT_PROJECT)
    meta = ensure_store(sid)
    proj = meta.setdefault("projects", {}).setdefault(
        pid, {"title": pid, "created": date.today().isoformat()})
    proj[key] = value
    _write_meta(sid, meta)
    return value


_engines_lock = threading.Lock()


def _sqlite_on_connect(conn, _rec):
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")   # safe with WAL; fsync per checkpoint


def _bundle(store: str, project: str):
    """Get (or create) cached engine + SessionLocal for a (store, data-project).
    Creation is locked: two parallel requests first-touching the same NEW db file
    (e.g. a store switch fanning out panel fetches) would otherwise both run
    create_all and one dies with "table dim_product already exists"."""
    sid, pid = slug(store, DEFAULT_STORE), slug(project, DEFAULT_PROJECT)
    key = (sid, pid)
    if key not in _engines:
        with _engines_lock:
            if key in _engines:                 # double-checked: raced and lost
                return _engines[key]
            url = f"sqlite:///{_db_path(sid, pid)}"
            # timeout=30: sqlite's default 5s busy-wait is too short when a big write
            # (e.g. a cadence Clear deleting 100k+ accumulated fact rows) overlaps the
            # panels' concurrent reads — those reads would 500 with "database is locked".
            engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30},
                                   future=True)
            # WAL: readers and the (single) writer no longer block each other — a
            # long upload can't 500 the panels' concurrent GETs. The busy timeout
            # alone can't fix that: in rollback-journal mode a read txn racing a
            # writer gets SQLITE_BUSY immediately (deadlock guard, no wait).
            # SQLite ignores FKs unless told per-connection; enables ON DELETE CASCADE.
            event.listen(engine, "connect", _sqlite_on_connect)
            from . import models  # noqa: F401  (register mappers)
            Base.metadata.create_all(bind=engine)
            SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
            _engines[key] = (engine, SessionLocal)
    return _engines[key]


def get_session(store: str = DEFAULT_STORE, project: str = DEFAULT_PROJECT,
                cadence: str | None = None) -> Session:
    """Open a session for one (project, cadence) (caller closes). Creates the db if
    new. The session carries its (store, project) in .info so pipelines can reach
    store-scoped resources (benchmark, costs) without new params; .info['cadence']
    + .info['data_project'] expose the active cadence + its on-disk file id."""
    sid, base_pid = slug(store, DEFAULT_STORE), slug(project, DEFAULT_PROJECT)
    data_pid = _data_pid(base_pid, cadence)
    ensure_project(sid, base_pid)        # meta keyed by the REAL project, never the cadence file
    s = _bundle(sid, data_pid)[1]()
    s.info["store"], s.info["project"] = sid, base_pid
    s.info["cadence"] = slug(cadence or "full_month", "full_month")
    s.info["data_project"] = data_pid
    return s


def list_stores(owner_id) -> list[dict]:
    """One user's stores: [{id, title}] with PUBLIC (un-prefixed) ids. Auto-creates
    a starter store the first time so every user always has an isolated workspace."""
    os.makedirs(STORES_DIR, exist_ok=True)
    pre = _prefix(owner_id)
    out = []
    for sid in sorted(os.listdir(STORES_DIR)):
        if sid.startswith(pre) and os.path.isdir(os.path.join(STORES_DIR, sid)):
            pub = unscope(owner_id, sid)
            title = _read_meta(sid).get("title")
            # a dir auto-created by a data call carries the internal id as title;
            # show the friendly public id instead.
            if not title or title == sid:
                title = "My Store" if pub == DEFAULT_STORE else pub
            out.append({"id": pub, "title": title})
    if not out:
        sid = scoped(owner_id, DEFAULT_STORE)
        ensure_store(sid, "My Store")
        ensure_project(sid, DEFAULT_PROJECT, "Default Audit")
        out = [{"id": DEFAULT_STORE, "title": "My Store"}]
    return out


def list_projects(store: str) -> list[dict]:
    """Projects in a store: [{id, title, created}]."""
    sid = slug(store, DEFAULT_STORE)
    projects = _read_meta(sid).get("projects", {})
    return [{"id": pid, **info} for pid, info in sorted(projects.items(),
            key=lambda kv: kv[1].get("created", ""))]


def create_store(owner_id, title: str) -> dict:
    """Create a store (owned by owner_id) from a title + a starter project."""
    taken = {s["id"] for s in list_stores(owner_id)}
    pub = _uniquify(slug(title, "store"), taken)
    sid = scoped(owner_id, pub)
    ensure_store(sid, title)
    ensure_project(sid, DEFAULT_PROJECT, "Default Audit")
    return {"id": pub, "title": title}


def create_project(store: str, title: str) -> dict:
    """Create a named audit project inside a store."""
    sid = slug(store, DEFAULT_STORE)
    taken = {p["id"] for p in list_projects(sid)}
    pid = _uniquify(slug(title, "audit"), taken)
    info = ensure_project(sid, pid, title)
    _bundle(sid, pid)   # materialize the db file
    return {"id": pid, **info}


def _dispose_engines(store_id: str, project_id: str | None = None) -> None:
    """Drop + dispose cached engines so the SQLite file handle is released."""
    for key in [k for k in list(_engines)
                if k[0] == store_id and (project_id is None or k[1] == project_id)]:
        engine, _ = _engines.pop(key)
        engine.dispose()


def delete_store(store_id: str) -> dict:
    """STORE-level delete: remove the whole store dir (all audits, meta, benchmark)."""
    sid = slug(store_id, DEFAULT_STORE)
    _dispose_engines(sid)
    d = os.path.join(STORES_DIR, sid)
    if os.path.isdir(d):
        shutil.rmtree(d)
    return {"deleted": sid, "level": "store"}


def delete_project(store: str, project: str) -> dict:
    """AUDIT-level delete: remove the base db file + every per-cadence file + meta."""
    sid, pid = slug(store, DEFAULT_STORE), slug(project, DEFAULT_PROJECT)
    # dispose + delete the base file and all <pid>__<cadence>.db cadence files
    for dpid in [pid] + [f"{pid}__{c}" for c in CADENCE_KEYS]:
        _dispose_engines(sid, dpid)
        p = _db_path(sid, dpid)
        if os.path.exists(p):
            os.remove(p)
    meta = _read_meta(sid)
    meta.get("projects", {}).pop(pid, None)
    _write_meta(sid, meta)
    return {"deleted": pid, "level": "audit"}


def get_db(store: str = Query(DEFAULT_STORE, description="Amazon store id"),
           project: str = Query(DEFAULT_PROJECT, description="audit project id"),
           audit_type: str | None = Query(None, description="audit cadence (isolates the bulk data)"),
           user=Depends(_current_user)):
    """FastAPI dependency: yield a session for the CURRENT USER's (store, project,
    cadence). The store id is namespaced by the authenticated user and the db file
    by the cadence, so every pipeline router that `Depends(get_db)` is isolated per
    user AND per cadence with zero per-router code.
    """
    db = get_session(scoped(user.id, store), project, cadence=audit_type)
    try:
        yield db
    finally:
        db.close()


def pinned_db(cadence: str):
    """`get_db` variant pinned to ONE cadence — for routers whose whole URL path IS
    a cadence (`/daily-watch/*`, `/weekly/*`, `/mid-month/*`, `/full-month/*`,
    `/pause-scale/*`). The ambient `?audit_type=` (whatever cadence the UI has
    active) is IGNORED, so a keep-alive panel fetching in the background always
    hits its own db file, never the currently-selected cadence's."""
    def dep(store: str = Query(DEFAULT_STORE, description="Amazon store id"),
            project: str = Query(DEFAULT_PROJECT, description="audit project id"),
            user=Depends(_current_user)):
        db = get_session(scoped(user.id, store), project, cadence=cadence)
        try:
            yield db
        finally:
            db.close()
    return dep


def get_account_db(store: str = Query(DEFAULT_STORE, description="Amazon store id"),
                   project: str = Query(DEFAULT_PROJECT, description="audit project id"),
                   audit_type: str | None = Query(None, description="audit cadence (isolates the bulk data)"),
                   user=Depends(_current_user)):
    """Account-level engines (Waterfall / Structure Redesign / Cannibalization /
    Channels). Identical to `get_db` — the Audit Cadence is the partition key for
    everything a bulk upload feeds, so each cadence carries its own account-level
    plans built from its own bulk. `full_month` (and no cadence) still resolve to
    the base file, so runs made before cadence-scoping stay exactly where they were.
    """
    db = get_session(scoped(user.id, store), project, cadence=audit_type)
    try:
        yield db
    finally:
        db.close()


def get_base_db(store: str = Query(DEFAULT_STORE, description="Amazon store id"),
                project: str = Query(DEFAULT_PROJECT, description="audit project id"),
                user=Depends(_current_user)):
    """Like get_db but ALWAYS the base (project-level) db, ignoring the cadence —
    for shared, cross-cadence features (Monitoring tracker) that aren't part of a
    single cadence's bulk audit."""
    db = get_session(scoped(user.id, store), project, cadence=None)
    try:
        yield db
    finally:
        db.close()


def init_db(store: str = DEFAULT_STORE, project: str = DEFAULT_PROJECT):
    ensure_project(slug(store, DEFAULT_STORE), slug(project, DEFAULT_PROJECT))
    _bundle(store, project)
