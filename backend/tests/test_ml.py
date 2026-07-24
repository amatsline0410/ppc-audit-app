"""ML primitives (pipeline/ml.py): empirical Bayes, anomalies, Holt, logistic."""
import numpy as np
import pytest

from app.pipeline import ml


# ---- betainc / beta_ppf ------------------------------------------------------
def test_betainc_known_values():
    # Beta(1,1) is uniform: I_x = x
    assert ml.betainc(1, 1, 0.3) == pytest.approx(0.3, abs=1e-9)
    # Beta(2,2): I_x = 3x^2 - 2x^3
    assert ml.betainc(2, 2, 0.5) == pytest.approx(0.5, abs=1e-9)
    assert ml.betainc(2, 2, 0.25) == pytest.approx(3 * 0.0625 - 2 * 0.015625, abs=1e-9)
    # bounds
    assert ml.betainc(3, 5, 0.0) == 0.0 and ml.betainc(3, 5, 1.0) == 1.0


def test_beta_ppf_inverts_betainc():
    for a, b, q in [(2.0, 5.0, 0.05), (10.0, 3.0, 0.95), (0.8, 0.8, 0.5)]:
        x = ml.beta_ppf(a, b, q)
        assert ml.betainc(a, b, x) == pytest.approx(q, abs=1e-6)


# ---- empirical Bayes ---------------------------------------------------------
def _prior():
    # account with ~5% CVR across a spread of targets
    pairs = [(1, 20), (0, 15), (2, 40), (3, 50), (0, 10), (1, 30), (4, 60), (0, 8)]
    return ml.fit_beta_prior(pairs)


def test_prior_fit_reasonable():
    p = _prior()
    assert p is not None
    assert 0.02 < p["mean"] < 0.10                    # pooled ≈ 11/233 ≈ 4.7%
    assert 2.0 <= p["strength"] <= 500.0


def test_shrinkage_thin_vs_thick():
    p = _prior()
    thin = ml.posterior(0, 3, p)          # 0/3 clicks — nearly all prior
    thick = ml.posterior(50, 1000, p)     # 50/1000 — data dominates
    assert thin["cvr_smoothed"] > 0.02                # NOT zero
    assert abs(thin["cvr_smoothed"] - p["mean"]) < 0.02
    assert thick["cvr_smoothed"] == pytest.approx(0.05, abs=0.01)
    # credible interval sane and ordered
    assert thin["cvr_lo"] < thin["cvr_smoothed"] < thin["cvr_hi"]
    # more data -> tighter interval
    assert (thick["cvr_hi"] - thick["cvr_lo"]) < (thin["cvr_hi"] - thin["cvr_lo"])


def test_negation_confidence_grows_with_evidence():
    p = _prior()
    be = 0.05
    few = ml.p_below(0, 4, p, be)          # 0/4 — weak evidence of a loser
    many = ml.p_below(0, 80, p, be)        # 0/80 — strong evidence
    assert many > few
    assert many > 0.9                       # 80 clicks 0 orders: confidently below 5%
    assert few < 0.9                        # 4 clicks proves nothing


def test_prior_degrades_on_tiny_or_zero_data():
    assert ml.fit_beta_prior([(0, 5), (1, 9)]) is None            # < 5 targets
    assert ml.fit_beta_prior([(0, 5)] * 8) is None                # no conversions
    assert ml.fit_beta_prior([]) is None


# ---- anomalies ---------------------------------------------------------------
def test_anomaly_flags_planted_spike():
    series = [{"date": f"d{i}", "spend": 100.0, "sales": 400.0} for i in range(12)]
    series[7]["spend"] = 400.0            # planted 4x spend spike
    series[9]["sales"] = 40.0             # planted sales collapse
    # give the flat series a touch of noise so MAD isn't zero
    for i, p in enumerate(series):
        p["spend"] += (i % 3)
        p["sales"] += (i % 4)
    out = ml.robust_anomalies(series, ["spend", "sales"])
    flagged = {(a["metric"], a["date"], a["severity"], a["direction"]) for a in out}
    assert ("spend", "d7", "bad", "spike") in flagged
    assert ("sales", "d9", "bad", "drop") in flagged
    # normal days not flagged
    assert not any(a["date"] == "d2" for a in out)


