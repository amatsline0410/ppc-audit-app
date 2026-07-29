"""Ads Studio — target parsing, goal-ACoS verdicts, the consolidation plan, and
bulk-file validity. Builds a synthetic SP bulk in-test (no fixture workbook).
Run: pytest -q tests/test_adsstudio.py
"""
import io

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Thresholds
from app.database import Base
from app import models as md
from app.pipeline import adsstudio as st

# 16 digits — past float64 exact range, must survive as an exact string end to end
BIG_ID = "1234567890123456"

T = Thresholds(target_acos=0.30, min_clicks=5)


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


COLS = ["Product", "Entity", "Operation", "Campaign ID", "Ad Group ID", "Keyword ID",
        "Product Targeting ID", "Ad ID", "Campaign Name", "Ad Group Name", "Targeting Type",
        "Keyword Text", "Match Type", "Product Targeting Expression", "State", "Bid",
        "SKU", "ASIN", "Impressions", "Clicks", "Spend", "7 Day Total Sales",
        "7 Day Total Orders (#)", "7 Day Total Units (#)"]


def _r(**kw):
    row = {c: None for c in COLS}
    row["Product"] = "Sponsored Products"
    row.update(kw)
    return row


def _write(rows, tmp_path) -> str:
    """Rows -> an .xlsx on disk, the way the uploader hands one to the parser."""
    p = tmp_path / "bulk.xlsx"
    with pd.ExcelWriter(p, engine="openpyxl") as w:
        pd.DataFrame(rows, columns=COLS).to_excel(
            w, index=False, sheet_name="Sponsored Products Campaigns")
    return str(p)


