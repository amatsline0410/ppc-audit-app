"""Stage 3: clean. Coerce numeric types, normalize states, fill ids as strings."""
from __future__ import annotations
import pandas as pd

NUM = ["impressions", "clicks", "spend", "sales", "orders", "units",
       "bid", "daily_budget", "ad_group_default_bid", "percentage"]
IDCOLS = ["campaign_id", "ad_group_id", "ad_id", "keyword_id", "product_targeting_id", "portfolio_id"]


def _num(s: pd.Series) -> pd.Series:
    """Metric column -> float. Strings are stripped of $ , % first: the whole
    workbook is read as text (so 16-18 digit IDs stay exact), and a locale-formatted
    export would otherwise coerce straight to NaN and silently zero the money."""
    if s.dtype == object:
        s = s.astype(str).str.strip().str.replace(r"[$,%]", "", regex=True)
    return pd.to_numeric(s, errors="coerce")


def _idstr(v) -> str:
    """Exact integer string for an ID, however it arrived (str / int / float).

    `ingest` now reads ID columns as strings so 16-18 digit IDs stay exact; this
    just tidies any legacy float / "123.0" form without losing precision.
    """
    if pd.isna(v):
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else str(v)
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def clean(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    cleaned = {}
    for ent, df in frames.items():
        df = df.copy()
        for c in NUM:
            if c in df.columns:
                df[c] = _num(df[c]).fillna(0)
        # ids -> clean exact strings (never via float, which mangles big IDs)
        for c in IDCOLS:
            if c in df.columns:
                df[c] = df[c].apply(_idstr)
        if "state" in df.columns:
            df["state"] = df["state"].astype(str).str.strip().str.lower().replace({"nan": None})
        if "asin" in df.columns:
            df["asin"] = df["asin"].astype(str).str.strip().str.upper().replace({"NAN": None})
        cleaned[ent] = df
    return cleaned
