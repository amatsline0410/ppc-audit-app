"""Cannibalization / Keyword Ownership Detector.

Finds and resolves two overlap kinds from one uploaded bulk (shares the
Waterfall upload — same frames + embedded SP Search Term Report):

  Type 1 — duplicate targets (structural): the same keyword_text + match_type
  (or the same PT expression) enabled in 2+ campaigns. Splits data, budgets
  compete against each other.

  Type 2 — cross-product term overlap (from the STR): the same customer search
  term generating clicks/orders for 2+ DIFFERENT SKUs — Amazon may serve the
  worse-converting product. SKU attribution: term row -> source campaign ->
  single-SKU mapping via waterfall.classify (MULTI campaigns attribute to 'ALL',
  reported but never auto-resolved).

Ownership rule (pure `resolve_owner`): among candidates with clicks >= min_clicks,
owner = max CVR, tiebreak min ACoS; one qualified -> it; none -> insufficient_data.

Leave-both-alive exceptions (verdict 'coexist', no action emitted):
  * every candidate is profitable (ACoS < goal) AND has clicks >= min_clicks —
    the term is big enough to feed both;
  * same-SKU tier pair (exact in EXACT campaign + broad in BROAD campaign is the
    waterfall WORKING) — only flagged when the sculpting negative is missing, in
    which case the finding emits that negative instead of picking a winner.

Converter guard (regression): never emit a negative into a campaign where that
term/keyword itself is converting (orders > 0 there) or is a live enabled
keyword (the negative would kill it). Terms converting for the OWNER are fine
to negate in LOSER campaigns.

Findings are regenerated wholesale on each run (quarterly re-review is
idempotent — replace, not append). All IDs stay exact strings.
"""
from __future__ import annotations
import io
import json
import pandas as pd
from sqlalchemy.orm import Session
from .. import models as md
from . import bulkfmt, waterfall as wf
from . import ingest as ingest_stage, clean as clean_stage
from . import weekly as wk

MIN_CLICKS = 10
UPSTREAM_SLOTS = {"AT", "KWT-BROAD", "KWT-PHRASE"}


# ---- ownership rule (pure) ----------------------------------------------------
def resolve_owner(candidates: list[dict], min_clicks: int = MIN_CLICKS) -> dict | None:
    """candidates: [{sku, campaign_id, clicks, orders, spend, sales}]
    >=2 qualified -> max CVR (tiebreak min ACoS); 1 -> it; 0 -> None."""
    qualified = [c for c in candidates if (c.get("clicks") or 0) >= min_clicks]
    if not qualified:
        return None
    if len(qualified) == 1:
        return qualified[0]

    def keyf(c):
        clicks = c.get("clicks") or 0
        cvr = (c.get("orders") or 0) / clicks if clicks else 0.0
        sales = c.get("sales") or 0
        acos = (c.get("spend") or 0) / sales if sales else float("inf")
        return (-cvr, acos)
    return sorted(qualified, key=keyf)[0]


def _acos(c) -> float | None:
    return (c["spend"] / c["sales"]) if c.get("sales") else None


def _coexist(candidates: list[dict], goal_acos: float, min_clicks: int) -> bool:
    """Term big enough to feed everyone: all profitable AND all with volume."""
    if len(candidates) < 2:
        return False
    for c in candidates:
        a = _acos(c)
        if a is None or a >= goal_acos or (c.get("clicks") or 0) < min_clicks:
            return False
    return True


# ---- detection ------------------------------------------------------------------
def _cand(sku, campaign_id, campaign_name, slot, clicks, orders, spend, sales, **extra) -> dict:
    clicks, orders = int(clicks or 0), int(orders or 0)
    spend, sales = round(float(spend or 0), 2), round(float(sales or 0), 2)
    return {"sku": sku, "campaign_id": campaign_id, "campaign_name": campaign_name,
            "slot": slot, "clicks": clicks, "orders": orders, "spend": spend, "sales": sales,
            "cvr": round(orders / clicks, 4) if clicks else None,
            "acos": round(spend / sales, 4) if sales else None, **extra}


def detect(frames: dict, str_rows: list[dict], goal_acos: float,
           min_clicks: int = MIN_CLICKS) -> list[dict]:
    """All findings (both kinds) from one bulk's frames + its STR rows."""
    classified = wf.classify(frames)
    by_cid = {c["campaign_id"]: c for c in classified}
    kw_counts = _kw_text_counts(frames)

    findings = []
    findings += _type1(frames, by_cid, kw_counts, goal_acos, min_clicks)
    findings += _type2(str_rows, by_cid, kw_counts, goal_acos, min_clicks)
    return findings