def _account():
    """Two manual keyword campaigns + one auto, all advertising ASIN B0TEST0001.

    c1 is the intended destination (a winner + a loser), c2 a source with one
    winner / one 0-order bleeder / one thin row, c3 an auto campaign whose clause
    row converts but can never be migrated into a manual campaign.
    """
    return [
        # campaigns
        _r(Entity="Campaign", **{"Campaign ID": "c1", "Campaign Name": "Manual A",
                                 "Targeting Type": "manual", "State": "enabled"}),
        _r(Entity="Campaign", **{"Campaign ID": "c2", "Campaign Name": "Manual B",
                                 "Targeting Type": "manual", "State": "enabled"}),
        _r(Entity="Campaign", **{"Campaign ID": "c3", "Campaign Name": "Auto",
                                 "Targeting Type": "auto", "State": "enabled"}),
        # product ads -> which ASIN each campaign advertises
        _r(Entity="Product Ad", **{"Campaign ID": "c1", "Ad Group ID": "ag1", "Ad ID": "ad1",
                                   "ASIN": "B0TEST0001", "SKU": "SKU-1", "State": "enabled",
                                   "Spend": 20, "7 Day Total Sales": 100}),
        _r(Entity="Product Ad", **{"Campaign ID": "c2", "Ad Group ID": "ag2", "Ad ID": "ad2",
                                   "ASIN": "B0TEST0001", "SKU": "SKU-1", "State": "enabled",
                                   "Spend": 30, "7 Day Total Sales": 40}),
        _r(Entity="Product Ad", **{"Campaign ID": "c3", "Ad Group ID": "ag3", "Ad ID": "ad3",
                                   "ASIN": "B0TEST0001", "SKU": "SKU-1", "State": "enabled",
                                   "Spend": 10, "7 Day Total Sales": 50}),
        # c1 targets: one keeper, one over-goal loser
        _r(Entity="Keyword", **{"Campaign ID": "c1", "Ad Group ID": "ag1", "Keyword ID": "k1",
                                "Campaign Name": "Manual A", "Ad Group Name": "AG1",
                                "Keyword Text": "blue widget", "Match Type": "exact",
                                "State": "enabled", "Bid": 0.75, "Clicks": 20, "Spend": 10,
                                "7 Day Total Sales": 100, "7 Day Total Orders (#)": 4}),
        _r(Entity="Keyword", **{"Campaign ID": "c1", "Ad Group ID": "ag1", "Keyword ID": "k2",
                                "Campaign Name": "Manual A", "Ad Group Name": "AG1",
                                "Keyword Text": "bad widget", "Match Type": "exact",
                                "State": "enabled", "Bid": 0.90, "Clicks": 30, "Spend": 40,
                                "7 Day Total Sales": 50, "7 Day Total Orders (#)": 1}),
        # c2 targets: keeper (big id), 0-order bleeder, thin row, product target keeper
        _r(Entity="Keyword", **{"Campaign ID": "c2", "Ad Group ID": "ag2", "Keyword ID": BIG_ID,
                                "Campaign Name": "Manual B", "Ad Group Name": "AG2",
                                "Keyword Text": "green widget", "Match Type": "phrase",
                                "State": "enabled", "Bid": 0.65, "Clicks": 25, "Spend": 15,
                                "7 Day Total Sales": 120, "7 Day Total Orders (#)": 5}),
        _r(Entity="Keyword", **{"Campaign ID": "c2", "Ad Group ID": "ag2", "Keyword ID": "k4",
                                "Campaign Name": "Manual B", "Ad Group Name": "AG2",
                                "Keyword Text": "dud widget", "Match Type": "broad",
                                "State": "enabled", "Bid": 0.50, "Clicks": 18, "Spend": 12,
                                "7 Day Total Sales": 0, "7 Day Total Orders (#)": 0}),
        _r(Entity="Keyword", **{"Campaign ID": "c2", "Ad Group ID": "ag2", "Keyword ID": "k5",
                                "Campaign Name": "Manual B", "Ad Group Name": "AG2",
                                "Keyword Text": "thin widget", "Match Type": "exact",
                                "State": "enabled", "Bid": 0.40, "Clicks": 2, "Spend": 1,
                                "7 Day Total Sales": 0, "7 Day Total Orders (#)": 0}),
        _r(Entity="Product Targeting", **{"Campaign ID": "c2", "Ad Group ID": "ag2",
                                          "Product Targeting ID": "p1", "Campaign Name": "Manual B",
                                          "Ad Group Name": "AG2",
                                          "Product Targeting Expression": 'asin="B0RIVAL001"',
                                          "State": "enabled", "Bid": 0.55, "Clicks": 12,
                                          "Spend": 8, "7 Day Total Sales": 60,
                                          "7 Day Total Orders (#)": 2}),
        # c3: an auto clause that converts — real spend, but not migratable
        _r(Entity="Product Targeting", **{"Campaign ID": "c3", "Ad Group ID": "ag3",
                                          "Product Targeting ID": "p2", "Campaign Name": "Auto",
                                          "Ad Group Name": "AG3",
                                          "Product Targeting Expression": "close-match",
                                          "State": "enabled", "Bid": 0.35, "Clicks": 14,
                                          "Spend": 6, "7 Day Total Sales": 50,
                                          "7 Day Total Orders (#)": 2}),
        # negatives must never be picked up as positives
        _r(Entity="Negative Keyword", **{"Campaign ID": "c1", "Ad Group ID": "ag1",
                                         "Keyword Text": "free widget",
                                         "Match Type": "negativeExact", "State": "enabled"}),
    ]


def _load(db, tmp_path):
    """Ingest via Ads Studio's OWN upload (fills both of its tables)."""
    path = _write(_account(), tmp_path)
    st.ingest_bulk(db, path)
    return path


# ---- parsing -----------------------------------------------------------------
def test_parse_keeps_positives_only_and_flags_auto_clauses(tmp_path):
    rows = st.parse_targets(_write(_account(), tmp_path))
    assert {r["keyword_text"] for r in rows if r["entity"] == "keyword"} == {
        "blue widget", "bad widget", "green widget", "dud widget", "thin widget"}
    # the Negative Keyword row is not a target
    assert all(r["keyword_text"] != "free widget" for r in rows)
    clause = next(r for r in rows if r["expression"] == "close-match")
    assert clause["is_auto_clause"] is True
    assert clause["campaign_type"] == "auto"
    normal = next(r for r in rows if r["expression"] == 'asin="B0RIVAL001"')
    assert normal["is_auto_clause"] is False


