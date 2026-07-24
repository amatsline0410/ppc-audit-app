# SPEC — Competitor Research + Indexed Keywords / SEO Tracker

Replaces the manual Google Sheet workflow ("Project Snore x Competitor Research / Indexed Keywords / SEO" and siblings for other clients) with a tab in the PPC app. Multi-store: works for ZValves, Pro Ice, any client — competitor sets are per-store.

**Relationship to SPEC_LISTING_RESEARCH.md (build that first if not built):**
- Listing Research = point-in-time analysis run (Cerebro/Xray import → gaps → copy → conquest).
- THIS feature = the **ongoing tracker**: indexed-keyword status, SEO rank over time, competitor matrix maintained across weeks. Snapshots accumulate; trends emerge.
- Share, don't duplicate: reuse `parse_cerebro` for rank imports; a Listing Research run can seed the tracker's keyword list; tracker keywords can launch a Research run.

---

## ⚠️ PHASE 0 — MANDATORY FIRST TASK: map the real sheet

Do NOT write application code until this phase is confirmed by the user.

1. Ask the user for the path to their competitor research `.xlsx` (downloaded from Google Sheets, all tabs). Read it with pandas (`sheet_name=None`, `dtype=str` for anything ASIN/ID-like).
2. For EVERY tab produce: tab name, row/col counts, exact headers, 3 sample rows, detected formulas-now-values (columns that look computed: %, scores, ratios), cross-tab references you can infer (shared key columns like keyword or ASIN).
3. Write `research_tracker/MAPPING.md`:
   - tab → proposed table (or "merge into X" / "skip — presentation only")
   - column → field (name, type, nullable) with `manual_input | imported | computed` classification
   - every computed column → the formula reconstructed as a pure Python function signature
   - open questions list (ambiguous columns, mixed-type cells, legend rows)
4. STOP. Show MAPPING.md to the user. Iterate until approved. The approved mapping supersedes the reference model below wherever they conflict.

The user's sheet logic is the product. The reference model below exists so Phase 0 knows what to look for and the rest of this spec can define architecture, but **the real sheet wins**.

---

## Reference domain model (typical shape — validate against MAPPING.md)

Expected concept clusters in a competitor/SEO sheet like this:

```python
class TrackerProject(Base):          # e.g. "Project Snore" — one per client product line
    id, name, primary_asin, store_scope,
    brand_terms_json, created_at

class TrackedCompetitor(Base):
    id, project_id (FK cascade),
    asin (str), brand, title, notes,
    active (bool)                     # competitors rotate in/out

class TrackedKeyword(Base):           # master keyword list per project
    id, project_id (FK cascade),
    keyword, search_volume, sv_updated_at,
    intent_tag nullable,              # if sheet categorizes (e.g. problem/solution/brand)
    source,                           # cerebro | datadive | manual | ppc_str
    priority nullable                 # if sheet has manual priority/tier column

class IndexSnapshot(Base):            # indexed-keyword status over time — the SEO heart
    id, keyword_id (FK), asin (str),  # primary AND competitors share this table
    checked_at (date),
    indexed (bool nullable),          # None = unchecked
    organic_rank nullable, sponsored_rank nullable,
    page (computed: rank→page), method   # h10_index_checker | cerebro | manual

class SeoScorecard(Base):             # per-asin per-snapshot rollups (computed, cached)
    id, project_id, asin, snapshot_date,
    kw_tracked, kw_indexed, index_rate,        # indexed / tracked
    page1_count, top10_count, avg_rank,
    coverage_vs_best                            # your page1 / best competitor page1
```

Computed metrics (pure, `metrics.py` or `pipeline/tracker.py`):
```
index_rate      = indexed / tracked            (None-safe)
page(rank)      = ceil(rank / 48)  (desktop 48/page; confirm vs sheet's convention in Phase 0)
rank_delta      = current_rank - previous_snapshot_rank    (negative = improved)
coverage_matrix = keyword × asin grid of indexed/rank      (the sheet's core view, rebuilt)
movers          = top N improved / declined keywords since last snapshot
```

---

