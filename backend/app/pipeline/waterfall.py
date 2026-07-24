"""Waterfall Restructure Engine — automates a full account restructure into the
RAF Funnel System (Tiered Harvesting Funnel):

    AT (discovery) -> KWT-BROAD -> KWT-PHRASE -> KWT-EXACT (money tier)
                                              + PT (ASIN tier)
    each promotion downstream = negativeExact upstream (search-term isolation)
    1 SKU per campaign (SPAG). Boss campaign per SKU+slot; duplicates consolidated.

One uploaded bulk -> a draft plan of 4 phased bulk files, exported in dependency
order:  A renames (zero risk) -> B loser bid cuts (transitional overlap, not
pause) -> C creates (new campaigns born paused + seeds + sculpting negatives) ->
D pauses (gated in the UI until A-C are applied).

Self-contained: own upload, own tables (WaterfallRun / WaterfallItem), never
touches the audit star schema or `active_snapshot`. Bids computed for Phase B
read the effective-bid ledger overlay (see pipeline/ledger.py), not the raw
snapshot, so consecutive exports never double-apply. All IDs stay exact strings.
"""
from __future__ import annotations
import io
import os
import json
from datetime import date, datetime
import pandas as pd
from sqlalchemy.orm import Session
from .. import models as md
from . import bulkfmt, ingest as ingest_stage, clean as clean_stage
from . import weekly as wk
from . import ledger as ledger_stage

SLOTS = ["AT", "KWT-BROAD", "KWT-PHRASE", "KWT-EXACT", "PT"]
KWT_SLOT = {"exact": "KWT-EXACT", "phrase": "KWT-PHRASE", "broad": "KWT-BROAD"}
SLOT_LABEL = {"AT": "AT", "PT": "PT", "KWT-EXACT": "KWT - EXACT",
              "KWT-PHRASE": "KWT - PHRASE", "KWT-BROAD": "KWT - BROAD"}
# per-slot default bid for NEW campaigns (the ad group default bid + the slot's
# name {bid} placeholder). AT's split-target bids scale off its slot bid.
DEFAULT_SLOT_BIDS = {"AT": 0.30, "KWT-BROAD": 0.50, "KWT-PHRASE": 0.50,
                     "KWT-EXACT": 0.50, "PT": 0.40}
# new AT campaigns get the 4 auto clauses as individual split targets; bids are
# multiples of the AT slot bid (close-match richest, complements leanest)
AT_SPLIT_MULT = [("close-match", 3.33), ("loose-match", 2.50),
                 ("substitutes", 2.50), ("complements", 1.67)]

# Amazon bidding-strategy string per setting value
STRATEGY_STR = {"down": "Dynamic bids - down only",
                "up_down": "Dynamic bids - up and down", "fixed": "Fixed bid"}

DEFAULTS = {
    "naming_template": "SP - {sku} - {slot} - RAF",
    "budget": 10.0,             # daily budget for boss renames + new campaigns
    "goal_acos": 0.25,          # fraction
    "seed_min_orders": 1,       # STR orders needed for a seed keyword
    "seed_copies": True,        # broad/phrase copies of seeds into NEW slots
    "hero_n": 5,                # default hero count (top-N SKUs by 60d sales)
    "heroes": None,             # explicit hero SKU list (None -> top-N)
    "loser_cut_mult": 0.6,      # phase B: new bid = max(effective * this, floor)
    "loser_bid_floor": 0.15,
    "bid_floor": 0.30,          # seed-keyword bid clamp (was hardcoded)
    "bid_ceiling": 2.00,
    "force_down_only": False,   # phase A: flip boss to "down only" strategy on rename
    "protect_min_orders": 1,    # EMPTY campaigns at/above this orders count are
                                 # never auto-paused — flagged for manual review instead
    "protected_campaign_ids": None,  # explicit IDs never touched by phase B/D
    "slot_bids": None,          # per-slot default bid for NEW campaigns (None -> DEFAULT_SLOT_BIDS)
    "new_strategy": "down",     # bidding strategy for NEW campaigns: down | up_down | fixed
}

_ENABLED = ("enabled", "ok", "")


def _st(v) -> str:
    s = str(v or "").strip().lower()
    return "" if s == "nan" else s


def _enabled(v) -> bool:
    return _st(v) in _ENABLED


