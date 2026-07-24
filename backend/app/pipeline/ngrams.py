"""N-gram analysis over a Search Term Report.

Break every customer search term into 1/2/3-word grams and roll the term's
metrics up to each gram. Reveals *words* that win or waste across the whole
account — e.g. "for women" converts everywhere, "cheap" never does — which a
per-term view hides. Reuses the STR parser from harvest.py.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from typing import Optional
import pandas as pd
from .. import metrics as M
from ..config import Thresholds

_STOP = {"the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "with", "by"}


@dataclass
class Ngram:
    gram: str
    n: int                 # words in the gram (1|2|3)
    terms: int             # how many distinct search terms contain it
    impressions: int
    clicks: int
    spend: float
    sales: float
    orders: int
    acos: Optional[float]
    cvr: Optional[float]
    roas: Optional[float]
    verdict: str           # winner | waster | neutral
    # spend-weighted break-even ACoS across the ad groups the gram's terms ran
    # in (catalog listings' real Transactions-ledger fees + COGS) — a gram spans
    # products, so its break-even is the weighted mix of theirs
    break_even: Optional[float] = None

    def dict(self) -> dict:
        return asdict(self)


def _tokens(term: str) -> list[str]:
    words = re.sub(r"[^a-z0-9 ]", " ", term.lower()).split()
    return [w for w in words if len(w) > 1 and w not in _STOP]


def _grams_of(term: str, n_max: int) -> set[str]:
    toks = _tokens(term)
    out: set[str] = set()
    for n in range(1, n_max + 1):
        for i in range(len(toks) - n + 1):
            out.add(" ".join(toks[i:i + n]))
    return out


def mine(df: pd.DataFrame, t: Thresholds, n_max: int = 3,
         min_clicks: int = 2, top: int = 200) -> list[Ngram]:
    """Aggregate STR metrics per gram, classify, return spend-ranked rows."""
    acc: dict[str, dict] = {}
    has_be = "_be" in df.columns          # per-row break-even (see insights router)
    for _, r in df.iterrows():
        term = str(r["search_term"]).strip()
        if not term or term.lower() in ("nan", "*"):
            continue
        im, cl = int(r["impressions"]), int(r["clicks"])
        sp, sa, od = float(r["spend"]), float(r["sales"]), int(r["orders"])
        be = r.get("_be") if has_be else None
        for g in _grams_of(term, n_max):
            a = acc.setdefault(g, {"terms": 0, "im": 0, "cl": 0, "sp": 0.0, "sa": 0.0, "od": 0,
                                   "be_w": 0.0, "be_sp": 0.0})
            a["terms"] += 1; a["im"] += im; a["cl"] += cl
            a["sp"] += sp; a["sa"] += sa; a["od"] += od
            if be is not None and not pd.isna(be):
                w = sp if sp > 0 else 0.01     # spend-weighted; tiny floor keeps 0-spend rows counted
                a["be_w"] += float(be) * w
                a["be_sp"] += w

    rows: list[Ngram] = []
    for g, a in acc.items():
        if a["cl"] < min_clicks:
            continue  # too thin to read
        m = M.all_metrics(a["im"], a["cl"], a["sp"], a["sa"], a["od"], 0)
        acos = m["acos"]
        if a["od"] > 0 and acos is not None and acos <= t.target_acos:
            verdict = "winner"
        elif a["od"] == 0 and a["sp"] >= t.min_spend:
            verdict = "waster"
        else:
            verdict = "neutral"
        rows.append(Ngram(
            g, len(g.split()), a["terms"], a["im"], a["cl"],
            round(a["sp"], 2), round(a["sa"], 2), a["od"],
            round(acos, 4) if acos is not None else None,
            round(m["cvr"], 4) if m["cvr"] is not None else None,
            round(m["roas"], 4) if m["roas"] is not None else None,
            verdict,
            round(a["be_w"] / a["be_sp"], 4) if a["be_sp"] else None))

    rows.sort(key=lambda x: x.spend, reverse=True)
    return rows[:top]
