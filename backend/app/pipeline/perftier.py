"""Performance tiering for Ads Studio — HERO / A / B / C / D.

Ranks campaigns (or products) so the Studio can be filtered down to "just show me my
heroes" without eyeballing a 100-row table. Unsupervised: there are no labels to learn
from, so this scores each row on how it actually performed and then lets **1-D k-means**
find where the natural breaks between tiers sit (`ml.kmeans_1d`). Cut points follow the
account's own gaps rather than a fixed percentile, so a portfolio of twelve equally good
campaigns doesn't get a bottom tier invented for it.

Why NumPy and not scikit-learn: `ml.py` already hand-rolls its beta functions, logistic
regression and AUC precisely to keep scipy/sklearn out of the dependency set. A 1-D
k-means is ~20 lines; importing a 100MB stack for it would be the wrong trade in a repo
that ships a local, offline tool.

The score blends three things a PPC operator actually means by "hero":

  volume      share of the selection's ad sales, log-compressed so one whale doesn't
              flatten everything below it into a single tier
  efficiency  goal attainment — how far ACoS sits under (or over) the Target ACoS
  conviction  empirical-Bayes shrunk CVR (`ml.fit_beta_prior`), so a 1-click 100%
              converter can't outrank a campaign with 400 clicks of real evidence

Degrades honestly, like every other model here: too few rows to cluster falls back to
score-ordered quantiles, and a selection with no sales at all returns no tiers rather
than inventing a ranking out of spend.
"""
from __future__ import annotations

import math
from typing import Optional

from . import ml

# tiers, best first
HERO, A, B, C, D = "HERO", "A", "B", "C", "D"
TIERS = [HERO, A, B, C, D]
TIER_LABEL = {
    HERO: "Hero — top sales and efficiency",
    A: "Tier A — strong",
    B: "Tier B — solid",
    C: "Tier C — weak",
    D: "Tier D — no return",
}

# score weights (sum to 1.0)
W_VOLUME, W_EFFICIENCY, W_CONVICTION = 0.45, 0.35, 0.20

# a row that sold nothing can never be a hero, whatever it spent
NO_SALES_TIER = D
MIN_ROWS_TO_CLUSTER = 8


def _rate(part: float, whole: float) -> float:
    return (part / whole) if whole else 0.0


def _volume_score(sales: float, max_sales: float) -> float:
    """Share of the top performer's sales, log-compressed. Linear share would give
    a single dominant campaign ~1.0 and push everything else toward 0."""
    if max_sales <= 0 or sales <= 0:
        return 0.0
    return min(1.0, math.log1p(sales) / math.log1p(max_sales))


def _efficiency_score(acos: Optional[float], target_acos: float) -> float:
    """1.0 at half the goal ACoS or better, 0.5 exactly at goal, 0 at twice it."""
    if acos is None or acos <= 0:
        return 0.0
    ratio = target_acos / acos              # >1 = under goal = good
    return max(0.0, min(1.0, (ratio - 0.5) / 1.5))


def _conviction_score(orders: int, clicks: int, prior: Optional[dict],
                      account_cvr: float) -> float:
    """How confidently this row out-converts the account, relative to its average.

    Uses the posterior's **lower** credible bound, not the point estimate. A single
    order on a single click is a 100% observed CVR and shrinks to a high point
    estimate under a weak prior — but its interval is enormous, so its lower bound
    stays low. That is exactly the property "conviction" should have: evidence, not
    just an impressive-looking rate.
    """
    if account_cvr <= 0:
        return 0.0
    if prior:
        cvr = ml.posterior(int(orders), int(clicks), prior)["cvr_lo"]
    elif clicks:
        # no prior to fit -> Wilson-ish haircut so thin rows still can't top out
        cvr = orders / clicks / (1.0 + 2.0 / max(clicks, 1))
    else:
        return 0.0
    return max(0.0, min(1.0, cvr / (account_cvr * 2)))