def _s(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def _frame(frames: dict, key: str) -> pd.DataFrame:
    df = frames.get(key)
    return df if df is not None else pd.DataFrame()


def strategy_suffix(raw: str) -> str:
    """Actual bidding strategy in the data, not the old campaign label — 'down'
    for down-only, 'up/down' for up-and-down, 'down' default (fixed/legacy)."""
    s = str(raw or "").strip().lower()
    return "up/down" if "up and down" in s or "up/down" in s else "down"


def render_name(template: str, sku: str, asin: str, slot: str, n: int | None = None,
                bid: float | None = None, strategy: str | None = None) -> str:
    class _Safe(dict):
        def __missing__(self, k):        # unknown placeholder -> literal
            return "{" + k + "}"
    n = n if n is not None else (SLOTS.index(slot) + 1 if slot in SLOTS else "")
    bid_s = f"{float(bid):.2f}" if bid is not None else ""
    return str(template or DEFAULTS["naming_template"]).format_map(
        _Safe(sku=sku or "", asin=asin or "", slot=SLOT_LABEL.get(slot, slot),
              n=n, bid=bid_s, strategy=strategy or ""))


# ---- 1. classify -------------------------------------------------------------
def classify(frames: dict) -> list[dict]:
    """Per enabled campaign: SKU mapping (via Product Ad rows), funnel slot, and
    60d raw metrics. Auto targeting type ALWAYS wins over the campaign name
    (catches misnamed campaigns — a real 'PT'-named campaign was Auto type).

    kind: 'SKU' (single SKU, mappable) | 'MULTI' (excluded from the per-SKU
    funnel) | 'EMPTY' (no product ad — can't sell anything).
    """
    camp = _frame(frames, "campaign")
    ads = _frame(frames, "product ad")
    kws = _frame(frames, "keyword")
    pts = _frame(frames, "product targeting")

    # campaign -> SKUs (+ sku -> asin) from enabled Product Ad rows
    sku_map: dict[str, set[str]] = {}
    sku_asin: dict[str, str] = {}
    if len(ads):
        for _, r in ads.iterrows():
            if not _enabled(r.get("state")):
                continue
            cid, sku = _s(r.get("campaign_id")), _s(r.get("sku"))
            if not cid or not sku:
                continue
            sku_map.setdefault(cid, set()).add(sku)
            asin = _s(r.get("asin"))
            if asin and sku not in sku_asin:
                sku_asin[sku] = asin

    # campaign -> enabled keyword match-type counts / enabled product-target count
    kw_types: dict[str, dict[str, int]] = {}
    if len(kws):
        for _, r in kws.iterrows():
            if not _enabled(r.get("state")):
                continue
            cid, mt = _s(r.get("campaign_id")), _st(r.get("match_type"))
            if cid and mt in KWT_SLOT:
                kw_types.setdefault(cid, {})[mt] = kw_types.setdefault(cid, {}).get(mt, 0) + 1
    pt_count: dict[str, int] = {}
    if len(pts):
        for _, r in pts.iterrows():
            if not _enabled(r.get("state")):
                continue
            cid = _s(r.get("campaign_id"))
            if cid:
                pt_count[cid] = pt_count.get(cid, 0) + 1

    out = []
    if not len(camp):
        return out
    for _, r in camp.iterrows():
        if not _enabled(r.get("state")):
            continue
        cid = _s(r.get("campaign_id"))
        if not cid:
            continue
        skus = sorted(sku_map.get(cid, set()))
        kind = "SKU" if len(skus) == 1 else ("MULTI" if len(skus) > 1 else "EMPTY")
        ttype = _st(r.get("targeting_type"))
        types = kw_types.get(cid, {})
        mixed = False
        if ttype == "auto":
            slot = "AT"                       # auto type beats any name/keyword signal
        elif types:
            dominant = max(types, key=lambda k: types[k])
            slot = KWT_SLOT[dominant]
            mixed = len(types) > 1
        elif pt_count.get(cid):
            slot = "PT"
        else:
            slot = None
        spend = float(r.get("spend") or 0)
        sales = float(r.get("sales") or 0)
        out.append({
            "campaign_id": cid, "name": _s(r.get("campaign_name")),
            "state": _st(r.get("state")), "targeting_type": ttype,
            "strategy": _s(r.get("bidding strategy")),
            "daily_budget": float(r.get("daily_budget") or 0) or None,
            "skus": skus, "n_skus": len(skus),
            "sku": skus[0] if kind == "SKU" else None,
            "asin": sku_asin.get(skus[0]) if kind == "SKU" else None,
            "kind": kind, "slot": slot, "mixed": mixed,
            "spend": round(spend, 2), "sales": round(sales, 2),
            "acos": round(spend / sales, 4) if sales else None,
            "impressions": int(r.get("impressions") or 0),
            "clicks": int(r.get("clicks") or 0),
            "orders": int(r.get("orders") or 0),
        })
    return out


# ---- 2. boss selection --------------------------------------------------------
def pick_boss(cands: list[dict], goal_acos: float) -> dict:
    """Profitable-first rule — raw sales alone crowns bleeders (a 111% ACoS
    campaign can out-sell a 12.7% one; the 12.7% must win)."""
    profitable = [c for c in cands
                  if c["sales"] > 0 and c["acos"] is not None and c["acos"] < 2 * goal_acos]
    if profitable:
        return max(profitable, key=lambda c: c["sales"])
    with_sales = [c for c in cands if c["sales"] > 0]
    if with_sales:
        return min(with_sales, key=lambda c: c["acos"] if c["acos"] is not None else float("inf"))
    return max(cands, key=lambda c: c["impressions"])


def select_bosses(classified: list[dict], goal_acos: float,
                  forced: dict | None = None) -> list[dict]:
    """Group mappable campaigns by (sku, slot); each group elects one boss (keeps
    its Campaign ID — history preserved), the rest become losers. `forced` =
    {"sku|slot": campaign_id} user overrides — that campaign becomes the boss for
    its group instead of the auto-elected one (ignored if not a candidate there)."""
    forced = forced or {}
    groups: dict[tuple, list[dict]] = {}
    for c in classified:
        if c["kind"] == "SKU" and c["slot"]:
            groups.setdefault((c["sku"], c["slot"]), []).append(c)
    out = []
    for (sku, slot), cands in sorted(groups.items()):
        override_id = forced.get(f"{sku}|{slot}")
        boss = next((c for c in cands if c["campaign_id"] == override_id), None) \
            if override_id else None
        if boss is None:
            boss = pick_boss(cands, goal_acos)
        out.append({"sku": sku, "slot": slot, "boss": boss,
                    "boss_forced": bool(boss["campaign_id"] == override_id),
                    "losers": [c for c in cands if c["campaign_id"] != boss["campaign_id"]]})
    return out


def default_heroes(classified: list[dict], n: int) -> list[str]:
    """Top-N SKUs by 60d sales across their single-SKU campaigns."""
    sales: dict[str, float] = {}
    for c in classified:
        if c["kind"] == "SKU":
            sales[c["sku"]] = sales.get(c["sku"], 0.0) + c["sales"]
    return [s for s, _ in sorted(sales.items(), key=lambda kv: -kv[1])[:max(1, n)]]


# ---- 3. build phases ----------------------------------------------------------
def _seed_bid(spend: float, clicks: float, floor: float = 0.30, ceiling: float = 2.00) -> float:
    if not clicks:
        return floor
    return round(min(max(spend / clicks * 1.1, floor), ceiling), 2)


def _live_keywords_by_campaign(frames: dict) -> dict[str, set[str]]:
    """campaign_id -> lowercased enabled keyword texts (any match type). Negating
    a term that's a live keyword in the same campaign KILLS it — always skip."""
    out: dict[str, set[str]] = {}
    kws = _frame(frames, "keyword")
    if len(kws):
        for _, r in kws.iterrows():
            if not _enabled(r.get("state")):
                continue
            cid, txt = _s(r.get("campaign_id")), _s(r.get("keyword_text")).lower()
            if cid and txt:
                out.setdefault(cid, set()).add(txt)
    return out


def _exact_keywords_of(frames: dict, campaign_id: str) -> set[str]:
    out = set()
    kws = _frame(frames, "keyword")
    if len(kws):
        for _, r in kws.iterrows():
            if (_s(r.get("campaign_id")) == campaign_id and _enabled(r.get("state"))
                    and _st(r.get("match_type")) == "exact"):
                txt = _s(r.get("keyword_text")).lower()
                if txt:
                    out.add(txt)
    return out


def _campaign_negatives(frames: dict) -> dict[str, set[str]]:
    """campaign_id -> lowercased campaign-level negative keyword texts already in
    the account (dedup — Amazon rejects 'already exists')."""
    out: dict[str, set[str]] = {}
    cn = _frame(frames, "campaign negative keyword")
    if len(cn):
        for _, r in cn.iterrows():
            cid, txt = _s(r.get("campaign_id")), _s(r.get("keyword_text")).lower()
            if cid and txt:
                out.setdefault(cid, set()).add(txt)
    return out


def _first_enabled_adgroup(frames: dict, campaign_id: str) -> tuple[str, str]:
    """(ad_group_id, name) of the campaign's first enabled ad group ('' if none)."""
    ags = _frame(frames, "ad group")
    if len(ags):
        for _, r in ags.iterrows():
            if _s(r.get("campaign_id")) == campaign_id and _enabled(r.get("state")):
                return _s(r.get("ad_group_id")), _s(r.get("ad_group_name"))
    return "", ""


def build_phases(groups: list[dict], classified: list[dict], frames: dict,
                 str_rows: list[dict], effective: dict[str, dict], opts: dict) -> list[dict]:
    """The full A/B/C/D item list (dicts shaped like WaterfallItem rows)."""
    o = {**DEFAULTS, **{k: v for k, v in (opts or {}).items() if v is not None}}
    heroes = list(o.get("heroes") or default_heroes(classified, o["hero_n"]))
    hero_set = set(heroes)
    goal = float(o["goal_acos"])
    template = o["naming_template"]
    budget = float(o["budget"])
    today = date.today().strftime("%Y%m%d")
    slot_bids = {**DEFAULT_SLOT_BIDS, **(o.get("slot_bids") or {})}
    new_strategy = o.get("new_strategy") or "down"
    new_strategy_str = STRATEGY_STR.get(new_strategy, STRATEGY_STR["down"])
    new_strategy_sfx = "up/down" if new_strategy == "up_down" else "down"

    hero_groups = [g for g in groups if g["sku"] in hero_set]
    items: list[dict] = []

    def add(phase, action, payload, sku=None, slot=None, campaign_id=None,
            ad_group_id=None, target_id=None, selected=True):
        items.append(dict(phase=phase, action=action, sku=sku, slot=slot,
                          campaign_id=campaign_id, ad_group_id=ad_group_id,
                          target_id=target_id, payload_json=json.dumps(payload),
                          selected=selected))

    # ---- Phase A: boss renames (zero risk, first) ----
    ags = _frame(frames, "ad group")
    protected = set(o.get("protected_campaign_ids") or [])
    for g in hero_groups:
        boss = g["boss"]
        cur_strategy = strategy_suffix(boss.get("strategy"))
        flip = bool(o["force_down_only"]) and cur_strategy == "up/down"
        out_strategy = "down" if flip else cur_strategy
        ag_row = None
        if len(ags):
            for _, r in ags.iterrows():
                if _s(r.get("campaign_id")) == boss["campaign_id"] and _enabled(r.get("state")):
                    ag_row = r
                    break
        ag_bid = float(ag_row.get("ad_group_default_bid") or 0) if ag_row is not None else None
        new_name = render_name(template, g["sku"], boss.get("asin") or "", g["slot"],
                               bid=ag_bid or None, strategy=out_strategy)
        payload = {"old_name": boss["name"], "new_name": new_name, "budget": budget}
        if flip:
            payload["strategy"] = "Dynamic bids - down only"  # was up/down — force flip
        add("A", "rename", payload,
            sku=g["sku"], slot=g["slot"], campaign_id=boss["campaign_id"])
        if len(ags):
            for _, r in ags.iterrows():
                if _s(r.get("campaign_id")) == boss["campaign_id"] and _enabled(r.get("state")):
                    add("A", "rename_adgroup",
                        {"old_name": _s(r.get("ad_group_name")), "new_name": new_name},
                        sku=g["sku"], slot=g["slot"], campaign_id=boss["campaign_id"],
                        ad_group_id=_s(r.get("ad_group_id")))

    # ---- Phase B: loser bid cuts (transitional overlap, not pause) ----
    loser_ids = {l["campaign_id"] for g in hero_groups for l in g["losers"]}
    loser_meta = {l["campaign_id"]: (g["sku"], g["slot"])
                  for g in hero_groups for l in g["losers"]}
    for ent, kind, idcol in (("keyword", "keyword", "keyword_id"),
                             ("product targeting", "product_target", "product_targeting_id")):
        df = _frame(frames, ent)
        if not len(df):
            continue
        for _, r in df.iterrows():
            cid = _s(r.get("campaign_id"))
            if cid not in loser_ids or cid in protected or not _enabled(r.get("state")):
                continue
            tid = _s(r.get(idcol))
            if not tid:
                continue
            eff = effective.get(tid, {})
            if _st(eff.get("state")) == "paused":
                continue                       # already paused by a prior export
            cur = eff.get("bid")
            if cur is None:
                cur = float(r.get("bid") or 0)
            if not cur or cur <= 0:
                continue
            new = max(round(cur * float(o["loser_cut_mult"]), 2), float(o["loser_bid_floor"]))
            if new >= cur:
                continue
            sku, slot = loser_meta[cid]
            add("B", "bid_cut",
                {"kind": kind, "old_bid": round(cur, 2), "new_bid": new,
                 "label": _s(r.get("keyword_text")) or _s(r.get("expression"))},
                sku=sku, slot=slot, campaign_id=cid,
                ad_group_id=_s(r.get("ad_group_id")), target_id=tid)

    # ---- Phase C: creates (campaigns born paused) + seeds + sculpting negatives ----
    # campaign_id -> hero sku for single-SKU campaigns (STR seed attribution)
    cid_sku = {c["campaign_id"]: c["sku"] for c in classified if c["kind"] == "SKU"}
    sku_asin = {c["sku"]: c["asin"] for c in classified if c["kind"] == "SKU" and c["asin"]}
    boss_by_hero: dict[str, dict[str, dict]] = {}
    for g in hero_groups:
        boss_by_hero.setdefault(g["sku"], {})[g["slot"]] = g["boss"]

    live_kw = _live_keywords_by_campaign(frames)
    acct_camp_neg = _campaign_negatives(frames)
    created: dict[tuple, str] = {}            # (sku, slot) -> temp campaign ref (rendered name)

    for sku in heroes:
        bosses = boss_by_hero.get(sku, {})
        asin = sku_asin.get(sku, "")
        for slot in SLOTS:
            if slot in bosses:
                continue
            slot_bid = round(float(slot_bids.get(slot, DEFAULT_SLOT_BIDS[slot])), 2)
            name = render_name(template, sku, asin, slot, bid=slot_bid,
                               strategy=new_strategy_sfx)
            created[(sku, slot)] = name
            add("C", "create_campaign",
                {"name": name, "budget": budget, "start_date": today,
                 "targeting_type": "Auto" if slot == "AT" else "Manual",
                 "strategy": new_strategy_str, "state": "paused"},
                sku=sku, slot=slot, campaign_id=name)
            add("C", "create_adgroup", {"name": name, "default_bid": slot_bid},
                sku=sku, slot=slot, campaign_id=name, ad_group_id=name)
            add("C", "create_ad", {"sku": sku}, sku=sku, slot=slot,
                campaign_id=name, ad_group_id=name)
            if slot == "AT":
                for expr, mult in AT_SPLIT_MULT:
                    add("C", "create_pt", {"expression": expr, "bid": round(slot_bid * mult, 2)},
                        sku=sku, slot=slot, campaign_id=name, ad_group_id=name)

    # seeds: proven STR terms -> hero's EXACT campaign (boss if exists, else new)
    seed_terms: dict[str, list[str]] = {}     # hero sku -> seed texts (for sculpting)
    agg: dict[tuple, dict] = {}
    for r in str_rows or []:
        sku = cid_sku.get(r.get("campaign_id") or "")
        if sku not in hero_set:
            continue
        term = str(r.get("search_term") or "").strip()
        if not term or term == "*":
            continue
        a = agg.setdefault((sku, term.lower()),
                           {"sku": sku, "term": term, "clicks": 0, "spend": 0.0,
                            "sales": 0.0, "orders": 0})
        a["clicks"] += r.get("clicks") or 0
        a["spend"] += r.get("spend") or 0
        a["sales"] += r.get("sales") or 0
        a["orders"] += r.get("orders") or 0

    for a in agg.values():
        sku, term = a["sku"], a["term"]
        if a["orders"] < int(o["seed_min_orders"]) or not a["sales"]:
            continue
        if (a["spend"] / a["sales"]) >= goal:
            continue
        if bulkfmt.is_asin(term) or not bulkfmt.valid_keyword(term):
            continue                          # ASIN-shaped terms are never keywords
        bosses = boss_by_hero.get(sku, {})
        bid = _seed_bid(a["spend"], a["clicks"], float(o["bid_floor"]), float(o["bid_ceiling"]))
        exact_boss = bosses.get("KWT-EXACT")
        if exact_boss:
            dest_c = exact_boss["campaign_id"]
            if term.lower() in _exact_keywords_of(frames, dest_c):
                continue                      # already an exact keyword there
            dest_ag, _n = _first_enabled_adgroup(frames, dest_c)
            if not dest_ag:
                continue
        else:
            dest_c = dest_ag = created.get((sku, "KWT-EXACT"))
            if not dest_c:
                continue
        add("C", "create_keyword", {"text": term, "match": "Exact", "bid": bid},
            sku=sku, slot="KWT-EXACT", campaign_id=dest_c, ad_group_id=dest_ag)
        seed_terms.setdefault(sku, []).append(term)
        if o["seed_copies"]:
            # broad/phrase copies ONLY into slots that are NEW this run (empty)
            for cslot, match, mult in (("KWT-BROAD", "Broad", 0.6), ("KWT-PHRASE", "Phrase", 0.75)):
                ref = created.get((sku, cslot))
                if ref:
                    add("C", "create_keyword",
                        {"text": term, "match": match, "bid": round(bid * mult, 2)},
                        sku=sku, slot=cslot, campaign_id=ref, ad_group_id=ref)

    # sculpting negatives: boss-EXACT keywords + seeds -> negativeExact upstream
    seen_neg: set[tuple] = set()
    for sku in heroes:
        bosses = boss_by_hero.get(sku, {})
        negset: set[str] = set()
        exact_boss = bosses.get("KWT-EXACT")
        if exact_boss:
            negset |= _exact_keywords_of(frames, exact_boss["campaign_id"])
        negset |= {t.lower() for t in seed_terms.get(sku, [])}
        if not negset:
            continue
        for slot in ("AT", "KWT-BROAD", "KWT-PHRASE"):
            boss = bosses.get(slot)
            ref = boss["campaign_id"] if boss else created.get((sku, slot))
            if not ref:
                continue
            is_temp = boss is None
            for term in sorted(negset):
                if not bulkfmt.valid_keyword(term):
                    continue
                # never negate where the term is a live enabled keyword (mixed
                # campaigns — the negative kills it)
                if not is_temp and term in live_kw.get(ref, set()):
                    continue
                if not is_temp and term in acct_camp_neg.get(ref, set()):
                    continue                  # account already has this negative
                sig = (ref, term)
                if sig in seen_neg:
                    continue
                seen_neg.add(sig)
                add("C", "negative", {"term": term, "match": "Negative Exact"},
                    sku=sku, slot=slot, campaign_id=ref)

    # ---- Phase D: pauses (generated now, gated in the UI until A-C applied) ----
    # protected_campaign_ids: never touched. protect_min_orders only guards EMPTY
    # campaigns — losers still pause even with orders (sales continue under boss,
    # that's the point of consolidation); an EMPTY campaign has nowhere for its
    # history to go, so real orders there force a manual-review flag instead.
    boss_ids = {g["boss"]["campaign_id"] for g in hero_groups}
    protect_orders = int(o["protect_min_orders"])
    for g in hero_groups:
        for l in g["losers"]:
            if l["campaign_id"] in protected:
                continue
            add("D", "pause", {"name": l["name"], "reason": "loser — consolidated into boss",
                               "orders": l["orders"], "sales": l["sales"]},
                sku=g["sku"], slot=g["slot"], campaign_id=l["campaign_id"])
    for c in classified:
        if c["kind"] != "EMPTY" or c["campaign_id"] in boss_ids or c["campaign_id"] in protected:
            continue
        if c["orders"] >= protect_orders:
            continue                              # protected — flagged, not auto-paused
        add("D", "pause", {"name": c["name"], "reason": "no enabled product ad — can't sell",
                           "orders": c["orders"], "sales": c["sales"]},
            campaign_id=c["campaign_id"])
    assert not boss_ids & {i["campaign_id"] for i in items
                           if i["phase"] == "D"}, "a boss must never be paused"
    return items


# ---- 4. day-0 benchmark --------------------------------------------------------
def benchmark(classified: list[dict], heroes: list[str],
              be_lookup: dict | None = None) -> list[dict]:
    """Per-hero baseline from single-SKU campaigns only (MULTI would blur it).
    be_lookup = catalog.be_by_sku output (normalized SKU -> break-even ACoS from
    the listing's real Transactions-ledger fees + COGS), so each hero carries
    its break-even next to its ACoS."""
    from . import catalog as cat
    out = []
    for sku in heroes:
        camps = [c for c in classified if c["kind"] == "SKU" and c["sku"] == sku]
        im = sum(c["impressions"] for c in camps)
        cl = sum(c["clicks"] for c in camps)
        sp = round(sum(c["spend"] for c in camps), 2)
        sa = round(sum(c["sales"] for c in camps), 2)
        od = sum(c["orders"] for c in camps)
        out.append({"sku": sku, "campaigns": len(camps), "impressions": im, "clicks": cl,
                    "spend": sp, "sales": sa, "orders": od,
                    "acos": round(sp / sa, 4) if sa else None,
                    "break_even_acos": (be_lookup or {}).get(cat.norm_sku(sku)),
                    "cpc": round(sp / cl, 2) if cl else None,
                    "cvr": round(od / cl, 4) if cl else None})
    return out


# ---- orchestration (db) --------------------------------------------------------
def _snapshot_bids(frames: dict) -> dict[str, dict]:
    """target_id -> {'bid','state'} from the uploaded bulk (ledger reconcile)."""
    out: dict[str, dict] = {}
    for ent, idcol in (("keyword", "keyword_id"), ("product targeting", "product_targeting_id")):
        df = _frame(frames, ent)
        if not len(df):
            continue
        for _, r in df.iterrows():
            tid = _s(r.get(idcol))
            if tid:
                out[tid] = {"bid": float(r.get("bid") or 0) or None, "state": _st(r.get("state"))}
    return out


def saved_bulk_path(db: Session) -> str:
    """On-disk copy of the plan's raw bulk (per store+base project) — kept so
    boss overrides can rebuild without a re-upload. Cleared by delete_all."""
    from .. import database as dbmod
    return os.path.join(dbmod._store_dir(db.info.get("store")),
                        f"_waterfall_bulk__{db.info.get('project')}.xlsx")


def save_bulk(db: Session, blob: bytes) -> None:
    with open(saved_bulk_path(db), "wb") as f:
        f.write(blob)


def _delete_saved_bulk(db: Session) -> None:
    p = saved_bulk_path(db)
    if os.path.exists(p):
        os.remove(p)


def build_run(db: Session, path: str, opts: dict | None = None,
              forced: dict | None = None) -> dict:
    """Parse the bulk, classify, elect bosses, build the 4 phases, persist as a
    new draft WaterfallRun (replacing nothing — history is kept). `forced` =
    {"sku|slot": campaign_id} boss overrides (from the ASIN×slot grid)."""
    frames = ingest_stage.frames(path)
    try:
        str_rows = wk.parse_str_sheet(path)
    except ValueError:
        str_rows = []                          # no embedded STR sheet -> no seeds

    o = {**DEFAULTS, **{k: v for k, v in (opts or {}).items() if v is not None}}
    classified = classify(frames)
    if not classified:
        raise ValueError("No enabled campaigns found in that bulk — is it a Sponsored "
                         "Products bulk export with campaign rows?")
    heroes = list(o.get("heroes") or default_heroes(classified, o["hero_n"]))
    groups = select_bosses(classified, float(o["goal_acos"]), forced)
    recon = ledger_stage.reconcile(db, _snapshot_bids(frames))
    effective = ledger_stage.effective_map(db)
    items = build_phases(groups, classified, frames, str_rows, effective,
                         {**o, "heroes": heroes})
    # per-hero break-even from the store catalog + real Transactions-ledger fees
    from .. import database as dbmod
    from . import catalog as cat
    sku_be = cat.be_by_sku(db.info.get("store"),
                           dbmod.get_project_econ(db.info.get("store"), db.info.get("project")))
    bench = benchmark(classified, heroes, sku_be)

    run = md.WaterfallRun(naming_template=o["naming_template"],
                          heroes_json=json.dumps(heroes),
                          params_json=json.dumps({
                              "opts": {k: o[k] for k in DEFAULTS if k != "heroes"},
                              "benchmark": bench,
                              "classified": _classified_summary(classified),
                              "boss_map": _boss_map(groups),
                              "reconcile": recon,
                              "warnings": _pause_warnings(items, classified, o),
                              "overrides": forced or {},
                          }))
    db.add(run)
    db.flush()
    for it in items:
        db.add(md.WaterfallItem(run_id=run.id, **it))
    db.commit()
    return run_state(db, run.id)


def rebuild_with_overrides(db: Session, opts: dict, forced: dict) -> dict:
    """Re-run the plan from the saved raw bulk with new boss overrides, replacing
    the latest run in place (delete it, build fresh) so overrides don't bloat the
    run history — older runs (day-0 baselines from separate uploads) are kept."""
    path = saved_bulk_path(db)
    if not path or not os.path.exists(path):
        raise ValueError("The uploaded bulk for this plan is no longer on disk — "
                         "re-upload the Sponsored Products bulk to change boss picks.")
    prev = latest_run(db)
    prev_status = prev.status if prev else "draft"
    if prev:
        db.query(md.WaterfallItem).filter(md.WaterfallItem.run_id == prev.id).delete()
        db.query(md.WaterfallRun).filter(md.WaterfallRun.id == prev.id).delete()
        db.commit()
    build_run(db, path, opts, forced)
    # carry the prior applied-phase status forward (an override shouldn't reset
    # phase progress; the user re-exports the changed phases anyway)
    run = latest_run(db)
    if run and prev_status != "draft":
        run.status = prev_status
        db.commit()
    return run_state(db, run.id if run else None)


def _classified_summary(classified: list[dict]) -> dict:
    return {
        "campaigns": len(classified),
        "single_sku": sum(1 for c in classified if c["kind"] == "SKU"),
        "multi": [{"campaign_id": c["campaign_id"], "name": c["name"], "skus": c["skus"]}
                  for c in classified if c["kind"] == "MULTI"],
        "empty": [{"campaign_id": c["campaign_id"], "name": c["name"]}
                  for c in classified if c["kind"] == "EMPTY"],
        "mixed": [{"campaign_id": c["campaign_id"], "name": c["name"], "slot": c["slot"]}
                  for c in classified if c["mixed"]],
    }


def _pause_warnings(items: list[dict], classified: list[dict], o: dict) -> dict:
    """Revenue-at-risk surfacing for the pause wave — must never be buried.
    'with_orders': every Phase D pause that still has orders (consolidation
    losers keep pausing on purpose — sales continue under the boss — but the
    user must see the sales figure). 'protected_empty': EMPTY campaigns that
    orders protected from auto-pause, needing manual review."""
    with_orders = [{"campaign_id": i["campaign_id"], "name": json.loads(i["payload_json"])["name"],
                    "orders": json.loads(i["payload_json"]).get("orders", 0),
                    "sales": json.loads(i["payload_json"]).get("sales", 0)}
                   for i in items if i["phase"] == "D" and i["action"] == "pause"
                   and json.loads(i["payload_json"]).get("orders", 0) > 0]
    protect_orders = int(o["protect_min_orders"])
    paused_ids = {i["campaign_id"] for i in items if i["phase"] == "D"}
    protected_empty = [{"campaign_id": c["campaign_id"], "name": c["name"],
                        "orders": c["orders"], "sales": c["sales"]}
                       for c in classified
                       if c["kind"] == "EMPTY" and c["campaign_id"] not in paused_ids
                       and c["orders"] >= protect_orders]
    return {"with_orders": with_orders, "protected_empty": protected_empty}


_CAND_KEYS = ("campaign_id", "name", "spend", "sales", "acos", "orders",
              "clicks", "impressions")


def _cand(c: dict, is_boss: bool) -> dict:
    return {**{k: c.get(k) for k in _CAND_KEYS}, "is_boss": is_boss}


def _boss_map(groups: list[dict]) -> list[dict]:
    """Per SKU+slot group: the elected boss + every competing candidate with its
    metrics (drives the ASIN×slot grid + the click-to-override candidate panel)."""
    return [{"sku": g["sku"], "slot": g["slot"],
             "boss_id": g["boss"]["campaign_id"], "boss_name": g["boss"]["name"],
             "boss_forced": bool(g.get("boss_forced")),
             "asin": g["boss"].get("asin"),
             "acos": g["boss"]["acos"], "sales": g["boss"]["sales"],
             "losers": len(g["losers"]),
             "loser_names": [l["name"] for l in g["losers"]],
             "candidates": [_cand(g["boss"], True)]
                           + [_cand(l, False) for l in g["losers"]]} for g in groups]


PHASE_ORDER = ["A", "B", "C", "D"]
STATUS_AFTER = {"A": "a_applied", "B": "b_applied", "C": "c_applied", "D": "done"}


def latest_run(db: Session) -> md.WaterfallRun | None:
    return db.query(md.WaterfallRun).order_by(md.WaterfallRun.id.desc()).first()


def delete_all(db: Session) -> dict:
    """Wipe every waterfall run + its items (Clear button). Own tables only —
    settings and the bid ledger are untouched."""
    items = db.query(md.WaterfallItem).delete()
    runs = db.query(md.WaterfallRun).delete()
    db.commit()
    _delete_saved_bulk(db)
    return {"runs": runs, "items": items}


# A plan on a large account runs to six figures of items. The panel can't render
# that and the JSON can't be delivered (a multi-MB response stalls the dev-server
# proxy and wedges the connection), so `run_state` ships at most this many rows per
# phase and reports the true totals in `counts`. Exports always use every row —
# `phase_items` reads them straight from the db.
PHASE_PAGE = 500


def item_dict(it) -> dict:
    """One RestructureItem/WaterfallItem row as the flat dict the UI + emitters use."""
    return {"id": it.id, "action": it.action, "sku": it.sku, "slot": it.slot,
            "campaign_id": it.campaign_id, "ad_group_id": it.ad_group_id,
            "target_id": it.target_id, "selected": bool(it.selected),
            **json.loads(it.payload_json or "{}")}


def phase_items(db: Session, model, run_id: int, phase: str,
                ids: list[int] | None = None, offset: int = 0,
                limit: int | None = None) -> list[dict]:
    """Every item of one phase, straight from the db (no run_state page cap)."""
    q = db.query(model).filter(model.run_id == run_id, model.phase == phase)
    if ids:
        q = q.filter(model.id.in_(list(ids)))
    q = q.order_by(model.id.asc()).offset(offset or 0)
    if limit:
        q = q.limit(limit)
    return [item_dict(it) for it in q.all()]


def _paged_phases(db: Session, model, run_id: int,
                  page: int = PHASE_PAGE) -> tuple[dict, dict, dict]:
    """(phases, counts, truncated) — first `page` rows per phase + true totals."""
    from sqlalchemy import func
    totals = dict(db.query(model.phase, func.count(model.id))
                    .filter(model.run_id == run_id).group_by(model.phase).all())
    phases, counts, truncated = {}, {}, {}
    for p in PHASE_ORDER:
        counts[p] = int(totals.get(p, 0))
        phases[p] = phase_items(db, model, run_id, p, limit=page)
        truncated[p] = counts[p] > len(phases[p])
    return phases, counts, truncated


def run_state(db: Session, run_id: int | None = None) -> dict:
    run = (db.query(md.WaterfallRun).get(run_id) if run_id else latest_run(db))
    if not run:
        return {"run": None}
    params = json.loads(run.params_json or "{}")
    phases, counts, truncated = _paged_phases(db, md.WaterfallItem, run.id)
    applied = _applied_set(run.status)
    return {
        "run": {"id": run.id, "status": run.status,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "naming_template": run.naming_template,
                "heroes": json.loads(run.heroes_json or "[]"),
                "applied_phases": sorted(applied)},
        "summary": params.get("classified", {}),
        "boss_map": params.get("boss_map", []),
        "benchmark": params.get("benchmark", []),
        "reconcile": params.get("reconcile", {}),
        "warnings": params.get("warnings", {"with_orders": [], "protected_empty": []}),
        "overrides": params.get("overrides", {}),
        "phases": phases,
        "counts": counts,
        "truncated": truncated,
        "page": PHASE_PAGE,
        "d_unlocked": {"A", "B", "C"} <= applied,
    }


def _applied_set(status: str) -> set[str]:
    idx = {"draft": 0, "a_applied": 1, "b_applied": 2, "c_applied": 3,
           "d_applied": 4, "done": 4}.get(status or "draft", 0)
    return set(PHASE_ORDER[:idx])


def mark_phase_applied(db: Session, run_id: int, phase: str) -> dict:
    run = db.query(md.WaterfallRun).get(run_id)
    if not run:
        raise ValueError("No waterfall run found.")
    applied = _applied_set(run.status)
    order = PHASE_ORDER.index(phase)
    if set(PHASE_ORDER[:order]) - applied:
        raise ValueError(f"Apply phases in order — {'/'.join(sorted(set(PHASE_ORDER[:order]) - applied))} "
                         f"must be applied before {phase}.")
    run.status = STATUS_AFTER[phase]
    # only phase B carries bid changes — marking A/C/D applied must not flip
    # B's still-pending ledger rows
    if phase == "B":
        ledger_stage.mark_applied(db, source="waterfall", run_id=run.id)
    db.commit()
    return run_state(db, run.id)


# ---- bulk emit -----------------------------------------------------------------
BULK_COLS = ["Product", "Entity", "Operation", "Campaign ID", "Ad Group ID",
             "Ad ID", "Keyword ID", "Product Targeting ID", "Campaign Name",
             "Ad Group Name", "Start Date", "Targeting Type", "State",
             "Daily Budget", "SKU", "Ad Group Default Bid", "Bid", "Keyword Text",
             "Match Type", "Bidding Strategy", "Product Targeting Expression"]


def _blank() -> dict:
    return {c: None for c in BULK_COLS}


def _row(**kv) -> dict:
    r = _blank()
    r.update({"Product": "Sponsored Products", **kv})
    return r


def items_to_bulk(items: list[dict]) -> bytes:
    """Selected items of ONE phase -> Amazon SP bulk .xlsx. Creates reference
    new campaigns by their rendered name as the in-file temporary ID (Amazon's
    documented bulk-create pattern); real IDs go through bulkfmt.idstr."""
    rows, seen = [], set()

    def push(sig, row):
        if sig in seen:
            return
        seen.add(sig)
        rows.append(row)

    for it in items:
        act = it["action"]
        cid = it.get("campaign_id") or ""
        cid_out = bulkfmt.idstr(cid) if cid.isdigit() else cid      # temp names stay verbatim
        agid = it.get("ad_group_id") or ""
        agid_out = bulkfmt.idstr(agid) if agid.isdigit() else agid
        if act == "rename":
            r = _row(Entity="Campaign", Operation="update",
                    **{"Campaign ID": cid_out, "Campaign Name": it.get("new_name"),
                       "Daily Budget": it.get("budget"), "State": "enabled"})
            if it.get("strategy"):
                r["Bidding Strategy"] = it["strategy"]
            push(("camp_u", cid), r)
        elif act == "rename_adgroup":
            push(("ag_u", agid), _row(Entity="Ad Group", Operation="update",
                 **{"Campaign ID": cid_out, "Ad Group ID": agid_out,
                    "Ad Group Name": it.get("new_name"), "State": "enabled"}))
        elif act == "bid_cut":
            tid = bulkfmt.idstr(it.get("target_id"))
            is_kw = it.get("kind") == "keyword"
            r = _row(Entity="Keyword" if is_kw else "Product Targeting", Operation="update",
                     **{"Campaign ID": cid_out, "Ad Group ID": agid_out,
                        "Bid": it.get("new_bid"), "State": "enabled"})
            r["Keyword ID" if is_kw else "Product Targeting ID"] = tid
            push(("t_u", tid), r)
        elif act == "create_campaign":
            push(("camp_c", cid), _row(Entity="Campaign", Operation="create",
                 **{"Campaign ID": cid_out, "Campaign Name": it.get("name"),
                    "Start Date": it.get("start_date"),
                    "Targeting Type": it.get("targeting_type"),
                    "State": it.get("state", "paused"),
                    "Daily Budget": it.get("budget"),
                    "Bidding Strategy": it.get("strategy")}))
        elif act == "create_adgroup":
            push(("ag_c", cid, agid), _row(Entity="Ad Group", Operation="create",
                 **{"Campaign ID": cid_out, "Ad Group ID": agid_out,
                    "Ad Group Name": it.get("name"), "State": "enabled",
                    "Ad Group Default Bid": it.get("default_bid", 1.0)}))
        elif act == "create_ad":
            push(("ad_c", cid, agid, it.get("sku")), _row(Entity="Product Ad", Operation="create",
                 **{"Campaign ID": cid_out, "Ad Group ID": agid_out,
                    "SKU": it.get("sku"), "State": "enabled"}))
        elif act == "create_keyword":
            txt = str(it.get("text") or "").strip()
            if not bulkfmt.valid_keyword(txt):
                continue
            push(("kw_c", cid, agid, txt.lower(), str(it.get("match", "")).lower()),
                 _row(Entity="Keyword", Operation="create",
                      **{"Campaign ID": cid_out, "Ad Group ID": agid_out,
                         "Keyword Text": txt, "Match Type": it.get("match", "Exact"),
                         "Bid": it.get("bid"), "State": "enabled"}))
        elif act == "create_pt":
            push(("pt_c", cid, agid, str(it.get("expression", "")).lower()),
                 _row(Entity="Product Targeting", Operation="create",
                      **{"Campaign ID": cid_out, "Ad Group ID": agid_out,
                         "Product Targeting Expression": it.get("expression"),
                         "Bid": it.get("bid"), "State": "enabled"}))
        elif act == "negative":
            term = str(it.get("term") or "").strip()
            if bulkfmt.is_asin(term):
                continue                       # ASIN terms are never negative keywords
            if not bulkfmt.valid_keyword(term):
                continue
            # campaign-wide negation MUST be Campaign Negative Keyword (a plain
            # Negative Keyword without Ad Group ID errors "Missing Parent ID")
            push(("cneg", cid, term.lower()),
                 _row(Entity="Campaign Negative Keyword", Operation="create",
                      **{"Campaign ID": cid_out, "Keyword Text": term,
                         "Match Type": it.get("match", "Negative Exact"), "State": "enabled"}))
        elif act == "pause":
            push(("camp_u", cid), _row(Entity="Campaign", Operation="update",
                 **{"Campaign ID": cid_out, "Campaign Name": it.get("name"),
                    "State": "paused"}))

    df = pd.DataFrame(rows, columns=BULK_COLS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Sponsored Products Campaigns")
    return buf.getvalue()


def ledger_entries(items: list[dict]) -> list[dict]:
    """BidLedger entries for a phase's exported items (bid/state changes only)."""
    out = []
    for it in items:
        if it["action"] == "bid_cut" and it.get("target_id"):
            out.append({"target_id": it["target_id"], "campaign_id": it.get("campaign_id"),
                        "bid": it.get("new_bid"), "state": "enabled"})
    return out


def changelog_entries(items: list[dict], phase: str) -> list[dict]:
    out = []
    for it in items:
        act = it["action"]
        if act == "rename":
            out.append(dict(campaign_id=it.get("campaign_id"), entity_type="campaign",
                            label=it.get("old_name"), field="name",
                            old_value=it.get("old_name"), new_value=it.get("new_name"),
                            action="rename", reason=f"waterfall phase {phase} — boss rename"))
        elif act == "bid_cut":
            out.append(dict(campaign_id=it.get("campaign_id"), entity_type=it.get("kind"),
                            entity_id=it.get("target_id"), label=it.get("label"), field="bid",
                            old_value=str(it.get("old_bid")), new_value=str(it.get("new_bid")),
                            action="lower", reason=f"waterfall phase {phase} — loser wind-down"))
        elif act == "create_campaign":
            out.append(dict(entity_type="campaign", label=it.get("name"), field="create",
                            new_value="paused", action="promote",
                            reason=f"waterfall phase {phase} — missing {it.get('slot')} slot"))
        elif act == "create_keyword":
            out.append(dict(campaign_id=it.get("campaign_id"), entity_type="keyword",
                            label=it.get("text"), field="create",
                            new_value=str(it.get("match", "")).lower(), action="promote",
                            reason=f"waterfall phase {phase} — seed"))
        elif act == "negative":
            out.append(dict(campaign_id=it.get("campaign_id"), entity_type="negative",
                            label=it.get("term"), field="create", new_value="negative exact",
                            action="negate", reason=f"waterfall phase {phase} — sculpting"))
        elif act == "pause":
            out.append(dict(campaign_id=it.get("campaign_id"), entity_type="campaign",
                            label=it.get("name"), field="state", old_value="enabled",
                            new_value="paused", action="pause",
                            reason=f"waterfall phase {phase} — {it.get('reason')}"))
    return out


def benchmark_compare(db: Session) -> dict:
    """Day-0 vs latest: earliest run's hero benchmark against the newest run's
    (upload a fresh bulk at day 21 to create the comparison point)."""
    runs = db.query(md.WaterfallRun).order_by(md.WaterfallRun.id.asc()).all()
    if not runs:
        return {"day0": [], "current": [], "rows": []}
    day0 = json.loads(runs[0].params_json or "{}").get("benchmark", [])
    cur = json.loads(runs[-1].params_json or "{}").get("benchmark", [])
    cur_by = {r["sku"]: r for r in cur}
    rows = []
    for b in day0:
        c = cur_by.get(b["sku"])
        row = {"sku": b["sku"], "day0": b, "current": c}
        if c:
            row["delta"] = {k: (round(c[k] - b[k], 4) if c.get(k) is not None
                                and b.get(k) is not None else None)
                            for k in ("spend", "sales", "orders", "acos", "cpc", "cvr")}
        rows.append(row)
    return {"day0_run": runs[0].id, "current_run": runs[-1].id,
            "same_run": runs[0].id == runs[-1].id, "rows": rows}


def benchmark_xlsx(db: Session) -> bytes:
    run = latest_run(db)
    bench = json.loads(run.params_json or "{}").get("benchmark", []) if run else []
    df = pd.DataFrame(bench)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Waterfall Benchmark")
    return buf.getvalue()
