"""Ads Studio funnel strategy — tier classification, the health report (budget band,
gaps, never-mix rule), promotion routing with sculpting negatives, the Top-of-Search
placement rule, and bulk validity.
Run: pytest -q tests/test_funnel.py
"""
import io

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Thresholds
from app.database import Base
from app.pipeline import adsstudio as st
from app.pipeline import funnel as fn

from tests.test_adsstudio import COLS, _r, _write   # reuse the synthetic-bulk builder

T = Thresholds(target_acos=0.30, min_clicks=5)


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


# ---- tier classification ------------------------------------------------------
@pytest.mark.parametrize("row,expected", [
    ({"entity": "keyword", "match_type": "broad"}, fn.BROAD),
    ({"entity": "keyword", "match_type": "phrase"}, fn.PHRASE),
    ({"entity": "keyword", "match_type": "exact"}, fn.EXACT),
    ({"entity": "product_target", "expression": 'asin="B0X"'}, fn.PT),
    ({"entity": "product_target", "expression": "close-match", "is_auto_clause": True}, fn.AUTO),
    ({"entity": "keyword", "match_type": None, "campaign_type": "auto"}, fn.AUTO),
])
def test_target_tier(row, expected):
    assert fn.target_tier(row) == expected


def test_campaign_tier_follows_the_spend_not_the_row_count():
    """One stray exact keyword must not reclassify a broad research campaign."""
    camp = {"campaign_type": "keyword", "targets": [
        {"entity": "keyword", "match_type": "broad", "metrics": {"spend": 100.0}},
        {"entity": "keyword", "match_type": "exact", "metrics": {"spend": 1.0}},
        {"entity": "keyword", "match_type": "exact", "metrics": {"spend": 1.0}},
    ]}
    assert fn.campaign_tier(camp) == fn.BROAD


def test_campaign_tier_of_an_auto_campaign_is_always_auto():
    assert fn.campaign_tier({"campaign_type": "auto", "targets": []}) == fn.AUTO


# ---- never-mix rule -----------------------------------------------------------
def test_mix_violation_flags_a_campaign_holding_two_match_types():
    camps = [
        {"campaign_id": "c1", "campaign_name": "Mixed", "campaign_type": "keyword", "targets": [
            {"entity": "keyword", "match_type": "broad", "metrics": {"spend": 5}},
            {"entity": "keyword", "match_type": "exact", "metrics": {"spend": 5}}]},
        {"campaign_id": "c2", "campaign_name": "Clean", "campaign_type": "keyword", "targets": [
            {"entity": "keyword", "match_type": "exact", "metrics": {"spend": 5}}]},
    ]
    v = fn.mix_violations(camps)
    assert [x["campaign_id"] for x in v] == ["c1"]
    assert set(v[0]["tiers"]) == {fn.BROAD, fn.EXACT}


def test_auto_campaigns_are_exempt_from_the_never_mix_rule():
    """Auto clause rows are Amazon's own match groups, not a structural mistake."""
    camps = [{"campaign_id": "a1", "campaign_name": "Auto", "campaign_type": "auto", "targets": [
        {"entity": "product_target", "expression": "close-match", "is_auto_clause": True, "metrics": {"spend": 3}},
        {"entity": "product_target", "expression": "substitutes", "is_auto_clause": True, "metrics": {"spend": 3}}]}]
    assert fn.mix_violations(camps) == []


# ---- the health report --------------------------------------------------------
def _camp(cid, name, ctype, tier_match, spend, sales=0.0, orders=0, clicks=0):
    tgt = {"entity": "product_target", "expression": 'asin="B0R"'} if tier_match == "pt" else \
          {"entity": "keyword", "match_type": tier_match}
    return {"campaign_id": cid, "campaign_name": name, "campaign_type": ctype,
            "ad_groups": [{"ad_group_id": f"ag{cid}", "ad_group_name": "AG"}],
            "targets": [{**tgt, "id": f"t{cid}", "label": name, "verdict": "keep",
                         "ad_group_id": f"ag{cid}", "ad_group_name": "AG",
                         "metrics": {"spend": spend, "sales": sales, "orders": orders,
                                     "clicks": clicks}}],
            "metrics": {"spend": spend, "sales": sales, "orders": orders, "clicks": clicks,
                        "acos": (spend / sales) if sales else None}}


def test_report_budget_band():
    # auto = 10 of 100 -> under the 15% floor
    camps = [_camp("a", "Auto", "auto", None, 10), _camp("e", "Exact", "keyword", "exact", 90)]
    rep = fn.report(camps, 0.30)
    assert rep["auto_share"] == pytest.approx(0.10)
    assert rep["budget_verdict"] == "under"

    camps = [_camp("a", "Auto", "auto", None, 18), _camp("e", "Exact", "keyword", "exact", 82)]
    assert fn.report(camps, 0.30)["budget_verdict"] == "ok"

    camps = [_camp("a", "Auto", "auto", None, 40), _camp("e", "Exact", "keyword", "exact", 60)]
    assert fn.report(camps, 0.30)["budget_verdict"] == "over"


