"""What-if SEO scorecard preview: current card vs projected if the mined pool
were pushed (Cerebro-ranked keywords project into ranked/page-1)."""
import pandas as pd
import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

STORE = "pytest-kw-preview"
Q = f"store={STORE}&project=default"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        r = c.post("/auth/login", json={"username": "SAdmin", "password": "RootPass"})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c
        c.delete(f"/stores/{STORE}")


def test_preview_projects_ranked_and_denominator(client, tmp_path):
    # cerebro pool: 1 keyword ranked page-1 (rank 8), 1 ranked deep (120), 1 unranked
    path = tmp_path / "cerebro.csv"
    pd.DataFrame([
        {"Keyword Phrase": "ice sleeve", "Search Volume": 1200, "Organic Rank": 8},
        {"Keyword Phrase": "arm wrap", "Search Volume": 700, "Organic Rank": 120},
        {"Keyword Phrase": "cold therapy", "Search Volume": 300, "Organic Rank": ""},
    ]).to_csv(path, index=False)
    with open(path, "rb") as fh:
        r = client.post(f"/keywords/upload?{Q}&source=cerebro",
                        files={"file": ("cerebro.csv", fh, "text/csv")})
    assert r.status_code == 200, r.text

    r = client.post(f"/tracker/projects?{Q}",
                    json={"name": "Preview Test", "primary_asin": "B0AAAA1111"})
    pid = r.json()["project_id"]

    r = client.get(f"/keywords/project-preview?{Q}&project_id={pid}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["pool"] == {"total": 3, "new": 3, "already_tracked": 0,
                         "with_cerebro_rank": 2, "page1_candidates": 1}
    # blank project: current 0/0, projected 2 ranked of 3 tracked
    assert d["current"]["tracked"] == 0 and d["current"]["ranked"] == 0
    assert d["projected"]["tracked"] == 3 and d["projected"]["ranked"] == 2
    assert d["projected"]["indexed"] == round(2 / 3, 4)
    assert d["projected"]["page1"] == 1 and d["projected"]["top10"] == 1
    assert d["projected"]["avg_rank"] == 64.0    # (8 + 120) / 2

    # push, then preview again: everything already tracked -> projection = current
    assert client.post(f"/keywords/to-project?{Q}", json={"project_id": pid}).status_code == 200
    d2 = client.get(f"/keywords/project-preview?{Q}&project_id={pid}").json()
    assert d2["pool"]["new"] == 0 and d2["pool"]["already_tracked"] == 3
    assert d2["projected"]["tracked"] == d2["current"]["tracked"] == 3


def test_pool_scorecard_indexed_and_listing_coverage(client, tmp_path):
    """Fresh store: pool of 4 (2 cerebro-ranked, 1 page-1) + current listing copy
    covering one keyword -> pool indexed 50%, listing coverage 25%."""
    Q2 = "store=pytest-kw-pool&project=default"
    path = tmp_path / "cerebro2.csv"
    pd.DataFrame([
        {"Keyword Phrase": "ice sleeve", "Search Volume": 1200, "Organic Rank": 8},
        {"Keyword Phrase": "arm wrap", "Search Volume": 700, "Organic Rank": 120},
        {"Keyword Phrase": "cold therapy", "Search Volume": 300, "Organic Rank": ""},
        {"Keyword Phrase": "shoulder brace", "Search Volume": 200, "Organic Rank": ""},
    ]).to_csv(path, index=False)
    with open(path, "rb") as fh:
        assert client.post(f"/keywords/upload?{Q2}&source=cerebro",
                           files={"file": ("cerebro2.csv", fh, "text/csv")}).status_code == 200
    pid = client.post(f"/tracker/projects?{Q2}",
                      json={"name": "Pool Test", "primary_asin": "B0AAAA2222"}).json()["project_id"]
    # current listing copy covers "ice sleeve" only
    assert client.put(f"/tracker/listing?{Q2}", json={
        "project_id": pid, "variant": "current", "element": "title",
        "text": "Pro Ice Sleeve for Pitchers"}).status_code == 200

    ps = client.get(f"/keywords/project-preview?{Q2}&project_id={pid}").json()["pool_scorecard"]
    assert ps["total"] == 4 and ps["ranked"] == 2 and ps["indexed"] == 0.5
    assert ps["page1"] == 1 and ps["top10"] == 1 and ps["avg_rank"] == 64.0
    assert ps["listing"]["has_copy"] is True
    assert ps["listing"]["covered"] == 1 and ps["listing"]["coverage"] == 0.25
    assert ps["by_source"]["cerebro"]["total"] == 4 and ps["by_source"]["sqp"]["total"] == 0
    client.delete("/stores/pytest-kw-pool")


