# KICKOFF — PPC App Feature Build (4 features)

Feed this file + the three spec files to Claude Code from the repo root. Build in this order, one feature per session/PR:

1. `SPEC_WATERFALL_ENGINE.md` — Waterfall Restructure Engine + strategy-aware bid math + effective-bid ledger
2. `SPEC_CANNIBALIZATION.md` — Cannibalization / Keyword Ownership Detector (depends on #1's classifier)
3. `SPEC_PLACEMENT_SBSD.md` — Placement panel upgrade + SB/SD ingestion

## Non-negotiable repo conventions (from CLAUDE.md — verify against it, it wins on conflict)

- Each feature = **own table(s) + own upload where specified**, never mutate the audit star schema or shift `active_snapshot`.
- New routers use `Depends(get_db)` — per-user/store/project/cadence isolation is automatic. Zero scoping code in routers.
- Pure compute functions live in pipeline modules / `metrics.py`: `(rows, thresholds) -> result`, zero I/O, unit-testable.
- All bulk output routes through `bulkfmt.py`: `idstr` for IDs, `valid_keyword` check, ASIN terms → product targets never keywords, auto-clauses never negated, in-file + in-account dedup.
- **Amazon IDs are 16–18 digit strings.** Read with `dtype=str`, never let them touch float64. This has bitten before.
- Frontend: `DataTable` from `components/table.jsx` for every table (use `lean` for short sub-tables), tokens only (no hex), `useModals()` never `window.confirm`.
- After backend change: `python -m pytest -q`. After frontend change: `npm run build`. Update `MANUAL.md` (section + Changelog) with every feature.
- Every "action" = downloadable bulk `.xlsx` the user re-uploads to Amazon. No Ads API. Never auto-apply — user selects rows, then generate.

## Bulk file ground truth (verified against real export, Jul 2026 template)

Sheet `Sponsored Products Campaigns`, exact columns:

```
Product, Entity, Operation, Campaign ID, Ad Group ID, Portfolio ID, Ad ID, Keyword ID,
Product Targeting ID, Campaign Name, Ad Group Name, Campaign Name (Informational only),
Ad Group Name (Informational only), Portfolio Name (Informational only), Start Date, End Date,
Targeting Type, State, Campaign State (Informational only), Ad Group State (Informational only),
Daily Budget, SKU, ASIN (Informational only), Eligibility Status (Informational only),
Reason for Ineligibility (Informational only), Ad Group Default Bid,
Ad Group Default Bid (Informational only), Bid, Keyword Text, Native Language Keyword,
Native Language Locale, Match Type, Bidding Strategy, Placement, Percentage,
Product Targeting Expression, Resolved Product Targeting Expression (Informational only),
Audience ID, Shopper Cohort Percentage, Shopper Cohort Type, Segment Name (Informational only),
Sites, Off-Amazon ad serving, Impressions, Clicks, Click-through Rate, Spend, Sales, Orders,
Units, Conversion Rate, ACOS, CPC, ROAS
```

Entity values seen: `Campaign, Bidding Adjustment, Ad Group, Product Ad, Negative Keyword, Product Targeting, Negative Product Targeting, Keyword`.

Other sheets: `Portfolios`, `Sponsored Brands Campaigns` (legacy), `SB Multi Ad Group Campaigns`, `Sponsored Display Campaigns`, `SP Search Term Report`, `SB Search Term Report`, `RAS Search Term Report`, `Budget Rules`.

**Trap:** `Sponsored Brands Campaigns` and `SB Multi Ad Group Campaigns` contain the SAME campaigns duplicated across both sheets. Ingest SB from `SB Multi Ad Group Campaigns` only, or dedupe by Campaign ID — never sum both.

Ignore precomputed rate columns (`ACOS, CPC, ROAS, CTR, Conversion Rate`) — recompute from raw counts per existing app rule.

## Field bugs already hit in production use — encode as tests

1. **CPC-based bid cut on up/down campaigns RAISES bids.** Up/down inflates CPC to ~2× bid; formula `cpc × goal/acos` can exceed current bid. See `safe_bid_cut` in SPEC_WATERFALL_ENGINE.md §Bid Math.
2. **`Negative Keyword` entity requires Ad Group ID** (parent). Campaign-wide negation = `Campaign Negative Keyword`, no ad group. Wrong entity → Amazon error "Missing Parent ID" on every row.
3. **Consecutive exports computed from stale snapshot bids** double-apply or overwrite prior changes. See Effective-Bid Ledger spec.
4. **Never negate a term that converts in ANY campaign account-wide** (term can be a loser in campaign A, winner in campaign B). Negation candidates must be checked against account-wide search-term orders.
5. **Boss selection by raw sales crowns bleeders.** A 111% ACoS campaign can out-sell a 12% one. Profitable-first rule required (spec §Boss Selection).
6. **Naive sci-notation:** writing IDs through float64 produces `4.64974E+14` → Amazon "temporary ID" rejection. Already solved by `bulkfmt.idstr` — use it everywhere.

## Definition of done per feature

- pytest green, `npm run build` green
- Unit tests for every pure function incl. the 6 regression cases above where applicable
- End-to-end: sample bulk in → expected plan/flags out → generated bulk validates (no dup IDs, no missing parents, IDs exact strings)
- MANUAL.md updated
- Panel renders with `DataTable`, respects cadence/store/project scope prop pattern
