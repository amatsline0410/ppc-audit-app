"""Keywords-tab harvest: keyword terms only (ASIN-shaped terms hidden) and,
with ?project_id=, scoped to the keyword project's ASIN(s) via the bulk's
Product Ad rows."""
import pandas as pd
import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

STORE = "pytest-harvest-scope"
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
    """Two ad groups advertising two different ASINs, three STR terms:
    one converting keyword per ad group + one ASIN-shaped term."""
    sp = [dict(Entity="Campaign", **{"Campaign Id": "111", "Campaign Name": "C1"},
               State="enabled", **{"Targeting Type": "manual", "Daily Budget": 10})]
    for ag, asin in (("222", "B0AAAA1111"), ("333", "B0BBBB2222")):
        sp.append({"Entity": "Ad Group", "Campaign Id": "111", "Ad Group Id": ag,
                   "Ad Group Name": f"AG{ag}", "State": "enabled", "Ad Group Default Bid": 0.5})
        sp.append({"Entity": "Product Ad", "Campaign Id": "111", "Ad Group Id": ag,
                   "Ad Id": f"9{ag}", "ASIN": asin, "SKU": f"SKU-{ag}", "State": "enabled"})
        sp.append({"Entity": "Keyword", "Campaign Id": "111", "Ad Group Id": ag,
                   "Keyword Id": f"4{ag}", "Keyword Text": "widget", "Match Type": "broad",
                   "Bid": 0.75, "State": "enabled"})
    # third ad group with NO keyword rows: its ASIN-shaped term would be promoted
    # as a product target by the engine — the keywords-only filter must hide it
    sp.append({"Entity": "Ad Group", "Campaign Id": "111", "Ad Group Id": "444",
               "Ad Group Name": "AG444", "State": "enabled", "Ad Group Default Bid": 0.5})
    sp.append({"Entity": "Product Ad", "Campaign Id": "111", "Ad Group Id": "444",
               "Ad Id": "9444", "ASIN": "B0CCCC3333", "SKU": "SKU-444", "State": "enabled"})
    terms = []
    for ag, term in (("222", "arm ice wrap"), ("333", "knee brace"), ("444", "b0zzzzzz99")):
        terms.append({"Campaign Id": "111", "Campaign Name": "C1", "Ad Group Id": ag,
                      "Ad Group Name": f"AG{ag}", "Keyword Id": f"4{ag}" if ag != "444" else "",
                      "Keyword Text": "widget" if ag != "444" else "",
                      "Match Type": "broad" if ag != "444" else "",
                      "Customer Search Term": term, "Impressions": 400, "Clicks": 20,
                      "Spend": 10.0, "Sales": 60.0, "Orders": 3, "Units": 3})
    path = tmp_path / "bulk.xlsx"
    with pd.ExcelWriter(path) as xw:
        pd.DataFrame(sp).to_excel(xw, sheet_name="Sponsored Products Campaigns", index=False)
        pd.DataFrame(terms).to_excel(xw, sheet_name="SP Search Term Report", index=False)
    return path


def _harvest(client, path, extra=""):
    with open(path, "rb") as fh:
        r = client.post(f"/harvest/from-bulk?{Q}&target_acos=0.3{extra}",
                        files={"file": ("bulk.xlsx", fh, "application/vnd.ms-excel")})
    assert r.status_code == 200, r.text
    return r.json()


def test_asin_terms_hidden_and_project_scoping(client, tmp_path):
    path = _bulk(tmp_path)

    # unscoped: both keyword terms, ASIN term hidden
    out = _harvest(client, path)
    terms = {p["search_term"] for p in out["promotes"]}
    assert terms == {"arm ice wrap", "knee brace"}
    assert out["asin_terms_hidden"] == 1
    assert out["scope"] is None

    # project with primary ASIN B0AAAA1111 -> only its ad group's term remains
    r = client.post(f"/tracker/projects?{Q}",
                    json={"name": "Scope Test", "primary_asin": "B0AAAA1111"})
    assert r.status_code == 200, r.text
    pid = r.json()["project_id"]

    out = _harvest(client, path, f"&project_id={pid}")
    terms = {p["search_term"] for p in out["promotes"]}
    assert terms == {"arm ice wrap"}, terms
    assert out["scope"]["asins"] == ["B0AAAA1111"]
    assert out["scope"]["hidden"] == 1          # knee brace (other ASIN's ad group)


def test_ngrams_scoped_to_project_asins(client, tmp_path):
    """/ngrams with ?project_id= keeps only rows from ad groups advertising the
    project's ASIN(s) — terms from other ASINs never reach the gram mining."""
    path = _bulk(tmp_path)
    r = client.post(f"/tracker/projects?{Q}",
                    json={"name": "Ngram Scope", "primary_asin": "B0BBBB2222"})
    pid = r.json()["project_id"]

    with open(path, "rb") as fh:
        r = client.post(f"/ngrams?{Q}&target_acos=0.3&min_clicks=1&project_id={pid}",
                        files={"file": ("bulk.xlsx", fh, "application/vnd.ms-excel")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["scope"]["asins"] == ["B0BBBB2222"]
    assert d["scope"]["hidden_rows"] == 2          # ag 222 (other ASIN) + ag 444 rows
    words = {g["gram"] for g in d["grams"]}
    assert "knee" in words or "brace" in words     # only the B0BBBB2222 ad group's term
    assert "arm" not in words and "wrap" not in words


def test_ngrams_summary_asin_filter_and_export(client, tmp_path):
    """ASIN-pattern terms never reach gram mining; summary block present;
    export returns an xlsx with Summary + N-Grams sheets."""
    path = _bulk(tmp_path)
    with open(path, "rb") as fh:
        r = client.post(f"/ngrams?{Q}&target_acos=0.3&min_clicks=1",
                        files={"file": ("bulk.xlsx", fh, "application/vnd.ms-excel")})
    d = r.json()
    assert d["asin_terms_hidden"] == 1                      # b0zzzzzz99 row dropped
    assert d["summary"]["terms"] == 2 and d["summary"]["clicks"] == 40
    assert all("b0zzzzzz99" not in g["gram"] for g in d["grams"])

    r = client.post(f"/ngrams/export?{Q}", json={"grams": d["grams"], "summary": d["summary"]})
    assert r.status_code == 200
    import io
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert set(wb.sheetnames) == {"Summary", "N-Grams"}