def test_keywords_rows_stamped_indexed(client, tmp_path):
    """GET /keywords?project_id= stamps each row: 'ranked' (Cerebro rank),
    'listing' (covered by current copy), or None."""
    Q3 = "store=pytest-kw-indexed&project=default"
    path = tmp_path / "cerebro3.csv"
    pd.DataFrame([
        {"Keyword Phrase": "beach umbrella", "Search Volume": 1000, "Organic Rank": 12},
        {"Keyword Phrase": "pool bag", "Search Volume": 500, "Organic Rank": ""},
        {"Keyword Phrase": "boat tube", "Search Volume": 300, "Organic Rank": ""},
    ]).to_csv(path, index=False)
    with open(path, "rb") as fh:
        assert client.post(f"/keywords/upload?{Q3}&source=cerebro",
                           files={"file": ("cerebro3.csv", fh, "text/csv")}).status_code == 200
    pid = client.post(f"/tracker/projects?{Q3}",
                      json={"name": "Idx Test", "primary_asin": "B0AAAA3333"}).json()["project_id"]
    assert client.put(f"/tracker/listing?{Q3}", json={
        "project_id": pid, "variant": "current", "element": "title",
        "text": "Waterproof Pool Bag for the Beach"}).status_code == 200

    d = client.get(f"/keywords?{Q3}&project_id={pid}").json()
    by = {r["keyword"]: r.get("indexed") for r in d["rows"]}
    assert by["beach umbrella"] == "ranked"     # Cerebro organic rank
    assert by["pool bag"] == "listing"          # both words in current title
    assert by["boat tube"] is None
    assert d["has_listing_copy"] is True
    # without project_id: no stamping
    d2 = client.get(f"/keywords?{Q3}").json()
    assert all("indexed" not in r for r in d2["rows"])
    client.delete("/stores/pytest-kw-indexed")


def test_selection_scoped_preview_and_push(client, tmp_path):
    """POST preview/to-project with `keywords` computes over the selection only."""
    Q4 = "store=pytest-kw-select&project=default"
    path = tmp_path / "cerebro4.csv"
    pd.DataFrame([
        {"Keyword Phrase": "ice sleeve", "Search Volume": 1200, "Organic Rank": 8},
        {"Keyword Phrase": "arm wrap", "Search Volume": 700, "Organic Rank": 120},
        {"Keyword Phrase": "cold therapy", "Search Volume": 300, "Organic Rank": ""},
    ]).to_csv(path, index=False)
    with open(path, "rb") as fh:
        assert client.post(f"/keywords/upload?{Q4}&source=cerebro",
                           files={"file": ("cerebro4.csv", fh, "text/csv")}).status_code == 200
    pid = client.post(f"/tracker/projects?{Q4}",
                      json={"name": "Select Test", "primary_asin": "B0AAAA4444"}).json()["project_id"]

    # selection of 1 ranked keyword -> pool of 1, projected 1/1 indexed
    d = client.post(f"/keywords/project-preview?{Q4}", json={
        "project_id": pid, "keywords": ["ice sleeve"]}).json()
    assert d["pool"]["total"] == 1 and d["pool"]["new"] == 1
    assert d["projected"]["tracked"] == 1 and d["projected"]["ranked"] == 1
    assert d["pool_scorecard"]["total"] == 1 and d["pool_scorecard"]["indexed"] == 1.0

    # selection push: only that keyword lands
    r = client.post(f"/keywords/to-project?{Q4}", json={
        "project_id": pid, "keywords": ["ice sleeve"]}).json()
    assert r["added"] == 1 and r["total"] == 1
    client.delete("/stores/pytest-kw-select")


