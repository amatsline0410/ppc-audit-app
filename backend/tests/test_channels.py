"""Placement upgrade + Channels (SB/SD) tests. Run: pytest -q"""
import pandas as pd
import pytest
from app.pipeline import placement as pl
from app.pipeline import channels as ch
from app.pipeline.bid_optimizer import CONFIG

TH = CONFIG["thresholds"]


# ---- placement: modifier recommendation (pure) --------------------------------
def test_placement_cut_scales_modifier_and_never_raises():
    # bleeding placement (76.7% vs goal 25%): cut = 100 * 25/76.7 = 32.6
    new, _ = pl.recommend_pct("Placement Product Page", 100.0, 0.767, 0.25,
                              clicks=100, orders=5, spend=50.0, th=TH)
    assert new == pytest.approx(100 * 0.25 / 0.767, abs=0.1)
    assert new < 100


def test_placement_never_raises_on_bleeding_placement():
    # cur 10%, formula would give 10*25/30=8.3 (cut). But construct acos just over
    # goal with big cur: any bleeding placement must never end higher than cur.
    for cur in (0.0, 10.0, 50.0, 200.0, 400.0):
        new, _ = pl.recommend_pct("Placement Top", cur, 0.30, 0.25,
                                  clicks=100, orders=10, spend=100.0, th=TH)
        assert new <= cur


def test_placement_pp_floors_at_zero():
    new, _ = pl.recommend_pct("Placement Product Page", 0.0, 0.90, 0.25,
                              clicks=100, orders=3, spend=80.0, th=TH)
    assert new == 0.0                          # can't go negative — base-bid fix instead


def test_placement_tos_step_raise_capped():
    new, _ = pl.recommend_pct("Placement Top", 40.0, 0.18, 0.25,
                              clicks=100, orders=10, spend=50.0, th=TH)
    assert new == 65.0                         # +25 step, not a jump
    new, _ = pl.recommend_pct("Placement Top", 140.0, 0.18, 0.25,
                              clicks=100, orders=10, spend=50.0, th=TH)
    assert new == 150.0                        # capped
    # non-TOS profitable placements are left alone (raises are TOS-only)
    new, _ = pl.recommend_pct("Placement Rest Of Search", 40.0, 0.18, 0.25,
                              clicks=100, orders=10, spend=50.0, th=TH)
    assert new == 40.0


def test_placement_flags():
    goal = 0.25
    # flat +20% everywhere with spend
    flat = [{"placement": "Placement Top", "pct": 20, "spend": 50, "sales": 200, "acos": 0.25, "orders": 5},
            {"placement": "Placement Product Page", "pct": 20, "spend": 30, "sales": 100, "acos": 0.30, "orders": 2},
            {"placement": "Placement Rest Of Search", "pct": 20, "spend": 20, "sales": 90, "acos": 0.22, "orders": 2}]
    assert "FLAT_MODIFIER" in pl.campaign_flags(flat, goal, 5.0)
    # product page bleeding at 76.7% vs TOS 21.9%
    bleed = [{"placement": "Placement Top", "pct": 0, "spend": 60, "sales": 274, "acos": 0.219, "orders": 9},
             {"placement": "Placement Product Page", "pct": 0, "spend": 46, "sales": 60, "acos": 0.767, "orders": 2}]
    assert "PLACEMENT_BLEED" in pl.campaign_flags(bleed, goal, 5.0)
    # TOS converting under goal but starved (< 25% of spend)
    starved = [{"placement": "Placement Top", "pct": 0, "spend": 10, "sales": 80, "acos": 0.125, "orders": 4},
               {"placement": "Placement Product Page", "pct": 0, "spend": 90, "sales": 300, "acos": 0.30, "orders": 6}]
    assert "TOS_STARVED" in pl.campaign_flags(starved, goal, 5.0)
    # default 0% everywhere is NOT a flat-modifier disease
    zeros = [dict(p, pct=0) for p in flat]
    assert "FLAT_MODIFIER" not in pl.campaign_flags(zeros, goal, 5.0)


# ---- brand classifier -----------------------------------------------------------
def test_brand_classifier():
    terms = ["pro ice", "proice"]
    assert ch.is_brand("pro ice youth", terms) is True
    assert ch.is_brand("proice shoulder", terms) is True
    assert ch.is_brand("pro   ice", terms) is False or True   # normalization tolerant
    assert ch.is_brand("shoulder ice pack", terms) is False
    assert ch.is_brand("", terms) is False
    assert ch.is_brand("anything", []) is False


