"""Waterfall Restructure Engine tests — classifier, boss selection, phase builder,
safe_bid_cut (field-bug regressions), ledger overlay, and bulk-file validity.
Run: pytest -q
"""
import json
import io
import pandas as pd
import pytest
from app import metrics as M
from app.pipeline import waterfall as wf


# ---- safe_bid_cut: live field bugs, encoded ---------------------------------
def test_safe_bid_cut_updown_never_raises_regression_1():
    # up/down inflates CPC ~2x bid; cpc-based formula would give 1.95*(24/34)=1.38 (a RAISE)
    new = M.safe_bid_cut(0.86, 1.95, 34, 24, "Dynamic bids - up and down")
    assert new == pytest.approx(0.61, abs=0.01)
    assert new < 0.86


def test_safe_bid_cut_updown_never_raises_regression_2():
    new = M.safe_bid_cut(2.16, 3.30, 36.4, 24, "Dynamic bids - up and down")
    assert new == pytest.approx(1.42, abs=0.015)
    assert new < 2.16


def test_safe_bid_cut_down_only_uses_cpc_lever():
    # down-only: cpc is the correct lever (cpc*ratio), still never above the bid
    assert M.safe_bid_cut(1.00, 0.50, 50, 25, "Dynamic bids - down only") == 0.25


def test_safe_bid_cut_no_cut_needed_or_possible():
    assert M.safe_bid_cut(1.00, 0.9, 20, 25, None) is None        # under goal
    assert M.safe_bid_cut(1.00, 0.9, None, 25, None) is None      # no ACoS signal
    assert M.safe_bid_cut(0.15, 0.9, 80, 25, None) is None        # already at floor
    assert M.safe_bid_cut(None, 0.9, 80, 25, None) is None


def test_safe_bid_cut_never_raise_property():
    for bid in (0.2, 0.5, 0.86, 1.4, 2.16, 4.9):
        for cpc in (0.1, 0.5, 1.0, 2.0, 3.3, 8.0):
            for acos in (26, 34, 50, 80, 120, 300):
                for strat in ("Dynamic bids - up and down", "Dynamic bids - down only",
                              "Fixed bid", None):
                    new = M.safe_bid_cut(bid, cpc, acos, 25, strat)
                    assert new is None or new < bid


# ---- fixtures ----------------------------------------------------------------
BIG_ID = "5585544115802929"       # 16 digits — float64 would mangle it


