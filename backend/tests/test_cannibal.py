"""Cannibalization / Keyword Ownership Detector tests. Run: pytest -q"""
import io
import pandas as pd
from app.pipeline import cannibal as cn


# ---- resolve_owner (pure) ------------------------------------------------------
def C(sku, cid, clicks, orders, spend, sales):
    return dict(sku=sku, campaign_id=cid, clicks=clicks, orders=orders, spend=spend, sales=sales)


def test_resolve_owner_max_cvr_wins():
    a = C("A", "1", clicks=100, orders=5, spend=50, sales=100)    # CVR 5%
    b = C("B", "2", clicks=100, orders=12, spend=80, sales=300)   # CVR 12%
    assert cn.resolve_owner([a, b])["campaign_id"] == "2"


def test_resolve_owner_tiebreak_min_acos():
    a = C("A", "1", clicks=100, orders=10, spend=90, sales=100)   # CVR 10%, ACoS 90%
    b = C("B", "2", clicks=100, orders=10, spend=20, sales=100)   # CVR 10%, ACoS 20%
    assert cn.resolve_owner([a, b])["campaign_id"] == "2"


def test_resolve_owner_one_qualified():
    a = C("A", "1", clicks=3, orders=1, spend=5, sales=20)        # under min_clicks
    b = C("B", "2", clicks=15, orders=1, spend=5, sales=20)
    assert cn.resolve_owner([a, b])["campaign_id"] == "2"


def test_resolve_owner_insufficient_data():
    a = C("A", "1", clicks=3, orders=0, spend=1, sales=0)
    b = C("B", "2", clicks=4, orders=0, spend=2, sales=0)
    assert cn.resolve_owner([a, b]) is None


# ---- detection fixtures ----------------------------------------------------------
def _frames():
    camp = pd.DataFrame([
        dict(campaign_id="10", campaign_name="A exact", targeting_type="Manual", state="enabled",
             impressions=100, clicks=10, spend=10.0, sales=50.0, orders=2),
        dict(campaign_id="20", campaign_name="B exact", targeting_type="Manual", state="enabled",
             impressions=100, clicks=10, spend=10.0, sales=50.0, orders=2),
        dict(campaign_id="30", campaign_name="A broad", targeting_type="Manual", state="enabled",
             impressions=100, clicks=10, spend=10.0, sales=50.0, orders=2),
    ])
    ads = pd.DataFrame([
        dict(campaign_id="10", sku="SKU-A", asin="B000000001", state="enabled"),
        dict(campaign_id="20", sku="SKU-B", asin="B000000002", state="enabled"),
        dict(campaign_id="30", sku="SKU-A", asin="B000000001", state="enabled"),
    ])
    kws = pd.DataFrame([
        # duplicate exact "ice pack" in campaigns 10 + 20 (different SKUs)
        dict(campaign_id="10", ad_group_id="ag10", keyword_id="k1", keyword_text="ice pack",
             match_type="Exact", bid=1.0, state="enabled",
             clicks=50, orders=8, spend=40.0, sales=200.0),     # CVR 16%
        dict(campaign_id="20", ad_group_id="ag20", keyword_id="k2", keyword_text="ice pack",
             match_type="Exact", bid=1.0, state="enabled",
             clicks=60, orders=2, spend=55.0, sales=60.0),      # CVR 3.3%, converting!
        # broad copy in 30 (same text, different match — no Type 1 group)
        dict(campaign_id="30", ad_group_id="ag30", keyword_id="k3", keyword_text="ice pack",
             match_type="Broad", bid=0.6, state="enabled",
             clicks=10, orders=0, spend=6.0, sales=0.0),
    ])
    return {"campaign": camp, "product ad": ads, "keyword": kws,
            "product targeting": pd.DataFrame(), "ad group": pd.DataFrame()}


def test_type1_duplicate_detected_owner_by_cvr():
    fs = cn.detect(_frames(), [], goal_acos=0.25)
    dup = [f for f in fs if f["kind"] == "duplicate_target"]
    assert len(dup) == 1
    f = dup[0]
    assert f["verdict"] == "resolve"
    assert f["owner_campaign_id"] == "10"      # 16% CVR beats 3.3%
    pauses = [a for a in f["actions"] if a["type"] == "pause_keyword"]
    assert [p["keyword_id"] for p in pauses] == ["k2"]


def test_type1_converter_guard_blocks_negative():
    # loser k2 converts (orders=2) in campaign 20 -> pause yes, negative NO
    fs = cn.detect(_frames(), [], goal_acos=0.25)
    f = [x for x in fs if x["kind"] == "duplicate_target"][0]
    negs = [a for a in f["actions"] if a["type"] == "campaign_negative"]
    assert negs == []


def test_type1_negative_when_loser_never_converted():
    frames = _frames()
    frames["keyword"].loc[frames["keyword"].keyword_id == "k2",
                          ["orders", "sales"]] = [0, 0.0]
    fs = cn.detect(frames, [], goal_acos=0.25)
    f = [x for x in fs if x["kind"] == "duplicate_target"][0]
    negs = [a for a in f["actions"] if a["type"] == "campaign_negative"]
    assert [n["campaign_id"] for n in negs] == ["20"]


def test_coexist_when_all_profitable_with_volume():
    frames = _frames()
    kw = frames["keyword"]
    kw.loc[kw.keyword_id == "k2", ["orders", "spend", "sales", "clicks"]] = [10, 12.0, 300.0, 60]
    kw.loc[kw.keyword_id == "k1", ["orders", "spend", "sales", "clicks"]] = [8, 10.0, 200.0, 50]
    fs = cn.detect(frames, [], goal_acos=0.25)
    f = [x for x in fs if x["kind"] == "duplicate_target"][0]
    assert f["verdict"] == "coexist"
    assert f["actions"] == []


