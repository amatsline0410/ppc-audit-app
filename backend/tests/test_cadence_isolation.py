"""Cross-cadence isolation, end-to-end over HTTP.

An upload into ONE cadence must be visible in that cadence only — every other
cadence's panel plan, flag audit, dashboard and upload-meta must stay empty.
This guards the whole chain (client query params -> pinned_db routing ->
per-cadence db files), not just the pipeline helpers.
"""
import pandas as pd
import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

STORE = "pytest-cadence-isolation"
Q = f"store={STORE}&project=default"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        r = c.post("/auth/login", json={"username": "SAdmin", "password": "RootPass"})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c
        c.delete(f"/stores/{STORE}")


def _bulk(tmp_path, terms=("blue widget",), name="bulk.xlsx"):
    """Minimal real-shaped SP bulk + SP Search Term Report sheet."""
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
    rows = [{"Campaign Id": "111", "Campaign Name": "C1", "Ad Group Id": "222",
             "Ad Group Name": "AG1", "Keyword Id": "444", "Keyword Text": "widget",
             "Match Type": "exact", "Customer Search Term": t,
             "Impressions": 500, "Clicks": 30, "Spend": 15.0, "Sales": 60.0,
             "Orders": 3, "Units": 3} for t in terms]
    path = tmp_path / name
    with pd.ExcelWriter(path) as xw:
        sp.to_excel(xw, sheet_name="Sponsored Products Campaigns", index=False)
        pd.DataFrame(rows).to_excel(xw, sheet_name="SP Search Term Report", index=False)
    return path


def test_full_month_upload_stays_in_full_month(client, tmp_path):
    with open(_bulk(tmp_path), "rb") as fh:
        r = client.post(f"/full-month/upload?{Q}&audit_type=full_month",
                        files={"file": ("bulk.xlsx", fh, "application/vnd.ms-excel")})
    assert r.status_code == 200, r.text
    assert r.json()["terms"] == 1

    # the uploaded cadence sees its plan
    r = client.get(f"/full-month/plan?{Q}&audit_type=full_month&target_acos=0.3")
    assert r.status_code == 200
    assert r.json()["upload_meta"]["rows"] == 1

    # every OTHER cadence panel has no data — and no upload meta
    for path in ("/mid-month/plan", "/weekly/plan", "/pause-scale/plan"):
        r = client.get(f"{path}?{Q}&target_acos=0.3")
        assert r.status_code == 400, f"{path} leaked: {r.text[:120]}"
    assert client.get(f"/daily-watch/days?{Q}").json()["days"] == []

    # generic flag audit + dashboard are empty for every other cadence
    for cad in ("weekly", "mid_month", "pause_scale", "daily"):
        flags = client.get(f"/audit?{Q}&audit_type={cad}&target_acos=0.3").json()
        assert flags == [], f"audit leaked into {cad}"
        dash = client.get(f"/dashboard?{Q}&audit_type={cad}&target_acos=0.3").json()
        assert dash.get("trees") in ([], None), f"dashboard leaked into {cad}"


def test_cadence_routes_ignore_ambient_audit_type(client, tmp_path):
    """A keep-alive panel fetching in the background carries the ACTIVE cadence's
    ?audit_type= — the cadence routes must ignore it (pinned to their own db)."""
    # full-month data exists (uploaded above); asking with audit_type=weekly must
    # still return the full-month plan (route pinned), not the weekly db
    r = client.get(f"/full-month/plan?{Q}&audit_type=weekly&target_acos=0.3")
    assert r.status_code == 200
    # and the weekly route with audit_type=full_month must NOT see full-month data
    r = client.get(f"/weekly/plan?{Q}&audit_type=full_month&target_acos=0.3")
    assert r.status_code == 400


def _post(client, path, bulk_path):
    with open(bulk_path, "rb") as fh:
        return client.post(path, files={"file": (bulk_path.name, fh, "application/vnd.ms-excel")})


def test_weekly_upload_stays_in_weekly(client, tmp_path):
    with open(_bulk(tmp_path), "rb") as fh:
        r = client.post(f"/weekly/upload?{Q}&audit_type=weekly&week=1",
                        files={"file": ("bulk.xlsx", fh, "application/vnd.ms-excel")})
    assert r.status_code == 200, r.text

    assert client.get(f"/weekly/plan?{Q}&target_acos=0.3").status_code == 200
    # mid-month / pause-scale still empty; full-month untouched by the weekly upload
    assert client.get(f"/mid-month/plan?{Q}&target_acos=0.3").status_code == 400
    assert client.get(f"/pause-scale/plan?{Q}&target_acos=0.3").status_code == 400
    r = client.get(f"/full-month/plan?{Q}&target_acos=0.3")
    assert r.status_code == 200 and r.json()["upload_meta"]["rows"] == 1

def test_every_cadence_keeps_its_own_data(client, tmp_path):
    """Each cadence gets a DIFFERENT bulk (different term counts). Every cadence
    must keep exactly its own upload; a later re-upload in one cadence must not
    change any other cadence's data (no overriding across frequencies).
    (Runs last in this module — it seeds every cadence.)"""
    terms = lambda n: tuple(f"term {i}" for i in range(n))
    assert _post(client, f"/full-month/upload?{Q}", _bulk(tmp_path, terms(2), "fm.xlsx")).status_code == 200
    assert _post(client, f"/mid-month/upload?{Q}", _bulk(tmp_path, terms(3), "mm.xlsx")).status_code == 200
    assert _post(client, f"/weekly/upload?{Q}&week=2", _bulk(tmp_path, terms(4), "wk.xlsx")).status_code == 200
    assert _post(client, f"/pause-scale/upload?{Q}", _bulk(tmp_path, terms(5), "ps.xlsx")).status_code == 200
    assert _post(client, f"/daily-watch/upload?{Q}&day=2026-07-20", _bulk(tmp_path, terms(1), "dw.xlsx")).status_code == 200

    def rows(path):
        r = client.get(f"{path}?{Q}&target_acos=0.3")
        assert r.status_code == 200, r.text
        return r.json()["upload_meta"]["rows"]

    assert rows("/full-month/plan") == 2
    assert rows("/mid-month/plan") == 3
    assert rows("/pause-scale/plan") == 5
    assert 2 in client.get(f"/weekly/weeks?{Q}").json()["weeks"]
    assert client.get(f"/daily-watch/days?{Q}").json()["days"] == ["2026-07-20"]

    # re-upload Full Month with a different file — nothing else may move
    assert _post(client, f"/full-month/upload?{Q}", _bulk(tmp_path, terms(7), "fm2.xlsx")).status_code == 200
    assert rows("/full-month/plan") == 7          # its own snapshot replaced
    assert rows("/mid-month/plan") == 3           # everyone else untouched
    assert rows("/pause-scale/plan") == 5
    assert 2 in client.get(f"/weekly/weeks?{Q}").json()["weeks"]
    assert client.get(f"/daily-watch/days?{Q}").json()["days"] == ["2026-07-20"]