def test_names_resolve_on_a_real_amazon_column_layout(db, tmp_path):
    """Regression: a real bulk fills the bare "Campaign Name" ONLY on Campaign rows
    and "Ad Group Name" ONLY on Ad Group rows — both are blank on the Product Ad and
    Keyword rows we read. Matching the bare column left every card showing a raw ID.
    The "(Informational only)" twins are populated on every row and must win.
    """
    cols = COLS + ["Campaign Name (Informational only)", "Ad Group Name (Informational only)"]

    def row(**kw):
        r = {c: None for c in cols}
        r["Product"] = "Sponsored Products"
        r.update(kw)
        return r

    rows = [
        # names live on the parent entity rows only...
        row(Entity="Campaign", **{"Campaign ID": "c1", "Campaign Name": "SP - Widgets - Exact",
                                  "Targeting Type": "manual", "State": "enabled"}),
        row(Entity="Ad Group", **{"Campaign ID": "c1", "Ad Group ID": "ag1",
                                  "Ad Group Name": "AG - Widgets", "State": "enabled"}),
        # ...while the child rows carry only the informational twins
        row(Entity="Product Ad", **{
            "Campaign ID": "c1", "Ad Group ID": "ag1", "Ad ID": "ad1", "ASIN": "B0TEST0001",
            "SKU": "SKU-1", "State": "enabled", "Spend": 10, "7 Day Total Sales": 50,
            "Campaign Name (Informational only)": "SP - Widgets - Exact",
            "Ad Group Name (Informational only)": "AG - Widgets"}),
        row(Entity="Keyword", **{
            "Campaign ID": "c1", "Ad Group ID": "ag1", "Keyword ID": "k1",
            "Keyword Text": "blue widget", "Match Type": "exact", "State": "enabled",
            "Bid": 0.75, "Clicks": 20, "Spend": 10, "7 Day Total Sales": 100,
            "7 Day Total Orders (#)": 4,
            "Campaign Name (Informational only)": "SP - Widgets - Exact",
            "Ad Group Name (Informational only)": "AG - Widgets"}),
    ]
    p = tmp_path / "real.xlsx"
    with pd.ExcelWriter(p, engine="openpyxl") as w:
        pd.DataFrame(rows, columns=cols).to_excel(
            w, index=False, sheet_name="Sponsored Products Campaigns")

    from app.pipeline import productads as pa
    ads = pa.parse_product_ads(str(p))
    assert ads[0]["campaign_name"] == "SP - Widgets - Exact"
    assert ads[0]["ad_group_name"] == "AG - Widgets"

    tgs = st.parse_targets(str(p))
    assert tgs[0]["campaign_name"] == "SP - Widgets - Exact"
    assert tgs[0]["ad_group_name"] == "AG - Widgets"

    st.ingest_bulk(db, str(p))
    c = st.board(db, ["B0TEST0001"], T)["campaigns"][0]
    assert c["campaign_name"] == "SP - Widgets - Exact"    # not the raw "c1"
    assert c["has_name"] is True
    assert c["ad_groups"][0]["ad_group_name"] == "AG - Widgets"


def test_board_falls_back_to_the_id_when_the_bulk_has_no_name(db, tmp_path):
    """No name anywhere -> show the ID, and say so, rather than an empty card."""
    rows = [r for r in _account() if r["Entity"] != "Campaign"]
    for r in rows:
        r["Campaign Name"] = None
        r["Ad Group Name"] = None
    st.ingest_bulk(db, _write(rows, tmp_path))
    c = next(c for c in st.board(db, ["B0TEST0001"], T)["campaigns"] if c["campaign_id"] == "c1")
    assert c["campaign_name"] == "c1"
    assert c["has_name"] is False


def test_parse_keeps_big_ids_exact(tmp_path):
    rows = st.parse_targets(_write(_account(), tmp_path))
    kw = next(r for r in rows if r["keyword_text"] == "green widget")
    assert kw["target_id"] == BIG_ID          # not 1.234567890123456e+15, not '...456.0'