def test_impression_share_and_str_source(client, tmp_path):
    """Harvest bulk upload merges STR terms into the mined pool (source STR);
    Impression Share = STR impressions / total search volume x 100 over keywords
    present in BOTH the research and the harvest."""
    Q5 = "store=pytest-kw-str&project=default"
    # research: search volumes
    path = tmp_path / "sqp.csv"
    pd.DataFrame([
        {"Search Query": "arm ice wrap", "Search Query Volume": 4000,
         "Impressions: Total Count": 100, "Clicks: Total Count": 10, "Purchases: Total Count": 1},
        {"Search Query": "knee brace", "Search Query Volume": 6000,
         "Impressions: Total Count": 200, "Clicks: Total Count": 20, "Purchases: Total Count": 2},
    ]).to_csv(path, index=False)
    with open(path, "rb") as fh:
        assert client.post(f"/keywords/upload?{Q5}&source=sqp",
                           files={"file": ("sqp.csv", fh, "text/csv")}).status_code == 200

    # harvest bulk: STR carries impressions for ONE of those keywords (400 imps)
    sp = [dict(Entity="Campaign", **{"Campaign Id": "111", "Campaign Name": "C1"},
               State="enabled", **{"Targeting Type": "manual", "Daily Budget": 10}),
          {"Entity": "Ad Group", "Campaign Id": "111", "Ad Group Id": "222",
           "Ad Group Name": "AG1", "State": "enabled", "Ad Group Default Bid": 0.5},
          {"Entity": "Product Ad", "Campaign Id": "111", "Ad Group Id": "222",
           "Ad Id": "9222", "ASIN": "B0AAAA5555", "SKU": "SKU-1", "State": "enabled"},
          {"Entity": "Keyword", "Campaign Id": "111", "Ad Group Id": "222",
           "Keyword Id": "4222", "Keyword Text": "widget", "Match Type": "broad",
           "Bid": 0.75, "State": "enabled"}]
    term = {"Campaign Id": "111", "Campaign Name": "C1", "Ad Group Id": "222",
            "Ad Group Name": "AG1", "Keyword Id": "4222", "Keyword Text": "widget",
            "Match Type": "broad", "Customer Search Term": "arm ice wrap",
            "Impressions": 400, "Clicks": 20, "Spend": 10.0, "Sales": 60.0,
            "Orders": 3, "Units": 3}
    bulk = tmp_path / "bulk-str.xlsx"
    with pd.ExcelWriter(bulk) as xw:
        pd.DataFrame(sp).to_excel(xw, sheet_name="Sponsored Products Campaigns", index=False)
        pd.DataFrame([term]).to_excel(xw, sheet_name="SP Search Term Report", index=False)
    with open(bulk, "rb") as fh:
        r = client.post(f"/harvest/from-bulk?{Q5}&target_acos=0.3",
                        files={"file": ("bulk.xlsx", fh, "application/vnd.ms-excel")})
    assert r.status_code == 200, r.text
    assert r.json()["pool_merged"]["merged"] == 1     # merged into existing SQP row

    # pool now tags the term with STR source
    d = client.get(f"/keywords?{Q5}").json()
    by = {x["keyword"]: x for x in d["rows"]}
    assert "STR" in by["arm ice wrap"]["sources"] and by["arm ice wrap"]["str_impressions"] == 400
    assert d["str"] == 1

    # impression share over the overlap: 400 / 4000 x 100 = 10%
    pid = client.post(f"/tracker/projects?{Q5}",
                      json={"name": "IS Test", "primary_asin": "B0AAAA5555"}).json()["project_id"]
    ish = client.get(f"/keywords/project-preview?{Q5}&project_id={pid}").json()["impression_share"]
    assert ish["keywords"] == 1 and ish["impressions"] == 400 and ish["search_volume"] == 4000
    assert ish["share"] == 10.0
    # not-indexed points present in the pool scorecard
    ps = client.get(f"/keywords/project-preview?{Q5}&project_id={pid}").json()["pool_scorecard"]
    assert ps["not_indexed"] == 2       # neither keyword ranked nor in listing copy
    client.delete("/stores/pytest-kw-str")


