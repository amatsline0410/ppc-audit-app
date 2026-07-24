# MAPPING.md — "Project Snore x Competitor Research / Indexed Keywords / SEO"

Phase 0 mapping of the real sheet (13 tabs, read with `sheet_name=None, dtype=str`).
Source: `files/Project Snore x Competitor Research_Indexed Keywords_SEO.xlsx`.

Cast of characters found in the sheet:
- **Primary ASIN:** `B0FT3YGR9V` (ZValves — "Anti Snoring Devices | Fir…")
- **10 competitors:** Breathe Right `B07FHM225F`, intake `B0C15R4FN8`, SnoreLessNow `B0D47W3PGH`, Rhinomed `B011LR55UU`, Air Max `B00B4S61QE`, PureSleep `B07SD5W2KQ`, TRANQUILITY `B07BTL8QZ6`, Difiney `B0GTC2D6B4`, OHALEEP `B0GWLF5JKY`, NBF `B0GT933QWR`
- **Master keyword list:** 10,797 keywords (Main grid = Comp Cerebro rows, 1:1)
- Cell markers everywhere: rank grids use number-or-`-`; listing-coverage grids use `exact` / `broad` (blank = not present)

---

## Tab → table decisions

| Tab | Shape | Verdict |
|---|---|---|
| **Main** | 14797×16 | **Core.** Three blocks: KPI header, competitor attribute matrix, keyword×ASIN organic-rank grid → `TrackedKeyword` + `RankSnapshot` (+ competitor attrs merged into `TrackedCompetitor`) |
| **Comp Cerebro** | 19462×14 | **Import source** for the Main rank grid (identical data, 10,797 rows). → `RankSnapshot` rows. Same table, not a new one |
| **Your Cerebro** | 3505×14 | **Import source** for primary-ASIN ranks → `RankSnapshot`. ⚠ only 100 keyword rows survived export (see open questions) |
| **Comp X-ray** | 14×22 | **Import source** → `TrackedCompetitor` product attributes (10 rows) |
| **Your X-ray** | 2×22 | Same, for primary ASIN → stored on `TrackerProject` (or a competitor row flagged `is_primary`) |
| **Listing Audit** | 999×26 | **Core.** Keyword (996 top-SV subset) × our-listing-element usage (`exact`/`broad` per Title/BP/A+/Description/Search Terms/Alt text/SP-Broad/Phrase/Exact/SB-Broad/Phrase/Exact) + competitor rank columns (duplicate of Main — skip those cols) → `KeywordUsage` |
| **Listing Copy** | 1653×39 | **Core.** Our listing only: **Current** vs **Proposed** copy blocks (Title, Bullet Points, A+ Texts, Description, Search Terms, Alt Text) + per-keyword `exact`/`broad` coverage of each → `ListingCopy` (the 12 text blobs) + computed coverage (no table — recompute) |
| **Title Comparison** | 1001×15 | Computed view: per-ASIN title text + `No. of exact` + `Total exact SV` + keyword×ASIN exact/broad grid → **skip as table**; recompute from `ListingCopy`/competitor copy + keyword list |
| **BP Comparison** | 1001×15 | Same as Title Comparison but bullet points → **skip; recompute** |
| **Titles** | 992×39 | Working sheet behind Title Comparison (3 cols per ASIN, `#REF!` artifacts) → **skip — presentation/scratch** (its output = the same exact/broad markers; we recompute) |
| **Bullet Points** | 992×39 | Same as Titles → **skip — scratch** |
| **Search Terms** | 1368×30 | Keyword list (1,365 rows: keyword, SV, relevancy) with **Proposed BP / Parent / 7×Child column blocks all EMPTY** (0 data cells) → import keywords into `TrackedKeyword` (source=`search_terms`); the empty grid = **skip** (never used) |
| **Targeting** | 202×10 | SP + SB blocks: Match Type (`exact`/`broad`/`negativeExact`) + BROAD/PHRASE/EXACT marker cols, but **Keyword Text column is empty** (broken cross-file formula) → **skip / open question** |

