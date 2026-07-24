# SPEC — Waterfall Restructure Engine (+ safe bid math + effective-bid ledger)

Automates a full account restructure into the **RAF Funnel System** (Tiered Harvesting Funnel):

```
AT (discovery) → KWT-BROAD → KWT-PHRASE → KWT-EXACT (money tier)
                                        + PT (ASIN tier)
each promotion ↓ = negativeExact upstream (search term isolation)
1 SKU per campaign (SPAG). Boss campaign per SKU+slot; duplicates consolidated.
```

Output = **4 phased bulk files (A/B/C/D) + day-0 benchmark**, generated from one uploaded bulk, exported in dependency order.

## Data model

New tables (own upload, own db rows — do NOT touch star schema or `active_snapshot`):

```python
class WaterfallRun(Base):        # one row per generated plan
    id, created_at, status,      # status: draft|a_applied|b_applied|c_applied|d_applied|done
    naming_template,             # e.g. "SP - {sku} - {asin} - {slot} - RAF - up/down $1"
    heroes_json,                 # list of hero SKUs chosen
    params_json                  # thresholds used

class WaterfallItem(Base):       # one row per planned action
    id, run_id (FK cascade),
    phase,                       # 'A'|'B'|'C'|'D'
    action,                      # rename|budget|bid_cut|create_campaign|create_adgroup|
                                 # create_ad|create_keyword|create_pt|negative|pause
    sku, slot,                   # slot: AT|KWT-BROAD|KWT-PHRASE|KWT-EXACT|PT
    campaign_id, ad_group_id, target_id,   # strings, exact
    payload_json,                # new name / new bid / keyword text / expression etc.
    selected (bool, default True)

class BidLedger(Base):           # effective-bid overlay (see §Ledger)
    id, target_id (str, indexed), campaign_id,
    exported_bid, exported_state,
    run_id nullable, source,     # 'waterfall'|'weekly'|'bidopt'|'midmonth'|'pausescale'
    exported_at, applied (bool default False), applied_at nullable
```

## Pipeline module `pipeline/waterfall.py` — pure functions

### 1. `classify(frames) -> DataFrame`
Per enabled campaign:
- **SKU mapping:** group `Product Ad` rows by Campaign ID → `skus` list. `n_skus==1` → mappable; `n_skus>1` → `MULTI` (excluded from per-SKU funnel, listed separately); `n_skus==0` → `EMPTY`.
- **Slot:**
  - `Targeting Type == 'Auto'` → `AT` (regardless of campaign name — catches misnamed campaigns; real case: campaign named "PT" was Auto type).
  - Has keywords → dominant match type → `KWT-EXACT|KWT-PHRASE|KWT-BROAD`; >1 match type present → flag `mixed=True`.
  - No keywords but product targets → `PT`.
- Compute per-campaign 60d: spend, sales, acos (None when sales==0), impressions.

### 2. `select_bosses(classified, goal_acos) -> plan`
Per (sku, slot) group with >1 campaign, **profitable-first rule**:
```
candidates with acos < 2×goal AND sales > 0  → pick max sales
elif any sales > 0                            → pick min acos
else                                          → pick max impressions
```
Boss keeps Campaign ID (history preserved). Rest = losers.
**Regression test:** slot with {campaign A: sales 569, acos 111%} and {campaign B: sales 50, acos 12.7%} → boss MUST be B.

### 3. `build_phases(plan, frames, ledger, naming, opts) -> items`

**Phase A — renames (zero risk, first):**
- Boss campaign: `Operation=Update`, `Campaign Name` = template render, `Daily Budget` = opts.budget (default 10), State enabled.
- Every enabled ad group in boss: `Ad Group Name` = same rendered name.
- Slot render: AT→`AT`, PT→`PT`, KWT-*→`KWT - EXACT/BROAD/PHRASE`.

**Phase B — loser bid cuts (transitional overlap, not pause):**
- Every enabled Keyword/Product Targeting in loser campaigns: new bid = `max(effective_bid × 0.6, 0.15)`.
- `effective_bid` from BidLedger overlay (§Ledger), NOT raw snapshot bid.
- Skip targets whose ledger state = paused.

**Phase C — creates:**
- Missing (sku, slot) combos → new campaign (**State=paused** — born paused, user enables in batches), `Bidding Strategy = Dynamic bids - down only` (training wheels; naming can still say up/down — strategy flipped manually at day 14), Daily Budget = opts.budget, Start Date = today `YYYYMMDD`. + Ad Group (default bid 1.0) + Product Ad (SKU).
- New AT campaigns: 4 split targets with individual bids — `close-match 1.00, loose-match 0.75, substitutes 0.75, complements 0.50`.
- **Seeds:** from embedded `SP Search Term Report` — terms attributed to hero via single-SKU source campaign, `orders ≥ seed_min_orders (default 1)` AND `acos < goal`. Exclude ASIN-shaped terms (regex `^b0[a-z0-9]{8}$`) from keywords. Seed bid = `clip(spend/clicks × 1.1, 0.30, 2.00)`. Destination = hero's EXACT campaign (boss if exists, else new). Optional broad/phrase copies at ×0.6 / ×0.75 for heroes whose broad/phrase slots are NEW (empty) only.
- **Sculpting negatives:** for each hero, set = enabled exact keywords in boss EXACT + seeds. Emit `Campaign Negative Keyword` / `negativeExact` into that hero's AT + BROAD + PHRASE campaigns, **skipping any campaign where the term is a live enabled keyword** (mixed campaigns — negating kills it). Route through `bulkfmt` dedup vs existing account negatives.