def test_empty_selection_keeps_pool_insight(client, tmp_path):
    """POST with keywords=[]: forecast equals current, but the insight blocks
    (pool scorecard / impression share) fall back to the whole pool."""
    Q6 = "store=pytest-kw-empty&project=default"
    path = tmp_path / "cerebro6.csv"
    pd.DataFrame([
        {"Keyword Phrase": "ice sleeve", "Search Volume": 1200, "Organic Rank": 8},
        {"Keyword Phrase": "arm wrap", "Search Volume": 700, "Organic Rank": ""},
    ]).to_csv(path, index=False)
    with open(path, "rb") as fh:
        assert client.post(f"/keywords/upload?{Q6}&source=cerebro",
                           files={"file": ("cerebro6.csv", fh, "text/csv")}).status_code == 200
    pid = client.post(f"/tracker/projects?{Q6}",
                      json={"name": "Empty Test", "primary_asin": "B0AAAA6666"}).json()["project_id"]

    d = client.post(f"/keywords/project-preview?{Q6}", json={
        "project_id": pid, "keywords": []}).json()
    assert d["pool"]["total"] == 0 and d["pool"]["new"] == 0
    assert d["projected"]["tracked"] == d["current"]["tracked"]      # forecast = current
    assert d["pool_scorecard"]["scope"] == "pool"
    assert d["pool_scorecard"]["total"] == 2 and d["pool_scorecard"]["ranked"] == 1
    # with a selection, insight narrows too
    d2 = client.post(f"/keywords/project-preview?{Q6}", json={
        "project_id": pid, "keywords": ["arm wrap"]}).json()
    assert d2["pool_scorecard"]["scope"] == "selection" and d2["pool_scorecard"]["total"] == 1
    client.delete("/stores/pytest-kw-empty")


def test_full_keywords_export(client):
    """POST /keywords/export builds one workbook from whatever the tab shows."""
    import io
    import openpyxl
    r = client.post(f"/keywords/export?{Q}", json={
        "project": {"name": "Export Test", "primary_asin": "B0AAAA9999", "tracked_keywords": 5},
        "forecast": {"current": {"indexed": 0.23, "page1": 110, "tracked": 2392},
                     "projected": {"indexed": 0.226, "page1": 112, "tracked": 2504}},
        "pool_scorecard": {"total": 10, "ranked": 4, "indexed": 0.4, "not_indexed": 5},
        "impression_share": {"keywords": 3, "impressions": 400, "search_volume": 4000, "share": 10.0},
        "mined": [{"keyword": "pool floats", "search_volume": 516035, "sources": ["Cerebro"]}],
        "recommend": [{"keyword": "beach bag", "score": 12, "reason": "dual-source"}],
        "harvest": [{"search_term": "arm ice wrap", "action": "promote", "orders": 3}],
        "ngrams": [{"gram": "pool", "n": 1, "verdict": "winner", "clicks": 30}],
        "ngram_summary": {"terms": 100, "winners": 5, "wasters": 3},
    })
    assert r.status_code == 200, r.text
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert set(wb.sheetnames) == {"Summary", "Mined Keywords", "Recommendations", "Harvest", "N-Grams"}
    # sources list flattened to a readable string
    mk = wb["Mined Keywords"]
    header = [c.value for c in mk[1]]
    row = [c.value for c in mk[2]]
    assert row[header.index("sources")] == "Cerebro"