def test_report_lists_missing_tiers_and_the_sb_sd_gap():
    rep = fn.report([_camp("a", "Auto", "auto", None, 10)], 0.30)
    gaps = {g["tier"] for g in rep["gaps"]}
    assert {fn.BROAD, fn.PHRASE, fn.EXACT, fn.PT} <= gaps
    # Phase 3 is reported as a gap the app deliberately cannot fix
    sb = next(g for g in rep["gaps"] if g["tier"] == "SB_SD")
    assert sb["phase"] == 3 and "cannot write an SB/SD bulk" in sb["reason"]


def test_report_tier_rollup_keeps_every_tier_present_or_not():
    rep = fn.report([_camp("e", "Exact", "keyword", "exact", 50, sales=200, orders=8)], 0.30)
    tiers = {t["tier"]: t for t in rep["tiers"]}
    assert set(tiers) == set(fn.TIERS)
    assert tiers[fn.EXACT]["present"] is True and tiers[fn.EXACT]["count"] == 1
    assert tiers[fn.AUTO]["present"] is False


# ---- promotion routing --------------------------------------------------------
def _funnel_account():
    """Auto + broad + phrase discovery, one exact money campaign, one PT campaign."""
    auto = _camp("a1", "Auto", "auto", None, 20, sales=100, orders=3, clicks=30)
    auto["targets"][0].update({"entity": "keyword", "keyword_text": "widget clamp",
                               "match_type": None, "label": "widget clamp"})
    broad = _camp("b1", "Broad", "keyword", "broad", 15, sales=90, orders=3, clicks=25)
    broad["targets"][0].update({"keyword_text": "steel widget", "label": "steel widget"})
    phrase = _camp("p1", "Phrase", "keyword", "phrase", 12, sales=80, orders=2, clicks=20)
    phrase["targets"][0].update({"keyword_text": "widget for sink", "label": "widget for sink"})
    exact = _camp("e1", "Exact", "keyword", "exact", 40, sales=300, orders=10, clicks=50)
    exact["targets"][0].update({"keyword_text": "widget", "label": "widget"})
    pt = _camp("t1", "PT", "product", "pt", 8, sales=40, orders=2, clicks=10)
    pt["targets"][0].update({"expression": 'asin="B0OWN0001"', "label": 'asin="B0OWN0001"'})
    return [auto, broad, phrase, exact, pt]


def test_winners_promote_from_discovery_into_exact():
    p = fn.plan(_funnel_account(), {fn.EXACT: "e1", fn.PT: "t1"}, 0.30)
    moved = {m["label"]: m for m in p["promotes"]}
    assert set(moved) == {"widget clamp", "steel widget", "widget for sink"}
    for m in moved.values():
        assert m["to_campaign_id"] == "e1"
        assert m["to_tier"] == fn.EXACT
        assert m["match_type"] == "exact"      # everything graduates AS exact
        assert m["new_bid"] > 0


def test_every_promotion_leaves_a_sculpting_negative_upstream():
    p = fn.plan(_funnel_account(), {fn.EXACT: "e1", fn.PT: "t1"}, 0.30)
    assert len(p["negatives"]) == len(p["promotes"])
    by_src = {n["campaign_id"]: n for n in p["negatives"]}
    assert set(by_src) == {"a1", "b1", "p1"}    # negated where they came FROM
    assert all(n["entity"] == "keyword" for n in p["negatives"])


def test_targets_already_in_the_money_tier_are_not_promoted_or_negated():
    p = fn.plan(_funnel_account(), {fn.EXACT: "e1", fn.PT: "t1"}, 0.30)
    assert all(m["from_campaign_id"] != "e1" for m in p["promotes"] + p["migrates"])
    assert all(n["campaign_id"] != "e1" for n in p["negatives"])


def test_an_asin_term_routes_to_the_pt_boss_not_exact():
    camps = _funnel_account()
    camps[0]["targets"][0].update({"keyword_text": "B0RIVAL001", "label": "B0RIVAL001"})
    p = fn.plan(camps, {fn.EXACT: "e1", fn.PT: "t1"}, 0.30)
    m = next(m for m in p["promotes"] if m["label"] == "B0RIVAL001")
    assert m["to_campaign_id"] == "t1"
    assert m["to_tier"] == fn.PT
    assert m["expression"] == 'asin="B0RIVAL001"'


