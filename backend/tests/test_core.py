"""Unit tests for the pure core (metrics + rules). Run: pytest -q

These have zero I/O / DB — they exercise the formulas and flag logic that drive
every bid recommendation and bulk-file row.
"""
from app import metrics as M
from app.config import Thresholds
from app.rules import run_target_rules


def test_acos_and_guards():
    assert M.acos(25, 100) == 0.25
    assert M.acos(10, 0) is None          # no sales -> undefined, never 0
    assert M.cvr(2, 100) == 0.02
    assert M.cpc(50, 0) is None


def test_target_acos_bid_scaling():
    t = Thresholds()
    # observed 50% ACoS, target 25% -> halve, but capped at max_cut(0.5)
    assert M.target_acos_bid(1.00, 0.50, 0.25, 0.5, 1.25, 0.20) == 0.50
    # great performer 10% ACoS -> would 2.5x, capped to +25%
    assert M.target_acos_bid(1.00, 0.10, 0.25, 0.5, 1.25, 0.20) == 1.25
    # no sales -> cut by max_cut
    assert M.target_acos_bid(1.00, None, 0.25, 0.5, 1.25, 0.20) == 0.50
    # floor respected
    assert M.target_acos_bid(0.10, 5.0, 0.25, 0.5, 1.25, 0.20) == 0.20


def _ctx(**kw):
    base = dict(entity_type="target", entity_id="t1", asin="B0X", bid=1.50, label="kw")
    base.update(kw); return base


def test_high_acos_flag_fires_above_target():
    t = Thresholds(target_acos=0.25, min_spend=5)
    m = M.all_metrics(clicks=20, spend=50, sales=100, orders=2)   # 50% ACoS
    flags = run_target_rules(m, t, _ctx())
    names = {f.flag for f in flags}
    assert "HIGH_ACOS" in names
    ha = next(f for f in flags if f.flag == "HIGH_ACOS")
    assert ha.new_bid is not None and ha.new_bid < 1.50


def test_no_high_acos_when_under_target():
    t = Thresholds(target_acos=0.25, min_spend=5)
    m = M.all_metrics(clicks=20, spend=15, sales=100, orders=3)   # 15% ACoS
    names = {f.flag for f in run_target_rules(m, t, _ctx())}
    assert "HIGH_ACOS" not in names


def test_wasted_spend_flag():
    t = Thresholds(min_spend=5)
    m = M.all_metrics(clicks=12, spend=20, sales=0, orders=0)
    flags = run_target_rules(m, t, _ctx())
    assert any(f.flag == "WASTED_SPEND" for f in flags)


def test_threshold_override_changes_outcome():
    m = M.all_metrics(clicks=20, spend=30, sales=100, orders=2)   # 30% ACoS
    strict = run_target_rules(m, Thresholds(target_acos=0.25), _ctx())
    loose = run_target_rules(m, Thresholds(target_acos=0.40), _ctx())
    assert any(f.flag == "HIGH_ACOS" for f in strict)     # 30% > 25% -> flag
    assert not any(f.flag == "HIGH_ACOS" for f in loose)  # 30% < 40% -> clean
