"""Base fulfillment + referral fee per unit (Selling economics / Fee Preview)."""
import pytest

from app import database as dbmod
from app.pipeline import catalog as cat
from app.pipeline import fbafees as fba
from app.pipeline import transactions as txn


HEADER = ("sku,fnsku,asin,product-name,your-price,currency,product-size-tier,"
          "estimated-referral-fee-per-unit,base-fulfilment-fee-per-unit\n")


def _write(tmp_path, body, header=HEADER, name="fee_preview.csv"):
    p = tmp_path / name
    p.write_text(header + body)
    return str(p)


def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(dbmod, "_store_dir", lambda sid: str(tmp_path))


def test_parse_base_fulfillment_fee(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    path = _write(tmp_path,
                  "PI-100,X001,B0AAA11111,Widget,29.99,USD,Large standard,$4.50,$5.68\n"
                  "PI-200,X002,B0BBB22222,Gadget,9.99,USD,Small standard,1.50,3.22\n")
    rows = fba.parse_fee_preview(path)
    assert [r["sku"] for r in rows] == ["PI-100", "PI-200"]
    assert rows[0]["fulfillment_fee"] == 5.68
    assert rows[0]["asin"] == "B0AAA11111"
    assert rows[0]["referral_pct"] == pytest.approx(0.15, abs=1e-3)   # 4.50 / 29.99
    assert rows[1]["fulfillment_fee"] == 3.22
    assert rows[0]["size_tier"] == "Large standard"


def test_parse_tolerates_column_drift(tmp_path, monkeypatch):
    """American spelling, 'expected-domestic-...' naming, tab-separated, preamble."""
    _store(tmp_path, monkeypatch)
    p = tmp_path / "fees.txt"
    p.write_text("Fee Preview report generated 2026-07-01\n\n"
                 "seller-sku\tasin\tyour-price\texpected-domestic-fulfillment-fee-per-unit\n"
                 "PI-100\tB0AAA11111\t29.99\t5.68\n")
    rows = fba.parse_fee_preview(str(p))
    assert rows[0]["sku"] == "PI-100" and rows[0]["fulfillment_fee"] == 5.68


def test_parse_old_schema_sums_pick_pack_and_weight(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    path = _write(tmp_path, "PI-100,X,B0AAA11111,29.99,3.00,1.50\n",
                  header="sku,fnsku,asin,your-price,estimated-pick-pack-fee-per-unit,"
                         "estimated-weight-handling-fee-per-unit\n")
    assert fba.parse_fee_preview(path)[0]["fulfillment_fee"] == 4.50


def test_parse_rejects_wrong_file(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    # no fee column anywhere -> no header row qualifies
    path = _write(tmp_path, "PI-100,29.99\n", header="sku,your-price\n")
    with pytest.raises(ValueError, match="doesn't look like a fee report"):
        fba.parse_fees(path)
    # a fee-shaped header that quotes only totals -> nothing usable per unit
    path = _write(tmp_path, "PI-100,120.00\n",
                  header="sku,base-fulfilment-fee-total\n")
    with pytest.raises(ValueError, match="No rows with a fulfillment or referral fee"):
        fba.parse_fees(path)


# Selling economics (SKU Economics) export — real column shape: Parent ASIN AND
# ASIN, an EMPTY MSKU column, per-unit + quantity + total triplets per fee, and
# most rows quoting no fee at all (zero-sales ASINs).
ECON_H = ("Amazon store,Start date,End date,Parent ASIN,ASIN,FNSKU,MSKU,Currency code,"
          "Average sales price,Units sold,Sales,"
          "Base fulfillment fee per unit,Base fulfillment fee quantity,Base fulfillment fee total,"
          "FBA fulfillment fees per unit,FBA fulfillment fees quantity,FBA fulfillment fees total,"
          "Referral Fee Refunds per unit,Referral fee per unit,Referral fee quantity,"
          "Referral fee total\n")
ECON_ROWS = (
    # zero-sales row — no fees quoted, must be skipped
    "US,06/23/2026,07/22/2026,B001GPJ4R8,B001GPJ4R8,,,USD,0.0,0,0.0,,,,,,,,,,\n"
    # child ASIN under a different parent
    "US,06/23/2026,07/22/2026,B0DM2KMKTX,B005JF11R2,,,USD,63.858777,278,17752.74,"
    "13.024104,307.0,3998.4,14.277459,307.0,4383.18,-9.681852,9.574717,265.0,2537.3\n"
    # standalone (parent ASIN == ASIN)
    "US,06/23/2026,07/22/2026,B00I0ESPJG,B00I0ESPJG,,,USD,64.4125,44,2834.15,"
    "11.36925,44.0,500.25,11.74925,44.0,516.97,0.0,9.564103,39.0,373.0\n")


def test_parse_selling_economics(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    rows = fba.parse_fees(_write(tmp_path, ECON_ROWS, header=ECON_H, name="selling economics.csv"))
    assert len(rows) == 2                       # the zero-sales row is skipped
    r = rows[0]
    assert r["sku"] == "" and r["asin"] == "B005JF11R2"     # MSKU empty -> ASIN keyed
    assert r["parent_asin"] == "B0DM2KMKTX"
    # BASE fulfillment fee per unit — not the quantity/total column, and not the
    # all-in "FBA fulfillment fees per unit" (13.02, not 307 / 3998.4 / 14.28)
    assert r["fulfillment_fee"] == 13.02
    # marginal referral rate = per-unit fee / average price (NOT the refund-netted
    # total 2537.3 / 17752.74 = 14.29%), and not the "Referral Fee Refunds" column
    assert r["referral_fee"] == 9.57
    assert r["referral_pct"] == pytest.approx(0.1499, abs=1e-4)
    # TOTAL FEES per unit = base fulfillment + referral, summed from the report
    assert r["total_fee"] == 22.6          # raw 13.024104 + 9.574717, then rounded
    assert r["price"] == 63.86 and r["units"] == 278
    assert rows[1]["asin"] == "B00I0ESPJG"      # standalone keeps its own ASIN


def test_selling_economics_asin_rows_reach_catalog_skus(tmp_path, monkeypatch):
    """MSKU is empty in this export, so fees key by ASIN and reach a catalog SKU
    through the catalog's SKU -> ASIN map. The Parent ASIN is never a key."""
    _store(tmp_path, monkeypatch)
    cat.write_catalog("s1", {"products": {
        "PARENT-1": {"sku": "PARENT-1", "asin": "B0DM2KMKTX", "parentage": "parent"},
        "PI-100": {"sku": "PI-100", "asin": "B005JF11R2", "parentage": "child",
                   "parent_sku": "PARENT-1", "price": 63.86},
    }})
    rows = fba.parse_fees(_write(tmp_path, ECON_ROWS, header=ECON_H, name="econ.csv"))
    data, added, _ = fba.merge(fba.read_fba("s1"), rows, "econ.csv")
    fba.write_fba("s1", data)
    assert added == 2

    by_asin = fba.by_asin("s1")
    assert "B0DM2KMKTX" not in by_asin                    # parent ASIN never keyed
    assert by_asin["B005JF11R2"]["fulfillment_fee"] == 13.02

    f = cat.fees_by_sku("s1")
    assert f["pi100"]["fba_fee"] == 13.02 and f["pi100"]["fba_source"] == "report"
    assert f["pi100"]["referral_pct"] == pytest.approx(0.1499, abs=1e-4)
    assert f["pi100"]["total_fee"] == 22.6        # 13.02 fulfillment + 9.57 referral
    assert "parent1" not in f

    # break-even charges the report's TOTAL FEES as an exact $ per unit:
    # (63.86 − 25.54 COGS − 22.59 fees) / 63.86
    be = cat.be_metrics({"price": 63.86}, None,
                        {"default_referral_pct": 0.15, "default_cogs_pct": 0.0},
                        None, f["pi100"])
    assert be["amazon_fee"] == 22.6 and be["total_fee"] == 22.6
    assert be["total_source"] == "report"
    assert be["fba_fee"] == 13.02 and be["referral_fee"] == 9.57
    assert be["profit_per_unit"] == pytest.approx(15.72, abs=0.01)
    assert be["break_even_acos"] == pytest.approx(0.2463, abs=1e-3)   # was a flat 45%


def test_by_asin_skips_parent_asins(tmp_path, monkeypatch):
    """Fee Preview rows are per child SKU. A parent ASIN is not a purchasable
    unit — it must never receive a fulfillment fee."""
    _store(tmp_path, monkeypatch)
    cat.write_catalog("s1", {"products": {
        "PARENT-1": {"sku": "PARENT-1", "asin": "B0PARENT00", "parentage": "parent"},
        "PI-100":   {"sku": "PI-100", "asin": "B0CHILD111", "parentage": "child",
                     "parent_sku": "PARENT-1", "price": 29.99},
        "PI-200":   {"sku": "PI-200", "asin": "B0ALONE222", "parentage": "", "price": 9.99},
    }})
    path = _write(tmp_path,
                  "PARENT-1,X,B0PARENT00,Parent,29.99,USD,-,4.50,9.99\n"
                  "PI-100,X,B0CHILD111,Child,29.99,USD,Large standard,4.50,5.68\n"
                  "pi 200,X,B0ALONE222,Alone,9.99,USD,Small standard,1.50,3.22\n")
    data, added, _ = fba.merge(fba.read_fba("s1"), fba.parse_fee_preview(path), "fee.csv")
    fba.write_fba("s1", data)
    assert added == 3

    by_asin = fba.by_asin("s1")
    assert "B0PARENT00" not in by_asin                       # parent dropped
    assert by_asin["B0CHILD111"]["fulfillment_fee"] == 5.68
    assert by_asin["B0ALONE222"]["fulfillment_fee"] == 3.22  # SKU matched loosely


def test_fee_preview_wins_over_ledger_and_covers_unsold_skus(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    txn.write_txn("s1", {"rows": [
        {"type": "Order", "sku": "PI 100", "date": "2026-06-01", "quantity": 2,
         "product_sales": 70.0, "selling_fees": -10.5, "fba_fees": -7.08, "total": 52.42},
    ]})
    fba.write_fba("s1", {"skus": {
        "PI-100": {"sku": "PI-100", "asin": "B0CHILD111", "fulfillment_fee": 5.68,
                   "referral_pct": 0.15, "size_tier": "Large standard"},
        "PI-900": {"sku": "PI-900", "asin": "B0NEW99999", "fulfillment_fee": 4.10,
                   "referral_pct": None, "size_tier": "Small standard"},
    }})
    f = cat.fees_by_sku("s1")
    # Fee Preview base fee (5.68) beats the ledger average (7.08/2 = 3.54)
    assert f["pi100"]["fba_fee"] == 5.68
    assert f["pi100"]["fba_source"] == "report"
    assert f["pi100"]["referral_pct"] == 0.15          # report rate wins over ledger
    # a SKU with no sales yet still gets a fulfillment fee
    assert f["pi900"]["fba_fee"] == 4.10 and f["pi900"]["referral_pct"] is None


def test_be_metrics_breaks_out_fulfillment(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    econ = {"default_referral_pct": 0.15, "default_cogs_pct": 0.0}
    fees = {"referral_pct": 0.15, "fba_fee": 5.68, "fba_source": "report",
            "size_tier": "Large standard"}
    be = cat.be_metrics({"price": 20.0}, None, econ, None, fees)
    # no exact total in the fees dict -> referral priced off the % of price, and
    # total_fee reports what break-even actually charges
    assert be["fba_fee"] == 5.68 and be["referral_fee"] == 3.0
    assert be["total_fee"] == 8.68 and be["total_source"] == "scaled"
    assert be["amazon_fee"] == pytest.approx(8.68)              # referral + fulfillment
    assert be["profit_per_unit"] == pytest.approx(3.32)         # 20 - 8 COGS - 8.68
    assert be["break_even_acos"] == pytest.approx(0.166, abs=1e-3)
    assert be["fba_source"] == "report" and be["size_tier"] == "Large standard"
    # no fee data at all -> fulfillment priced at $0 (old behaviour), BE = 45%
    assert cat.be_metrics({"price": 20.0}, None, econ)["fba_fee"] == 0.0


def test_cost_map_feeds_benchmark_view(tmp_path, monkeypatch):
    """The uploaded Product Benchmark path (benchmark_view / break_even_map) must
    account for fulfillment too — it used to price every FBA fee at $0."""
    from app.pipeline import benchmark as bn
    _store(tmp_path, monkeypatch)
    cat.write_catalog("s1", {"products": {
        "PARENT-1": {"sku": "PARENT-1", "asin": "B0PARENT00", "parentage": "parent"},
        "PI-100": {"sku": "PI-100", "asin": "B0CHILD111", "parentage": "child"},
    }})
    fba.write_fba("s1", {"skus": {
        "PARENT-1": {"sku": "PARENT-1", "asin": "B0PARENT00", "fulfillment_fee": 9.99},
        "PI-100": {"sku": "PI-100", "asin": "B0CHILD111", "fulfillment_fee": 5.68,
                   "referral_pct": 0.15},
    }})

    class _DB:            # benchmark.cost_map only needs session.info["store"]
        info = {"store": "s1", "project": "p1"}

    costs = bn.cost_map(_DB())
    assert "B0PARENT00" not in costs
    assert costs["B0CHILD111"].fba_fee == 5.68
    assert costs["B0CHILD111"].fba_source == "report"

    # break-even on a $20 price: 20 - 8 COGS - 3 referral - 5.68 fulfillment = 3.32
    be = bn._derive_be(20.0, costs["B0CHILD111"], 0.15, 0.40)
    assert be == pytest.approx(0.166, abs=1e-3)


# ---- Referral Fee Preview (second sheet of the Selling economics workbook) ----
def _wb(tmp_path, sheets, name="selling economics.xlsx"):
    """Build a workbook: {sheet name: [rows]}."""
    import openpyxl
    wb = openpyxl.Workbook()
    first = True
    for title, rows in sheets.items():
        ws = wb.active if first else wb.create_sheet(title)
        ws.title = title
        first = False
        for r in rows:
            ws.append(r)
    p = tmp_path / name
    wb.save(p)
    return str(p)


ECON_SHEET = [
    ["Parent ASIN", "ASIN", "MSKU", "Average sales price", "Sales",
     "Base fulfillment fee per unit", "Referral fee per unit"],
    ["B0PARENT00", "B005JF11R2", "", 63.86, 17752.74, 13.02, 9.57],
    ["B00HZMTU7U", "B00HZMTU7U", "", 15.60, 1029.9, 5.93, 2.35],
]
REF_SHEET = [
    ["ASIN", "SKU", "Your price", "Referral fee percentage", "Estimated referral fee per unit"],
    ["B005JF11R2", "", 63.86, "17%", 10.86],     # $ AND rate — overrides sheet 1
    ["B00HZMTU7U", "", 15.60, "8%", ""],         # rate only — priced off the item
]


def test_referral_preview_sheet_overrides_economics_referral(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    path = _wb(tmp_path, {"Selling economics": ECON_SHEET, "Referral Fee Preview": REF_SHEET})
    rows = fba.parse_fees(path)
    # BOTH sheets parsed; the referral sheet has no fulfillment column
    assert sorted(r["kind"] for r in rows) == ["fees", "fees", "referral", "referral"]

    data, added, updated = fba.merge({}, rows, "econ.xlsx")
    assert (added, updated) == (2, 2)            # 2 fee rows in, both re-referral'd

    a = data["skus"]["B005JF11R2"]
    assert a["fulfillment_fee"] == 13.02         # fulfillment untouched
    assert a["referral_fee"] == 10.86            # was 9.57 — preview wins
    assert a["referral_pct"] == 0.17
    assert a["total_fee"] == 23.88               # 13.02 + 10.86, recomputed
    assert a["referral_source"] == "referral_preview"

    # rate-only preview row: referral priced off the item's own price
    b = data["skus"]["B00HZMTU7U"]
    assert b["referral_pct"] == 0.08 and b["referral_fee"] == 1.25
    assert b["total_fee"] == 7.18                # 5.93 + 1.25 (was 5.93 + 2.35)


def test_referral_preview_matches_by_sku_and_stands_alone(tmp_path, monkeypatch):
    """A preview row matches by SKU too, and one with no fee row of its own is
    kept as a referral-only item (still gives break-even a real rate)."""
    _store(tmp_path, monkeypatch)
    fee_sheet = [["sku", "asin", "your-price", "base-fulfilment-fee-per-unit"],
                 ["PI-100", "B0CHILD111", 29.99, 5.68]]
    ref_sheet = [["SKU", "ASIN", "Referral fee percentage"],
                 ["pi 100", "B0CHILD111", 12],          # loose SKU match
                 ["PI-900", "B0FBM99999", 15]]          # no fee row -> stands alone
    rows = fba.parse_fees(_wb(tmp_path, {"Fee Preview": fee_sheet, "Referral": ref_sheet},
                              name="fees.xlsx"))
    data, added, updated = fba.merge({}, rows, "fees.xlsx")

    it = data["skus"]["PI-100"]
    assert it["referral_pct"] == 0.12
    assert it["referral_fee"] == 3.60            # 29.99 * 12%
    assert it["total_fee"] == 9.28               # 5.68 + 3.60
    assert added == 2 and updated == 1           # PI-900 added as referral-only

    solo = data["skus"]["PI-900"]
    assert solo["fulfillment_fee"] is None and solo["referral_pct"] == 0.15
    assert solo["total_fee"] is None             # no fulfillment fee to add


def test_total_scales_when_listing_price_differs_from_report_price(tmp_path, monkeypatch):
    """The report quotes its total at ITS price. Fulfillment is a fixed $, but
    referral is a % — so at a different selling price the referral must scale,
    not stay frozen at the report's dollar amount."""
    _store(tmp_path, monkeypatch)
    econ = {"default_referral_pct": 0.15, "default_cogs_pct": 0.0}
    fees = {"referral_pct": 0.15, "fba_fee": 5.00, "referral_fee": 15.00,
            "total_fee": 20.00, "fee_price": 100.0, "fba_source": "report"}

    # same price -> the report's exact total is charged as-is
    same = cat.be_metrics({"price": 100.0}, None, econ, None, fees)
    assert same["amazon_fee"] == 20.00 and same["total_source"] == "report"

    # half the price -> referral halves (7.50), fulfillment stays $5.00
    half = cat.be_metrics({"price": 50.0}, None, econ, None, fees)
    assert half["amazon_fee"] == 12.50 and half["total_source"] == "scaled"
    # (50 - 20 COGS - 12.50 fees) / 50
    assert half["break_even_acos"] == pytest.approx(0.35, abs=1e-3)
