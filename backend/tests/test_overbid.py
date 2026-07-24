"""Overbid guardrail (rule 6): a bid over the hard cap — or several times the
observed CPC — is noise, not an anchor. It must reset to the computed target in
ONE pass instead of crawling down $0.20/cycle for years."""
from types import SimpleNamespace

from app.config import Thresholds
from app.pipeline import bid_optimizer as bo
from app.pipeline.weekly import compute_bid_tweaks


def _fact(**kw):
    base = dict(keyword_id="111111111111111111", product_targeting_id=None,
                campaign_id="c1", ad_group_id="g1", is_auto=False,
                keyword_text="pro ice shoulder and elbow", expression=None,
                match_type="phrase", state="enabled", bid=1.0,
                impressions=1000, clicks=0, spend=0.0, sales=0.0, orders=0)
    base.update(kw)
    return SimpleNamespace(**base)


def test_is_overbid():
    assert bo.is_overbid(39.18, "keyword_bid")                 # over the $5 hard cap
    assert bo.is_overbid(4.50, "keyword_bid", cpc=1.00)        # 3x+ CPC with $1+ gap
    assert not bo.is_overbid(0.60, "keyword_bid", cpc=0.15)    # 4x CPC but tiny $ gap
    assert not bo.is_overbid(2.50, "keyword_bid", cpc=1.00)    # under 3x CPC
    assert not bo.is_overbid(4.90, "keyword_bid")              # under cap, no CPC signal
    assert not bo.is_overbid(None, "keyword_bid")


def test_overbid_resets_in_one_pass():
    # the screenshot bug: $39.18 bid @ 88% ACoS was only stepped to $38.98
    t = Thresholds()
    rows = [_fact(bid=39.18, clicks=17, spend=30.0, sales=34.0, orders=2)]
    out = compute_bid_tweaks(rows, t)
    assert len(out) == 1
    r = out[0]
    assert r["overbid"] is True
    assert r["suggested_bid"] <= bo.caps_for("keyword_bid")[1]   # under the hard cap NOW
    assert r["reason"].startswith("overbid")


def test_normal_cut_still_step_limited():
    t = Thresholds()
    rows = [_fact(bid=2.50, clicks=20, spend=20.0, sales=22.7, orders=2)]
    out = compute_bid_tweaks(rows, t)
    assert len(out) == 1
    r = out[0]
    assert r["overbid"] is False
    assert r["suggested_bid"] == 2.30            # $0.20 per-pass step still applies


def test_optimize_row_overbid_skips_step():
    res = bo.optimize_row({"target_type": "keyword_bid", "current": 39.18,
                           "clicks": 30, "purchases": 5, "spend": 40.0,
                           "actual_acos": 88.0, "target_acos": 25.0})
    assert res["recommended"] <= bo.caps_for("keyword_bid")[1]
    assert "overbid" in res["reason"]


def test_optimize_row_normal_still_stepped():
    res = bo.optimize_row({"target_type": "keyword_bid", "current": 2.50,
                           "clicks": 30, "purchases": 5, "spend": 40.0,
                           "actual_acos": 88.0, "target_acos": 25.0})
    assert res["recommended"] == 2.30
