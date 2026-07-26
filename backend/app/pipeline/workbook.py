"""Shared workbook read cache.

A real Amazon bulk export is a 15 MB workbook whose Sponsored Products sheet runs
to six figures of rows — one `read_excel` of it costs ~20 seconds with openpyxl,
far more than any engine's actual computation. The suite upload hands the same file
to eight engines, and several of them want the same sheet, so without a cache the
upload is mostly the same bytes parsed over and over.

Two layers cut that cost:
  1. **Engine** — `calamine` (Rust) reads the same sheet ~8x faster than openpyxl
     (~2.5s vs ~21s on 120k rows) with identical `dtype=str` output, so IDs stay
     exact. Used when `python-calamine` is installed; falls back to openpyxl.
  2. **Cache** — everything keyed by (path, size, mtime), so a rewritten file at the
     same path is never served stale, and `clear_cache()` drops the frames once an
     upload is done.
"""
from __future__ import annotations

import os
import importlib.util

import pandas as pd

# calamine reads xlsx ~8x faster than openpyxl (Rust), same dtype=str output.
# Optional — the app works on openpyxl alone; installing python-calamine speeds
# every bulk read. Resolved once at import.
_XLSX_ENGINE = "calamine" if importlib.util.find_spec("python_calamine") else "openpyxl"

_SHEETS: dict[tuple, list[str]] = {}
_FRAMES: dict[tuple, pd.DataFrame] = {}


def excel_engine() -> str:
    """The active xlsx read engine ('calamine' when available, else 'openpyxl')."""
    return _XLSX_ENGINE


def stamp(path: str, *extra) -> tuple:
    """Cache key for a file: absolute path + size + mtime (+ caller's own bits)."""
    try:
        st = os.stat(path)
        return (os.path.abspath(path), st.st_size, st.st_mtime_ns, *extra)
    except OSError:
        return (os.path.abspath(path), None, None, *extra)


def clear_cache() -> None:
    _SHEETS.clear()
    _FRAMES.clear()


def sheet_names(path: str) -> list[str]:
    """Sheet names of a workbook ([] for a csv)."""
    if path.lower().endswith(".csv"):
        return []
    key = stamp(path)
    hit = _SHEETS.get(key)
    if hit is None:
        # closed explicitly — Windows can't unlink a file still held open.
        with pd.ExcelFile(path, engine=_XLSX_ENGINE) as xls:
            hit = _SHEETS[key] = list(xls.sheet_names)
    return list(hit)


def find_sheet(path: str, *keywords: str) -> str | None:
    """First sheet whose name contains every keyword (case-insensitive)."""
    want = [k.lower() for k in keywords]
    for sn in sheet_names(path):
        low = sn.lower()
        if all(k in low for k in want):
            return sn
    return None


def read_str(path: str, sheet: str | None = None) -> pd.DataFrame:
    """One sheet read with every column as a string — the safe read for Amazon
    exports, since 16-18 digit IDs must never touch float64. Cached; callers get a
    copy because parsers rename and coerce columns in place."""
    key = stamp(path, sheet or "", "str")
    hit = _FRAMES.get(key)
    if hit is None:
        if path.lower().endswith(".csv"):
            hit = pd.read_csv(path, dtype=str)
        else:
            hit = pd.read_excel(path, sheet_name=sheet, dtype=str, engine=_XLSX_ENGINE)
        _FRAMES[key] = hit
    return hit.copy()


def columns(path: str, sheet: str | None = None) -> list[str]:
    """A sheet's header only. Reads the header row directly (never the whole sheet)
    unless the full frame is already cached."""
    key = stamp(path, sheet or "", "str")
    hit = _FRAMES.get(key)
    if hit is not None:
        return list(hit.columns)
    hdr = stamp(path, sheet or "", "header")
    cached = _SHEETS.get(hdr)
    if cached is None:
        if path.lower().endswith(".csv"):
            cols = list(pd.read_csv(path, nrows=0).columns)
        else:
            cols = list(pd.read_excel(path, sheet_name=sheet, nrows=0, engine=_XLSX_ENGINE).columns)
        cached = _SHEETS[hdr] = cols
    return list(cached)