Competitor copy texts (title/BP row 1 of the Comparison tabs) → store on `TrackedCompetitor` (title, bullet_points) so comparisons recompute without the scratch tabs.

---

## Proposed schema (per approved-mapping; base db via `get_base_db`, store-scoped)

```python
class TrackerProject(Base):        # "Project Snore" — one per client product line
    id, store,                     # store-scoped like other side features
    name, primary_asin,            # B0FT3YGR9V
    created_at

class TrackedCompetitor(Base):     # from Comp X-ray / Your X-ray (primary = is_primary)
    id, project_id (FK CASCADE), asin (str!), brand, title,
    is_primary (bool), active (bool),
    price, sales, revenue, bsr, seller_country, fba_fees, active_sellers,
    rating, review_count, images, review_velocity, buy_box, category,
    size_tier, fulfillment, dimensions, weight, creation_date, image_url,
    bullet_points (text),          # from BP Comparison row 1
    # listing-health block (Main rows 19-27, manual yes/no audit):
    listing_health_score, pdp_images, pdp_videos, brand_story, aplus,
    crawlable_text, alt_text, comparison_table, amazon_badge   # bools nullable

class TrackedKeyword(Base):        # master list (Main grid / Comp Cerebro)
    id, project_id (FK CASCADE),
    keyword, search_volume (int), relevancy (int),   # sheet's manual 0/1/2/4 tag
    keyword_sales (int nullable),                    # Cerebro "Keyword Sales"
    source                                           # cerebro | search_terms | manual

class RankSnapshot(Base):          # keyword × asin × date — append-only
    id, keyword_id (FK CASCADE), asin (str),
    checked_at (date), organic_rank (int nullable),  # None = '-' (not ranked/unchecked)
    method                                           # cerebro | manual | migrate

class KeywordUsage(Base):          # Listing Audit markers, our listing/campaigns
    id, keyword_id (FK CASCADE),
    element,   # title|bullet_points|aplus|description|search_terms|alt_text|
               # sp_broad|sp_phrase|sp_exact|sb_broad|sb_phrase|sb_exact
    match      # exact | broad
    # (one row per marker; blank cells = no row)

class ListingCopy(Base):           # Listing Copy tab, our ASIN, current vs proposed
    id, project_id (FK CASCADE),
    variant,   # current | proposed
    element,   # title|bullet_points|aplus|description|search_terms|alt_text
    text
```

## Column map (imported / manual / computed)

**Main — KPI header (rows 0–27):**
| Sheet cell | Field | Class |
|---|---|---|
| A3 `3683032.25` Total Revenue (Top 10) | — | computed: `sum(revenue of top-10 competitors)` |
| B3 `0.00258…` Our Market Share | — | computed: `our_revenue / total_revenue_top10` |
| C1 `All SV Page 1` / C2 `#VALUE!` | — | computed (broken in export): `sum(SV where our rank ≤ page-1)` — reconstruct |
| A11 Average Reviews (Top 10) | — | computed: `mean(review_count)` |
| rows 6–18 attribute matrix (Brand→Listing Age) | `TrackedCompetitor.*` | imported (X-ray) |
| row 18 Listing Age | — | computed: `(today - creation_date)/365` |
| rows 19–27 (Health Score, PDP Images…Badge) | `TrackedCompetitor.*` | **manual_input** (user audit, yes/blank) |

**Main — rank grid (row 30 header, rows 33+ data, 10,797 kw):**
| Col | Field | Class |
|---|---|---|
| 0 Search Terms | `TrackedKeyword.keyword` | imported |
| 1 Search Volume | `.search_volume` | imported (Cerebro) |
| 2 Relevancy | `.relevancy` | **manual_input** (0/1/2/4 tags) |
| 3 Keyword Sales | `.keyword_sales` | imported (Cerebro) |
| 4 (B0FT3YGR9V) | `RankSnapshot` primary | imported (Your Cerebro) — number or `-` |
| 5–14 (competitor ASINs) | `RankSnapshot` per comp | imported (Comp Cerebro) |
| rows 31–32 `Organic Rank`/`Filter` | — | skip (UI chrome) |