def _frames():
    camp = pd.DataFrame([
        # misnamed campaign: called "PT" but Targeting Type=Auto -> must classify AT
        dict(campaign_id="101", campaign_name="ZV PT something", targeting_type="Auto",
             state="enabled", daily_budget=25.0, **{"bidding strategy": "Dynamic bids - up and down"},
             impressions=1000, clicks=50, spend=40.0, sales=100.0, orders=5),
        # exact contest: A big seller but bleeding, B smaller but profitable
        dict(campaign_id="201", campaign_name="hero exact A", targeting_type="Manual",
             state="enabled", daily_budget=70.0, **{"bidding strategy": "Dynamic bids - up and down"},
             impressions=9000, clicks=400, spend=632.0, sales=569.0, orders=40),   # 111% ACoS
        dict(campaign_id="202", campaign_name="hero exact B", targeting_type="Manual",
             state="enabled", daily_budget=10.0, **{"bidding strategy": "Dynamic bids - down only"},
             impressions=2000, clicks=60, spend=6.35, sales=50.0, orders=6),       # 12.7% ACoS
        # mixed match types in one campaign
        dict(campaign_id="301", campaign_name="hero mixed", targeting_type="Manual",
             state="enabled", daily_budget=10.0, **{"bidding strategy": "Fixed bid"},
             impressions=500, clicks=10, spend=5.0, sales=0.0, orders=0),
        # multi-SKU campaign
        dict(campaign_id="401", campaign_name="multi", targeting_type="Manual",
             state="enabled", daily_budget=10.0, **{"bidding strategy": ""},
             impressions=100, clicks=2, spend=1.0, sales=0.0, orders=0),
        # empty campaign (no product ad)
        dict(campaign_id="501", campaign_name="empty", targeting_type="Manual",
             state="enabled", daily_budget=10.0, **{"bidding strategy": ""},
             impressions=0, clicks=0, spend=0.0, sales=0.0, orders=0),
        # paused campaign — ignored
        dict(campaign_id="601", campaign_name="off", targeting_type="Manual",
             state="paused", daily_budget=10.0, **{"bidding strategy": ""},
             impressions=0, clicks=0, spend=0.0, sales=0.0, orders=0),
    ])
    ads = pd.DataFrame([
        dict(campaign_id="101", sku="HERO-1", asin="B000LI9SI6", state="enabled"),
        dict(campaign_id="201", sku="HERO-1", asin="B000LI9SI6", state="enabled"),
        dict(campaign_id="202", sku="HERO-1", asin="B000LI9SI6", state="enabled"),
        dict(campaign_id="301", sku="HERO-1", asin="B000LI9SI6", state="enabled"),
        dict(campaign_id="401", sku="HERO-1", asin="B000LI9SI6", state="enabled"),
        dict(campaign_id="401", sku="OTHER-2", asin="B0AAAAAAA1", state="enabled"),
    ])
    kws = pd.DataFrame([
        dict(campaign_id="201", ad_group_id="ag201", keyword_id=BIG_ID, keyword_text="ice pack",
             match_type="Exact", bid=0.86, state="enabled"),
        dict(campaign_id="202", ad_group_id="ag202", keyword_id="777", keyword_text="shoulder wrap",
             match_type="Exact", bid=0.50, state="enabled"),
        dict(campaign_id="301", ad_group_id="ag301", keyword_id="888", keyword_text="knee brace",
             match_type="Broad", bid=0.40, state="enabled"),
        dict(campaign_id="301", ad_group_id="ag301", keyword_id="889", keyword_text="ice pack",
             match_type="Exact", bid=0.45, state="enabled"),
    ])
    pts = pd.DataFrame([
        dict(campaign_id="401", ad_group_id="ag401", product_targeting_id="991",
             expression='asin="B01IKS0ANK"', bid=0.75, state="enabled"),
    ])
    ags = pd.DataFrame([
        dict(campaign_id="101", ad_group_id="ag101", ad_group_name="old at ag", state="enabled"),
        dict(campaign_id="201", ad_group_id="ag201", ad_group_name="old ag a", state="enabled"),
        dict(campaign_id="202", ad_group_id="ag202", ad_group_name="old ag b", state="enabled"),
        dict(campaign_id="301", ad_group_id="ag301", ad_group_name="old ag m", state="enabled"),
        dict(campaign_id="401", ad_group_id="ag401", ad_group_name="old ag x", state="enabled"),
    ])
    return {"campaign": camp, "product ad": ads, "keyword": kws,
            "product targeting": pts, "ad group": ags}


def _opts(**kw):
    return {**wf.DEFAULTS, "goal_acos": 0.25, "heroes": ["HERO-1"], **kw}


# ---- classifier ----------------------------------------------------------------
def test_classify_auto_type_beats_name():
    c = {x["campaign_id"]: x for x in wf.classify(_frames())}
    assert c["101"]["slot"] == "AT"           # named "PT", but Auto type wins
    assert c["201"]["slot"] == "KWT-EXACT"
    assert c["301"]["mixed"] is True          # broad + exact in one campaign
    assert c["401"]["kind"] == "MULTI"
    assert c["501"]["kind"] == "EMPTY"
    assert "601" not in c                     # paused campaigns are skipped