def score_rows(rows: list[dict], target_acos: float) -> list[dict]:
    """Attach a 0-1 `score` and its components to each row.

    Each row needs `metrics` (spend / sales / orders / clicks / acos) and an `id`.
    """
    metric = [(r.get("metrics") or {}) for r in rows]
    sales = [float(m.get("sales") or 0) for m in metric]
    clicks = [int(m.get("clicks") or 0) for m in metric]
    orders = [int(m.get("orders") or 0) for m in metric]

    max_sales = max(sales) if sales else 0.0
    tot_clicks, tot_orders = sum(clicks), sum(orders)
    account_cvr = _rate(tot_orders, tot_clicks)
    prior = ml.fit_beta_prior(list(zip(orders, clicks)))

    out = []
    for r, m, s, c, o in zip(rows, metric, sales, clicks, orders):
        vol = _volume_score(s, max_sales)
        eff = _efficiency_score(m.get("acos"), target_acos)
        con = _conviction_score(o, c, prior, account_cvr)
        score = W_VOLUME * vol + W_EFFICIENCY * eff + W_CONVICTION * con
        out.append({**r, "score": round(score, 6),
                    "score_parts": {"volume": round(vol, 4), "efficiency": round(eff, 4),
                                    "conviction": round(con, 4)},
                    "_no_sales": s <= 0})
    return out


def assign(rows: list[dict], target_acos: float) -> dict:
    """Score, cluster, and label every row with a tier.

    Returns {rows, method, breaks, prior, counts}. `method` is 'kmeans' when the
    natural breaks were found, 'quantile' for a small selection, and 'none' when
    there was nothing to rank.
    """
    if not rows:
        return {"rows": [], "method": "none", "breaks": [], "counts": {}}

    scored = score_rows(rows, target_acos)
    # zero-sales rows are tiered separately: they can't be ranked on return, only
    # on how much they burned, so they all land in the bottom tier by definition.
    earners = [r for r in scored if not r["_no_sales"]]
    burners = [r for r in scored if r["_no_sales"]]

    method, breaks = "none", []
    if not earners:
        for r in scored:
            r["tier"] = NO_SALES_TIER
            r["tier_reason"] = "no ad sales in this bulk"
    else:
        k = min(len(TIERS), len(earners))
        clustered = ml.kmeans_1d([r["score"] for r in earners], k) if \
            len(earners) >= MIN_ROWS_TO_CLUSTER else None
        if clustered:
            method, breaks = "kmeans", clustered["breaks"]
            # cluster 0 is the lowest score; map the top cluster to HERO
            top = clustered["k"] - 1
            for r, lab in zip(earners, clustered["labels"]):
                r["tier"] = TIERS[top - lab] if (top - lab) < len(TIERS) else D
        else:
            method = "quantile"
            ordered = sorted(earners, key=lambda r: r["score"], reverse=True)
            n = len(ordered)
            for i, r in enumerate(ordered):
                r["tier"] = TIERS[min(len(TIERS) - 1, int(i * len(TIERS) / n))]
        for r in earners:
            r["tier_reason"] = _reason(r, target_acos)
        for r in burners:
            r["tier"] = NO_SALES_TIER
            r["tier_reason"] = "spend with no ad sales"

    for r in scored:
        r.pop("_no_sales", None)
    counts = {t: sum(1 for r in scored if r.get("tier") == t) for t in TIERS}
    return {"rows": scored, "method": method, "breaks": breaks, "counts": counts,
            "target_acos": target_acos}


def _reason(row: dict, target_acos: float) -> str:
    m = row.get("metrics") or {}
    p = row.get("score_parts") or {}
    acos = m.get("acos")
    bits = [f"{m.get('orders') or 0} orders"]
    if acos is not None:
        under = "under" if acos <= target_acos else "over"
        bits.append(f"{acos * 100:.0f}% ACoS ({under} goal)")
    bits.append(f"volume {p.get('volume', 0) * 100:.0f}%")
    return " · ".join(bits)
