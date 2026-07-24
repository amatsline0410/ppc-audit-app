"""Serve the user's preferred template files as downloadable blanks/references.

Files live in <project>/preferred_templates. Each upload panel links here so the
operator downloads the exact format the parsers expect.
"""
from __future__ import annotations
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

TEMPLATES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "preferred_templates"))

# kind -> filename keyword(s) to match (first hit wins)
_KINDS = {
    "bulk": ("bulk",),
    "business": ("businessreport", "business"),
    "str": ("search_term", "search term"),
    "benchmark": ("benchmark",),
    "fee_preview": ("fee_preview", "fee preview", "feepreview"),
}


def _find(kind: str) -> str | None:
    if not os.path.isdir(TEMPLATES_DIR):
        return None
    keys = _KINDS.get(kind, ())
    for fn in sorted(os.listdir(TEMPLATES_DIR)):
        low = fn.lower()
        if low.endswith((".xlsx", ".xlsm", ".csv")) and any(k in low for k in keys):
            return fn
    return None


@router.get("/templates")
def list_templates():
    return {"templates": [{"kind": k, "file": _find(k), "available": _find(k) is not None}
                          for k in _KINDS]}


@router.get("/templates/{kind}")
def get_template(kind: str):
    if kind not in _KINDS:
        raise HTTPException(404, f"unknown template kind '{kind}'")
    fn = _find(kind)
    if not fn:
        raise HTTPException(404, f"no template file for '{kind}' in preferred_templates")
    return FileResponse(os.path.join(TEMPLATES_DIR, fn),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=fn)
