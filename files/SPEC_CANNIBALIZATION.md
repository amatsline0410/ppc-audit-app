# SPEC — Cannibalization / Keyword Ownership Detector

Finds and resolves two overlap types. Depends on `waterfall.classify()` for campaign→SKU mapping (build after Waterfall Engine).

## Overlap types

**Type 1 — Duplicate targets (structural):** same `keyword_text + match_type` enabled in 2+ campaigns (or same PT expression). Splits data, budgets compete. Real account showed 62 such pairs.

**Type 2 — Cross-product term overlap (from STR):** same customer search term generating clicks/orders for 2+ different SKUs. Amazon may serve the worse-converting product. Detection needs SKU attribution: term row → source campaign → single-SKU mapping (MULTI campaigns attribute to `ALL`, reported but not auto-resolved).

## Ownership rule (pure function)

```python
def resolve_owner(candidates, min_clicks=10):
    """candidates: [{sku, campaign_id, clicks, orders, spend, sales}]
    qualified = clicks >= min_clicks
    - >=2 qualified: owner = max CVR, tiebreak min ACoS
    - 1 qualified:   owner = it
    - 0 qualified:   owner = None (verdict 'insufficient_data' — no action)
    """
```

**Leave-both-alive exceptions (verdict `coexist`, no action emitted):**
- All candidates ACoS < goal AND each candidate's clicks ≥ min_clicks (term big enough to feed both).
- Different match-type tiers of the SAME SKU's funnel (exact in EXACT campaign + broad in BROAD campaign is the waterfall working — only flag if sculpting negative missing, then emit the negative instead).

## Resolution actions (user selects, never auto)

- Type 1 losers: keyword `State=paused` (by exact Keyword ID) + `Campaign Negative Keyword negativeExact` in loser campaign. Winner untouched.
- Type 2 losers: `negativeExact` of the term in loser SKU's AT/BROAD/PHRASE campaigns.
- **Account-wide converter guard (regression):** never emit a negative for a term with orders > 0 in the candidate's own campaign... AND check the negation target campaign doesn't have the term as live enabled keyword (mixed-campaign kill bug). Terms converting for the OWNER are of course fine to negate in LOSER campaigns — the guard is: never negate in a campaign where that term/keyword itself is converting or live.
- All output through `bulkfmt` (dedup vs existing negatives, ASIN terms → negative product targets, no auto-clause negation).

## Data model

```python
class OverlapFinding(Base):
    id, run_id, kind,            # 'duplicate_target'|'cross_product'
    term, match_type nullable,
    owner_sku nullable, owner_campaign_id nullable,
    verdict,                     # 'resolve'|'coexist'|'insufficient_data'
    candidates_json,             # per-candidate metrics for UI drill-down
    selected (default: verdict=='resolve')
```

Own table + own run; reads latest snapshot + embedded STR from the same upload used by Waterfall (share the upload — one POST can fan out to both engines via query flag `?engines=waterfall,cannibal`).

## Router `/cannibal/*`
`POST /cannibal/run` (reuse latest waterfall upload or accept own), `GET /cannibal/findings?kind=`, `POST /cannibal/bulk` (selected → bulk + ChangeLog + BidLedger for state changes).

## Frontend `Cannibalization.jsx`
Two `DataTable` sections (Type 1 / Type 2): term | candidates (expandable drill-down, `lean` sub-table per finding: SKU, campaign, clicks, CVR, ACoS) | owner badge | verdict tag | select. Coexist rows shown grey, unselectable. Summary cards: duplicates found, est. monthly wasted overlap spend, resolvable count.

## Tests
- resolve_owner: CVR winner; tiebreak ACoS; insufficient data → None
- coexist: both profitable + volume → no action; same-SKU tier pair → sculpting-negative-only
- converter guard: term with orders in target campaign never negated there
- quarterly re-review: findings regenerate idempotently on re-run (replace run, not append)