def test_ingest_survives_a_bulk_with_no_targets(db, tmp_path):
    """An all-auto account has no keyword rows — the Product Ads upload must not fail."""
    rows = [r for r in _account() if r["Entity"] in ("Campaign", "Product Ad")]
    out = st.ingest_bulk(db, _write(rows, tmp_path))
    assert out["targets"] == 0 and out["product_ads"] == 3
    assert st.has_data(db) is True          # the product ads landed
    assert st.has_targets(db) is False      # there was simply nothing to judge


# ---- verdicts ----------------------------------------------------------------
@pytest.mark.parametrize("m,expected", [
    ({"orders": 4, "clicks": 20, "acos": 0.10}, "keep"),      # well under goal
    ({"orders": 1, "clicks": 10, "acos": 0.30}, "keep"),      # exactly at goal
    ({"orders": 1, "clicks": 30, "acos": 0.80}, "drop"),      # converts, over goal
    ({"orders": 0, "clicks": 18, "acos": None}, "drop"),      # spent through, no orders
    ({"orders": 0, "clicks": 2, "acos": None}, "review"),     # too thin to judge
])
def test_classify(m, expected):
    verdict, reason = st.classify(m, 0.30, 5)
    assert verdict == expected
    assert reason


# ---- board -------------------------------------------------------------------
def test_board_groups_campaigns_and_judges_targets(db, tmp_path):
    _load(db, tmp_path)
    b = st.board(db, ["B0TEST0001"], T)
    assert {c["campaign_id"] for c in b["campaigns"]} == {"c1", "c2", "c3"}
    by = {c["campaign_id"]: c for c in b["campaigns"]}
    assert by["c1"]["counts"] == {"keep": 1, "drop": 1, "review": 0}
    assert by["c2"]["counts"] == {"keep": 2, "drop": 1, "review": 1}
    assert by["c3"]["campaign_type"] == "auto"
    assert b["counts"]["keep"] == 4          # k1, BIG_ID, p1, auto clause p2


def test_board_ignores_unselected_asins(db, tmp_path):
    _load(db, tmp_path)
    assert st.board(db, ["B0NOTMINE1"], T)["campaigns"] == []


def test_board_campaign_type_filter(db, tmp_path):
    """The panel's Automatic / Manual chooser — 'manual' covers keyword AND product."""
    _load(db, tmp_path)
    auto = st.board(db, ["B0TEST0001"], T, ["auto"])
    assert {c["campaign_id"] for c in auto["campaigns"]} == {"c3"}
    manual = st.board(db, ["B0TEST0001"], T, ["manual"])
    assert {c["campaign_id"] for c in manual["campaigns"]} == {"c1", "c2"}
    both = st.board(db, ["B0TEST0001"], T, ["auto", "manual"])
    assert len(both["campaigns"]) == 3
    assert len(st.board(db, ["B0TEST0001"], T, [])["campaigns"]) == 3   # no filter


def test_studio_owns_its_data_separately_from_product_ads(db, tmp_path):
    """Studio's upload must not touch ProductAdFact, and clearing it must not either."""
    from app.pipeline import productads as pa
    pa.ingest(db, _write(_account(), tmp_path))          # Product Ads tab has its own snapshot
    assert pa.has_data(db) is True
    _load(db, tmp_path)                                  # Studio's own upload
    assert st.has_data(db) is True
    st.delete_all(db)
    assert st.has_data(db) is False
    assert pa.has_data(db) is True                       # untouched


def test_products_table_renders_off_studios_own_upload(db, tmp_path):
    _load(db, tmp_path)
    out = st.products(db)
    assert out["count"] == 1                             # one (ASIN, SKU) pair
    row = out["rows"][0]
    assert row["asin"] == "B0TEST0001"
    assert row["auto_campaigns"] == 1 and row["keyword_campaigns"] == 2


