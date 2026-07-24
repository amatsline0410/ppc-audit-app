"""Stage 6: automate. Turn selected flags into an Amazon SP bulk-upload sheet.

Never auto-applies. Caller passes the flags the user confirmed.
Output = .xlsx the user re-uploads to Amazon manually (no Ads API in v1).
"""
from __future__ import annotations
import io
import pandas as pd
from sqlalchemy.orm import Session
from .. import models as md
from . import bulkfmt

# minimal SP bulk columns Amazon accepts for updates/creates
BULK_COLS = ["Product", "Entity", "Operation", "Campaign ID", "Ad Group ID",
             "Keyword ID", "Product Targeting ID", "Keyword Text", "Match Type",
             "Product Targeting Expression", "Bid", "State"]


def flags_to_bulk(db: Session, flags: list[dict]) -> bytes:
    """flags: list of dicts with at least entity_id + flag + new_bid.
    Returns xlsx bytes ready to download."""
    targets = {t.target_id: t for t in db.query(md.DimTarget).all()}
    neg_kw_acct, neg_pt_acct = bulkfmt.existing_negatives(db)   # already in account
    seen_neg: set[tuple] = set()                                # dedup within this file
    rows = []
    for f in flags:
        t = targets.get(f["entity_id"])
        if not t:
            continue
        ag = db.get(md.DimAdGroup, t.ad_group_id)
        base = {c: None for c in BULK_COLS}
        base.update({"Product": "Sponsored Products",
                     "Campaign ID": bulkfmt.idstr(ag.campaign_id) if ag else None,
                     "Ad Group ID": bulkfmt.idstr(t.ad_group_id)})
        is_kw = t.target_type == "keyword"
        if is_kw:
            base.update({"Keyword ID": bulkfmt.idstr(t.target_id), "Keyword Text": t.keyword_text,
                         "Match Type": t.match_type})
        else:
            base.update({"Product Targeting ID": bulkfmt.idstr(t.target_id),
                         "Product Targeting Expression": t.expression})

        def pause_and_negate():
            pause = dict(base); pause.update({
                "Entity": "Keyword" if is_kw else "Product Targeting",
                "Operation": "update", "State": "paused"})
            rows.append(pause)
            neg = {c: None for c in BULK_COLS}
            neg.update({"Product": "Sponsored Products",
                        "Campaign ID": base["Campaign ID"], "Ad Group ID": t.ad_group_id,
                        "Operation": "create", "State": "enabled"})
            ag = t.ad_group_id
            # a keyword whose text is actually an ASIN must be negated as a product
            # target, not a keyword (Amazon rejects ASIN-as-negative-keyword).
            kw_text = t.keyword_text if is_kw else None
            if is_kw and not bulkfmt.is_asin(kw_text):
                term = (kw_text or "").strip().lower()
                key = (ag, "nkw", term)
                if not term or key in seen_neg or term in neg_kw_acct.get(ag, set()):
                    return  # blank / dup-in-file / already in account -> pause only
                seen_neg.add(key)
                neg.update({"Entity": "Negative Keyword", "Keyword Text": kw_text,
                            "Match Type": "Negative Exact"})
                rows.append(neg)
            else:
                # product target, or a keyword carrying an ASIN -> negative product target
                expr = bulkfmt.neg_pt_expression(kw_text if is_kw else t.expression)
                if expr is None:
                    return  # auto clause / non-ASIN expression: pause only, can't negate
                key = (ag, "npt", expr.lower())
                if key in seen_neg or expr.lower() in neg_pt_acct.get(ag, set()):
                    return
                seen_neg.add(key)
                neg.update({"Entity": "Negative Product Targeting",
                            "Product Targeting Expression": expr})
                rows.append(neg)

        flag, stage = f["flag"], f.get("stage")
        if flag == "HIGH_ACOS" and stage == "PAUSE":
            # ladder reached the end: stop the target + block the term
            pause_and_negate()
        elif flag in ("HIGH_ACOS", "OVERBID", "SCALE_WINNER", "BLEEDING") and f.get("new_bid"):
            # reduce / scale bid (MONITOR-with-bid included)
            base.update({"Entity": "Keyword" if is_kw else "Product Targeting",
                         "Operation": "update", "Bid": f["new_bid"], "State": "enabled"})
            rows.append(base)
        elif flag == "WASTED_SPEND":
            pause_and_negate()

    # final dedup: never emit the same update twice (Amazon "Duplicate Id") or the
    # same create/negate twice (Amazon "Duplicate Keyword Text" / "already exists").
    def _sig(r):
        kid = r.get("Keyword ID") or r.get("Product Targeting ID")
        if r.get("Operation") == "update" and kid:
            return ("u", r.get("Entity"), kid)
        return ("c", r.get("Entity"), r.get("Ad Group ID"),
                str(r.get("Keyword Text") or r.get("Product Targeting Expression") or "").lower())
    seen_row, deduped = set(), []
    for r in rows:
        s = _sig(r)
        if s in seen_row:
            continue
        seen_row.add(s)
        deduped.append(r)

    df = pd.DataFrame(deduped, columns=BULK_COLS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Sponsored Products Campaigns")
    return buf.getvalue()