def test_promotion_is_skipped_when_no_money_tier_was_chosen():
    p = fn.plan(_funnel_account(), {}, 0.30)
    assert p["promotes"] == []
    assert all("no " in s["skip_reason"] for s in p["skipped"])


def test_losers_are_paused_and_never_promoted():
    camps = _funnel_account()
    camps[1]["targets"][0].update({"verdict": "drop", "reason": "18 clicks, no orders"})
    p = fn.plan(camps, {fn.EXACT: "e1", fn.PT: "t1"}, 0.30)
    assert [x["label"] for x in p["pauses"]] == ["steel widget"]
    assert all(m["label"] != "steel widget" for m in p["promotes"])


def test_duplicate_promotion_into_the_same_exact_campaign_is_skipped():
    camps = _funnel_account()
    camps[2]["targets"][0].update({"keyword_text": "steel widget", "label": "steel widget"})
    p = fn.plan(camps, {fn.EXACT: "e1", fn.PT: "t1"}, 0.30)
    assert sum(1 for m in p["promotes"] if m["label"] == "steel widget") == 1
    assert any("already" in s["skip_reason"] for s in p["skipped"])


# ---- Top of Search ------------------------------------------------------------
def test_tos_uplift_only_for_stable_converting_exact_campaigns():
    exact = _camp("e1", "Exact", "keyword", "exact", 40, sales=400, orders=10)
    exact["metrics"]["acos"] = 0.10                    # comfortably under a 30% goal
    thin = _camp("e2", "Thin", "keyword", "exact", 5, sales=20, orders=1)
    thin["metrics"]["acos"] = 0.10                     # good ACoS, not enough orders
    bad = _camp("e3", "Bad", "keyword", "exact", 40, sales=50, orders=9)
    bad["metrics"]["acos"] = 0.80                      # over goal
    auto = _camp("a1", "Auto", "auto", None, 40, sales=400, orders=10)
    auto["metrics"]["acos"] = 0.10                     # right numbers, wrong tier
    recs = fn.placement_recommendations([exact, thin, bad, auto],
                                        {"e1": {"Placement Top": 20.0}}, 0.30)
    assert [r["campaign_id"] for r in recs] == ["e1"]
    assert recs[0]["current_pct"] == 20.0
    assert 0.20 <= recs[0]["uplift"] <= 0.50
    assert recs[0]["new_pct"] > 20.0


def test_tos_uplift_scales_with_headroom_under_goal():
    at_goal = _camp("e1", "AtGoal", "keyword", "exact", 40, sales=400, orders=10)
    at_goal["metrics"]["acos"] = 0.30                  # exactly at goal -> minimum uplift
    r = fn.placement_recommendations([at_goal], {"e1": {"Placement Top": 10.0}}, 0.30)
    assert r[0]["uplift"] == pytest.approx(fn.TOS_UPLIFT_MIN)


def test_tos_percentage_is_capped():
    c = _camp("e1", "Exact", "keyword", "exact", 40, sales=400, orders=10)
    c["metrics"]["acos"] = 0.01
    r = fn.placement_recommendations([c], {"e1": {"Placement Top": 800.0}}, 0.30)
    assert r[0]["new_pct"] <= fn.TOS_CAP


# ---- bulk emit ----------------------------------------------------------------
def _sheets(data):
    xl = pd.ExcelFile(io.BytesIO(data))
    return {n: pd.read_excel(xl, sheet_name=n, dtype=str) for n in xl.sheet_names}


def test_funnel_bulk_orders_creates_then_negatives_then_pauses():
    p = fn.plan(_funnel_account(), {fn.EXACT: "e1", fn.PT: "t1"}, 0.30)
    p["pauses"] = [{"id": "z1", "entity": "keyword", "campaign_id": "b1", "ad_group_id": "agb1"}]
    df = _sheets(st.funnel_to_bulk(p["promotes"], p["migrates"], p["negatives"], p["pauses"]))[
        "Sponsored Products Campaigns"]
    ents = list(df["Entity"])
    assert ents.index("Keyword") < ents.index("Negative Keyword")
    creates = df[df["Operation"] == "create"]
    assert set(creates[creates["Entity"] == "Keyword"]["Match Type"]) == {"Exact"}
    assert list(df[df["Operation"] == "update"]["State"]) == ["paused"]


def test_funnel_bulk_negatives_land_in_the_source_ad_group():
    p = fn.plan(_funnel_account(), {fn.EXACT: "e1", fn.PT: "t1"}, 0.30)
    df = _sheets(st.funnel_to_bulk([], [], p["negatives"], []))["Sponsored Products Campaigns"]
    assert set(df["Entity"]) == {"Negative Keyword"}
    assert set(df["Match Type"]) == {"Negative Exact"}
    assert set(df["Campaign ID"]) == {"a1", "b1", "p1"}
    assert df["Ad Group ID"].notna().all()


