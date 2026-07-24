"""Machine-learning primitives for the Audit Cadences. NumPy only, no I/O.

Everything here is fit per-account, on that cadence's OWN data, at plan time —
no persisted models, no RNG (deterministic run-to-run), and every function
degrades to None when the account is too small to learn from. Advisory only:
exported bulk files stay rule-driven.

Four techniques, matched to what Amazon PPC data supports:

1. **Beta-binomial empirical Bayes** (`fit_beta_prior` / `posterior`) — the core
   thin-data fix. A 0-order / 3-click search term does NOT have CVR 0; it has a
   posterior pulled toward the account's own conversion prior. Gives smoothed
   CVR, a 90% credible interval, and calibrated confidences: P(true CVR below
   the break-even CVR) for negate/pause decisions, P(above) for promote/scale.
   The regularized incomplete beta is hand-rolled (continued fraction), so no
   scipy dependency.
2. **Robust anomaly detection** (`robust_anomalies`) — median/MAD z-scores over
   a daily KPI series (Daily Watch). MAD instead of stddev so one real spike
   can't mask itself by inflating the scale; direction-aware severity.
3. **Holt double exponential smoothing** (`holt_forecast`) — next-period
   level+trend forecast with a residual-σ interval, for the Weekly series.
4. **Logistic regression** (`train_term_model`) — conversion propensity
   P(order | click) per search term from cheap term features, trained full-batch
   with fixed init (deterministic). Quality-gated: if the model can't beat
   chance (AUC < 0.62) on its own training data, it returns nothing rather than
   pretending to know.
"""
from __future__ import annotations

import math
import re
from typing import Optional

import numpy as np


