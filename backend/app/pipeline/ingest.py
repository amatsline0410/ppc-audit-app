"""Stages 1-2: ingest the .xlsx and split rows by Entity.

Header normalization happens here so the rest of the pipeline never sees
version-specific column-name drift.
"""
from __future__ import annotations
import pandas as pd

from . import workbook

# canonical column aliases -> normalized snake-ish keys used downstream
ALIASES = {
    "campaign id": "campaign_id", "campaign name": "campaign_name",
    "campaign name (informational only)": "campaign_name_info",
    "ad group id": "ad_group_id", "ad group name": "ad_group_name",
    "ad group default bid": "ad_group_default_bid",
    "ad id": "ad_id", "asin": "asin", "asin (informational only)": "asin", "sku": "sku",
    "keyword id": "keyword_id", "keyword text": "keyword_text", "match type": "match_type",
    "product targeting id": "product_targeting_id",
    "product targeting expression": "expression",
    "targeting type": "targeting_type", "state": "state", "entity": "entity",
    "operation": "operation", "daily budget": "daily_budget", "portfolio id": "portfolio_id",
    "bid": "bid", "placement": "placement", "percentage": "percentage",
    "impressions": "impressions", "clicks": "clicks", "spend": "spend",
    "sales": "sales", "orders": "orders", "units": "units",
}

SP_SHEET = "Sponsored Products Campaigns"


def _is_id_col(name) -> bool:
    """An Amazon ID column (Campaign/Ad Group/Ad/Keyword/Product Targeting/… ID)."""
    low = str(name).strip().lower()
    return low == "id" or low.endswith(" id")


# Parse caches. One suite upload hands the same temp file to ~8 engines, and reading
# the workbook costs far more than every downstream computation combined (a real
# bulk's Sponsored Products sheet is ~140k rows — about 20 seconds a read). Keys
# carry size+mtime, so a rewritten file at the same path is never served stale;
# `clear_cache()` drops everything once an upload finishes.
_CACHE: dict[tuple, pd.DataFrame] = {}
_FRAMES: dict[tuple, dict] = {}


def _stamp(path: str, sheet: str) -> tuple:
    return workbook.stamp(path, sheet)


def clear_cache() -> None:
    _CACHE.clear()
    _FRAMES.clear()
    workbook.clear_cache()


def frames(path: str, sheet: str = SP_SHEET) -> dict:
    """The bulk's per-entity **cleaned** frames — `clean(split(ingest(path)))`.

    This is the shape most engines actually want (core load, Waterfall,
    Cannibalization, Structure Redesign, Daily Watch), so splitting and cleaning
    once and handing out copies saves each of them a full pass over the sheet.
    """
    from . import clean as clean_stage
    key = _stamp(path, sheet)
    hit = _FRAMES.get(key)
    if hit is None:
        hit = _FRAMES[key] = clean_stage.clean(split(ingest(path, sheet)))
    return {k: v.copy() for k, v in hit.items()}


def ingest(path: str, sheet: str = SP_SHEET) -> pd.DataFrame:
    """Read one bulk sheet, normalize headers to canonical keys.
    Accepts .csv (single sheet) as well as .xlsx/.xlsm.

    ID columns are read as **strings**: Amazon entity IDs run 16-18 digits, past
    float64's exact range, so the default numeric parse mangles them (e.g.
    5585544115802929 -> 5585544115802929.0/.9). A mangled ID gets rejected on
    re-upload as a "temporary ID" or collides with another into a "Duplicate Id".

    Repeat reads of the same file come from the cache. Callers get a copy, since
    downstream stages rename/coerce columns in place.
    """
    key = _stamp(path, sheet)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit.copy()
    df = _read(path, sheet)
    _CACHE[key] = df
    return df.copy()


def _read(path: str, sheet: str) -> pd.DataFrame:
    # every column as text — ID columns must stay exact, and `clean` coerces the
    # metric columns back to numbers. One text read then serves every engine that
    # wants this sheet (see workbook.read_str) instead of one read per engine.
    df = workbook.read_str(path, None if path.lower().endswith(".csv") else sheet)
    rename = {c: ALIASES.get(str(c).strip().lower(), str(c).strip().lower()) for c in df.columns}
    return df.rename(columns=rename)


def split(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split into per-entity frames keyed by lowercased entity name."""
    if "entity" not in df.columns:
        raise ValueError("bulk file missing 'Entity' column")
    out = {}
    for ent, g in df.groupby(df["entity"].astype(str).str.lower()):
        out[ent] = g.reset_index(drop=True)
    return out