# ---- boss selection --------------------------------------------------------------
def test_boss_profitable_first_regression():
    # {A: sales 569, acos 111%} vs {B: sales 50, acos 12.7%} -> boss MUST be B
    classified = wf.classify(_frames())
    groups = wf.select_bosses(classified, 0.25)
    g = next(x for x in groups if x["slot"] == "KWT-EXACT" and x["sku"] == "HERO-1")
    assert g["boss"]["campaign_id"] == "202"
    assert {l["campaign_id"] for l in g["losers"]} == {"201"}


def test_boss_all_zero_sales_falls_back_to_impressions():
    cands = [dict(campaign_id="1", sales=0.0, acos=None, impressions=10),
             dict(campaign_id="2", sales=0.0, acos=None, impressions=99)]
    assert wf.pick_boss(cands, 0.25)["campaign_id"] == "2"


# ---- phases ---------------------------------------------------------------------
def _build(str_rows=None, effective=None, **opt_kw):
    frames = _frames()
    classified = wf.classify(frames)
    groups = wf.select_bosses(classified, 0.25)
    return wf.build_phases(groups, classified, frames, str_rows or [],
                           effective or {}, _opts(**opt_kw))


def test_phase_b_reads_ledger_not_snapshot():
    # loser 201's keyword snapshot bid = 0.86, but a prior export set it to 0.50
    items = _build(effective={BIG_ID: {"bid": 0.50, "state": "enabled"}})
    cut = next(i for i in items if i["phase"] == "B" and i["target_id"] == BIG_ID)
    p = json.loads(cut["payload_json"])
    assert p["old_bid"] == 0.50                       # effective, NOT 0.86
    assert p["new_bid"] == max(round(0.50 * 0.6, 2), 0.15)


def test_phase_b_skips_ledger_paused_targets():
    items = _build(effective={BIG_ID: {"bid": 0.50, "state": "paused"}})
    assert not any(i for i in items if i["phase"] == "B" and i["target_id"] == BIG_ID)


def test_phase_c_sculpting_skips_live_keywords():
    # "ice pack" is boss-exact ("202"? no — boss exact kw lives in 202: "shoulder wrap");
    # seed "ice pack" via STR, then check the mixed campaign 301 (where "ice pack" is a
    # LIVE enabled keyword) never receives that negative.
    str_rows = [dict(campaign_id="202", search_term="ice pack", clicks=10, spend=2.0,
                     sales=40.0, orders=2)]
    items = _build(str_rows=str_rows)
    negs = [i for i in items if i["phase"] == "C" and i["action"] == "negative"]
    assert negs, "sculpting negatives expected"
    for n in negs:
        p = json.loads(n["payload_json"])
        if n["campaign_id"] == "301":                 # 301 has live "ice pack" keyword
            assert p["term"] != "ice pack"


def test_phase_c_seeds_exclude_asin_terms_and_clip_bid():
    str_rows = [
        dict(campaign_id="202", search_term="b01iks0ank", clicks=5, spend=5.0, sales=60.0, orders=2),
        dict(campaign_id="202", search_term="cold wrap", clicks=10, spend=30.0, sales=200.0, orders=3),
    ]
    items = _build(str_rows=str_rows)
    seeds = [json.loads(i["payload_json"]) for i in items
             if i["phase"] == "C" and i["action"] == "create_keyword"]
    texts = {s["text"] for s in seeds}
    assert "b01iks0ank" not in texts                  # ASIN-shaped -> never a keyword
    exact = next(s for s in seeds if s["text"] == "cold wrap" and s["match"] == "Exact")
    assert exact["bid"] == pytest.approx(2.00)        # 30/10*1.1=3.3 -> clipped to 2.00