def _kw_text_counts(frames: dict) -> dict[str, dict[str, int]]:
    """campaign_id -> {lowercased enabled keyword text: how many live keywords
    carry it (across match types)}. Distinguishes 'the only live copy is the one
    being paused' from 'another live keyword would be killed by the negative'."""
    out: dict[str, dict[str, int]] = {}
    kws = wf._frame(frames, "keyword")
    if len(kws):
        for _, r in kws.iterrows():
            if not wf._enabled(r.get("state")):
                continue
            cid, txt = wf._s(r.get("campaign_id")), wf._s(r.get("keyword_text")).lower()
            if cid and txt:
                d = out.setdefault(cid, {})
                d[txt] = d.get(txt, 0) + 1
    return out


def _neg_ok(term: str, campaign_id: str, term_orders_in_campaign: int,
            kw_counts: dict[str, dict[str, int]], pausing_here: bool = False) -> bool:
    """Converter guard: negation allowed only where the term isn't converting and
    isn't a live enabled keyword. When we're pausing that campaign's own copy in
    the same file (`pausing_here`), one live occurrence is tolerated — but a second
    live keyword with the same text (another match type) still blocks the negative."""
    if term_orders_in_campaign > 0:
        return False
    n = kw_counts.get(campaign_id, {}).get(term.lower(), 0)
    return n <= (1 if pausing_here else 0)


def _type1(frames: dict, by_cid: dict, kw_counts: dict, goal_acos: float,
           min_clicks: int) -> list[dict]:
    """Duplicate targets: same keyword text+match (or PT expression) enabled in
    2+ campaigns. Auto clauses excluded (they exist in every auto campaign)."""
    groups: dict[tuple, list[dict]] = {}

    kws = wf._frame(frames, "keyword")
    if len(kws):
        for _, r in kws.iterrows():
            if not wf._enabled(r.get("state")):
                continue
            txt, mt = wf._s(r.get("keyword_text")).lower(), wf._st(r.get("match_type"))
            cid = wf._s(r.get("campaign_id"))
            if not txt or not mt or not cid:
                continue
            c = by_cid.get(cid, {})
            groups.setdefault(("kw", txt, mt), []).append(_cand(
                c.get("sku") or ("ALL" if c.get("kind") == "MULTI" else None),
                cid, c.get("name") or cid, c.get("slot"),
                r.get("clicks"), r.get("orders"), r.get("spend"), r.get("sales"),
                keyword_id=wf._s(r.get("keyword_id")), ad_group_id=wf._s(r.get("ad_group_id")),
                target_kind="keyword", term=wf._s(r.get("keyword_text")), match_type=mt))

    pts = wf._frame(frames, "product targeting")
    if len(pts):
        for _, r in pts.iterrows():
            if not wf._enabled(r.get("state")):
                continue
            expr = wf._s(r.get("expression")).lower()
            cid = wf._s(r.get("campaign_id"))
            if not expr or not cid or expr in bulkfmt.AUTO_CLAUSES:
                continue
            c = by_cid.get(cid, {})
            groups.setdefault(("pt", expr, None), []).append(_cand(
                c.get("sku") or ("ALL" if c.get("kind") == "MULTI" else None),
                cid, c.get("name") or cid, c.get("slot"),
                r.get("clicks"), r.get("orders"), r.get("spend"), r.get("sales"),
                product_targeting_id=wf._s(r.get("product_targeting_id")),
                ad_group_id=wf._s(r.get("ad_group_id")),
                target_kind="product_target", term=wf._s(r.get("expression")), match_type=None))

    out = []
    for (tkind, key, mt), cands in groups.items():
        # collapse duplicates WITHIN a campaign first — the finding is cross-campaign
        if len({c["campaign_id"] for c in cands}) < 2:
            continue
        term = cands[0]["term"]
        f = {"kind": "duplicate_target", "term": term, "match_type": mt,
             "candidates": cands, "owner_sku": None, "owner_campaign_id": None,
             "actions": []}
        if _coexist(cands, goal_acos, min_clicks):
            f["verdict"] = "coexist"
            out.append(f)
            continue
        owner = resolve_owner(cands, min_clicks)
        if owner is None:
            f["verdict"] = "insufficient_data"
            out.append(f)
            continue
        f["verdict"] = "resolve"
        f["owner_sku"], f["owner_campaign_id"] = owner["sku"], owner["campaign_id"]
        for c in cands:
            if c["campaign_id"] == owner["campaign_id"]:
                continue                       # winner untouched
            if c["target_kind"] == "keyword":
                f["actions"].append({"type": "pause_keyword", "keyword_id": c["keyword_id"],
                                     "campaign_id": c["campaign_id"],
                                     "ad_group_id": c["ad_group_id"], "term": term})
                if _neg_ok(term, c["campaign_id"], c["orders"], kw_counts, pausing_here=True):
                    f["actions"].append({"type": "campaign_negative", "term": term,
                                         "campaign_id": c["campaign_id"]})
            else:
                f["actions"].append({"type": "pause_pt",
                                     "product_targeting_id": c["product_targeting_id"],
                                     "campaign_id": c["campaign_id"],
                                     "ad_group_id": c["ad_group_id"], "term": term})
        out.append(f)
    return out


