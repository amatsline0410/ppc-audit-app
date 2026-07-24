"""Consultation engine: tier routing by ASIN count + tier-tuned problem scan."""
import pandas as pd
import pytest

from app.pipeline import consult as ct


@pytest.mark.parametrize("n,tier", [
    (1, 1), (5, 1), (6, 2), (20, 2), (21, 3), (50, 3), (51, 4), (100, 4),
    (101, 5), (500, 5), (501, 6), (1000, 6), (1001, 7), (50000, 7),
])
def test_tier_for_boundaries(n, tier):
    assert ct.tier_for(n)["tier"] == tier


def test_tier_for_empty():
    assert ct.tier_for(0) is None and ct.tier_for(None) is None


def _bulk(tmp_path, n_asins=2, mixed=False):
    """Synthetic SP bulk: n ASINs, one wasted-spend keyword, one high-ACoS keyword,
    one underexposed winner, plus an STR sheet with a harvest candidate."""
    rows = [dict(Entity="Campaign", **{"Campaign Id": "111", "Campaign Name": "C1"},
                 State="enabled", **{"Targeting Type": "manual", "Daily Budget": 10},
                 Impressions=1000, Clicks=50, Spend=25.0, Sales=100.0, Orders=5, Units=5),
            {"Entity": "Ad Group", "Campaign Id": "111", "Ad Group Id": "222",
             "Ad Group Name": "AG1", "State": "enabled", "Ad Group Default Bid": 0.5}]
    for i in range(n_asins):
        rows.append({"Entity": "Product Ad", "Campaign Id": "111",
                     "Ad Group Id": "222" if (mixed or i == 0) else f"22{i+2}",
                     "Ad Id": f"33{i}", "ASIN": f"B00TEST{i:04d}", "SKU": f"SKU-{i}",
                     "State": "enabled"})
    # wasted spend: $9 spent, 0 orders (over tier-1 min_spend 5, under tier-4 min_spend 10)
    rows.append({"Entity": "Keyword", "Campaign Id": "111", "Ad Group Id": "222",
                 "Keyword Id": "441", "Keyword Text": "loser kw", "Match Type": "broad",
                 "Bid": 0.75, "State": "enabled", "Impressions": 500, "Clicks": 12,
                 "Spend": 9.0, "Sales": 0.0, "Orders": 0, "Units": 0})
    # high acos: 20 clicks (over tier-1 min_clicks 15, at tier-4's 20 boundary), ACoS 60%
    rows.append({"Entity": "Keyword", "Campaign Id": "111", "Ad Group Id": "222",
                 "Keyword Id": "442", "Keyword Text": "expensive kw", "Match Type": "exact",
                 "Bid": 1.50, "State": "enabled", "Impressions": 2000, "Clicks": 21,
                 "Spend": 30.0, "Sales": 50.0, "Orders": 2, "Units": 2})
    # underexposed winner: ACoS 10%, 400 impressions (< min_impr 1000)
    rows.append({"Entity": "Keyword", "Campaign Id": "111", "Ad Group Id": "222",
                 "Keyword Id": "443", "Keyword Text": "winner kw", "Match Type": "exact",
                 "Bid": 0.50, "State": "enabled", "Impressions": 400, "Clicks": 10,
                 "Spend": 5.0, "Sales": 50.0, "Orders": 3, "Units": 3})
    term = {"Campaign Id": "111", "Campaign Name": "C1", "Ad Group Id": "222",
            "Ad Group Name": "AG1", "Keyword Id": "441", "Keyword Text": "loser kw",
            "Match Type": "broad", "Customer Search Term": "great term",
            "Impressions": 300, "Clicks": 6, "Spend": 3.0, "Sales": 30.0,
            "Orders": 2, "Units": 2}
    path = tmp_path / f"bulk-{n_asins}-{mixed}.xlsx"
    with pd.ExcelWriter(path) as xw:
        pd.DataFrame(rows).to_excel(xw, sheet_name="Sponsored Products Campaigns", index=False)
        pd.DataFrame([term]).to_excel(xw, sheet_name="SP Search Term Report", index=False)
    return path


def test_analyze_routes_and_flags(tmp_path):
    out = ct.analyze(str(_bulk(tmp_path, n_asins=2)), 0.30)
    assert out["asin_count"] == 2 and out["tier"]["tier"] == 1
    c = out["counts"]
    assert c.get("WASTED_SPEND") == 1        # $9 >= tier-1 min_spend 5, 0 orders
    assert c.get("HIGH_ACOS") == 1           # 21 clicks > 15, ACoS 60% > 36%
    assert c.get("RAISE_WINNER") == 1        # ACoS 10% < 24%, 400 impr < 1000
    assert c.get("HARVEST_CANDIDATE") == 1   # 6 clicks / 2 orders
    for plist in out["problems"].values():
        for p in plist:
            assert p["resolution"]


def test_tier_thresholds_gate_problems(tmp_path):
    """Same bulk, tier override 4 (min_spend 10, min_clicks 20): the $9 wasted-spend
    keyword no longer qualifies — higher tiers demand more evidence."""
    path = str(_bulk(tmp_path, n_asins=2))
    t1 = ct.analyze(path, 0.30)                       # tier 1 gates
    t4 = ct.analyze(path, 0.30, tier_override=4)      # tier 4 gates
    assert t1["counts"].get("WASTED_SPEND") == 1
    assert "WASTED_SPEND" not in t4["counts"]
    assert t4["tier_overridden"] is True and t4["auto_tier"] == 1


def test_mixed_ad_group_policy(tmp_path):
    """Tier 1: mixed ad group = error rows. Tier 7: suppressed (count only)."""
    path = str(_bulk(tmp_path, n_asins=3, mixed=True))
    t1 = ct.analyze(path, 0.30)
    assert t1["counts"].get("MIXED_AD_GROUP") == 1
    assert t1["problems"]["MIXED_AD_GROUP"][0]["severity"] == "error"
    t7 = ct.analyze(path, 0.30, tier_override=7)
    assert "MIXED_AD_GROUP" not in t7["counts"]
    assert t7["mixed_suppressed"] == 1
