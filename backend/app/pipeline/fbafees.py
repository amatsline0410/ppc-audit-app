"""Base fulfillment fee per unit — Amazon SKU Economics / FBA Fee Preview reports.

Feeds the Product Benchmark tab: the FBA fulfillment fee is a fixed $ per unit,
so it weighs far more on a cheap product than the percent-only defaults suggest.
Without it, break-even ACoS comes out too optimistic and every downstream
consumer (BLEEDING flags, BidOptimizer caps, profit-per-unit) is wrong the same
way.

Scope: STORE-level (like the catalog, COGS overrides and transactions) —
persisted as `<store>/_fba.json`, shared by every audit/cadence in the store,
deleted with the store dir. Uploads MERGE by SKU, so re-uploads after a fee
change just upsert.

Two Amazon reports carry the fee, and one parser reads both (columns matched
loosely by name, never by position — names drift per marketplace and schema
revision, and both British and American spellings ship):

* **Selling economics / SKU Economics** (Seller Central > Reports > Business >
  Selling economics — "selling economics.csv"): one row per ASIN over a date
  range, with `Base fulfillment fee per unit`, `Referral fee per unit`,
  `Average sales price`, units and totals. It carries `Parent ASIN` AND `ASIN`
  columns and its `MSKU` column is usually EMPTY, so rows key off the **ASIN**
  column — which is the child/standalone ASIN. `Parent ASIN` is never used as
  a key: a parent is not a purchasable unit and has no fulfillment fee.
* **FBA Fee Preview** (Seller Central > Reports > Fulfilment > Fee Preview):
  one row per SKU. The fulfillment fee has shipped as
  `base-fulfilment-fee-per-unit`, `expected-domestic-fulfilment-fee-per-unit`,
  `expected-fulfillment-fee-per-unit`, and (older schema) as the
  `estimated-pick-pack-fee-per-unit` + `estimated-weight-handling-fee-per-unit`
  pair, which are summed.

Rows are stored under their SKU when the report gives one, else their ASIN.
Rows quoting no fulfillment fee (zero-sales ASINs fill most of a SKU Economics
export) are skipped.

Referral: the referral fee comes back as a per-unit $ and as a percentage —
`referral fee per unit ÷ average selling price`, the MARGINAL rate an
incremental ad sale pays (the totals-based `referral fee total ÷ sales` is
refund-netted and reads ~0.7pt low, so it's only the fallback). It feeds
break-even as the referral % when the Transactions ledger has no observed value
for that SKU.

ASIN mapping: `by_asin()` maps a fee onto an ASIN only when it is a child or
standalone listing — a catalog parent SKU is skipped and a row whose ASIN is a
catalog parent is dropped.
"""
from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime

from .. import database as dbmod

_MAX_FILES = 6   # rolling upload-history length (matches catalog/transactions)

_num_re = re.compile(r"-?[\d,]*\.?\d+")


# ---- store-scoped file --------------------------------------------------------
def _store_path(store_id: str) -> str:
    return os.path.join(dbmod._store_dir(store_id), "_fba.json")


def read_fba(store_id: str | None) -> dict:
    if not store_id:
        return {}
    p = _store_path(store_id)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def write_fba(store_id: str, data: dict) -> None:
    with open(_store_path(store_id), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)


def delete_all(store_id: str) -> None:
    p = _store_path(store_id)
    if os.path.exists(p):
        os.unlink(p)


# ---- parsing -------------------------------------------------------------------
def _s(v) -> str:
    return str(v).strip() if v is not None else ""


def _money(v):
    """'$3.22' / '3,22' / 3.22 -> float · ''/'--'/None -> None (no fee quoted)."""
    s = _s(v).replace(",", "")
    if not s or s in ("--", "-", "N/A", "n/a"):
        return None
    m = _num_re.search(s)
    return float(m.group()) if m else None


def _pct(v):
    """Referral RATE cell -> fraction. '15%' / 15 -> 0.15 · 0.15 -> 0.15 ·
    ''/'--' -> None. Values > 1 read as percent."""
    x = _money(v)
    if x is None or x <= 0:
        return None
    return round(x / 100.0 if x > 1 else x, 4)