def test_phase_c_new_campaigns_born_paused_down_only():
    # drop the AT boss (101) so the AT slot must be created with its 4 split targets
    frames = _frames()
    frames["campaign"] = frames["campaign"][frames["campaign"].campaign_id != "101"]
    classified = wf.classify(frames)
    groups = wf.select_bosses(classified, 0.25)
    items = wf.build_phases(groups, classified, frames, [], {}, _opts())
    creates = [json.loads(i["payload_json"]) for i in items if i["action"] == "create_campaign"]
    assert creates, "missing slots must be created"
    for c in creates:
        assert c["state"] == "paused"
        assert c["strategy"] == "Dynamic bids - down only"
    at = [i for i in items if i["action"] == "create_pt" and i["slot"] == "AT"]
    assert {json.loads(i["payload_json"])["expression"] for i in at} == \
           {"close-match", "loose-match", "substitutes", "complements"}
    # existing-slot bosses are NOT re-created
    created_slots = {i["slot"] for i in items if i["action"] == "create_campaign"}
    assert "KWT-EXACT" not in created_slots


def test_phase_d_pauses_losers_never_bosses():
    items = _build()
    d_ids = {i["campaign_id"] for i in items if i["phase"] == "D"}
    assert "201" in d_ids                             # loser
    assert "501" in d_ids                             # empty
    assert "202" not in d_ids and "101" not in d_ids  # bosses stay


# ---- new knobs: naming/strategy/protection --------------------------------------
def test_strategy_suffix():
    assert wf.strategy_suffix("Dynamic bids - up and down") == "up/down"
    assert wf.strategy_suffix("Dynamic bids - down only") == "down"
    assert wf.strategy_suffix("Fixed bid") == "down"
    assert wf.strategy_suffix(None) == "down"


def test_render_name_new_placeholders():
    name = wf.render_name("SP - {asin} - {sku} - {n} - {slot} - {strategy} ${bid}",
                          "3pk2", "B01M00ZHJJ", "KWT-EXACT", bid=0.75, strategy="up/down")
    assert name == "SP - B01M00ZHJJ - 3pk2 - 4 - KWT - EXACT - up/down $0.75"


def test_phase_a_force_down_only_flips_strategy_and_name():
    # 201 is a loser here (boss stays 202, which is already down-only) — force
    # AT boss 101 instead, which IS up/down, to exercise the flip
    items = _build(force_down_only=True)
    at_rename = next(i for i in items if i["phase"] == "A" and i["campaign_id"] == "101")
    p = json.loads(at_rename["payload_json"])
    assert p["strategy"] == "Dynamic bids - down only"


def test_phase_a_no_flip_when_disabled():
    items = _build(force_down_only=False)
    at_rename = next(i for i in items if i["phase"] == "A" and i["campaign_id"] == "101")
    assert "strategy" not in json.loads(at_rename["payload_json"])


def test_protected_campaign_ids_skip_bid_cut_and_pause():
    items = _build(protected_campaign_ids=["201"])
    assert not any(i for i in items if i["phase"] == "B" and i["campaign_id"] == "201")
    assert not any(i for i in items if i["phase"] == "D" and i["campaign_id"] == "201")


def test_protect_min_orders_guards_empty_campaign_from_autopause():
    frames = _frames()
    frames["campaign"].loc[frames["campaign"].campaign_id == "501", "orders"] = 5
    classified = wf.classify(frames)
    groups = wf.select_bosses(classified, 0.25)
    items = wf.build_phases(groups, classified, frames, [], {}, _opts(protect_min_orders=1))
    assert not any(i for i in items if i["phase"] == "D" and i["campaign_id"] == "501")
    warn = wf._pause_warnings(items, classified, _opts(protect_min_orders=1))
    assert any(w["campaign_id"] == "501" for w in warn["protected_empty"])


def test_pause_warnings_surfaces_orders_on_loser_pause():
    items = _build()
    warn = wf._pause_warnings(items, wf.classify(_frames()), _opts())
    row = next(w for w in warn["with_orders"] if w["campaign_id"] == "201")
    assert row["orders"] == 40 and row["sales"] == pytest.approx(569.0)