## Imports (tolerant parsers, like existing ingest/benchmark)

1. **The sheet itself** — one-time migration: Phase 0 mapping doubles as the importer spec. `POST /tracker/migrate` ingests the xlsx into the tables.
2. **Cerebro CSV** — reuse `parse_cerebro`; rank columns per ASIN → IndexSnapshot rows (indexed inferred: has rank OR H10 index flag).
3. **H10 Index Checker export** (if user uses it) — keyword | indexed yes/no per ASIN.
4. **Manual grid edits** — UI allows toggling indexed/entering rank inline (the sheet habit, preserved), writes IndexSnapshot with `method=manual`.
5. **PPC bridge (read):** converting search terms from the app's STR data → suggest as TrackedKeywords (`source=ppc_str`).

Every import stamps `checked_at` — snapshots accumulate, never overwrite (trend data). ASINs always `dtype=str`.

## Outputs / bridges

- **PPC bridge (write):** page-1-indexed-but-poorly-ranked keywords → suggested exact targets ("rank support" list) via `bulkfmt` / Waterfall seeds. Competitor ASINs → PT suggestions. Same pattern as Listing Research conquest bridge — share that code.
- **Export:** current coverage matrix → xlsx download (client deliverable, replaces sharing the Google Sheet).

## Router `routers/tracker.py` — all `Depends(get_base_db)`

| Method | Path | Purpose |
|---|---|---|
| POST | `/tracker/projects` | create project (name, primary asin, competitors) |
| POST | `/tracker/migrate` | one-time sheet xlsx import per MAPPING.md |
| POST | `/tracker/import?kind=cerebro\|index_checker` | snapshot import |
| GET | `/tracker/matrix?project_id=&date=` | keyword × asin coverage grid |
| GET | `/tracker/scorecard?project_id=` | per-asin SEO scorecards + trend series |
| GET | `/tracker/movers?project_id=` | rank deltas since previous snapshot |
| PATCH | `/tracker/cell` | manual indexed/rank edit (writes snapshot row) |
| POST | `/tracker/ppc-suggest?project_id=` | rank-support keywords + PT ASINs → bulk/Waterfall |
| GET | `/tracker/export?project_id=` | coverage matrix xlsx |

## Frontend `Tracker.jsx` (new tab)

- Project switcher (per client). Setup drawer: primary ASIN, competitor list (add/retire), brand terms.
- **Coverage matrix** — the sheet, upgraded: `DataTable`, keywords as rows, ASIN columns; cell = indexed badge + rank; primary column pinned/highlighted; heat via tokens (page1 / page2-3 / unranked). Inline editable (PATCH), `useModals()` confirm on bulk edits.
- **Scorecard cards** — per ASIN: index rate, page-1 count, avg rank, trend sparkline (Chart.js).
- **Movers panel** — two `lean` tables: climbers / decliners since last snapshot.
- **Import panel** — dropzones (Cerebro / Index Checker / sheet migration), snapshot date picker, parse summary.
- **PPC suggest panel** — rank-support keyword list + competitor PT list, select → export bulk or push to Waterfall seeds.

## Tests

- Phase 0 artifacts: mapping-driven migrate importer covered by fixture built FROM the user's real sheet (small anonymized slice)
- page(rank) boundary cases; index_rate None-safe; rank_delta sign convention
- snapshot append-only: re-import same date replaces that date only (idempotent), other dates untouched
- coverage matrix: unchecked ≠ not-indexed (None vs False rendered distinctly)
- movers: keyword absent in previous snapshot → "new", not fake delta
- ppc-suggest: ASIN → product target expr via bulkfmt; dedup vs live targets
- migration e2e: fixture sheet → tables → matrix equals sheet grid

## Build order

0. **Phase 0 mapping (STOP for user approval)**
1. Models + migrate importer (from approved mapping) + tests
2. Snapshot imports (Cerebro reuse, index checker) + metrics + tests
3. Matrix / scorecard / movers endpoints + tests
4. PPC bridges (suggest out, STR in) + tests
5. Frontend tab
6. MANUAL.md + Changelog