def _type2(str_rows: list[dict], by_cid: dict, kw_counts: dict,
           goal_acos: float, min_clicks: int) -> list[dict]:
    """Cross-product term overlap from the STR + the same-SKU tier-pair check."""
    if not str_rows:
        return []
    # term -> sku -> aggregate + campaign traffic map
    terms: dict[str, dict] = {}
    for r in str_rows:
        term = str(r.get("search_term") or "").strip()
        cid = r.get("campaign_id") or ""
        c = by_cid.get(cid)
        if not term or term == "*" or c is None:
            continue
        sku = c["sku"] if c["kind"] == "SKU" else ("ALL" if c["kind"] == "MULTI" else None)
        if sku is None:
            continue
        t = terms.setdefault(term.lower(), {"term": term, "skus": {}, "camps": {}})
        s = t["skus"].setdefault(sku, {"clicks": 0, "orders": 0, "spend": 0.0, "sales": 0.0,
                                       "top_cid": cid, "top_clicks": -1})
        s["clicks"] += r.get("clicks") or 0
        s["orders"] += r.get("orders") or 0
        s["spend"] += r.get("spend") or 0
        s["sales"] += r.get("sales") or 0
        cm = t["camps"].setdefault(cid, {"clicks": 0, "orders": 0, "spend": 0.0, "sku": sku})
        cm["clicks"] += r.get("clicks") or 0
        cm["orders"] += r.get("orders") or 0
        cm["spend"] += r.get("spend") or 0
        if cm["clicks"] > s["top_clicks"]:
            s["top_cid"], s["top_clicks"] = cid, cm["clicks"]

    out = []
    for t in terms.values():
        term = t["term"]
        skus = t["skus"]
        if len(skus) < 2:
            # same-SKU tier pair: one SKU, term active in 2+ campaigns of its funnel
            f = _tier_pair(t, by_cid, kw_counts)
            if f:
                out.append(f)
            continue
        cands = []
        for sku, s in skus.items():
            c = by_cid.get(s["top_cid"], {})
            cands.append(_cand(sku, s["top_cid"], c.get("name") or s["top_cid"], c.get("slot"),
                               s["clicks"], s["orders"], s["spend"], s["sales"]))
        f = {"kind": "cross_product", "term": term, "match_type": None,
             "candidates": cands, "owner_sku": None, "owner_campaign_id": None, "actions": []}
        if _coexist(cands, goal_acos, min_clicks):
            f["verdict"] = "coexist"
            out.append(f)
            continue
        owner = resolve_owner([c for c in cands if c["sku"] != "ALL"], min_clicks)
        if owner is None:
            f["verdict"] = "insufficient_data"
            out.append(f)
            continue
        f["verdict"] = "resolve"
        f["owner_sku"], f["owner_campaign_id"] = owner["sku"], owner["campaign_id"]
        # losers: negativeExact the term in the loser SKU's upstream campaigns where
        # it actually got traffic — MULTI ('ALL') is reported but never auto-resolved
        for cid, cm in t["camps"].items():
            c = by_cid.get(cid)
            if c is None or cm["sku"] == "ALL" or cm["sku"] == owner["sku"]:
                continue
            if c.get("slot") not in UPSTREAM_SLOTS:
                continue                       # never negate inside the EXACT/PT money tiers
            if not _neg_ok(term, cid, cm["orders"], kw_counts):
                continue                       # converter/live-keyword guard
            f["actions"].append({"type": "campaign_negative", "term": term, "campaign_id": cid})
        out.append(f)
    return out