def test_anomaly_needs_min_points_and_skips_constant():
    flat = [{"date": f"d{i}", "spend": 5.0} for i in range(10)]
    assert ml.robust_anomalies(flat, ["spend"]) == []             # constant
    short = [{"date": f"d{i}", "spend": float(i * i)} for i in range(3)]
    assert ml.robust_anomalies(short, ["spend"]) == []            # < min_points


# ---- Holt forecast -----------------------------------------------------------
def test_holt_tracks_linear_trend():
    f = ml.holt_forecast([10, 20, 30, 40, 50])
    assert f is not None
    assert f["forecast"] == pytest.approx(60, abs=6)              # next step ~60
    assert f["lo"] <= f["forecast"] <= f["hi"]
    assert ml.holt_forecast([5, 9]) is None                       # < 3 points


# ---- logistic regression -----------------------------------------------------
def _term(term, clicks, impressions, orders, match="broad", spend=None):
    return {"search_term": term, "clicks": clicks, "impressions": impressions,
            "orders": orders, "match_type": match,
            "spend": spend if spend is not None else clicks * 1.1}


def test_logreg_learns_separable_terms():
    # convertors: exact match, high CTR; non-convertors: broad, low CTR
    rows = []
    for i in range(30):
        rows.append(_term(f"good term {i}", 20 + i % 5, 200, 2, match="exact"))
    for i in range(30):
        rows.append(_term(f"bad long term number {i} extra words", 20 + i % 5, 4000, 0, match="broad"))
    m = ml.train_term_model(rows)
    assert m is not None and m["auc"] > 0.9
    scored = ml.score_terms(m, [_term("new exact candidate", 10, 100, 0, match="exact"),
                                _term("new broad word soup candidate here", 10, 2000, 0, match="broad")])
    assert scored[0]["search_term"] == "new exact candidate"
    assert scored[0]["p_convert"] > scored[1]["p_convert"]


def test_logreg_gates_small_or_hopeless_data():
    assert ml.train_term_model([_term(f"t{i}", 5, 50, i % 2) for i in range(10)]) is None   # < 30 rows
    # 40 rows but only 2 positives -> below min_class
    rows = [_term(f"t{i}", 5, 50, 1 if i < 2 else 0) for i in range(40)]
    assert ml.train_term_model(rows) is None


# ---- plan integration --------------------------------------------------------
def test_enrich_plan_stamps_rows_and_summary():
    agg = [{"orders": o, "clicks": c, "spend": c * 1.0, "sales": o * 30.0}
           for o, c in [(1, 20), (0, 15), (2, 40), (3, 50), (0, 10), (1, 30), (4, 60), (0, 8)]]
    plan = {
        "bid_tweaks": [{"orders": 2, "clicks": 40}],
        "promotes": [{"orders": 3, "clicks": 30}],
        "negates": [{"orders": 0, "clicks": 25}],
        "pauses": [{"orders": 0, "clicks": 60}],
    }
    ml.enrich_plan(plan, agg, target_acos=0.30)
    assert plan["ml"]["prior"]["mean"] > 0
    assert plan["ml"]["be_cvr"] is not None
    for key in ("bid_tweaks", "promotes", "negates", "pauses"):
        assert "ml" in plan[key][0]
        assert 0 < plan[key][0]["ml"]["cvr_smoothed"] < 1
    assert "confidence" not in plan["bid_tweaks"][0]["ml"]        # no mode
    # a 0/60 pause is judged a loser far more confidently than a 0/25 negate
    assert plan["pauses"][0]["ml"]["confidence"] > plan["negates"][0]["ml"]["confidence"]
    # promote confidence = P(above break-even)
    assert 0 <= plan["promotes"][0]["ml"]["confidence"] <= 1


def test_enrich_plan_degrades_without_prior():
    plan = {"negates": [{"orders": 0, "clicks": 10}]}
    ml.enrich_plan(plan, [{"orders": 0, "clicks": 5}], target_acos=0.3)
    assert plan["ml"] is None
    assert "ml" not in plan["negates"][0]
