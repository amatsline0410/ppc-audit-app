"""Changing the Goal ACoS must change the computed plan — same upload, different
goal, different bid suggestions / harvest verdicts (guards the '25% -> 9% shows
the same results' bug end-to-end)."""
import pandas as pd
import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

STORE = "pytest-goal-acos"
Q = f"store={STORE}&project=default"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        r = c.post("/auth/login", json={"username": "SAdmin", "password": "RootPass"})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c
        c.delete(f"/stores/{STORE}")


def _bulk(tmp_path):
    sp = pd.DataFrame([
        dict(Entity="Campaign", **{"Campaign Id": "111", "Campaign Name": "C1"},
             State="enabled", **{"Targeting Type": "manual", "Daily Budget": 10},
             Impressions=1000, Clicks=50, Spend=25.0, Sales=100.0, Orders=5, Units=5),
        {"Entity": "Ad Group", "Campaign Id": "111", "Ad Group Id": "222",
         "Ad Group Name": "AG1", "State": "enabled", "Ad Group Default Bid": 0.5,
         "Impressions": 1000, "Clicks": 50, "Spend": 25.0, "Sales": 100.0,
         "Orders": 5, "Units": 5},
        {"Entity": "Product Ad", "Campaign Id": "111", "Ad Group Id": "222",
         "Ad Id": "333", "ASIN": "B00TEST0001", "SKU": "SKU-1", "State": "enabled",
         "Impressions": 1000, "Clicks": 50, "Spend": 25.0, "Sales": 100.0,
         "Orders": 5, "Units": 5},
        {"Entity": "Keyword", "Campaign Id": "111", "Ad Group Id": "222",
         "Keyword Id": "444", "Keyword Text": "widget", "Match Type": "exact",
         "Bid": 0.75, "State": "enabled", "Impressions": 800, "Clicks": 40,
         "Spend": 20.0, "Sales": 80.0, "Orders": 4, "Units": 4},
    ])
    # term ACoS = 25% with 3 orders: a winner at goal 25%, a bleeder at goal 9%
    term = {"Campaign Id": "111", "Campaign Name": "C1", "Ad Group Id": "222",
            "Ad Group Name": "AG1", "Keyword Id": "444", "Keyword Text": "widget",
            "Match Type": "exact", "Customer Search Term": "blue widget",
            "Impressions": 500, "Clicks": 30, "Spend": 15.0, "Sales": 60.0,
            "Orders": 3, "Units": 3}
    path = tmp_path / "bulk.xlsx"
    with pd.ExcelWriter(path) as xw:
        sp.to_excel(xw, sheet_name="Sponsored Products Campaigns", index=False)
        pd.DataFrame([term]).to_excel(xw, sheet_name="SP Search Term Report", index=False)
    return path


def _plan(client, path, target):
    r = client.get(f"{path}?{Q}&target_acos={target}")
    assert r.status_code == 200, r.text
    return r.json()


def test_plan_changes_with_goal_acos(client, tmp_path):
    bulk = _bulk(tmp_path)
    with open(bulk, "rb") as fh:
        assert client.post(f"/full-month/upload?{Q}",
                           files={"file": ("bulk.xlsx", fh, "application/vnd.ms-excel")}).status_code == 200
    with open(bulk, "rb") as fh:
        assert client.post(f"/pause-scale/upload?{Q}",
                           files={"file": ("bulk.xlsx", fh, "application/vnd.ms-excel")}).status_code == 200

    fm25, fm09 = _plan(client, "/full-month/plan", 0.25), _plan(client, "/full-month/plan", 0.09)
    # bid suggestions scale with the goal — must differ
    bids25 = [b["new_bid"] for b in fm25["bid_tweaks"]]
    bids09 = [b["new_bid"] for b in fm09["bid_tweaks"]]
    assert (bids25, len(fm25["promotes"]), len(fm25["bleeders"])) \
        != (bids09, len(fm09["promotes"]), len(fm09["bleeders"])), \
        "full-month plan identical at goal 25% vs 9%"

    ps25, ps09 = _plan(client, "/pause-scale/plan", 0.25), _plan(client, "/pause-scale/plan", 0.09)
    assert ps25 != ps09, "pause-scale plan identical at goal 25% vs 9%"

def test_audit_tile_recomputes_at_current_goal(client, tmp_path):
    """POST /cadence/runs with refresh=true must recompute flags at the new goal
    (stored run numbers alone would keep showing the old goal's results)."""
    def run(target, refresh=True):
        r = client.post(f"/cadence/runs?{Q}&audit_type=full_month",
                        json={"year": 2026, "month": 7, "audit_type": "full_month",
                              "target_acos": target, "refresh": refresh})
        assert r.status_code == 200, r.text
        return r.json()

    flags25 = run(0.25)["flags"]
    flags09 = run(0.09)["flags"]
    assert flags09 != flags25, "re-audit returned identical flags at goal 25% vs 9%"
    # keyword ACoS is 25% -> tightening the goal to 9% must flag MORE, not fewer
    assert flags09 > flags25
