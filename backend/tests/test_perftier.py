"""Performance tiering (HERO / A / B / C / D) — the 1-D k-means primitive, the
score components, tier assignment and its honest degradations, and the board filter.
Run: pytest -q tests/test_perftier.py
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Thresholds
from app.database import Base
from app.pipeline import adsstudio as st
from app.pipeline import ml
from app.pipeline import perftier as pt

from tests.test_adsstudio import _r, _write

T = Thresholds(target_acos=0.30, min_clicks=5)


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


# ---- the clustering primitive -------------------------------------------------
def test_kmeans_1d_finds_natural_groups():
    out = ml.kmeans_1d([1, 1.1, 1.2, 9, 9.1, 9.2], 2)
    assert out["k"] == 2
    assert out["labels"] == [0, 0, 0, 1, 1, 1]          # ordered by ascending centre
    assert 1.2 < out["breaks"][0] < 9.0


def test_kmeans_1d_is_deterministic():
    """No RNG anywhere — the same file must tier the same way every run."""
    vals = [0.9, 0.1, 0.5, 0.44, 0.8, 0.2, 0.75, 0.31, 0.62, 0.05]
    first = ml.kmeans_1d(vals, 4)
    for _ in range(20):
        assert ml.kmeans_1d(vals, 4) == first


def test_kmeans_1d_refuses_when_there_is_not_enough_distinct_data():
    assert ml.kmeans_1d([5, 5, 5, 5], 3) is None       # one distinct value
    assert ml.kmeans_1d([1, 2], 5) is None             # fewer points than groups
    assert ml.kmeans_1d([], 3) is None
    assert ml.kmeans_1d([1, 2, 3], 1) is None          # k must be >= 2


def test_kmeans_1d_rejects_non_finite_input():
    assert ml.kmeans_1d([1.0, float("nan"), 3.0], 2) is None
    assert ml.kmeans_1d([1.0, float("inf"), 3.0], 2) is None


# ---- score components ---------------------------------------------------------
def test_efficiency_score_anchors():
    assert pt._efficiency_score(0.15, 0.30) == pytest.approx(1.0)    # half of goal
    assert pt._efficiency_score(0.30, 0.30) == pytest.approx(0.333, abs=0.01)
    assert pt._efficiency_score(0.60, 0.30) == pytest.approx(0.0)    # twice the goal
    assert pt._efficiency_score(None, 0.30) == 0.0


def test_volume_score_is_log_compressed_not_linear():
    """A single whale must not flatten everyone else into one tier."""
    assert pt._volume_score(10_000, 10_000) == pytest.approx(1.0)
    mid = pt._volume_score(1_000, 10_000)
    assert mid > 0.10 + 0.4          # linear share would be 0.10
    assert pt._volume_score(0, 10_000) == 0.0


def test_conviction_uses_shrunk_cvr_so_thin_data_cannot_win():
    """1 click / 1 order is a 100% CVR, and must still not beat real evidence."""
    rows = [
        _row("thin", sales=40, spend=10, orders=1, clicks=1),
        _row("proven", sales=40, spend=10, orders=40, clicks=200),
    ] + [_row(f"f{i}", sales=20, spend=10, orders=4, clicks=40) for i in range(8)]
    scored = {r["campaign_id"]: r for r in pt.score_rows(rows, 0.30)}
    assert scored["thin"]["score_parts"]["conviction"] < scored["proven"]["score_parts"]["conviction"]


def _row(cid, sales, spend, orders, clicks, name=None):
    acos = (spend / sales) if sales else None
    return {"campaign_id": cid, "campaign_name": name or cid,
            "metrics": {"sales": sales, "spend": spend, "orders": orders,
                        "clicks": clicks, "acos": acos}}


# ---- tier assignment ----------------------------------------------------------
def _portfolio():
    """One clear hero, a good middle, and a tail — plus a pure burner."""
    return [
        _row("hero", sales=5000, spend=750, orders=200, clicks=2000),
        _row("a1", sales=1800, spend=400, orders=70, clicks=800),
        _row("a2", sales=1500, spend=380, orders=60, clicks=700),
        _row("b1", sales=600, spend=220, orders=25, clicks=400),
        _row("b2", sales=500, spend=200, orders=20, clicks=350),
        _row("c1", sales=120, spend=110, orders=5, clicks=180),
        _row("c2", sales=90, spend=100, orders=4, clicks=160),
        _row("d1", sales=40, spend=120, orders=2, clicks=150),
        _row("burner", sales=0, spend=300, orders=0, clicks=400),
    ]


def test_the_top_earner_is_the_hero():
    out = pt.assign(_portfolio(), 0.30)
    tiers = {r["campaign_id"]: r["tier"] for r in out["rows"]}
    assert tiers["hero"] == pt.HERO
    assert out["method"] == "kmeans"
    # the ranking is monotone in score: no lower tier outscores a higher one
    order = {t: i for i, t in enumerate(pt.TIERS)}
    earners = [r for r in out["rows"] if (r["metrics"]["sales"] or 0) > 0]
    for a in earners:
        for b in earners:
            if order[a["tier"]] < order[b["tier"]]:
                assert a["score"] >= b["score"]


def test_a_campaign_with_no_sales_is_always_bottom_tier():
    out = pt.assign(_portfolio(), 0.30)
    burner = next(r for r in out["rows"] if r["campaign_id"] == "burner")
    assert burner["tier"] == pt.D
    assert burner["tier_reason"] == "spend with no ad sales"


def test_high_spend_no_sales_can_never_be_hero():
    rows = _portfolio() + [_row("whale_burner", sales=0, spend=9999, orders=0, clicks=8000)]
    out = pt.assign(rows, 0.30)
    wb = next(r for r in out["rows"] if r["campaign_id"] == "whale_burner")
    assert wb["tier"] == pt.D


def test_small_selection_degrades_to_quantiles_not_a_fake_cluster():
    rows = [_row("x", sales=100, spend=20, orders=5, clicks=50),
            _row("y", sales=50, spend=25, orders=2, clicks=40)]
    out = pt.assign(rows, 0.30)
    assert out["method"] == "quantile"
    assert out["rows"][0]["tier"] in pt.TIERS


def test_a_selection_with_no_sales_at_all_returns_no_ranking():
    rows = [_row("a", sales=0, spend=10, orders=0, clicks=20),
            _row("b", sales=0, spend=30, orders=0, clicks=40)]
    out = pt.assign(rows, 0.30)
    assert out["method"] == "none"
    assert {r["tier"] for r in out["rows"]} == {pt.D}
    assert all(r["tier_reason"] == "no ad sales in this bulk" for r in out["rows"])


def test_assign_is_deterministic():
    first = [(r["campaign_id"], r["tier"]) for r in pt.assign(_portfolio(), 0.30)["rows"]]
    for _ in range(10):
        assert [(r["campaign_id"], r["tier"]) for r in pt.assign(_portfolio(), 0.30)["rows"]] == first


def test_empty_input():
    out = pt.assign([], 0.30)
    assert out["rows"] == [] and out["method"] == "none"


def test_tighter_goal_acos_moves_the_tiers():
    """Tiering is relative to YOUR goal, so the same account re-ranks when it changes."""
    loose = {r["campaign_id"]: r["score"] for r in pt.assign(_portfolio(), 0.60)["rows"]}
    tight = {r["campaign_id"]: r["score"] for r in pt.assign(_portfolio(), 0.10)["rows"]}
    assert loose["c1"] > tight["c1"]      # a weak-ACoS campaign suffers under a tight goal


# ---- the board filter ---------------------------------------------------------
def test_filter_tiers_runs_after_tiering_not_before(db, tmp_path):
    """Filtering must not re-rank: a B campaign can't become HERO because the real
    heroes were hidden."""
    b = {"campaigns": [
            {"campaign_id": "1", "tier": pt.HERO, "counts": {"keep": 1, "drop": 0, "review": 0},
             "metrics": {"spend": 100.0, "sales": 500.0, "clicks": 10, "impressions": 0,
                         "orders": 5, "units": 5}},
            {"campaign_id": "2", "tier": pt.B, "counts": {"keep": 0, "drop": 2, "review": 0},
             "metrics": {"spend": 40.0, "sales": 50.0, "clicks": 5, "impressions": 0,
                         "orders": 1, "units": 1}}],
         "counts": {"keep": 1, "drop": 2, "review": 0}, "totals": {}}
    out = st.filter_tiers(b, ["B"])
    assert [c["campaign_id"] for c in out["campaigns"]] == ["2"]
    assert out["campaigns"][0]["tier"] == pt.B        # unchanged, not re-ranked
    assert out["counts"] == {"keep": 0, "drop": 2, "review": 0}
    assert out["totals"]["spend"] == 40.0
    assert out["tier_filter"] == ["B"]


def test_filter_tiers_no_filter_is_a_passthrough():
    b = {"campaigns": [{"campaign_id": "1", "tier": pt.HERO}], "counts": {}, "totals": {}}
    assert st.filter_tiers(b, []) is b
    assert st.filter_tiers(b, None) is b


def test_board_and_products_carry_tiers_end_to_end(db, tmp_path):
    rows = [
        _r(Entity="Campaign", **{"Campaign ID": "c1", "Campaign Name": "Winner",
                                 "Targeting Type": "manual", "State": "enabled"}),
        _r(Entity="Campaign", **{"Campaign ID": "c2", "Campaign Name": "Loser",
                                 "Targeting Type": "manual", "State": "enabled"}),
        _r(Entity="Product Ad", **{"Campaign ID": "c1", "Ad Group ID": "ag1", "Ad ID": "a1",
                                   "ASIN": "B0TIER0001", "SKU": "S1", "State": "enabled",
                                   "Spend": 50, "7 Day Total Sales": 500,
                                   "7 Day Total Orders (#)": 20, "Clicks": 200}),
        _r(Entity="Product Ad", **{"Campaign ID": "c2", "Ad Group ID": "ag2", "Ad ID": "a2",
                                   "ASIN": "B0TIER0001", "SKU": "S1", "State": "enabled",
                                   "Spend": 80, "7 Day Total Sales": 0, "Clicks": 100}),
        _r(Entity="Keyword", **{"Campaign ID": "c1", "Ad Group ID": "ag1", "Keyword ID": "k1",
                                "Keyword Text": "winner kw", "Match Type": "exact",
                                "State": "enabled", "Bid": 0.8, "Clicks": 200, "Spend": 50,
                                "7 Day Total Sales": 500, "7 Day Total Orders (#)": 20}),
        _r(Entity="Keyword", **{"Campaign ID": "c2", "Ad Group ID": "ag2", "Keyword ID": "k2",
                                "Keyword Text": "loser kw", "Match Type": "exact",
                                "State": "enabled", "Bid": 0.8, "Clicks": 100, "Spend": 80,
                                "7 Day Total Sales": 0, "7 Day Total Orders (#)": 0}),
    ]
    st.ingest_bulk(db, _write(rows, tmp_path))

    b = st.board(db, ["B0TIER0001"], T)
    tiers = {c["campaign_id"]: c["tier"] for c in b["campaigns"]}
    assert tiers["c2"] == pt.D                    # spent, sold nothing
    assert tiers["c1"] != pt.D
    assert b["tiering"]["method"] in ("kmeans", "quantile", "none")

    assert st.filter_tiers(b, ["D"])["campaigns"][0]["campaign_id"] == "c2"

    prods = st.products(db)
    assert prods["rows"][0]["tier"] in pt.TIERS
    assert "tiering" in prods