# ---- regularized incomplete beta (no scipy) ----------------------------------
def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for betainc (Numerical Recipes, Lentz's method)."""
    MAXIT, EPS, FPMIN = 200, 3e-12, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a,b) = P(Beta(a,b) <= x)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_bt = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
             + a * math.log(x) + b * math.log(1.0 - x))
    bt = math.exp(ln_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def beta_ppf(a: float, b: float, q: float) -> float:
    """Quantile of Beta(a,b) by bisection on betainc (plenty fast at 60 iters)."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if betainc(a, b, mid) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ---- empirical-Bayes CVR shrinkage -------------------------------------------
def fit_beta_prior(pairs: list[tuple[int, int]]) -> Optional[dict]:
    """Fit a Beta(alpha, beta) prior to the account's own (orders, clicks) pairs
    by method of moments on the per-target CVRs (click-weighted mean, unweighted
    dispersion). `strength` = alpha+beta ≈ how many clicks of pseudo-evidence the
    prior carries. None when there's too little to fit (< 5 targets with clicks,
    or no conversions at all — nothing to shrink toward)."""
    pts = [(int(o), int(c)) for o, c in pairs if c and c > 0 and 0 <= o <= c]
    if len(pts) < 5:
        return None
    orders = np.array([o for o, _ in pts], dtype=float)
    clicks = np.array([c for _, c in pts], dtype=float)
    if orders.sum() <= 0:
        return None                       # a prior of exactly 0 can't be a Beta
    m = float(orders.sum() / clicks.sum())            # pooled mean CVR
    rates = orders / clicks
    var = float(np.var(rates))
    m = min(max(m, 1e-4), 0.999)
    # moment match: Var[p] = m(1-m)/(s+1)  ->  s = m(1-m)/var - 1
    if var <= 1e-9:
        s = 200.0
    else:
        s = m * (1.0 - m) / var - 1.0
    s = float(min(max(s, 2.0), 500.0))    # clamp: never dogmatic, never mush
    return {"alpha": round(m * s, 4), "beta": round((1.0 - m) * s, 4),
            "mean": round(m, 4), "strength": round(s, 1), "n_targets": len(pts)}


def posterior(orders: int, clicks: int, prior: dict) -> dict:
    """Posterior CVR for one target under the account prior: smoothed point
    estimate + 90% credible interval."""
    a = prior["alpha"] + max(orders, 0)
    b = prior["beta"] + max(clicks - orders, 0)
    return {"cvr_smoothed": round(a / (a + b), 4),
            "cvr_lo": round(beta_ppf(a, b, 0.05), 4),
            "cvr_hi": round(beta_ppf(a, b, 0.95), 4)}


def p_below(orders: int, clicks: int, prior: dict, x: float) -> float:
    """P(true CVR < x) under the posterior — the negation/pause confidence."""
    a = prior["alpha"] + max(orders, 0)
    b = prior["beta"] + max(clicks - orders, 0)
    return betainc(a, b, min(max(x, 0.0), 1.0))


# ---- robust anomaly detection (median/MAD + direction-aware severity) --------
# metric -> which direction is BAD (+1 spike-up is bad, -1 drop is bad)
BAD_DIRECTION = {"spend": +1, "acos": +1, "cpc": +1, "sales": -1, "orders": -1,
                 "clicks": -1, "impressions": -1, "ctr": -1, "cvr": -1}


def robust_anomalies(series: list[dict], keys: list[str],
                     z_thresh: float = 3.5, min_points: int = 5) -> list[dict]:
    """Flag points whose robust z-score (|x − median| / (1.4826·MAD)) crosses
    `z_thresh`, per metric, over a list of {date, <metric>...} dicts. Severity is
    direction-aware: an anomaly moving in the metric's BAD direction = 'bad',
    the other way = 'good' (still reported — a sales spike is worth seeing).
    MAD (not σ) so one genuine spike can't inflate the scale and hide itself.
    Needs ≥ min_points points; ties (MAD 0) fall back to mean abs deviation."""
    out = []
    if len(series) < min_points:
        return out
    for key in keys:
        vals = np.array([float(p.get(key) or 0.0) for p in series])
        med = float(np.median(vals))
        mad = float(np.median(np.abs(vals - med)))
        scale = 1.4826 * mad
        if scale <= 1e-9:
            scale = float(np.mean(np.abs(vals - med))) or 0.0
            if scale <= 1e-9:
                continue                  # constant series — nothing to flag
        z = (vals - med) / scale
        for i, p in enumerate(series):
            if abs(z[i]) < z_thresh:
                continue
            direction = 1 if z[i] > 0 else -1
            bad = BAD_DIRECTION.get(key, +1) == direction
            out.append({"date": p.get("date"), "metric": key,
                        "value": round(float(vals[i]), 2), "typical": round(med, 2),
                        "z": round(float(z[i]), 1),
                        "direction": "spike" if direction > 0 else "drop",
                        "severity": "bad" if bad else "good"})
    sev = {"bad": 0, "good": 1}
    out.sort(key=lambda r: (sev[r["severity"]], -abs(r["z"])))
    return out


# ---- Holt double exponential smoothing (level + trend forecast) --------------
def holt_forecast(values: list[float], alpha: float = 0.5, beta: float = 0.3) -> Optional[dict]:
    """One-step-ahead forecast with a ±1.28σ (~80%) interval from in-sample
    one-step residuals. Needs ≥ 3 points; returns None below that."""
    v = [float(x or 0.0) for x in values]
    if len(v) < 3:
        return None
    level, trend = v[0], v[1] - v[0]
    residuals = []
    for x in v[1:]:
        pred = level + trend
        residuals.append(x - pred)
        new_level = alpha * x + (1 - alpha) * (level + trend)
        trend = beta * (new_level - level) + (1 - beta) * trend
        level = new_level
    fc = level + trend
    sigma = float(np.std(residuals)) if residuals else 0.0
    return {"forecast": round(fc, 2),
            "lo": round(fc - 1.28 * sigma, 2), "hi": round(fc + 1.28 * sigma, 2),
            "sigma": round(sigma, 2), "n": len(v)}


# ---- logistic regression (conversion propensity) -----------------------------
_MATCH_TYPES = ("broad", "phrase", "exact")


def _term_features(row: dict) -> list[float]:
    """Cheap, leak-free features for one aggregated search term. Deliberately
    excludes orders/sales (the label) and spend (≈ clicks × cpc, near-leak)."""
    clicks = float(row.get("clicks") or 0)
    impressions = float(row.get("impressions") or 0)
    spend = float(row.get("spend") or 0)
    term = str(row.get("search_term") or "")
    mt = str(row.get("match_type") or "").strip().lower()
    cpc = spend / clicks if clicks else 0.0
    ctr = clicks / impressions if impressions else 0.0
    words = len(term.split())
    is_asin = 1.0 if re.fullmatch(r"[Bb]0[0-9A-Za-z]{8}", term.strip()) else 0.0
    return ([math.log1p(clicks), math.log1p(impressions), cpc, ctr,
             float(words), float(len(term)), is_asin]
            + [1.0 if mt == m else 0.0 for m in _MATCH_TYPES])


FEATURE_NAMES = (["log_clicks", "log_impressions", "cpc", "ctr", "words",
                  "chars", "is_asin"] + [f"match_{m}" for m in _MATCH_TYPES])


class LogReg:
    """L2 logistic regression, full-batch gradient descent, zero init —
    deterministic. Standardizes features internally."""

    def __init__(self, l2: float = 1.0, iters: int = 400, lr: float = 0.5):
        self.l2, self.iters, self.lr = l2, iters, lr
        self.w = self.b = self.mu = self.sd = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "LogReg":
        self.mu = X.mean(axis=0)
        self.sd = X.std(axis=0)
        self.sd[self.sd < 1e-9] = 1.0
        Xs = (X - self.mu) / self.sd
        n, d = Xs.shape
        self.w, self.b = np.zeros(d), 0.0
        for _ in range(self.iters):
            z = Xs @ self.w + self.b
            p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
            g = p - y
            self.w -= self.lr * ((Xs.T @ g) / n + self.l2 * self.w / n)
            self.b -= self.lr * float(g.mean())
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        Xs = (X - self.mu) / self.sd
        z = Xs @ self.w + self.b
        return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _auc(y: np.ndarray, p: np.ndarray) -> float:
    """Rank AUC via the Mann-Whitney statistic (tie-aware)."""
    order = np.argsort(p, kind="stable")
    ranks = np.empty(len(p), dtype=float)
    ranks[order] = np.arange(1, len(p) + 1)
    # average ranks over ties
    for val in np.unique(p):
        m = p == val
        if m.sum() > 1:
            ranks[m] = ranks[m].mean()
    pos = y == 1
    n1, n0 = int(pos.sum()), int((~pos).sum())
    if n1 == 0 or n0 == 0:
        return 0.5
    return float((ranks[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def train_term_model(rows: list[dict], min_rows: int = 30, min_class: int = 5,
                     min_auc: float = 0.62) -> Optional[dict]:
    """Train the conversion-propensity model on the cadence's own aggregated
    search terms (label = converted). Returns {model, auc, n, base_rate} or None
    when the account is too small / the model can't beat chance."""
    usable = [r for r in rows if (r.get("clicks") or 0) > 0 and r.get("search_term")]
    if len(usable) < min_rows:
        return None
    y = np.array([1.0 if (r.get("orders") or 0) > 0 else 0.0 for r in usable])
    n_pos = int(y.sum())
    if n_pos < min_class or len(usable) - n_pos < min_class:
        return None
    X = np.array([_term_features(r) for r in usable])
    model = LogReg().fit(X, y)
    auc = _auc(y, model.predict(X))
    if auc < min_auc:
        return None                       # can't beat chance — stay silent
    return {"model": model, "auc": round(auc, 3), "n": len(usable),
            "base_rate": round(n_pos / len(usable), 4)}