def test_backend_terms_recommendation(client, tmp_path):
    """Backend Search Terms line: highest-volume keywords' words NOT already in
    the current visible copy, deduped, byte-capped."""
    Q7 = "store=pytest-kw-bt&project=default"
    path = tmp_path / "cerebro7.csv"
    pd.DataFrame([
        {"Keyword Phrase": "pool floats", "Search Volume": 516035, "Organic Rank": ""},
        {"Keyword Phrase": "beach umbrella", "Search Volume": 454016, "Organic Rank": ""},
        {"Keyword Phrase": "pool bag", "Search Volume": 48356, "Organic Rank": ""},
    ]).to_csv(path, index=False)
    with open(path, "rb") as fh:
        assert client.post(f"/keywords/upload?{Q7}&source=cerebro",
                           files={"file": ("cerebro7.csv", fh, "text/csv")}).status_code == 200
    pid = client.post(f"/tracker/projects?{Q7}",
                      json={"name": "BT Test", "primary_asin": "B0AAAA7777"}).json()["project_id"]
    # current copy already contains "pool" -> only new words qualify
    assert client.put(f"/tracker/listing?{Q7}", json={
        "project_id": pid, "variant": "current", "element": "title",
        "text": "Giant Pool Toy"}).status_code == 200

    d = client.get(f"/keywords/backend-terms?{Q7}&project_id={pid}").json()
    words = d["line"].split()
    assert "pool" not in words                      # already in visible copy
    assert "floats" in words and "beach" in words and "umbrella" in words and "bag" in words
    assert d["bytes"] <= d["limit"] and d["has_copy"] is True
    assert len(words) == len(set(words))            # deduped
    client.delete("/stores/pytest-kw-bt")


def test_listing_forecast_proposed_copy(client, tmp_path):
    """'In listing' forecast: 0 without proposed copy; with proposed copy, counts
    how many forecast keywords the new copy would index."""
    Q8 = "store=pytest-kw-lf&project=default"
    path = tmp_path / "cerebro8.csv"
    pd.DataFrame([
        {"Keyword Phrase": "pool floats", "Search Volume": 1000, "Organic Rank": ""},
        {"Keyword Phrase": "beach umbrella", "Search Volume": 900, "Organic Rank": ""},
    ]).to_csv(path, index=False)
    with open(path, "rb") as fh:
        assert client.post(f"/keywords/upload?{Q8}&source=cerebro",
                           files={"file": ("cerebro8.csv", fh, "text/csv")}).status_code == 200
    pid = client.post(f"/tracker/projects?{Q8}",
                      json={"name": "LF Test", "primary_asin": "B0AAAA8888"}).json()["project_id"]

    sel = {"project_id": pid, "keywords": ["pool floats", "beach umbrella"]}
    lf = client.post(f"/keywords/project-preview?{Q8}", json=sel).json()["listing_forecast"]
    assert lf["has_proposed"] is False and lf["proposed_covered"] == 0 and lf["gain"] == 0

    # proposed copy covers "pool floats" only
    assert client.put(f"/tracker/listing?{Q8}", json={
        "project_id": pid, "variant": "proposed", "element": "title",
        "text": "Giant Pool Floats for Adults"}).status_code == 200
    lf = client.post(f"/keywords/project-preview?{Q8}", json=sel).json()["listing_forecast"]
    assert lf["has_proposed"] is True
    assert lf["current_covered"] == 0 and lf["proposed_covered"] == 1 and lf["gain"] == 1
    client.delete("/stores/pytest-kw-lf")