def test_seed_bid_respects_configured_floor_and_ceiling():
    assert wf._seed_bid(0.0, 0.0, floor=0.5, ceiling=1.0) == 0.5
    assert wf._seed_bid(100.0, 1.0, floor=0.5, ceiling=1.0) == 1.0


# ---- boss override (ASIN×slot grid) ---------------------------------------------
def test_select_bosses_forced_override_wins():
    classified = wf.classify(_frames())
    # default boss for HERO-1 KWT-EXACT is 202 (profitable); force 201 instead
    groups = wf.select_bosses(classified, 0.25, forced={"HERO-1|KWT-EXACT": "201"})
    g = next(x for x in groups if x["slot"] == "KWT-EXACT" and x["sku"] == "HERO-1")
    assert g["boss"]["campaign_id"] == "201"
    assert g["boss_forced"] is True
    assert {l["campaign_id"] for l in g["losers"]} == {"202"}


def test_select_bosses_forced_ignored_when_not_a_candidate():
    classified = wf.classify(_frames())
    groups = wf.select_bosses(classified, 0.25, forced={"HERO-1|KWT-EXACT": "999"})
    g = next(x for x in groups if x["slot"] == "KWT-EXACT" and x["sku"] == "HERO-1")
    assert g["boss"]["campaign_id"] == "202"      # falls back to auto-pick
    assert g["boss_forced"] is False


def _build_with_at_created(**opt_kw):
    # drop AT boss so the AT slot is created (exercises slot bids + strategy)
    frames = _frames()
    frames["campaign"] = frames["campaign"][frames["campaign"].campaign_id != "101"]
    classified = wf.classify(frames)
    groups = wf.select_bosses(classified, 0.25)
    return wf.build_phases(groups, classified, frames, [], {}, _opts(**opt_kw))


def test_new_strategy_setting_drives_created_campaigns():
    items = _build_with_at_created(new_strategy="up_down")
    creates = [json.loads(i["payload_json"]) for i in items if i["action"] == "create_campaign"]
    assert creates
    for c in creates:
        assert c["strategy"] == "Dynamic bids - up and down"


def test_default_new_strategy_is_down_only():
    items = _build_with_at_created()
    creates = [json.loads(i["payload_json"]) for i in items if i["action"] == "create_campaign"]
    assert all(c["strategy"] == "Dynamic bids - down only" for c in creates)


def test_slot_bids_setting_drives_created_adgroup_and_at_splits():
    # KWT-EXACT has boss 202 (not created); KWT-PHRASE has no boss -> created
    items = _build_with_at_created(slot_bids={"AT": 0.40, "KWT-PHRASE": 0.65})
    ags = {i["slot"]: json.loads(i["payload_json"]) for i in items if i["action"] == "create_adgroup"}
    assert ags["AT"]["default_bid"] == 0.40
    assert ags["KWT-PHRASE"]["default_bid"] == 0.65
    # AT split targets scale off the AT slot bid (0.40 × 3.33 = 1.33 for close-match)
    at = {json.loads(i["payload_json"])["expression"]: json.loads(i["payload_json"])["bid"]
          for i in items if i["action"] == "create_pt" and i["slot"] == "AT"}
    assert at["close-match"] == round(0.40 * 3.33, 2)
    assert at["complements"] == round(0.40 * 1.67, 2)


def test_at_split_defaults_match_legacy_bids():
    # default AT slot bid 0.30 must reproduce the old hardcoded split bids
    items = _build_with_at_created()
    at = {json.loads(i["payload_json"])["expression"]: json.loads(i["payload_json"])["bid"]
          for i in items if i["action"] == "create_pt" and i["slot"] == "AT"}
    assert at == {"close-match": 1.00, "loose-match": 0.75, "substitutes": 0.75, "complements": 0.50}