def score_terms(model: dict, rows: list[dict]) -> list[dict]:
    """P(convert) per term under the trained model, highest first."""
    if not model or not rows:
        return []
    X = np.array([_term_features(r) for r in rows])
    p = model["model"].predict(X)
    out = []
    for r, pi in zip(rows, p):
        out.append({**r, "p_convert": round(float(pi), 3)})
    out.sort(key=lambda r: -r["p_convert"])
    return out


# ---- cadence-plan integration ------------------------------------------------
def _stamp(row: dict, prior: dict, be_cvr: Optional[float], mode: str) -> None:
    """Attach the ml block to one plan row. `mode` decides what the confidence
    means:  'loser'  = P(true CVR below break-even CVR)   (negate / pause)
            'winner' = P(true CVR above break-even CVR)   (promote / scale)
            None     = no confidence, just the smoothed CVR (bid tweaks)."""
    orders, clicks = int(row.get("orders") or 0), int(row.get("clicks") or 0)
    ml = posterior(orders, clicks, prior)
    if be_cvr and mode:
        below = p_below(orders, clicks, prior, be_cvr)
        ml["confidence"] = round(below if mode == "loser" else 1.0 - below, 3)
    row["ml"] = ml


def enrich_plan(plan: dict, all_rows: list[dict], target_acos: float,
                avg_cpc: Optional[float] = None) -> None:
    """Stamp every actionable row of a cadence plan with its ml block and add the
    plan-level `ml` summary. `all_rows` = the aggregates the prior is fit on
    (dicts with orders/clicks — aggregate_targets() or harvest aggregates).

    Break-even CVR: converting at goal ACoS needs CVR ≥ cpc / (target_acos × AOV).
    Without a reliable AOV chain we use the account-level identity
    be_cvr = avg_cpc × account_cvr / (target_acos × revenue_per_order) collapsed
    to the pooled form below — good enough as a single account-wide threshold
    for calibrated confidences, and clearly labeled as such in the UI."""
    prior = fit_beta_prior([(r.get("orders") or 0, r.get("clicks") or 0) for r in all_rows])
    if prior is None:
        plan["ml"] = None
        return
    # account-wide break-even CVR: spend/sales identity at goal ACoS.
    clicks = sum(r.get("clicks") or 0 for r in all_rows)
    spend = sum(r.get("spend") or 0 for r in all_rows)
    sales = sum(r.get("sales") or 0 for r in all_rows)
    orders = sum(r.get("orders") or 0 for r in all_rows)
    cpc = avg_cpc if avg_cpc else (spend / clicks if clicks else None)
    aov = sales / orders if orders else None
    be_cvr = None
    if cpc and aov and target_acos:
        be_cvr = min(max(cpc / (target_acos * aov), 1e-4), 0.999)
    for key, mode in (("bid_tweaks", None), ("promotes", "winner"), ("scales", "winner"),
                      ("negates", "loser"), ("bleeders", "loser"), ("pauses", "loser")):
        for row in plan.get(key) or []:
            _stamp(row, prior, be_cvr, mode)
    plan["ml"] = {"prior": prior,
                  "be_cvr": round(be_cvr, 4) if be_cvr else None,
                  "account_cvr": round(orders / clicks, 4) if clicks else None}