def _norm(h: str) -> str:
    """Header key normalized for loose matching: lowercase, punctuation -> space.
    `base-fulfilment-fee-per-unit` -> `base fulfilment fee per unit`."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _s(h).lower())).strip()


def _fulfil(h: str) -> bool:
    return "fulfilment" in h or "fulfillment" in h


_SKU_H = ("sku", "seller sku", "merchant sku", "msku")


def _has_referral(norm: list[str]) -> bool:
    return any("referral" in h and ("fee" in h or "percent" in h) and "refund" not in h
               and "liquidation" not in h for h in norm)


def _is_header(norm: list[str]) -> bool:
    """A header row identifies a row by SKU or ASIN and quotes a fee somewhere —
    a fulfillment fee (Selling economics / Fee Preview) OR a referral fee (the
    Referral Fee Preview sheet, which carries no fulfillment column)."""
    ident = any(h in _SKU_H for h in norm) or any(h == "asin" for h in norm)
    fee = any(_fulfil(h) and "fee" in h for h in norm) or \
        any("pick" in h and "pack" in h for h in norm) or _has_referral(norm)
    return ident and fee


def _sheets(path: str):
    """Yield (sheet_name, rows) for each sheet. A .csv/.txt is one nameless sheet;
    a workbook yields EVERY sheet, so a Selling economics export whose second
    sheet is a Referral Fee Preview gets both parsed."""
    low = path.lower()
    if low.endswith((".csv", ".txt", ".tsv")):
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            sample = f.read(8192)
            f.seek(0)
            delim = "\t" if sample.count("\t") > sample.count(",") else ","
            yield "", list(csv.reader(f, delimiter=delim))
        return
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            yield ws.title, list(ws.iter_rows(values_only=True))
    finally:
        wb.close()


def _resolve(header: list[str]) -> dict:
    """Map the header row to column indexes. Fee columns are picked by
    preference order so a report carrying several takes the BASE per-unit
    fulfillment fee, not a quantity/total column, an EFN/cross-border variant,
    or a refund/liquidation referral line."""
    norm = [_norm(h) for h in header]
    col: dict = {}

    def pick(*preds):
        for pred in preds:
            for i, h in enumerate(norm):
                if pred(h):
                    return i
        return None

    col["sku"] = pick(lambda h: h in _SKU_H, lambda h: h.endswith(" sku"))
    # child/standalone ASIN — never "parent asin" (a parent has no unit fee)
    col["asin"] = pick(lambda h: h == "asin",
                       lambda h: "asin" in h and "parent" not in h)
    col["parent_asin"] = pick(lambda h: "parent" in h and "asin" in h)
    col["price"] = pick(lambda h: h in ("your price", "sales price", "price"),
                        lambda h: "average sales price" in h,
                        lambda h: "price" in h and "list" not in h)
    col["size_tier"] = pick(lambda h: "size tier" in h)
    col["currency"] = pick(lambda h: "currency" in h)
    col["units"] = pick(lambda h: h in ("units sold", "net units sold", "quantity"))
    col["sales"] = pick(lambda h: h == "sales", lambda h: h == "net sales")
    # referral fee: per-unit first, and never a refund / liquidation variant
    def _ref(h):
        return "referral fee" in h and "refund" not in h and "liquidation" not in h
    col["referral"] = pick(lambda h: _ref(h) and "per unit" in h and "percent" not in h,
                           lambda h: _ref(h) and "quantity" not in h and "total" not in h
                                     and "percent" not in h and "rate" not in h)
    col["referral_total"] = pick(lambda h: _ref(h) and "total" in h)
    # Referral Fee Preview quotes a RATE (e.g. 15 / 15% / 0.15) as well as / instead
    # of a per-unit $
    col["referral_rate"] = pick(lambda h: _ref(h) and ("percent" in h or "rate" in h))
    # fulfillment fee, best match first
    col["fulfillment"] = pick(
        lambda h: "base" in h and _fulfil(h) and "fee" in h and "per unit" in h,
        lambda h: "domestic" in h and _fulfil(h) and "fee" in h and "per unit" in h,
        lambda h: "expected" in h and _fulfil(h) and "fee" in h and "efn" not in h,
        lambda h: _fulfil(h) and "fee" in h and "per unit" in h and "efn" not in h,
        lambda h: "base" in h and _fulfil(h) and "fee" in h and "quantity" not in h and "total" not in h,
        lambda h: _fulfil(h) and "fee" in h and "efn" not in h
                  and "quantity" not in h and "total" not in h,
    )
    # older Fee Preview schema: sum pick&pack + weight handling instead
    col["pick_pack"] = pick(lambda h: "pick" in h and "pack" in h)
    col["weight_handling"] = pick(lambda h: "weight handling" in h)
    return col


def parse_fees(path: str) -> list[dict]:
    """Parse a Selling economics (SKU Economics) / FBA Fee Preview / Referral Fee
    Preview report into per-unit fee rows. EVERY sheet of a workbook is parsed, so
    an export whose second sheet is a Referral Fee Preview yields both kinds:

    * `kind="fees"`      — carries a fulfillment fee (and usually a referral fee)
    * `kind="referral"`  — referral only; merge() applies it OVER the referral of
                           the matching item, since the Referral Fee Preview is
                           the authoritative rate

    Rows key off SKU when the report has one, else ASIN."""
    out: list[dict] = []
    saw_header = False
    for _name, sheet in _sheets(path):
        col = None
        for row in sheet:
            cells = list(row)
            if col is None:
                if not _is_header([_norm(c) for c in cells]):
                    continue                    # still in the preamble
                col = _resolve([_s(c) for c in cells])
                saw_header = True
                continue

            def cell(name, _col=col, _cells=cells):
                i = _col.get(name)
                return _cells[i] if i is not None and i < len(_cells) else None

            sku = _s(cell("sku"))
            asin = _s(cell("asin")).upper()
            if _norm(sku) in _SKU_H or _norm(asin) == "asin":
                continue                        # repeated header row
            if not sku and not asin:
                continue
            fee = _money(cell("fulfillment"))
            if fee is None:
                pp, wh = _money(cell("pick_pack")), _money(cell("weight_handling"))
                if pp is not None or wh is not None:
                    fee = round((pp or 0.0) + (wh or 0.0), 2)
            price = _money(cell("price"))
            referral = _money(cell("referral"))
            rate = _pct(cell("referral_rate"))
            sales, ref_total = _money(cell("sales")), _money(cell("referral_total"))
            if referral is None and rate and price:
                referral = round(price * rate, 2)   # preview quotes only a rate
            if not fee and not referral and not rate:
                continue    # nothing quoted (zero-sales ASIN row / FBM listing)
            # referral % = per-unit fee ÷ selling price — the MARGINAL rate, which
            # is what an incremental ad sale pays. An explicit rate column wins;
            # the totals-based rate (referral fee total ÷ sales) is refund-netted
            # and understates it, so it's the last fallback.
            pct = rate
            if pct is None and referral and price:
                pct = round(referral / price, 4)
            if pct is None and ref_total and sales:
                pct = round(abs(ref_total) / sales, 4)
            out.append({
                "kind": "fees" if fee else "referral",
                "sku": sku,
                "asin": asin,
                "parent_asin": _s(cell("parent_asin")).upper() or None,
                "fulfillment_fee": round(fee, 2) if fee else None,
                "referral_fee": round(referral, 2) if referral else None,
                # TOTAL FEES per unit = base fulfillment + referral, both straight
                # from the report. This exact $ is what break-even charges, instead
                # of re-deriving the referral as a % of price. None when there's no
                # referral fee yet (then break-even falls back to the %).
                "total_fee": round(fee + referral, 2) if fee and referral else None,
                "referral_pct": pct,
                "price": round(price, 2) if price else None,
                "units": _money(cell("units")),
                "size_tier": _s(cell("size_tier")) or None,
                "currency": _s(cell("currency")) or None,
            })
    if not saw_header:
        raise ValueError(
            "This doesn't look like a fee report — no header row with a SKU/ASIN column "
            "and a fulfillment or referral fee was found. Use the Selling economics report "
            "(Reports > Business > Selling economics), the FBA Fee Preview or the Referral "
            "Fee Preview (Reports > Fulfilment).")
    if not out:
        raise ValueError("No rows with a fulfillment or referral fee found in that report.")
    return out


# back-compat alias: the Fee Preview is one of the two shapes parse_fees reads
parse_fee_preview = parse_fees


def _total(item: dict, force: bool = False) -> None:
    """Keep total_fee = fulfillment + referral in sync. Without `force` an
    existing total is left alone — parse computes it from the report's full
    precision, which beats re-adding the rounded parts."""
    if not force and item.get("total_fee") is not None:
        return
    f, r = item.get("fulfillment_fee"), item.get("referral_fee")
    item["total_fee"] = round(f + r, 2) if f and r else None


def merge(data: dict, rows: list[dict], filename: str) -> tuple[dict, int, int]:
    """Upsert parsed fee rows into the store blob, keyed by SKU when the report
    gives one, else by ASIN (Selling economics leaves MSKU empty).

    Two passes, because the Referral Fee Preview must land ON TOP of whatever
    fulfillment row the item already has:
      1. `kind="fees"` rows upsert wholesale (they carry the fulfillment fee).
      2. `kind="referral"` rows update only the referral fee / rate of the
         matching item — found by SKU, else by ASIN — and total_fee is
         recomputed. An item's existing referral fee IS overwritten: the
         Referral Fee Preview is the authoritative rate. A referral row with no
         matching item is kept on its own (referral-only, no fulfillment fee)."""
    blob = data if isinstance(data, dict) else {}
    items = blob.setdefault("skus", {})
    added = updated = 0
    fee_rows = [r for r in rows if r.get("kind", "fees") == "fees"]
    ref_rows = [r for r in rows if r.get("kind") == "referral"]

    for r in fee_rows:
        key = r.get("sku") or r.get("asin")
        if not key:
            continue
        if key in items:
            updated += 1
        else:
            added += 1
        items[key] = {k: v for k, v in r.items() if k != "kind"}
        _total(items[key])

    if ref_rows:
        by_norm_sku = {}
        by_asin_key = {}
        hit: set = set()      # items already re-referral'd by this file
        from .catalog import norm_sku
        for k, it in items.items():
            if it.get("sku"):
                by_norm_sku[norm_sku(it["sku"])] = k
            if it.get("asin"):
                by_asin_key.setdefault(it["asin"].upper(), k)
        for r in ref_rows:
            key = (by_norm_sku.get(norm_sku(r["sku"])) if r.get("sku") else None) \
                or (by_asin_key.get(r["asin"].upper()) if r.get("asin") else None)
            if key is None:                       # referral-only item, no fee row
                key = r.get("sku") or r.get("asin")
                if not key:
                    continue
                items[key] = {k: v for k, v in r.items() if k != "kind"}
                added += 1
                _total(items[key])
                continue
            it = items[key]
            # Several preview SKUs can point at ONE item (an ASIN-keyed Selling
            # economics row covers every SKU of that ASIN). Keep the highest rate
            # so break-even stays conservative, instead of last-row-wins.
            if key in hit and (r.get("referral_pct") or 0) <= (it.get("referral_pct") or 0):
                continue
            hit.add(key)
            if r.get("referral_fee") is not None:
                it["referral_fee"] = r["referral_fee"]
            if r.get("referral_pct") is not None:
                it["referral_pct"] = r["referral_pct"]
            if it.get("referral_fee") is None and r.get("referral_pct") and it.get("price"):
                # preview quoted only a rate — price it off the item's own price
                it["referral_fee"] = round(it["price"] * r["referral_pct"], 2)
            it["referral_source"] = "referral_preview"
            _total(it, force=True)
            updated += 1

    now = datetime.now().isoformat(timespec="seconds")
    files = [f for f in blob.get("files", []) if f.get("name") != filename]
    files.append({"name": filename, "rows": len(rows), "uploaded": now})
    blob["files"] = files[-_MAX_FILES:]
    blob["updated"] = now
    return blob, added, updated


# ---- lookups ------------------------------------------------------------------
def by_sku(store_id: str | None) -> dict:
    """normalized SKU -> fee row (SKUs drift on case/spaces/dashes across reports).
    ASIN-keyed rows (Selling economics, no MSKU) are not SKUs — see by_asin."""
    from .catalog import norm_sku
    return {norm_sku(r["sku"]): r for r in (read_fba(store_id) or {}).get("skus", {}).values()
            if r.get("sku")}


def by_asin(store_id: str | None) -> dict:
    """ASIN -> fee row, CHILD/standalone listings only.

    A parent ASIN is not a purchasable unit and carries no fulfillment fee, so
    parent SKUs in the catalog are skipped and a Fee Preview row whose own ASIN
    column points at a catalog parent is dropped. The catalog SKU -> ASIN map
    wins over the report's ASIN column (the catalog is the listing source of
    truth); the report's ASIN is the fallback for SKUs not in the catalog yet."""
    from . import catalog as cat
    rows = (read_fba(store_id) or {}).get("skus", {})
    if not rows:
        return {}
    prods = (cat.read_catalog(store_id) or {}).get("products", {})
    by_norm = {cat.norm_sku(sku): p for sku, p in prods.items()}
    parents = {(p.get("asin") or "").upper() for p in prods.values()
               if p.get("parentage") == "parent" and p.get("asin")}
    out: dict[str, dict] = {}
    for key, r in rows.items():
        p = by_norm.get(cat.norm_sku(r["sku"])) if r.get("sku") else None
        if p is not None and p.get("parentage") == "parent":
            continue                                   # parent SKU — no unit fee
        # the row's own ASIN column is the child/standalone ASIN; the report's
        # Parent ASIN is never used as a key
        asin = ((p.get("asin") if p else "") or r.get("asin") or "").upper()
        if not asin or asin in parents:
            continue
        out[asin] = r
    return out


def stats(store_id: str | None) -> dict:
    """Coverage summary for the upload panel."""
    data = read_fba(store_id) or {}
    rows = list((data.get("skus") or {}).values())
    fees = [r["fulfillment_fee"] for r in rows if r.get("fulfillment_fee") is not None]
    return {"skus": len(rows), "files": data.get("files", []), "updated": data.get("updated"),
            "avg_fee": round(sum(fees) / len(fees), 2) if fees else None,
            "min_fee": min(fees) if fees else None, "max_fee": max(fees) if fees else None}
