# SPEC — Enterprise AI Auditor (PRD → existing app gap map)

Source: user PRD "Amazon PPC Enterprise AI Auditor" (2026-07-19). Goal: enterprise-scale audit
(100–10,000+ ASINs), full-account restructure plans, scoring, ASIN classification, AI assistant.

## Stack decision

PRD lists Next.js / AG Grid / ECharts / Polars / DuckDB / PostgreSQL / OpenAI / LangGraph.
**Decision: keep existing stack** (FastAPI + SQLAlchemy + pandas + SQLite; React Vite + Tailwind +
DataTable + Chart.js; provider-agnostic `llm/`). Rationale: CLAUDE.md architecture is load-bearing
(per-user/store/project/cadence SQLite isolation, token design system, one-table-everywhere);
PRD stack = rewrite, zero user value. OpenAI reachable already via `llm/` OpenAI-compatible
provider. Postgres later by URL swap (documented). Scale targets (1M keywords) revisit only if
pandas hot paths actually choke — measure first.

## Module map (PRD 01–18 → repo)

| PRD module | Status | Where / gap |
|---|---|---|
| 01 File Importer | EXISTS | `ingest` + per-feature uploads |
| 02 Data Validator | EXISTS | tolerant parsers + `bulkfmt` validation |
| 03 Bulk Parser | EXISTS | `ingest → split → clean → load` |
| 04 Search Term Analyzer | EXISTS | `weekly`/`midmonth`/`fullmonth`/`harvest`/`ngrams` |
| 05 Keyword Intelligence | PARTIAL | `keywords.py` (research). GAP: quality score / intent / suggested match+bid dashboard |
| 06 ASIN Intelligence | PARTIAL | `build_tree`, benchmark, profit. GAP: lifecycle classification (below) |
| 07 Campaign Auditor | EXISTS | `rules.py` flags + cadence presets. GAP: structure checks (mixed match types, naming, auto abuse, duplicate campaigns) |
| 08 Portfolio Auditor | MISSING | portfolios not modeled at all (bulk Portfolios sheet unread) |
| 09 Budget Optimizer | MISSING | budget cols ingested but unaudited (budget-limited / overspending / underfunded winners) |
| 10 Placement Optimizer | EXISTS | `placement.py` |
| 11 Harvester | EXISTS | `harvest.py` + cadence engines |
| 12 Negative Engine | EXISTS | harvest/midmonth/cannibal negatives |
| 13 Enterprise Campaign Generator | PARTIAL | `waterfall.py` = SP-only RAF funnel. GAP: portfolio layer + SB/SD tiers (SB/SD bulk emit = channels v2) |
| 14 Bulk File Generator | EXISTS | `bulkfmt.py` (SP). GAP: SB/SD sheets |
| 15 Dashboard | EXISTS | Dashboard/Stores/Monitoring. GAP: score cards (below) |
| 16 AI Chat Assistant | MISSING | `llm/` narrates only; no Q&A over data |
| 17 ML Forecast | FUTURE | out of scope v1 |
| 18 Report Generator | EXISTS | `report.py` |

## New builds (priority order)

### P1 — Structure + Budget + Portfolio audits (pure bulk, no new uploads)
- `pipeline/structure.py`: campaign-structure checks off existing dims/facts — mixed match types
  in one ad group, duplicate campaign names, naming-convention breaks (configurable regex,
  default RAF template), auto-campaign abuse (auto spend share > threshold with no harvest flow),
  overlapping campaigns (delegates to `cannibal`).
- Budget audit: parse `Daily Budget` + campaign-level spend; flags BUDGET_LIMITED (spend ≈ budget,
  good ACoS), OVERSPENDING (high spend, bad ACoS), UNDERFUNDED_WINNER (low budget, ACoS ≤ goal).
  New rules in `rules.py` pattern (pure fns) at campaign level.
- Portfolio: `ingest` reads bulk `Portfolios` sheet → `DimPortfolio` (nullable FK on DimCampaign);
  audit flags campaigns without portfolio; report groups by portfolio.

### P2 — ASIN Classification + Account Scoring
- `pipeline/asinclass.py`: classify every ASIN — Hero / Growth / Launch / Seasonal / Clearance /
  Dormant / Low-Margin / High-Margin / Brand-Builder / Profit-Driver. Deterministic rules off
  existing data (profit.compute margins, sales share, trend from snapshots/monitoring, catalog
  price). Manual override per ASIN (project extra). Feeds strategy + dashboards.
- `pipeline/score.py`: 0–100 account score + sub-scores (structure, keyword quality, budget,
  profitability, search-term quality, placement, portfolio org, scalability, automation
  readiness). Deterministic: each sub-score = weighted penalty sum from existing flag/audit
  outputs (LLM never scores). Dashboard score cards + per-campaign / per-ASIN health scores.

### P3 — New report parsers (own tables, tolerant-parser rules)
- Advertised Product Report → per-ASIN spend/sales/TACoS/ROAS (cross-checks star schema).
- Purchased Product Report → cross-sell matrix (advertised ASIN → purchased ASIN).
- Inventory Report (optional) → out-of-stock detection + inventory-aware bidding guard
  (suppress bid raises on low-stock ASINs in bidopt/cadence engines).

### P4 — AI Chat Assistant
- `/assistant/ask`: NL question → deterministic tool calls over existing endpoints (audit,
  strategy, cannibal, scores) → `llm/` narrates answer with numbers from tools. Provider-agnostic,
  optional like all LLM features; degrade to "LLM not configured". No LangGraph dep — thin
  tool-router inside `llm/`.

### P5 — Enterprise generator extensions
- Waterfall + portfolio layer (one portfolio per product family; Portfolios sheet in bulk out).
- SB/SD structure generation = channels v2 (blocked on SB bulk format work).

### Out of v1
ML forecasts (17), organic-rank prediction, campaign saturation. Keyword intent/competition
scoring needs external data — keep to Helium10 import (`keywords.py`).

## Constraints (unchanged)
100% local, no Amazon Ads API — outputs = bulk files. All math deterministic; LLM narrates only.
IDs stay exact strings. New tables follow own-table pattern (never shift audit snapshot).
Every feature → MANUAL.md update.
