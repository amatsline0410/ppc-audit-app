"""Shared Amazon SP bulk-file validity helpers.

Every engine that emits a bulk file for re-upload to Amazon routes its negative
targets through here, so the output always matches Amazon's accepted format:

  * a search term that is an ASIN must be a (negative) PRODUCT TARGET with an
    `asin="B0..."` expression — never a keyword;
  * auto-campaign match clauses (loose-match / close-match / substitutes /
    complements) cannot be negated as product targets at all;
  * a negative that already exists in the account, or is repeated within the
    file, must not be re-created (Amazon rejects "already exists" / "Duplicate").
"""
from __future__ import annotations
import re
from sqlalchemy.orm import Session
from .. import models as md

# Amazon product ASIN: 10 chars, "B0" + 8 alphanumerics.
_ASIN_RE = re.compile(r"^b0[a-z0-9]{8}$", re.IGNORECASE)

# Automatic-campaign targeting clauses — auto match-type groups, NOT product
# targets. Amazon rejects them as negative-product-targeting expressions.
AUTO_CLAUSES = {"loose-match", "close-match", "substitutes", "complements"}


# A valid SP keyword: letters/digits/spaces + a little punctuation, ≤80 chars,
# ≤10 words. Amazon rejects anything else ("Keyword is invalid") — e.g. control /
# object-replacement chars (￼), ™ ® " : ( ) /, over-long phrases.
_KW_OK = re.compile(r"^[\w\s'\-.,&]+$", re.UNICODE)


def is_asin(term) -> bool:
    return bool(term) and bool(_ASIN_RE.match(str(term).strip()))


def valid_keyword(term) -> bool:
    t = str(term or "").strip()
    if not t or len(t) > 80 or len(t.split()) > 10:
        return False
    if any(ord(ch) < 32 or ord(ch) == 0xFFFC for ch in t):   # control / object-replacement
        return False
    return bool(_KW_OK.match(t))


def idstr(v) -> str:
    """Exact integer string for an entity ID, never via float (mangles big IDs)."""
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else str(v)
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def neg_pt_expression(expr) -> str | None:
    """A valid SP *negative* product-targeting expression, or None.

    SP only accepts `asin="B0..."` negatives. An auto clause or a non-ASIN
    expression (e.g. `category=...`) can't be negated -> None.
    """
    if not expr:
        return None
    e = str(expr).strip()
    low = e.lower()
    if low in AUTO_CLAUSES:
        return None
    if low.startswith('asin='):
        return e
    if _ASIN_RE.match(low):
        return f'asin="{e.upper()}"'
    return None


def existing_negatives(db: Session) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """What's already negated in the account, from the loaded dims.

    Returns (neg_kw, neg_pt):
      neg_kw : ad_group_id -> {negative keyword text, lowercased}
      neg_pt : ad_group_id -> {negative product-target expression, lowercased}
    Used to skip re-creating a negative Amazon already has.
    """
    neg_kw: dict[str, set[str]] = {}
    neg_pt: dict[str, set[str]] = {}
    for t in db.query(md.DimTarget).filter(
            md.DimTarget.target_type.in_(("negative_keyword", "negative_product_target"))).all():
        if t.target_type == "negative_keyword" and t.keyword_text:
            neg_kw.setdefault(t.ad_group_id, set()).add(t.keyword_text.strip().lower())
        elif t.target_type == "negative_product_target" and t.expression:
            neg_pt.setdefault(t.ad_group_id, set()).add(t.expression.strip().lower())
    return neg_kw, neg_pt
