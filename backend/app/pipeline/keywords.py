"""Keyword mining — consolidate Amazon Brand Analytics Search Query Performance
(SQP) + Helium10 Cerebro into one deduped pool, and recommend generic keywords
worth targeting.

Upload each source separately; rows merge by normalized phrase (case/space
folded), keeping the max search volume and each source's own metrics. The
recommender surfaces non-branded, not-yet-targeted head terms by opportunity.
"""
from __future__ import annotations
import re
from typing import Optional
import pandas as pd
from sqlalchemy.orm import Session
from .. import models as md
from .. import database as dbmod

_ASIN_RE = re.compile(r"^b0[a-z0-9]{8}$")


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def _int(x) -> int:
    try:
        return int(float(str(x).replace(",", "").replace("$", "").strip()))
    except (TypeError, ValueError):
        return 0


def _num(x):
    try:
        return float(str(x).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _header_row(raw: pd.DataFrame) -> Optional[int]:
    """Find the real header row — these exports carry a metadata preamble."""
    for i in range(min(15, len(raw))):
        low = [str(c).strip().lower() for c in raw.iloc[i].tolist()]
        if any(c in ("search query", "keyword phrase", "keyword") or "search query" in c for c in low):
            return i
    return None


def _promote(raw: pd.DataFrame) -> pd.DataFrame:
    i = _header_row(raw)
    if i is None:
        raw.columns = [str(c).strip() for c in raw.iloc[0].tolist()]
        return raw.iloc[1:].reset_index(drop=True)
    df = raw.iloc[i + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[i].tolist()]
    return df.reset_index(drop=True)


def _csv_header_idx(path: str) -> int:
    """Line index of the real header (these exports carry a metadata preamble)."""
    import csv as _csv
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, row in enumerate(_csv.reader(f)):
            if i > 15:
                break
            low = [str(c).strip().lower() for c in row]
            if any(c in ("search query", "keyword phrase", "keyword") or "search query" in c for c in low):
                return i
    return 0


def _read(path: str) -> pd.DataFrame:
    """Read a research file, skipping any metadata preamble to the real header.
    The preamble has fewer columns than the table, so detect the header line and
    skip to it (read_csv can't tokenize the ragged rows otherwise)."""
    if path.lower().endswith(".csv"):
        return pd.read_csv(path, skiprows=_csv_header_idx(path), encoding="utf-8-sig")
    from . import workbook
    # close the handle before returning: Windows can't unlink a file the
    # process still holds open, and callers unlink the temp upload after us.
    with pd.ExcelFile(path, engine=workbook.excel_engine()) as xls:
        for sn in xls.sheet_names:
            raw = pd.read_excel(xls, sheet_name=sn, header=None, nrows=20, dtype=str)
            if _header_row(raw) is not None:
                return _promote(pd.read_excel(xls, sheet_name=sn, header=None, dtype=str))
        return pd.read_excel(xls, sheet_name=xls.sheet_names[0])


def _find(df: pd.DataFrame, *preds) -> Optional[str]:
    norm = {str(c).strip().lower(): c for c in df.columns}
    for pred in preds:
        for low, orig in norm.items():
            if pred(low):
                return orig
    return None


def parse_sqp(path: str) -> list[dict]:
    """Amazon Brand Analytics — Search Query Performance."""
    df = _read(path)
    kw = _find(df, lambda s: s == "search query", lambda s: "search query" in s and "score" not in s)
    if not kw:
        raise ValueError("no 'Search Query' column — is this a Brand Analytics SQP file?")
    vol = _find(df, lambda s: "search query volume" in s, lambda s: "query volume" in s, lambda s: s == "volume")
    imp = _find(df, lambda s: "impressions" in s and "total" in s, lambda s: "impressions" in s)
    clk = _find(df, lambda s: "clicks" in s and "total" in s, lambda s: s == "clicks: total count")
    pur = _find(df, lambda s: "purchases" in s and "total" in s, lambda s: "purchases" in s)
    out = []
    for _, r in df.iterrows():
        phrase = str(r[kw]).strip()
        if not phrase or phrase.lower() == "nan":
            continue
        out.append({"keyword": phrase, "search_volume": _int(r[vol]) if vol else 0,
                    "sqp_impressions": _int(r[imp]) if imp else 0,
                    "sqp_clicks": _int(r[clk]) if clk else 0,
                    "sqp_purchases": _int(r[pur]) if pur else 0})
    return out


def parse_cerebro(path: str) -> list[dict]:
    """Helium10 Cerebro keyword export."""
    df = _read(path)
    kw = _find(df, lambda s: s == "keyword phrase", lambda s: "keyword phrase" in s, lambda s: s == "keyword")
    if not kw:
        raise ValueError("no 'Keyword Phrase' column — is this a Helium10 Cerebro file?")
    vol = _find(df, lambda s: s == "search volume", lambda s: "search volume" in s)
    org = _find(df, lambda s: "organic rank" in s)
    spo = _find(df, lambda s: "sponsored rank" in s)
    comp = _find(df, lambda s: "competing products" in s, lambda s: s == "competing products count")
    sales = _find(df, lambda s: "keyword sales" in s)
    out = []
    for _, r in df.iterrows():
        phrase = str(r[kw]).strip()
        if not phrase or phrase.lower() == "nan":
            continue
        out.append({"keyword": phrase, "search_volume": _int(r[vol]) if vol else 0,
                    "cerebro_organic_rank": _int(r[org]) if org and _int(r[org]) else None,
                    "cerebro_sponsored_rank": _int(r[spo]) if spo and _int(r[spo]) else None,
                    "cerebro_competing": _int(r[comp]) if comp else None,
                    "cerebro_sales": _num(r[sales]) if sales else None})
    return out


def _ensure_schema(db: Session) -> None:
    """Defensive: a mined_keyword table created before the STR-source columns
    won't have them — ALTER them in once so old pools keep working."""
    from sqlalchemy import text
    cols = [r[1] for r in db.execute(text("PRAGMA table_info(mined_keyword)")).fetchall()]
    if cols and "src_str" not in cols:
        for ddl in ("ALTER TABLE mined_keyword ADD COLUMN src_str BOOLEAN DEFAULT 0",
                    "ALTER TABLE mined_keyword ADD COLUMN str_impressions INTEGER DEFAULT 0",
                    "ALTER TABLE mined_keyword ADD COLUMN str_clicks INTEGER DEFAULT 0",
                    "ALTER TABLE mined_keyword ADD COLUMN str_orders INTEGER DEFAULT 0"):
            db.execute(text(ddl))
        db.commit()


def merge_str_terms(db: Session, terms: list[dict]) -> dict:
    """Merge Search Term Report terms (harvest bulk upload) into the mined pool
    as a third source. terms: [{keyword, impressions, clicks, orders}]."""
    _ensure_schema(db)
    added = merged = 0
    for r in terms:
        key = _norm(r.get("keyword"))
        if not key or _ASIN_RE.match(key):
            continue
        m = db.get(md.MinedKeyword, key)
        if m is None:
            m = md.MinedKeyword(keyword=key, display=str(r["keyword"]).strip(),
                                words=len(key.split()), search_volume=0)
            db.add(m); added += 1
        else:
            merged += 1
        m.src_str = True
        m.str_impressions = max(m.str_impressions or 0, int(r.get("impressions") or 0))
        m.str_clicks = max(m.str_clicks or 0, int(r.get("clicks") or 0))
        m.str_orders = max(m.str_orders or 0, int(r.get("orders") or 0))
    db.commit()
    return {"source": "str", "rows": len(terms), "new": added, "merged": merged}


def load_keywords(db: Session, rows: list[dict], source: str) -> dict:
    """Merge rows into the deduped pool. source = 'sqp' | 'cerebro'."""
    _ensure_schema(db)
    added = merged = 0
    for r in rows:
        key = _norm(r["keyword"])
        if not key:
            continue
        m = db.get(md.MinedKeyword, key)
        if m is None:
            m = md.MinedKeyword(keyword=key, display=r["keyword"].strip(),
                                words=len(key.split()), search_volume=0)
            db.add(m); added += 1
        else:
            merged += 1
        m.search_volume = max(m.search_volume or 0, r.get("search_volume") or 0)
        if source == "sqp":
            m.src_sqp = True
            m.sqp_impressions = max(m.sqp_impressions or 0, r.get("sqp_impressions") or 0)
            m.sqp_clicks = max(m.sqp_clicks or 0, r.get("sqp_clicks") or 0)
            m.sqp_purchases = max(m.sqp_purchases or 0, r.get("sqp_purchases") or 0)
        else:
            m.src_cerebro = True
            for col in ("cerebro_organic_rank", "cerebro_sponsored_rank", "cerebro_competing", "cerebro_sales"):
                if r.get(col) is not None:
                    setattr(m, col, r[col])
    db.commit()
    return {"source": source, "rows": len(rows), "new": added, "merged": merged}


def _serialize(m: md.MinedKeyword) -> dict:
    srcs = [s for s, on in (("SQP", m.src_sqp), ("Cerebro", m.src_cerebro),
                            ("STR", m.src_str)) if on]
    return {"keyword": m.display, "search_volume": m.search_volume, "words": m.words,
            "sources": srcs, "both": len(srcs) >= 2,
            "sqp_purchases": m.sqp_purchases, "sqp_clicks": m.sqp_clicks,
            "str_impressions": m.str_impressions, "str_orders": m.str_orders,
            "organic_rank": m.cerebro_organic_rank, "sponsored_rank": m.cerebro_sponsored_rank,
            "competing": m.cerebro_competing, "keyword_sales": m.cerebro_sales}


def consolidated(db: Session) -> dict:
    _ensure_schema(db)
    rows = db.query(md.MinedKeyword).order_by(md.MinedKeyword.search_volume.desc()).all()
    out = [_serialize(m) for m in rows]
    return {"count": len(out), "sqp": sum(1 for m in rows if m.src_sqp),
            "cerebro": sum(1 for m in rows if m.src_cerebro),
            "str": sum(1 for m in rows if m.src_str),
            "both": sum(1 for m in rows if (bool(m.src_sqp) + bool(m.src_cerebro) + bool(m.src_str)) >= 2),
            "rows": out}


def _brand_tokens(db: Session) -> set[str]:
    store = db.info.get("store")
    title = dbmod._read_meta(store).get("title", "") if store else ""
    return {t for t in re.split(r"[^a-z0-9]+", title.lower()) if len(t) >= 3}


def _is_branded(toks: list[str], brand: set[str]) -> bool:
    """Match brand even on singular/plural drift (zvalve ↔ zvalves)."""
    for t in toks:
        for b in brand:
            if t == b or (len(b) >= 4 and (t.startswith(b) or b.startswith(t))):
                return True
    return False


def recommend(db: Session, top: int = 60) -> dict:
    """Generic (non-branded), not-yet-targeted head terms ranked by opportunity."""
    brand = _brand_tokens(db)
    targeted = {(_norm(t.keyword_text)) for t in db.query(md.DimTarget)
                .filter(md.DimTarget.target_type == "keyword").all() if t.keyword_text}

    recs = []
    for m in db.query(md.MinedKeyword).all():
        key = m.keyword
        toks = key.split()
        if not (1 <= len(toks) <= 5):
            continue
        if key in targeted:
            continue                                   # already running
        if any(_ASIN_RE.match(t) for t in toks):
            continue                                   # ASIN target, not generic
        if brand and _is_branded(toks, brand):
            continue                                   # branded
        if (m.search_volume or 0) < 50:
            continue                                   # too thin
        score = (m.search_volume or 0) * (1.6 if (m.src_sqp and m.src_cerebro) else 1.0)
        why = []
        if m.src_sqp and m.src_cerebro:
            why.append("in both sources")
        if m.cerebro_organic_rank and m.cerebro_organic_rank > 0:
            why.append(f"organic rank {m.cerebro_organic_rank}")
        if m.sqp_purchases:
            why.append(f"{m.sqp_purchases} BA purchases")
        recs.append({"keyword": m.display, "search_volume": m.search_volume,
                     "words": m.words, "sources": [s for s, on in (("SQP", m.src_sqp), ("Cerebro", m.src_cerebro)) if on],
                     "score": round(score), "reason": ", ".join(why) or "generic head term"})
    recs.sort(key=lambda r: r["score"], reverse=True)
    return {"count": len(recs), "brand_excluded": sorted(brand), "rows": recs[:top]}


def clear(db: Session) -> int:
    n = db.query(md.MinedKeyword).delete()
    db.commit()
    return n