# ---- plan --------------------------------------------------------------------
def _plan(db):
    return st.plan(db, [{"name": "Manual consolidation",
                         "destination_campaign_id": "c1",
                         "destination_ad_group_id": "ag1",
                         "source_campaign_ids": ["c2", "c3"]}], T)


def test_plan_migrates_only_winners(db, tmp_path):
    _load(db, tmp_path)
    g = _plan(db)["groups"][0]
    moved = {m["label"] for m in g["migrate"]}
    assert moved == {"green widget", 'asin="B0RIVAL001"'}
    # losers and thin rows never migrate
    assert "dud widget" not in moved and "thin widget" not in moved


def test_plan_never_migrates_an_auto_clause(db, tmp_path):
    """Amazon rejects a create for close-match / loose-match / substitutes /
    complements — it must be reported as skipped, not silently dropped."""
    _load(db, tmp_path)
    g = _plan(db)["groups"][0]
    assert all(m["label"] != "close-match" for m in g["migrate"])
    skipped = {s["label"]: s["skip_reason"] for s in g["skipped"]}
    assert "close-match" in skipped
    assert "auto-campaign clause" in skipped["close-match"]


def test_plan_pauses_losers_including_in_the_destination(db, tmp_path):
    _load(db, tmp_path)
    g = _plan(db)["groups"][0]
    paused = {p["label"] for p in g["pause_targets"]}
    assert paused == {"bad widget", "dud widget"}     # 'bad widget' lives in the destination
    assert all(p["id"] for p in g["pause_targets"])   # every pause is by real ID


def test_plan_skips_a_target_the_destination_already_has(db, tmp_path):
    """Same keyword+match in source and destination -> Amazon's 'Duplicate Keyword'."""
    rows = _account() + [
        _r(Entity="Keyword", **{"Campaign ID": "c2", "Ad Group ID": "ag2", "Keyword ID": "k9",
                                "Campaign Name": "Manual B", "Ad Group Name": "AG2",
                                "Keyword Text": "blue widget", "Match Type": "exact",
                                "State": "enabled", "Bid": 0.60, "Clicks": 20, "Spend": 10,
                                "7 Day Total Sales": 100, "7 Day Total Orders (#)": 4}),
    ]
    st.ingest_bulk(db, _write(rows, tmp_path))
    g = _plan(db)["groups"][0]
    assert sum(1 for m in g["migrate"] if m["label"] == "blue widget") == 0
    assert any("already has" in s["skip_reason"] for s in g["skipped"])


def test_plan_campaign_pauses_are_reported_not_forced(db, tmp_path):
    _load(db, tmp_path)
    g = _plan(db)["groups"][0]
    assert {c["campaign_id"] for c in g["campaign_pauses"]} == {"c2", "c3"}
    # destination is never proposed for pause
    assert all(c["campaign_id"] != "c1" for c in g["campaign_pauses"])


def test_consolidated_view_describes_the_boss_campaign(db, tmp_path):
    """The panel's bottom section: what c1 holds once the plan is applied."""
    _load(db, tmp_path)
    c = _plan(db)["consolidated"][0]
    assert c["campaign_id"] == "c1"
    assert c["campaigns_absorbed"] == 2                  # c2 + c3 drained into it
    assert c["targets_migrated"] == 2                    # green widget + the ASIN target
    assert c["targets_kept"] == 1                        # c1's own winner; its loser is paused
    assert c["targets_total"] == 3
    assert c["scope"] == "single"                        # one ASIN across the group
    assert c["spend_switched_off"] == pytest.approx(52.0)   # bad widget 40 + dud widget 12
    # surviving metrics = the winners only, never the paused losers
    assert c["metrics"]["sales"] == pytest.approx(280.0)     # 100 + 120 + 60
    assert c["metrics"]["orders"] == 11