def test_created_campaign_name_carries_bid_and_strategy_placeholders():
    items = _build_with_at_created(
        naming_template="SP - {sku} - {slot} - {strategy} ${bid}",
        new_strategy="up_down", slot_bids={"KWT-PHRASE": 0.65})
    ex = next(json.loads(i["payload_json"]) for i in items
              if i["action"] == "create_campaign" and i["slot"] == "KWT-PHRASE")
    assert ex["name"] == "SP - HERO-1 - KWT - PHRASE - up/down $0.65"


def test_boss_map_carries_candidate_metrics():
    classified = wf.classify(_frames())
    groups = wf.select_bosses(classified, 0.25)
    bm = wf._boss_map(groups)
    g = next(r for r in bm if r["slot"] == "KWT-EXACT" and r["sku"] == "HERO-1")
    ids = {c["campaign_id"]: c for c in g["candidates"]}
    assert ids["202"]["is_boss"] is True and ids["201"]["is_boss"] is False
    assert ids["201"]["sales"] == pytest.approx(569.0)   # loser metrics present
    assert ids["202"]["acos"] is not None


# ---- bulk emit -------------------------------------------------------------------
def _bulk_df(items):
    data = wf.items_to_bulk(items)
    return pd.read_excel(io.BytesIO(data), sheet_name="Sponsored Products Campaigns", dtype=str)


def test_bulk_ids_stay_exact_strings():
    items = [dict(id=1, action="bid_cut", kind="keyword", campaign_id="201",
                  ad_group_id="ag201", target_id=BIG_ID, new_bid=0.52, old_bid=0.86)]
    df = _bulk_df(items)
    assert df.loc[0, "Keyword ID"] == BIG_ID          # 16 digits, no sci-notation/.0


def test_bulk_campaign_negative_has_no_adgroup_parent():
    items = [dict(id=1, action="negative", campaign_id="201", term="ice pack",
                  match="Negative Exact")]
    df = _bulk_df(items)
    assert df.loc[0, "Entity"] == "Campaign Negative Keyword"
    assert pd.isna(df.loc[0, "Ad Group ID"])          # campaign-wide: NO ad-group parent
    assert df.loc[0, "Match Type"] == "Negative Exact"


def test_bulk_dedups_repeated_rows():
    items = [dict(id=1, action="pause", campaign_id="201", name="x"),
             dict(id=2, action="pause", campaign_id="201", name="x")]
    assert len(_bulk_df(items)) == 1


def test_e2e_phase_files_validate():
    str_rows = [dict(campaign_id="202", search_term="cold wrap", clicks=10, spend=3.0,
                     sales=60.0, orders=2)]
    items = _build(str_rows=str_rows)
    for phase in "ABCD":
        sub = [dict(json.loads(i["payload_json"]), **{k: i[k] for k in
                    ("action", "campaign_id", "ad_group_id", "target_id", "sku", "slot")})
               for i in items if i["phase"] == phase]
        if not sub:
            continue
        df = _bulk_df(sub)
        assert len(df) > 0
        # no duplicate update/create signatures
        sig = df[["Entity", "Operation", "Campaign ID", "Ad Group ID", "Keyword ID",
                  "Product Targeting ID", "Keyword Text", "Product Targeting Expression"]] \
            .fillna("").agg("|".join, axis=1)
        assert sig.is_unique
        # negative keywords are campaign-level (no missing-parent errors)
        neg = df[df["Entity"] == "Negative Keyword"]
        assert neg.empty or neg["Ad Group ID"].notna().all()


# ---- benchmark --------------------------------------------------------------------
def test_benchmark_single_sku_campaigns_only():
    classified = wf.classify(_frames())
    rows = wf.benchmark(classified, ["HERO-1"])
    b = rows[0]
    # 101 + 201 + 202 + 301 (single-SKU) but NOT 401 (multi)
    assert b["campaigns"] == 4
    assert b["spend"] == pytest.approx(40.0 + 632.0 + 6.35 + 5.0)