def test_backend_terms_harvest_basis(client, tmp_path):
    """basis=harvest orders by STR proof (orders desc) and only uses STR keywords."""
    Q9 = "store=pytest-kw-bth&project=default"
    # research keyword without STR data (must NOT appear under harvest basis)
    path = tmp_path / "cerebro9.csv"
    pd.DataFrame([{"Keyword Phrase": "beach umbrella", "Search Volume": 999999,
                   "Organic Rank": ""}]).to_csv(path, index=False)
    with open(path, "rb") as fh:
        assert client.post(f"/keywords/upload?{Q9}&source=cerebro",
                           files={"file": ("cerebro9.csv", fh, "text/csv")}).status_code == 200
    # harvest bulk: two STR terms, "arm ice wrap" has more orders than "knee brace"
    sp = [dict(Entity="Campaign", **{"Campaign Id": "111", "Campaign Name": "C1"},
               State="enabled", **{"Targeting Type": "manual", "Daily Budget": 10}),
          {"Entity": "Ad Group", "Campaign Id": "111", "Ad Group Id": "222",
           "Ad Group Name": "AG1", "State": "enabled", "Ad Group Default Bid": 0.5},
          {"Entity": "Product Ad", "Campaign Id": "111", "Ad Group Id": "222",
           "Ad Id": "9222", "ASIN": "B0AAAA1010", "SKU": "SKU-1", "State": "enabled"},
          {"Entity": "Keyword", "Campaign Id": "111", "Ad Group Id": "222",
           "Keyword Id": "4222", "Keyword Text": "widget", "Match Type": "broad",
           "Bid": 0.75, "State": "enabled"}]
    terms = [{"Campaign Id": "111", "Campaign Name": "C1", "Ad Group Id": "222",
              "Ad Group Name": "AG1", "Keyword Id": "4222", "Keyword Text": "widget",
              "Match Type": "broad", "Customer Search Term": t, "Impressions": 400,
              "Clicks": 20, "Spend": 10.0, "Sales": 60.0, "Orders": o, "Units": o}
             for t, o in (("arm ice wrap", 9), ("knee brace", 2))]
    bulk = tmp_path / "bulk-bth.xlsx"
    with pd.ExcelWriter(bulk) as xw:
        pd.DataFrame(sp).to_excel(xw, sheet_name="Sponsored Products Campaigns", index=False)
        pd.DataFrame(terms).to_excel(xw, sheet_name="SP Search Term Report", index=False)
    with open(bulk, "rb") as fh:
        assert client.post(f"/harvest/from-bulk?{Q9}&target_acos=0.3",
                           files={"file": ("bulk.xlsx", fh, "application/vnd.ms-excel")}).status_code == 200
    pid = client.post(f"/tracker/projects?{Q9}",
                      json={"name": "BTH Test", "primary_asin": "B0AAAA1010"}).json()["project_id"]

    d = client.get(f"/keywords/backend-terms?{Q9}&project_id={pid}&basis=harvest").json()
    words = d["line"].split()
    assert d["basis"] == "harvest"
    assert "umbrella" not in words                       # research-only keyword excluded
    assert words.index("arm") < words.index("knee")      # more orders first
    client.delete("/stores/pytest-kw-bth")


def test_listing_demand_comparison(client, tmp_path):
    """Demand totals: current copy's covered keywords + selection's contribution."""
    Q10 = "store=pytest-kw-ld&project=default"
    path = tmp_path / "cerebro10.csv"
    pd.DataFrame([
        {"Keyword Phrase": "pool floats", "Search Volume": 300, "Organic Rank": ""},
        {"Keyword Phrase": "beach umbrella", "Search Volume": 200, "Organic Rank": ""},
        {"Keyword Phrase": "pool toy", "Search Volume": 100, "Organic Rank": ""},
    ]).to_csv(path, index=False)
    with open(path, "rb") as fh:
        assert client.post(f"/keywords/upload?{Q10}&source=cerebro",
                           files={"file": ("cerebro10.csv", fh, "text/csv")}).status_code == 200
    pid = client.post(f"/tracker/projects?{Q10}",
                      json={"name": "LD Test", "primary_asin": "B0AAAA1212"}).json()["project_id"]
    # current copy covers "pool toy" (100)
    assert client.put(f"/tracker/listing?{Q10}", json={
        "project_id": pid, "variant": "current", "element": "title",
        "text": "Big Pool Toy"}).status_code == 200

    # select "pool floats" (300): current 100 -> projected 400 (+300)
    d = client.post(f"/keywords/project-preview?{Q10}", json={
        "project_id": pid, "keywords": ["pool floats"]}).json()["listing_demand"]
    assert d["current"]["search_volume"] == 100
    assert d["added"]["search_volume"] == 300
    assert d["projected"]["search_volume"] == 400
    assert d["current_keywords"] == 1 and d["added_keywords"] == 1

    # selecting an already-covered keyword adds nothing
    d = client.post(f"/keywords/project-preview?{Q10}", json={
        "project_id": pid, "keywords": ["pool toy"]}).json()["listing_demand"]
    assert d["added"]["search_volume"] == 0 and d["projected"]["search_volume"] == 100
    client.delete("/stores/pytest-kw-ld")