def test_consolidated_view_flags_a_multi_product_campaign(db, tmp_path):
    rows = _account() + [
        _r(Entity="Product Ad", **{"Campaign ID": "c2", "Ad Group ID": "ag2", "Ad ID": "ad9",
                                   "ASIN": "B0TEST0002", "SKU": "SKU-2", "State": "enabled",
                                   "Spend": 5, "7 Day Total Sales": 20}),
    ]
    st.ingest_bulk(db, _write(rows, tmp_path))
    p = st.plan(db, [{"destination_campaign_id": "c1", "destination_ad_group_id": "ag1",
                      "source_campaign_ids": ["c2"]}], T)
    c = p["consolidated"][0]
    assert c["scope"] == "multi"
    assert c["asins"] == ["B0TEST0001", "B0TEST0002"]


# ---- settings ----------------------------------------------------------------
def test_target_acos_is_scoped_to_this_feature(db, tmp_path, monkeypatch):
    """Studio's goal ACoS is saved on its own key and must not read the audit knob."""
    store = {}
    monkeypatch.setattr("app.database.get_project_extra",
                        lambda s, p, k, default=None: store.get(k, default))
    monkeypatch.setattr("app.database.set_project_extra",
                        lambda s, p, k, v: store.__setitem__(k, v))
    assert st.get_settings(db)["target_acos"] == st.DEFAULT_TARGET_ACOS
    st.set_settings(db, 0.42)
    assert store == {st.SETTINGS_KEY: {"target_acos": 0.42}}
    assert st.get_settings(db)["target_acos"] == 0.42
    assert st.thresholds(db).target_acos == 0.42
    assert st.thresholds(db, 0.10).target_acos == 0.10      # request still wins


# ---- bulk emit ---------------------------------------------------------------
def _df(migrate, pauses, camps):
    data = st.to_bulk(migrate, pauses, camps)
    return pd.read_excel(io.BytesIO(data), sheet_name="Sponsored Products Campaigns", dtype=str)


def test_bulk_creates_before_pauses_and_keeps_ids_exact(db, tmp_path):
    _load(db, tmp_path)
    g = _plan(db)["groups"][0]
    df = _df(g["migrate"], g["pause_targets"], g["campaign_pauses"])
    ops = list(df["Operation"])
    assert ops.index("create") < ops.index("update")     # winners land before lights go out
    kw = df[(df["Entity"] == "Keyword") & (df["Operation"] == "create")]
    assert kw["Campaign ID"].eq("c1").all()              # everything into the destination
    assert kw["Ad Group ID"].eq("ag1").all()
    paused = df[(df["Operation"] == "update") & (df["Entity"] == "Keyword")]
    assert BIG_ID not in set(paused["Keyword ID"])       # the winner moved, it isn't paused


def test_bulk_is_deduped(db, tmp_path):
    _load(db, tmp_path)
    g = _plan(db)["groups"][0]
    df = _df(g["migrate"] + g["migrate"], g["pause_targets"] + g["pause_targets"],
             g["campaign_pauses"] + g["campaign_pauses"])
    sig = df[["Entity", "Operation", "Campaign ID", "Ad Group ID", "Keyword ID",
              "Product Targeting ID", "Keyword Text", "Product Targeting Expression"]] \
        .fillna("").agg("|".join, axis=1)
    assert sig.is_unique


def test_bulk_refuses_an_auto_clause_create():
    """Defence in depth: even if a clause row reached to_bulk, it must not be emitted."""
    df = _df([dict(entity="product_target", expression="close-match", to_campaign_id="c1",
                   to_ad_group_id="ag1", new_bid=0.4)], [], [])
    assert df.empty


def test_bulk_refuses_an_illegal_keyword():
    long_kw = " ".join(["word"] * 12)      # >10 words — Amazon rejects it
    df = _df([dict(entity="keyword", keyword_text=long_kw, match_type="exact",
                   to_campaign_id="c1", to_ad_group_id="ag1", new_bid=0.4)], [], [])
    assert df.empty


def test_bulk_campaign_pause_is_a_campaign_row(db, tmp_path):
    _load(db, tmp_path)
    g = _plan(db)["groups"][0]
    df = _df([], [], g["campaign_pauses"])
    assert set(df["Entity"]) == {"Campaign"}
    assert set(df["State"]) == {"paused"}
    assert df["Ad Group ID"].isna().all()