def test_negative_falls_back_to_campaign_level_without_an_ad_group():
    """A promotion with no upstream negative means paying for the term twice, so a
    missing ad group must downgrade the sculpt, not drop it."""
    negs = [{"campaign_id": "b1", "ad_group_id": None, "entity": "keyword",
             "keyword_text": "steel widget", "label": "steel widget"}]
    df = _sheets(st.funnel_to_bulk([], [], negs, []))["Sponsored Products Campaigns"]
    assert list(df["Entity"]) == ["Campaign Negative Keyword"]
    assert pd.isna(df.loc[0, "Ad Group ID"])
    assert df.loc[0, "Match Type"] == "Negative Exact"


def test_funnel_bulk_placement_sheet():
    recs = [{"campaign_id": "e1", "placement_raw": "Placement Top", "new_pct": 35.0}]
    sheets = _sheets(st.funnel_to_bulk([], [], [], [], recs))
    assert "Placement Adjustments" in sheets
    row = sheets["Placement Adjustments"].iloc[0]
    assert row["Entity"] == "Bidding Adjustment" and row["Campaign ID"] == "e1"


def test_funnel_bulk_is_deduped():
    p = fn.plan(_funnel_account(), {fn.EXACT: "e1", fn.PT: "t1"}, 0.30)
    df = _sheets(st.funnel_to_bulk(p["promotes"] + p["promotes"], [],
                                   p["negatives"] + p["negatives"], []))[
        "Sponsored Products Campaigns"]
    sig = df[["Entity", "Operation", "Campaign ID", "Ad Group ID", "Keyword Text",
              "Product Targeting Expression"]].fillna("").agg("|".join, axis=1)
    assert sig.is_unique


# ---- end to end off a real parsed bulk ---------------------------------------
def test_funnel_report_end_to_end(db, tmp_path):
    rows = [
        _r(Entity="Campaign", **{"Campaign ID": "a1", "Campaign Name": "Auto",
                                 "Targeting Type": "auto", "State": "enabled"}),
        _r(Entity="Campaign", **{"Campaign ID": "e1", "Campaign Name": "Exact",
                                 "Targeting Type": "manual", "State": "enabled"}),
        _r(Entity="Product Ad", **{"Campaign ID": "a1", "Ad Group ID": "aga", "Ad ID": "d1",
                                   "ASIN": "B0FUNNEL01", "SKU": "S1", "State": "enabled",
                                   "Spend": 10, "7 Day Total Sales": 50}),
        _r(Entity="Product Ad", **{"Campaign ID": "e1", "Ad Group ID": "age", "Ad ID": "d2",
                                   "ASIN": "B0FUNNEL01", "SKU": "S1", "State": "enabled",
                                   "Spend": 90, "7 Day Total Sales": 400}),
        _r(Entity="Keyword", **{"Campaign ID": "a1", "Ad Group ID": "aga", "Keyword ID": "k1",
                                "Keyword Text": "found term", "State": "enabled", "Bid": 0.5,
                                "Clicks": 20, "Spend": 10, "7 Day Total Sales": 100,
                                "7 Day Total Orders (#)": 4}),
        _r(Entity="Keyword", **{"Campaign ID": "e1", "Ad Group ID": "age", "Keyword ID": "k2",
                                "Keyword Text": "proven term", "Match Type": "exact",
                                "State": "enabled", "Bid": 0.9, "Clicks": 60, "Spend": 90,
                                "7 Day Total Sales": 400, "7 Day Total Orders (#)": 12}),
        _r(Entity="Bidding Adjustment", **{"Campaign ID": "e1", "Placement": "Placement Top",
                                           "Percentage": 15}),
    ]
    st.ingest_bulk(db, _write(rows, tmp_path))
    rep = st.funnel_report(db, ["B0FUNNEL01"], T)
    tiers = {t["tier"]: t for t in rep["tiers"]}
    assert tiers[fn.AUTO]["present"] and tiers[fn.EXACT]["present"]
    assert rep["auto_share"] == pytest.approx(0.10, abs=0.01)   # 10 of 100
    assert rep["budget_verdict"] == "under"
    assert any(g["tier"] == fn.PT for g in rep["gaps"])
    assert [p["campaign_id"] for p in rep["placements"]] == ["e1"]

    plan = st.funnel_plan(db, ["B0FUNNEL01"], {fn.EXACT: "e1"}, T)
    assert [m["label"] for m in plan["promotes"]] == ["found term"]
    assert [n["campaign_id"] for n in plan["negatives"]] == ["a1"]