def _tier_pair(t: dict, by_cid: dict, kw_counts: dict) -> dict | None:
    """One SKU, term flowing through 2+ funnel tiers. That's the waterfall working —
    coexist. But if the term is a live EXACT keyword downstream and the sculpting
    negative is MISSING upstream, emit that negative (isolation repair)."""
    term = t["term"]
    camps = t["camps"]
    if len(camps) < 2:
        return None
    sku = next(iter(t["skus"]))
    if sku == "ALL":
        return None
    # is it harvested? (live exact keyword in one of this SKU's campaigns)
    exact_home = None
    for cid in camps:
        c = by_cid.get(cid)
        if c and c.get("slot") == "KWT-EXACT" and kw_counts.get(cid, {}).get(term.lower()):
            exact_home = cid
            break
    if not exact_home:
        return None                            # not harvested yet -> nothing to repair
    actions = []
    for cid, cm in camps.items():
        c = by_cid.get(cid)
        if cid == exact_home or c is None or c.get("slot") not in UPSTREAM_SLOTS:
            continue
        if not _neg_ok(term, cid, cm["orders"], kw_counts):
            continue
        actions.append({"type": "campaign_negative", "term": term, "campaign_id": cid})
    if not actions:
        return None                            # isolation already in place
    cands = [_cand(sku, cid, (by_cid.get(cid) or {}).get("name") or cid,
                   (by_cid.get(cid) or {}).get("slot"),
                   cm["clicks"], cm["orders"], cm["spend"], 0.0)
             for cid, cm in camps.items()]
    return {"kind": "cross_product", "term": term, "match_type": None,
            "candidates": cands, "owner_sku": sku, "owner_campaign_id": exact_home,
            "verdict": "coexist", "tier_pair": True, "actions": actions}


# ---- persistence -----------------------------------------------------------------
def run(db: Session, path: str, goal_acos: float, min_clicks: int = MIN_CLICKS) -> dict:
    """Parse the bulk + STR, detect, and REPLACE all stored findings (idempotent)."""
    frames = ingest_stage.frames(path)
    try:
        str_rows = wk.parse_str_sheet(path)
    except ValueError:
        str_rows = []
    return store(db, detect(frames, str_rows, goal_acos, min_clicks))


def store(db: Session, findings: list[dict]) -> dict:
    db.query(md.OverlapFinding).delete()
    for f in findings:
        db.add(md.OverlapFinding(
            kind=f["kind"], term=f["term"], match_type=f.get("match_type"),
            owner_sku=f.get("owner_sku"), owner_campaign_id=f.get("owner_campaign_id"),
            verdict=f["verdict"],
            candidates_json=json.dumps(f.get("candidates") or []),
            actions_json=json.dumps(f.get("actions") or []),
            selected=(f["verdict"] == "resolve")))
    db.commit()
    return summary(db)


def findings(db: Session, kind: str | None = None) -> list[dict]:
    q = db.query(md.OverlapFinding)
    if kind:
        q = q.filter(md.OverlapFinding.kind == kind)
    out = []
    for f in q.order_by(md.OverlapFinding.id.asc()).all():
        out.append({"id": f.id, "kind": f.kind, "term": f.term, "match_type": f.match_type,
                    "owner_sku": f.owner_sku, "owner_campaign_id": f.owner_campaign_id,
                    "verdict": f.verdict, "selected": bool(f.selected),
                    "candidates": json.loads(f.candidates_json or "[]"),
                    "actions": json.loads(f.actions_json or "[]")})
    return out


def summary(db: Session) -> dict:
    rows = findings(db)
    dup = [f for f in rows if f["kind"] == "duplicate_target"]
    cross = [f for f in rows if f["kind"] == "cross_product"]
    # overlap spend = loser-candidate spend on resolvable findings
    wasted = 0.0
    for f in rows:
        if f["verdict"] != "resolve":
            continue
        for c in f["candidates"]:
            if c["campaign_id"] != f["owner_campaign_id"]:
                wasted += c.get("spend") or 0
    return {"findings": len(rows), "duplicates": len(dup), "cross_product": len(cross),
            "resolvable": sum(1 for f in rows if f["verdict"] == "resolve"),
            "coexist": sum(1 for f in rows if f["verdict"] == "coexist"),
            "insufficient": sum(1 for f in rows if f["verdict"] == "insufficient_data"),
            "overlap_spend": round(wasted, 2)}


def has_data(db: Session) -> bool:
    return db.query(md.OverlapFinding.id).first() is not None