def test_type2_cross_product_owner_and_negatives():
    str_rows = [
        # "cold wrap" sells for SKU-A (exact camp 10) AND SKU-B (camp 20)
        dict(campaign_id="10", search_term="cold wrap", clicks=40, orders=8, spend=20.0, sales=160.0),
        dict(campaign_id="20", search_term="cold wrap", clicks=30, orders=1, spend=25.0, sales=20.0),
        # ...and shows in SKU-B's upstream? camp 20 slot is KWT-EXACT (money tier) — no negation there
    ]
    fs = cn.detect(_frames(), str_rows, goal_acos=0.25)
    cross = [f for f in fs if f["kind"] == "cross_product"]
    assert len(cross) == 1
    f = cross[0]
    assert f["verdict"] == "resolve"
    assert f["owner_sku"] == "SKU-A"           # CVR 20% vs 3.3%
    # loser campaign 20 is an EXACT (money-tier) campaign -> never auto-negated there
    assert f["actions"] == []


def test_type2_negates_loser_upstream_but_not_converting_campaign():
    str_rows = [
        dict(campaign_id="10", search_term="cold wrap", clicks=40, orders=8, spend=20.0, sales=160.0),
        # SKU-A's broad campaign 30 also catches the term — same SKU, ignore in cross set
        # SKU-B gets traffic via ITS broad campaign (make 20 broad by using camp 20 with 0 orders)
        dict(campaign_id="20", search_term="cold wrap", clicks=30, orders=0, spend=25.0, sales=0.0),
    ]
    frames = _frames()
    # make campaign 20 a BROAD campaign of SKU-B so it's an upstream negation target
    frames["keyword"].loc[frames["keyword"].campaign_id == "20", "match_type"] = "Broad"
    frames["keyword"].loc[frames["keyword"].campaign_id == "20", "keyword_text"] = "other kw"
    fs = cn.detect(frames, str_rows, goal_acos=0.25)
    f = [x for x in fs if x["kind"] == "cross_product"][0]
    assert f["owner_sku"] == "SKU-A"
    negs = [a for a in f["actions"] if a["type"] == "campaign_negative"]
    assert [n["campaign_id"] for n in negs] == ["20"]


def test_tier_pair_same_sku_emits_missing_sculpting_negative_only():
    # "ice pack" is a live EXACT keyword in camp 10 (SKU-A) and also flows through
    # SKU-A's broad camp 30 with no orders -> coexist + sculpting negative in 30
    str_rows = [
        dict(campaign_id="10", search_term="ice pack", clicks=20, orders=4, spend=10.0, sales=80.0),
        dict(campaign_id="30", search_term="ice pack", clicks=15, orders=0, spend=8.0, sales=0.0),
    ]
    frames = _frames()
    # camp 30 stays a BROAD campaign, but its live keyword is a different text so
    # the "ice pack" negative isn't blocked by the live-keyword guard
    frames["keyword"].loc[frames["keyword"].keyword_id == "k3", "keyword_text"] = "gel wrap"
    fs = cn.detect(frames, str_rows, goal_acos=0.25)
    tier = [f for f in fs if f["kind"] == "cross_product" and f.get("tier_pair")]
    assert len(tier) == 1
    f = tier[0]
    assert f["verdict"] == "coexist"
    assert [a["campaign_id"] for a in f["actions"]] == ["30"]


def test_tier_pair_skipped_when_negative_blocked_by_live_keyword():
    # broad copy k3 ("ice pack" Broad) is LIVE in camp 30 -> negative would kill it -> no finding
    str_rows = [
        dict(campaign_id="10", search_term="ice pack", clicks=20, orders=4, spend=10.0, sales=80.0),
        dict(campaign_id="30", search_term="ice pack", clicks=15, orders=0, spend=8.0, sales=0.0),
    ]
    fs = cn.detect(_frames(), str_rows, goal_acos=0.25)
    assert not [f for f in fs if f.get("tier_pair")]


# ---- bulk ------------------------------------------------------------------------
def test_bulk_shapes_and_dedup():
    chosen = [{
        "verdict": "resolve", "term": "ice pack",
        "actions": [
            {"type": "pause_keyword", "keyword_id": "5585544115802929",
             "campaign_id": "20", "ad_group_id": "ag20", "term": "ice pack"},
            {"type": "campaign_negative", "term": "ice pack", "campaign_id": "20"},
            {"type": "campaign_negative", "term": "ice pack", "campaign_id": "20"},  # dup
            {"type": "campaign_negative", "term": "b01iks0ank", "campaign_id": "20"},  # ASIN
        ],
    }]
    df = pd.read_excel(io.BytesIO(cn.to_bulk(chosen)), dtype=str)
    assert len(df) == 2                                   # pause + ONE negative, ASIN dropped
    kw = df[df.Entity == "Keyword"].iloc[0]
    assert kw["Keyword ID"] == "5585544115802929"
    assert kw["State"] == "paused"
    neg = df[df.Entity == "Campaign Negative Keyword"].iloc[0]
    assert pd.isna(neg["Ad Group ID"])
    assert neg["Match Type"] == "Negative Exact"


def test_rerun_replaces_findings_idempotently():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    fs = cn.detect(_frames(), [], goal_acos=0.25)
    cn.store(db, fs)
    n1 = cn.summary(db)["findings"]
    cn.store(db, fs)                                       # re-run: replace, not append
    assert cn.summary(db)["findings"] == n1


def test_cannibal_delete_all():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    cn.store(db, [{"kind": "duplicate_target", "term": "widget", "verdict": "resolve",
                   "candidates": [], "actions": []}])
    assert cn.has_data(db)
    assert cn.delete_all(db) == 1
    assert not cn.has_data(db)