**Phase D — pauses (generated now, gated in UI):**
- Loser campaigns + EMPTY campaigns of heroes: `Operation=Update, State=paused`, include current name.
- UI must block D export until A, B, C are `applied` (ledger `mark applied`).

### 4. `benchmark(frames, heroes) -> rows`
Per hero (single-SKU campaigns only): impressions, clicks, spend, sales, orders, acos, cpc, cvr. Stored in `WaterfallRun.params_json` + downloadable sheet. Used by day-21 verdict view (compare vs latest snapshot at that time).

## §Bid Math — `metrics.py` additions (fixes live bugs)

```python
def safe_bid_cut(bid, cpc, acos, goal_acos, strategy) -> float | None:
    """Bid cut that can NEVER raise.
    up/down strategy: CPC runs ~2x bid, CPC-based formula can exceed bid -> cut from BID.
    down-only / fixed: CPC-based cut is correct lever.
    """
    if not acos or acos <= goal_acos: return None
    ratio = goal_acos / acos
    if strategy and 'up and down' in strategy.lower():
        new = bid * ratio
    else:
        new = min(cpc * ratio if cpc else bid * ratio, bid * ratio if not cpc else 1e9)
        new = min(new, bid)          # hard never-raise guard
    new = max(round(new, 2), 0.15)
    assert new < bid, "cut must lower bid"
    return new
```
Wire into `bid_optimizer`, `weekly.compute_bid_tweaks`, `midmonth`, `pausescale` (replace raw `target_cpc_bid` on the *cut* path only; raises keep existing guardrails).
**Regression tests:** `(bid=0.86, cpc=1.95, acos=34, goal=24, 'Dynamic bids - up and down')` → ~0.61, never 1.38. `(bid=2.16, cpc=3.30, acos=36.4, goal=24, up/down)` → ~1.43.

## §Ledger — effective-bid overlay

Problem: export #2 computed from the snapshot ignores export #1's changes → raises/pauses get overwritten.

- Every module that emits a bulk with bid/state changes (`waterfall`, `automate`, `bidopt`, `weekly`, `midmonth`, `pausescale`) also inserts BidLedger rows (`applied=False`).
- `effective_bid(target_id)` = latest ledger row's `exported_bid` if exists else snapshot bid; `effective_state` same.
- All *subsequent* bid computations read effective values.
- UI: per export "Mark applied" (sets `applied=True, applied_at`) after the user uploads to Amazon; "Discard" deletes rows. Unapplied ledger rows > 7 days old → warning badge.
- On new bulk upload: reconcile — ledger rows whose exported value matches the new snapshot auto-flip `applied=True`; mismatches surface in a "drift" list.

## Router `routers/waterfall.py`

| Method | Path | Purpose |
|---|---|---|
| POST | `/waterfall/upload` | bulk .xlsx → classify + plan → create draft run, return summary (boss table, missing slots, MULTI list, mixed flags) |
| GET | `/waterfall/run` | latest run: items grouped by phase, selectable |
| POST | `/waterfall/bulk?phase=A` | selected items of phase → bulk file via `bulkfmt`; logs ChangeLog + BidLedger |
| POST | `/waterfall/applied?phase=A` | mark phase applied |
| GET | `/waterfall/benchmark` | day-0 vs current comparison (day-21 verdict) |
| GET/PUT | `/waterfall/settings` | naming template, goal acos, budget, seed thresholds, hero SKUs |

All `Depends(get_db)` (auto-scoped). Cadence: base db (`get_base_db`) — restructure is account-level, not per-cadence.

## Frontend `Waterfall.jsx` (new tab)

- Upload button (own bulk) → summary cards: campaigns classified, bosses, losers, missing slots, MULTI/EMPTY/mixed warnings.
- Boss Map table (`DataTable`): SKU | slot | boss old name → new name | acos | losers count.
- 4 phase panels (`DataTable`, selectable, `lean` where short): items with payload preview. Export button per phase. Phase D export disabled until A–C applied (tooltip explains).
- Benchmark card: hero metrics day-0 vs now, delta colored `up`/`down` tokens.
- Settings drawer: naming template with live preview, goal ACoS, budgets, hero picker (default = top N SKUs by 60d sales).

## Tests
- classifier: auto-type beats name (misnamed "PT"→AT); MULTI/EMPTY; mixed detection
- boss: profitable-first regression case above; all-zero → impressions
- phases: B uses ledger not snapshot; C sculpting skips live keywords; D includes losers only, never bosses (assert boss∩pause == ∅)
- safe_bid_cut: both regression cases + never-raise property test
- e2e: fixture bulk → run → 4 files → each validates (no dup, no missing parent, string IDs)
