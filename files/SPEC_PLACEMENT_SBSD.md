# SPEC — Placement Panel Upgrade + SB/SD Ingestion

## Part 1 — Placement upgrade

Current `placement` pipeline exists; upgrade it to parse `Entity='Bidding Adjustment'` rows (currently in the ignore list) and act on them.

### Data
`Bidding Adjustment` rows carry per-placement metrics + current modifier:
- `Placement` values: `Placement Top` (top of search), `Placement Rest Of Search`, `Placement Product Page` (+ possibly `Placement Amazon Business`).
- `Percentage` = current modifier (0–900). `Bidding Strategy` present on same row.
- Metric columns populated per placement per campaign.

### Analysis (pure)
```
per campaign + account rollup:
  placement -> spend, sales, acos, cvr, cpc, share_of_spend
flags:
  FLAT_MODIFIER   same Percentage on all placements with spend (real case: +20% everywhere)
  PLACEMENT_BLEED placement acos > 2x goal AND spend >= min_spend  (real case: product page 76.7% vs TOS 21.9%)
  TOS_STARVED     TOS acos < goal AND TOS share_of_spend < 25%
```

### Modifier recommendation
```
new_pct = clip(current_pct * (goal_acos / placement_acos), 0, 400)   # cut path
TOS raise path: if TOS acos < goal: new_pct = min(current + 25, 150) # step raises only
Product Page: floor at 0 (can't go negative — lower base bid instead; if PP still
bleeding at 0%, emit companion bid-cut suggestion via safe_bid_cut on campaign's targets)
```
Emit `Bidding Adjustment` update rows (Campaign ID + Bidding Strategy + Placement + Percentage). Route through `bulkfmt`. Log to ChangeLog; no BidLedger (modifiers aren't target bids) but add `PlacementLedger` mirroring the applied/pending pattern if simple, else defer.

### UI
Placement panel gains: account placement table (3 rows, `lean`), per-campaign `DataTable` (campaign | placement | spend | sales | acos | current % | suggested % | flag tag), select + export.

### Tests
- flat-modifier detection; PP floor at 0 with companion suggestion; TOS step raise cap; never raise modifier on bleeding placement.

## Part 2 — SB/SD ingestion

App is SP-only. Add read + report (v1 = audit visibility, NOT bulk generation — SB bulk format differs enough that emitting updates is v2).

### Sheets
- **SB:** ingest `SB Multi Ad Group Campaigns` ONLY. `Sponsored Brands Campaigns` sheet duplicates the same campaigns (verified on real export — identical spend/sales) — reading both double-counts. Entities: Campaign, Ad Group, Keyword, Video Ad, Product Collection Ad, Store Spotlight Ad, Bidding Adjustment by Placement.
- **SD:** `Sponsored Display Campaigns`. Entities: Campaign, Ad Group, Product Ad, Contextual Targeting, Audience Targeting, Negative Product Targeting.
- **SB STR:** `SB Search Term Report` sheet — same STR compute functions from `weekly.py` are model-agnostic; reuse `summarize`/`compute_harvest` read-only (harvest suggestions displayed, bulk emission deferred to v2).

### Data model
Own tables, own upload (or fan-out flag on the shared upload): `SBFact`, `SDFact` — one row per entity per snapshot, raw counts + IDs as strings, `ad_format` column on SB (video/product_collection/store_spotlight).

### Report (pure)
- Channel mix card: SP vs SB vs SD spend/sales/ACoS side by side (answers "SB is 11.8% vs SP 39.4%" instantly).
- SB keyword table: keyword | match | ad format | spend | sales | acos | flag (`HIGH_ACOS`, `WASTED_SPEND` reuse thresholds from cadence presets).
- Brand vs non-brand split: term/keyword classified by configurable brand-term list per store (`_meta.json` addition, e.g. ["pro ice", "proice"]) → exposes "SB is 92% branded" defense-vs-growth ratio.
- SD: targeting table + dormant-channel banner when spend == 0.

### Router / UI
`/channels/upload`, `/channels/summary`, `/channels/sb-keywords`, `/channels/sd-targets`. New `Channels.jsx` tab: mix cards (mono font numbers, up/down tokens), brand split donut (Chart.js — already a dep), two `DataTable`s.

### Tests
- SB dedupe: legacy + multi sheets in one file → single campaign set, totals match multi sheet alone
- brand classifier: "pro ice youth" → brand, "shoulder ice pack" → non-brand
- channel rollup math vs fixture