def delete_all(db: Session) -> int:
    """Wipe the stored scan (Clear button). Own table only — the scan never
    touches the audit star schema."""
    n = db.query(md.OverlapFinding).delete()
    db.commit()
    return n


# ---- bulk emit ---------------------------------------------------------------------
BULK_COLS = ["Product", "Entity", "Operation", "Campaign ID", "Ad Group ID",
             "Keyword ID", "Product Targeting ID", "Keyword Text", "Match Type",
             "Product Targeting Expression", "Bid", "State"]


def to_bulk(chosen: list[dict]) -> bytes:
    """Selected findings -> one SP bulk: loser keyword/PT pauses (by exact ID) +
    Campaign Negative Keyword negativeExact rows. ASIN-shaped terms become
    negative PRODUCT targets (ad-group level needs a parent — campaign negatives
    only take keywords, so ASIN terms are emitted as campaign negative PT is not
    supported -> skipped defensively by bulkfmt shape rules)."""
    rows, seen = [], set()

    def blank():
        return {c: None for c in BULK_COLS}

    for f in chosen:
        for a in f.get("actions") or []:
            typ = a.get("type")
            cid = bulkfmt.idstr(a.get("campaign_id"))
            if typ == "pause_keyword":
                kid = bulkfmt.idstr(a.get("keyword_id"))
                if not kid or ("k", kid) in seen:
                    continue
                seen.add(("k", kid))
                r = blank()
                r.update({"Product": "Sponsored Products", "Entity": "Keyword",
                          "Operation": "update", "Campaign ID": cid,
                          "Ad Group ID": bulkfmt.idstr(a.get("ad_group_id")),
                          "Keyword ID": kid, "State": "paused"})
                rows.append(r)
            elif typ == "pause_pt":
                tid = bulkfmt.idstr(a.get("product_targeting_id"))
                if not tid or ("p", tid) in seen:
                    continue
                seen.add(("p", tid))
                r = blank()
                r.update({"Product": "Sponsored Products", "Entity": "Product Targeting",
                          "Operation": "update", "Campaign ID": cid,
                          "Ad Group ID": bulkfmt.idstr(a.get("ad_group_id")),
                          "Product Targeting ID": tid, "State": "paused"})
                rows.append(r)
            elif typ == "campaign_negative":
                term = str(a.get("term") or "").strip()
                if bulkfmt.is_asin(term):
                    continue                   # ASIN terms are never negative keywords
                if not bulkfmt.valid_keyword(term):
                    continue
                sig = ("n", cid, term.lower())
                if sig in seen:
                    continue
                seen.add(sig)
                r = blank()
                r.update({"Product": "Sponsored Products",
                          "Entity": "Campaign Negative Keyword", "Operation": "create",
                          "Campaign ID": cid, "Keyword Text": term,
                          "Match Type": "Negative Exact", "State": "enabled"})
                rows.append(r)

    df = pd.DataFrame(rows, columns=BULK_COLS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Sponsored Products Campaigns")
    return buf.getvalue()


def ledger_entries(chosen: list[dict]) -> list[dict]:
    out = []
    for f in chosen:
        for a in f.get("actions") or []:
            if a.get("type") == "pause_keyword":
                out.append({"target_id": a.get("keyword_id"),
                            "campaign_id": a.get("campaign_id"), "state": "paused"})
            elif a.get("type") == "pause_pt":
                out.append({"target_id": a.get("product_targeting_id"),
                            "campaign_id": a.get("campaign_id"), "state": "paused"})
    return out


def changelog_entries(chosen: list[dict]) -> list[dict]:
    out = []
    for f in chosen:
        for a in f.get("actions") or []:
            if a.get("type") in ("pause_keyword", "pause_pt"):
                out.append(dict(campaign_id=a.get("campaign_id"),
                                entity_type="keyword" if a["type"] == "pause_keyword" else "product_target",
                                entity_id=a.get("keyword_id") or a.get("product_targeting_id"),
                                label=f["term"], field="state", old_value="enabled",
                                new_value="paused", action="pause",
                                reason=f"cannibalization — owner {f.get('owner_sku') or f.get('owner_campaign_id')}"))
            elif a.get("type") == "campaign_negative":
                out.append(dict(campaign_id=a.get("campaign_id"), entity_type="negative",
                                label=f["term"], field="create", new_value="negative exact",
                                action="negate",
                                reason=f"cannibalization — owned by {f.get('owner_sku') or 'winner'}"))
    return out