**Listing Audit (996 kw subset):** cols 0–2 = same keyword fields; cols 3–14 = `KeywordUsage` markers (**manual_input** in sheet; app can later auto-compute vs `ListingCopy` text); cols 15–25 duplicate Main ranks (skip).

**BP/Title Comparison computed rows (recompute, don't store):**
```python
def count_exact(copy_text: str, keywords: list[Keyword]) -> int:
    """No. of exact — count of tracked keywords appearing verbatim (case/space-folded) in the text."""

def total_exact_sv(copy_text: str, keywords: list[Keyword]) -> int:
    """Total exact SV — sum of search_volume over those exact-matched keywords."""

def match_kind(copy_text: str, keyword: str) -> str | None:
    """'exact' if whole phrase appears; 'broad' if all words appear individually; None otherwise.
    (Reconstructed from marker distribution; confirm word-order/plural rules.)"""
```

**Computed metrics for the app (beyond the sheet):**
```python
index_rate(asin, date)            # ranked keywords / tracked keywords
page(rank)                        # ceil(rank/48) — sheet has no page concept; default 48/page
rank_delta(kw, asin, d1, d2)      # negative = improved; kw missing before = "new"
coverage_vs_best(project, date)   # our page-1 count / best competitor page-1 count
market_share(project)             # sheet's B3, live
```

## Cell-value semantics (confirmed from data)

- Rank cells: integer string = organic rank; **`-` = not ranked** (→ `organic_rank=None`); `0` appears as a rank value (Cerebro's "rank 0" = found but unranked position — treat as None? **open question**).
- Marker cells: `exact` / `broad` / blank. No `phrase` marker found in listing grids (only in Targeting's match-type column).
- `#VALUE!` / `#REF!` = broken formulas from the Sheets export — artifacts, not data.

## Open questions

1. **Rank `0` vs `-`** — Main/Cerebro grids contain both `0` and `-`. Is `0` "indexed but beyond measurable rank" (keep as 0) or same as not-ranked (None)? Affects index_rate.
2. **Your Cerebro truncation** — only the first 100 rows carry keyword/SV/rank; Relevancy col has 3,504 values and Keyword Sales 1,437 (orphaned formula columns). Migrate primary-ASIN ranks from the 100 rows + Main col 4 (96 values), or do you have a fuller Cerebro export for the primary ASIN?
3. **Targeting tab** — Keyword Text columns are empty (formulas to another file lost). 202 rows of match-type flags with no keywords. Skip entirely, or is there a source file to recover it? (The app's own STR/keywords data can replace this bridge.)
4. **Search Terms tab grid** — Proposed BP / Parent / 7 Child blocks have zero data. Confirm skip (import only its 1,365-keyword list, tagged `source=search_terms`)?
5. **Relevancy values** — 0/1/2/4 seen. Meaning of each tier (4 = highest?)? Kept as manual int tag either way.
6. **`match_kind` broad rule** — reconstruct as "all words present in any order"? Spot-checks fit, but confirm intended rule (stemming/plurals?).
7. **Page size** — no page convention in sheet. Default `ceil(rank/48)` per spec ok?
8. **Snapshot date for migration** — sheet has no dates. Stamp the whole migration `checked_at = migration day` (or a date you give)?

## Migration flow (once approved)

`POST /tracker/migrate` (file upload):
1. Create `TrackerProject` (name from filename/user), primary ASIN from Your X-ray.
2. Comp X-ray + Your X-ray → 11 `TrackedCompetitor` rows (+ Main rows 19–27 health block, BP/Title Comparison row 1 texts).
3. Main grid rows 33+ → 10,797 `TrackedKeyword` + `RankSnapshot` per non-`-` cell (one snapshot date).
4. Listing Audit markers → `KeywordUsage`.
5. Listing Copy Current/Proposed blocks → `ListingCopy` (12 texts).
6. Search Terms tab keywords not already present → `TrackedKeyword(source=search_terms)`.
7. Skip: Titles, Bullet Points, Title/BP Comparison (recomputed), Targeting (empty), Main KPI header (recomputed).