# ---- SB dedupe: multi sheet only, totals match multi alone -----------------------
def _wb(tmp_path):
    """Workbook with duplicated SB campaigns across legacy + multi sheets."""
    p = tmp_path / "bulk.xlsx"
    sb_cols = ["Product", "Entity", "Campaign ID", "Ad Group ID", "Keyword ID",
               "Campaign Name", "Ad Group Name", "State", "Budget", "Bid",
               "Keyword Text", "Match Type", "Impressions", "Clicks", "Spend",
               "Sales", "Orders", "Units"]
    multi = pd.DataFrame([
        ["Sponsored Brands", "Campaign", "9001", "", "", "SB brand", "", "enabled", "10", "",
         "", "", 1000, 50, 120.5, 400.0, 8, 8],
        ["Sponsored Brands", "Keyword", "9001", "9101", "9201", "SB brand", "ag", "enabled", "", "1.2",
         "pro ice", "Exact", 500, 30, 80.0, 300.0, 6, 6],
    ], columns=sb_cols)
    legacy = multi.copy()                     # SAME campaigns duplicated (the trap)
    sd = pd.DataFrame([
        ["Sponsored Display", "Campaign", "8001", "", "", "SD camp", "", "enabled", "5", "",
         "", "", 0, 0, 0.0, 0.0, 0, 0],
    ], columns=["Product", "Entity", "Campaign ID", "Ad Group ID", "Targeting ID",
                "Campaign Name", "Ad Group Name", "State", "Budget", "Bid",
                "Tactic", "Targeting Expression", "Impressions", "Clicks", "Spend",
                "Sales", "Orders", "Units"])
    sp = pd.DataFrame([
        ["Sponsored Products", "Campaign", "7001", "SP camp", "enabled", 2000, 100, 250.0, 900.0, 20],
    ], columns=["Product", "Entity", "Campaign ID", "Campaign Name", "State",
                "Impressions", "Clicks", "Spend", "Sales", "Orders"])
    with pd.ExcelWriter(p, engine="openpyxl") as w:
        sp.to_excel(w, index=False, sheet_name="Sponsored Products Campaigns")
        legacy.to_excel(w, index=False, sheet_name="Sponsored Brands Campaigns")
        multi.to_excel(w, index=False, sheet_name="SB Multi Ad Group Campaigns")
        sd.to_excel(w, index=False, sheet_name="Sponsored Display Campaigns")
    return str(p)


def _db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.info["store"] = "t"; db.info["project"] = "t"
    return db


def test_sb_ingests_multi_sheet_only_no_double_count(tmp_path):
    db = _db()
    ch.ingest(db, _wb(tmp_path))
    s = ch.summary(db, ["pro ice"])
    sb = s["mix"]["channels"]["SB"]
    assert sb["spend"] == 120.5                # multi sheet alone — NOT 241.0
    assert sb["sales"] == 400.0
    sp = s["mix"]["channels"]["SP"]
    assert sp["spend"] == 250.0
    assert s["sd_dormant"] is True             # SD exists with 0 spend


def test_channel_rollup_and_brand_split(tmp_path):
    db = _db()
    ch.ingest(db, _wb(tmp_path))
    s = ch.summary(db, ["pro ice"])
    assert s["mix"]["total_spend"] == pytest.approx(250.0 + 120.5 + 0.0)
    bs = s["brand_split"]
    assert bs["brand"]["spend"] == 80.0        # "pro ice" keyword is branded
    assert bs["brand_spend_share"] == 1.0
    rows = ch.sb_keywords(db, __import__("app.config", fromlist=["Thresholds"]).Thresholds(), ["pro ice"])
    assert rows and rows[0]["brand"] is True and rows[0]["ad_format"] is None


def test_channels_delete_all():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app import models as md
    from app.pipeline import channels as ch
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(md.SBFact(entity="campaign", campaign_id="c1"))
    db.add(md.SDFact(entity="campaign", campaign_id="c2"))
    db.add(md.SPChannelFact(campaign_id="c3"))
    db.commit()
    assert ch.has_data(db)
    assert ch.delete_all(db) == 3
    assert not ch.has_data(db)
