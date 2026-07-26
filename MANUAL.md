# PPC Audit — User Manual

A manual-data Amazon PPC audit console. You upload Amazon exports; it computes
flags, a bid ladder, break-even, trends, and an exec report. All math is
deterministic and runs locally — no Ads API, no cloud.

> **Keep this file current.** Whenever a feature is added or changed, update this
> manual in the same change (see the Changelog at the bottom).

---

## 0. Signing in

The app requires a login. The first-run **superuser** is **`SAdmin` / `RootPass`**
(change it after first login via *Users → reset pw*, or set `SUPERUSER_NAME` /
`SUPERUSER_PASS` env before first start).

- Each person has their own account; sign in with username + password.
- **Self sign-up** — no account yet? Click **"new here? Create an account"** on the
  login screen, pick a username + password (6+ chars), and you're in immediately. No
  email verification or OTP. Self-registered accounts are normal (non-superuser).
- **One active session per account** — signing in elsewhere logs out the previous
  session. Sessions expire after 12h of inactivity.
- **Your data is private to your account.** Each user has their own isolated
  stores + audits — nobody sees anyone else's PPC data. A new account starts with an
  empty **My Store**; upload your own bulk file into it. (Deleting a user also
  deletes that user's data.)
- **Superusers** get a **Users** tab to add / delete accounts and reset passwords —
  this is how you onboard the rest of the team. Same management-table pattern as
  the Stores tab: a `users · N` header with a yellow **New User** button (opens a
  modal form — username / password / superuser), the table below with your own
  row highlighted (`● you`), and per-row **reset pw** / **delete** actions
  (superusers can't be deleted). The bundled ZValves demo data lives
  in the **SAdmin** account only.
- **Log out** from the top-right of the header.

## 1. Quick start

**Backend** (FastAPI, port 8000):
```bash
cd backend
source .venv/bin/activate            # Windows: .venv\Scripts\activate
uvicorn app.main:app --port 8000
```

**Frontend** (Vite/React, port 5173):
```bash
cd frontend
npm run dev
```
Open http://localhost:5173.

First run is seeded with a sample store (`ZValves`) so the UI has data. To seed
manually: `cd backend && python -m app.main`.

---

## 2. Core concepts

- **Store → Audit (project) → data.** A *store* is one Amazon account. Inside it
  you create *audits* (projects), each an isolated SQLite file — campaign IDs from
  different accounts can never collide. Stores and audits are managed on the
  **Stores tab** (the sidebar keeps only a compact `store › audit` breadcrumb
  at the bottom — click it to jump there), laid out Google-Drive-style as a
  **tile grid**: level 1 shows one tile per **store** (name + spend · ACoS ·
  flags mini-stats, ⋮ menu for open / delete); **click a store tile to drill
  into its audits** — level 2 shows one tile per **audit**, each with a yellow
  **month badge** (the month of its latest uploaded snapshot, `no data` until a
  bulk is uploaded). Click an audit tile to open it in PPC Optimization; its ⋮
  menu holds Flush / Delete. A `Stores › <store>` breadcrumb navigates back,
  and **New Store / New Audit** buttons sit in the header next to a search box.
  The current pair also shows in the top-right breadcrumb. Sections (Dashboard / PPC
  Audit / Reports) are the sidebar nav.
- **Goal ACoS / ROAS.** The headline knob. ACoS and ROAS are reciprocals (ROAS =
  1 ÷ ACoS). Each audit stores its **own** Goal — switching audits loads its goal.
- **Snapshot = one upload period.** Every bulk upload is stamped with a date.
  Upload again on a later date to build history (enables Trends + the bid ladder).
  All "current" views use the **latest** snapshot, never a lifetime blend.
- **ASIN-rooted view.** Amazon data is campaign-rooted; the app re-roots it by
  product (ASIN) so you audit per product. Note: campaign/ad-group metrics are the
  whole campaign's — if an ad group runs multiple ASINs, that spend shows under
  each (ad- and keyword-level numbers are exact).

---

## 3. Recommended workflow

Uploads live **inside each panel that consumes them** — there is no separate Uploads
tab. Feed the app where the data is used:

- **PPC Optimization → Audit Cadence** — each cadence panel uploads its own Sponsored
  Products bulk (Daily Watch per day, Weekly per week, Mid-Month / Full Month / Pause-Scale
  per snapshot). The bulk auto-harvests an embedded Search Term Report if present.
- **Product Ads** — its own bulk upload for the Product-Ad view.

Then: **Dashboard** (account KPIs), **Strategy** (playbook + one-click bulks),
**Reports** (exec summary + Excel). Re-upload a fresh bulk each period → Trends + bid
ladder light up. Every uploader also has a `⬇ template` link.

---

## 4. Tabs

> **Every data table** shares the same controls: a **search** box (matches the key
> text columns), an Excel-style **column sort** (click a header to cycle A-Z → Z-A
> for text / ascending → descending for numbers → off; the ▲/▼ shows the active
> column), a **per-column filter funnel** (the **▾** next to every number column
> header — pick *greater than / greater than or equal / equals / less than or equal
> / less than* and type a number, just like Amazon's campaign manager; the funnel
> turns lime when active), **composite filters** (the **⛃ filters** button — stack
> any number of per-column conditions that are AND-combined: text columns offer
> contains / is / is not / is empty, number columns offer ≥ > ≤ < = ≠ / between; the
> badge counts the active ones, header-funnel conditions included), a **show 10 / 50
> / 300 / All** page-size selector, and prev/next
> **pagination** with a range readout. All client-side — totals, selections and
> bulk-file exports always use the full set, never just the visible page.

### Uploading data (per panel)
Every panel uploads its **own** bulk file: each Audit Cadence panel (Daily Watch /
Weekly / Mid-Month / Full Month / Pause-Scale), Product Ads, Channels, Waterfall
and Cannibalization all have their own yellow Upload button. Each cadence stores
its upload in its **own database file** — a bulk uploaded under Weekly only ever
feeds Weekly; cadences never mix or overwrite each other.

### Dashboard
PPC account KPIs (Ad spend, Ad sales, ACoS, **Avg Product ACoS** — Σ ad
spend ÷ Σ ad revenue across the per-product campaign rollups; can differ from
account ACoS when one campaign advertises several ASINs — ASINs, open flags,
wasted spend, scale opportunities), a **flag breakdown table** (count · flag type · what it
means — HIGH_ACOS shows its bid-ladder split inline — · which tool actions it,
sorted biggest first), a per-ASIN table with a **break-even** column (red ⚠ when a
product's ACoS is over its break-even) + **Trends** (period-over-period). Empty
tiles link to where to add the missing data.

**Analytics hub** — the Dashboard also rolls up **every other data source** into
one view (`GET /dashboard/analytics`, one fast call; every block shows a "what to
upload where" hint until its source has data, and an **open →** button jumps to
the owning tab):
- **Account states** (under the KPI tiles) — the Strategy methodology
  classifier's five state counts (below / at / above target · over break-even ·
  no data, colored) + the top spender's classification, with **open →** to the
  Strategy tab's full table.
- **Top movers** (next to the flag breakdown) — the 5 biggest campaign spend-Δ
  movers between the audit's two latest snapshots (needs 2+ uploads).
- **Product Ads · this audit** — products, distinct campaigns, ad spend/sales,
  ACoS + **Avg Product ACoS**, converting / no-orders / no-traffic split.
- **Product Benchmark · store catalog** — products, listing issues, advertised,
  Avg ACoS, over/under break-even counts.
- **Monitoring · last 14 days** — health score (colored), total sales, TACoS,
  ad spend/sales/ACoS over the tracker's last 14 days + up to 4 active alerts.
- **Transactions · SKU ledger** — whole-ledger orders / refunds / units /
  product sales / fees / net proceeds, a **product-sales-vs-net-proceeds daily
  line chart** across the full ledger, and the top-5 SKUs by net.
- **Footer counters** — actions logged in the Change Log (+ last action date)
  and keywords mined, each clickable.
- **Export Report** (yellow button, top right) — the whole hub as one
  client-ready workbook with **native Excel charts**: *Overview* (PPC KPIs,
  bid-ladder actions, flag breakdown + **flags-by-type bar**), *Features*
  (Product Ads block + **products-by-status pie**, catalog + monitoring blocks,
  counters — empty sources noted in place), *Transactions* (ledger totals,
  **top-SKU net bar**, daily table + **sales-vs-net line**) and *Top movers*
  (**spend-Δ bar**, when snapshot history exists). Endpoint:
  `GET /dashboard/export?target_acos=&audit_type=`.

### PPC Optimization
- **Bulk upload** — Amazon Sponsored Products bulk export (`.xlsx`). If the bulk
  also contains an **SP Search Term Report** sheet, it's harvested automatically
  and the candidates pre-load into the Harvest panel (a green banner notes it). No
  STR sheet? The bulk processes normally and harvesting is skipped.
- **Audit Setup drawer** — the setup panels (Audit setup checklist, Goal
  ACoS/ROAS control, AI narration, Flag legend) live in a **cart-style slide-in
  drawer** that overlays from the right edge (like an e-commerce cart). Open it
  with the floating yellow **Audit Setup** button (bottom-right of the PPC
  Optimization tab); close via ×, Esc, or clicking the dimmed backdrop. The
  open/closed state **persists across refreshes** (localStorage) — if it was
  showing, it comes back showing. The main audit content now spans the full
  width underneath.
- **Goal ACoS / ROAS** control — slider + editable ROAS field. Persists per audit.
- **Audit setup checklist** — compact card at the top of the drawer
  (above the Goal ACoS control, where the audit workflow lives). Items render
  as a **table list** (the shared DataTable, lean: `tasks · n/total` count
  caption, sortable ✓ / Task columns): *auto* rows tick themselves from real
  state (bulk uploaded, Goal set, benchmark set, a bulk action exported) and
  carry an `auto` tag; *manual* rows are your own tasks — checkbox toggles,
  ✕ deletes, the input below adds. Slim progress bar; header shows `n/total`,
  turns green **✓ done** at 100%. Auto-expands while setup is incomplete,
  collapses once done — and remembers whichever state you set by hand. Manual
  tasks survive a flush; auto items re-check against current data.
- **Audit table** — every flag, with bid-ladder stage chips, filters, select rows →
  **download bulk file** (Amazon-ready update sheet). Each row shows the ASIN's
  **BE ACoS** (break-even: benchmark upload wins, else catalog price + per-SKU
  COGS from the Product Benchmark tab; matched by ASIN, else by normalized SKU
  against the catalog listing) and the **Observed** ACoS colors against
  it — red above break-even (the target loses money per sale), green below.
- **Bid Optimizer** — optimal bid for *every* eligible target (not just flagged),
  computed first-principles: `bid = goal ACoS × revenue-per-click`, capped by
  break-even, clamped per pass. Filter raises/cuts, select → download bulk.
  The break-even cap uses the product's **real economics**: benchmark upload
  wins, else the catalog listing's price + per-SKU COGS + the SKU's **actual
  Transactions-ledger fees** (matched by ASIN, else normalized SKU). The plan
  table shows a **BE ACoS** column and colors each target's ACoS red/green
  against it.
- **Placement Optimizer** — scorecard of Top of Search / Product pages / Rest of
  search (ACoS + spend each) and a recommended bid-adjustment % per
  campaign+placement. Select → download an Amazon Bidding-Adjustment sheet.
  Each row shows the campaign's product **BE ACoS** (benchmark upload wins,
  else catalog price + per-SKU COGS + real Transactions-ledger fees, via the
  campaign's product ad; normalized-SKU fallback) with the placement ACoS
  colored red/green against it, and an **over BE** flag fires when a placement
  runs above the product's break-even even though it's under the 2×-goal
  bleed bar — money lost per sale the goal-based flags don't catch.
- **Guardrails (every bid/placement change).** All bid-changing engines share one
  tunable rulebook (`pipeline/bid_optimizer.py`, the `CONFIG` dict): (1) skip thin
  targets — need ≥20 clicks + ≥$5 spend (raises also need ≥3 orders); (2) hard
  caps — keyword/target bid $0.20–$5.00, ad-group default $0.30–$3.00, placement %
  0–150 (Top of Search / Product pages) or 0–200 (Rest of search); (3) step limit —
  one cycle moves a bid ≤$0.20 (default ≤$0.15) and a placement ≤25 pts, so big
  corrections happen gradually (a clamped row is marked *step-limited*). The module
  is pure/standalone — run `python -m app.pipeline.bid_optimizer` for a demo.
- **ASIN tree** — campaigns/ad-groups/targets under each product, with
  **state filter** (Active / Enabled / Paused / Archived / All) + colored state
  dots (green/amber/slate). Archived hidden by default and dimmed/struck when shown.
- **Search-term harvest** *(now on the **Keywords** tab)* — drop a Search Term Report; winners → Exact keywords,
  losers → Negative Exact; download a bulk file. Search terms that are **ASINs**
  (e.g. `B07FZ8S74R`) are emitted as **(Negative) Product Targeting** with an
  `asin="..."` expression — not keywords — and duplicates are collapsed so Amazon
  accepts the file. Wasted **Automatic-campaign** clauses (loose-match, close-match,
  substitutes, complements) are paused but never negated (Amazon rejects them as
  negative product targets). **Winners (promotes)** are only suggested where Amazon
  accepts them: never into Automatic campaigns (auto allows negatives only), and
  never where they'd mix keyword + product targets in one ad group. Negatives are
  always allowed. (Re-running harvest may re-suggest negatives you already uploaded
  — Amazon reports those as a harmless "already exists" warning, not a failure.)
- **N-gram miner** *(now on the **Keywords** tab)* — drop a Search Term Report; see winning/wasting *words* (1–3
  grams) across all terms.
- **Narrate** (optional LLM) — plain-English summary / client email.

### Product Ads
Product Ads has its **own dedicated bulk upload** and its **own data table** — **separate
from the PPC Optimization table**. Click the yellow **Upload Sponsored Products Bulk** button
(top-right, or the empty-state button)
and pick a Sponsored Products bulk export; its **Product Ad** rows (Entity = `Product Ad`)
are parsed straight into Product Ads' own table (re-uploading replaces them). It never
reads — or is affected by — the PPC Optimization pipeline. If nothing's uploaded yet you get a
prompt to upload. The header follows the app-wide upload pattern: a meta line shows the
**last uploaded file · row count · upload date** (persisted per audit + cadence), and a
ghost **Clear** button (danger-confirmed) wipes the snapshot — its own table only, the
PPC Optimization data is untouched, though the Product Benchmark tab's campaigns / ad spend /
ACoS join for that audit empties with it. Endpoint: `DELETE /product-ads/data`.
The yellow **Export Report** button downloads a client-ready workbook with **native
Excel charts**: an *Overview* sheet (account KPIs, **products-by-status pie**,
**campaigns-by-targeting-kind bar**) and a *Products* sheet (one row per ASIN+SKU
with the full metric set, sorted by spend, plus a **top-15 ad-spend bar chart**).
Endpoint: `GET /product-ads/export`.

Each **Product Ad** (ASIN + SKU) shows its metrics — **Unit Price**, **AOV**, Ad Spend,
Ad Sales, Orders (PPC), Clicks, Impressions, ACOS, **BE ACoS**, ROAS, CPC, CTR, CVR —
plus one **account total** across all ads. **BE ACoS** is the product's break-even
ACoS (an uploaded break-even benchmark wins; otherwise derived from the store
catalog's selling price + the product's per-SKU **COGS** set on the Product
Benchmark tab, default 40% of price) — the **ACOS cell colors against it**: red =
above break-even (each ad sale loses money), green = below. Products match the
catalog **by ASIN first, then by normalized SKU** (case / space / dash
insensitive — `PI 100` matches listing `pi-100`), so the join survives ASIN
drift between the ad bulk and the Category Listings Report. **Unit Price** = Ad Sales ÷ **Units** (not orders — an
order can hold several units, which would over-state the price); units summed across every
ad/campaign for the ASIN. The stats row shows **ACOS** next to **Avg Product ACOS** — computed as the
summation of Total Ad Spend ÷ the summation of Total Ad Revenue across ALL the
products' campaigns (zero-sale spend counts in the numerator). With **0 units but ad spend** it shows the bleed as a **negative**
(= −Ad Spend, in red); with no units and no spend it shows "—". **AOV** = Ad Sales ÷
**Orders**. Rows are **consolidated by (ASIN, SKU)**: when the same product runs as
multiple ads, their counts are summed into one line and the rates recomputed — a `×N`
badge shows how many ads merged. Each carries a **status**: *no traffic* (ad exists, 0
impressions/clicks → push it), *no orders* (spend + clicks but 0 sales → fix or push), or
*converting*. Action items sort to the top and a header banner counts them.

**Campaign tracing by targeting kind** — each SKU row also shows how many **Automatic**,
**Keyword-target**, and **Product-target** campaigns advertise it (**Auto / KW tgt / PT tgt**
columns, sortable). The type is classified from the *same* bulk: a campaign's **Targeting
Type** = auto → Automatic; otherwise a positive **Keyword** entity → Keyword-target, a
positive **Product Targeting** entity → Product-target (auto-clause targeting rows don't
mislabel an auto campaign). The header shows account-wide totals (`N auto · N kw · N pt
campaigns`) and the drill-down shows each ASIN's counts + a **Type** badge per campaign.
Needs the full SP bulk (campaign + keyword/target entity rows), not a Product-Ad-only
export. The total is
the exact PPC total (each ad counted once), not the ASIN rollup — so it never double-counts
campaigns that advertise multiple ASINs. Search / sort / page-size / pagination as on every
table. Endpoints: `POST /product-ads/upload`, `GET /product-ads`.

**Multi-select drill-down** — tick one or more ASIN checkboxes (or the header box to
select the page) and hit **▤ view selected**. A detail panel opens for each chosen ASIN
with: a roll-up stat strip, **all its ads** (SKU · campaign · ad group · state · spend ·
sales · orders · ACOS), and its **per-campaign rollups** (spend · sales · orders · ACOS ·
ROAS) — all from Product Ads' own data (no audit flags / strategy, since this is a separate
model). Endpoint: `GET /product-ads/detail?asins=A,B,C`.

### Tier Recommendations (right structure for your ASIN count)
First tab of the sidebar's **Consultation** group (same level as PPC Suite; also
holds Waterfall — the account structure tools). Goal: the
**right campaign structure, based on your number of ASINs**. Upload one Sponsored
Products bulk export; the tool counts your distinct advertised ASINs, routes the
account to one of **seven structure tiers**, and scans the bulk with **that
tier's rules**, returning problems with concrete resolutions:

| Tier | ASINs | Structure | Automation |
|---|---|---|---|
| 1 · Waterfall | 1–5 | One portfolio per ASIN, five-campaign waterfall (Auto → Broad → Phrase → Exact → ASIN targeting) | manual |
| 2 · Group + Hero | 6–20 | Heroes keep the full waterfall; the rest grouped, one ad group per ASIN | manual |
| 3 · Split Tier | 21–50 | Three bands: top own campaigns · mid single-product ad groups · tail one grouped auto | batch |
| 4 · Automate | 51–100 | SKU-tier portfolios (Core / Growth / Slow), rules engine runs the daily loop | auto |
| 5 · Portfolio | 101–500 | Budget buckets: Core break-even · Growth aggressive · Liquidation min-bid + catch-alls | auto |
| 6 · Multi-Ad-Group | 501–1000 | Tail bundled into multi-product ad groups; isolated heroes; harvest spots breakouts | auto |
| 7 · Capital Allocation | 1000+ | Target TACoS, budget allocated across tier portfolios; you steer money, not campaigns | continuous |

Each tier carries its own **audit thresholds** (min spend $5→$20, min clicks
15→25, bid step 15→20%, mixed-ad-group policy error→suppressed) — data gates
rise with catalog size because more products means more noise. The scan flags:
**Wasted spend** (spend ≥ tier minimum, 0 orders → negative + pause), **High
ACoS** (clicks over gate, ACoS > target+20% → cut bid one step, exact new bid
shown), **Underexposed winner** (ACoS < target−20% with starved impressions →
raise bid), **Overbid** (bid ≫ actual CPC → tighten toward CPC×1.1),
**Mixed ad group** (policy depends on tier: error at Tier 1, intentional and
suppressed at Tiers 6–7), **Harvest candidate** (search term with clicks ≥ 5 or
orders ≥ 1 → tier-specific promotion path, from "promote up the ladder" at
Tier 1 to "reclassify the SKU" at Tier 5+). The result page shows the tier card
(TL;DR, structure blueprint, optimization loop, cautions, thresholds, automation
mode) plus one table per problem type with the resolution on every row. Result
persists per audit until you Clear or re-upload. Endpoints: `POST
/consult/upload`, `GET /consult/run`, `GET /consult/tiers`, `DELETE
/consult/data`.

### Waterfall (restructure engine)
Lives in the sidebar's **Consultation** group, together with the Tier
Recommendations tab — the account structure tools.
Automates a full account restructure into the **RAF Funnel System** (Tiered Harvesting
Funnel): `AT (discovery) → KWT-BROAD → KWT-PHRASE → KWT-EXACT (money tier) + PT (ASIN
tier)`, one SKU per campaign (SPAG), one **boss** campaign per SKU+slot. Account-level —
it always uses the audit's **base** data, independent of the cadence picker. Header
follows the app-wide pattern: yellow **Upload Sponsored Products Bulk**, a meta line
with the **last uploaded file · campaign count · date**, and a ghost **Clear**
(danger-confirmed, `DELETE /waterfall/data`) that wipes every run — plan history,
phase progress and the day-0 benchmark baseline; settings + the bid ledger survive.
The day-0 benchmark is a sortable table like every other list.

**Upload the FULL Sponsored Products bulk** (campaign + ad group + product ad + keyword +
product-targeting rows; include the SP Search Term Report sheet for seed keywords). The
engine then:

1. **Classifies** every enabled campaign: SKU mapping from its Product Ad rows (1 SKU =
   mappable; several = **MULTI**, listed but excluded from the per-SKU funnel; none =
   **EMPTY**), and funnel slot — `Targeting Type = Auto` **always** wins over the name
   (catches misnamed campaigns), otherwise dominant keyword match type (mixed types are
   flagged), otherwise PT.
2. **Elects a boss per SKU+slot** with the *profitable-first* rule: among campaigns with
   sales and ACoS < 2× goal, pick max sales; else min ACoS among sellers; else max
   impressions. Raw sales alone would crown bleeders — a 111%-ACoS campaign can out-sell
   a 12.7% one; the 12.7% wins here. The boss keeps its Campaign ID (history preserved).
   An **ASIN × slot grid** (rows = SKU, columns = the 5 slots) visualizes the plan:
   each cell is the competing-campaign count — **green** = 1 clean candidate, **amber** =
   several (a boss was auto-picked), **grey ＋create** = no candidate (the slot is built in
   Phase C). Click a multi-candidate cell to open the **override panel** — every competing
   campaign with its orders / sales / ACoS, the boss highlighted, a radio to pick a
   different one. Overriding rebuilds the plan from the saved bulk (no re-upload); a ✎
   marks overridden cells. Picking the auto-elected campaign again clears the override.
3. Builds **4 phased bulk files** you export and re-upload to Amazon **in order**:
   - **A · Renames** — boss campaigns + their ad groups renamed to the naming template
     (`{sku}`/`{asin}`/`{slot}` placeholders, plus `{n}` = slot number 1–5, `{bid}` = the
     boss ad group's default bid, `{strategy}` = its actual bidding strategy — `down` or
     `up/down`, read from the data not the old name) + daily budget set. If **force
     down-only** is on and the boss is currently `up and down`, the same rename row also
     flips its Bidding Strategy to `down only` (off by default — some accounts run
     up/down deliberately). Zero risk.
   - **B · Loser bid cuts** — every enabled target in loser campaigns bid down to
     `max(effective bid × 0.6, $0.15)` (transitional overlap, **not** a pause — losers
     keep serving cheaply while bosses take over). Bids come from the **effective-bid
     ledger** (see below), never the stale snapshot.
   - **C · Creates** — missing SKU+slot combos created **born paused** with the
     **new-campaign bidding strategy** from Settings (default `Dynamic bids - down only`;
     also `up and down` or `fixed`) — training wheels; enable in batches. Each new
     campaign's ad group default bid comes from the **per-slot default bid** setting
     (AT $0.30 · BROAD/PHRASE/EXACT $0.50 · PT $0.40 by default), which also feeds the
     `{bid}` name placeholder. New AT campaigns get the 4 split targets, bid as multiples
     of the AT slot bid (close-match ×3.33 / loose-match ×2.50 / substitutes ×2.50 /
     complements ×1.67 — so the default $0.30 AT bid reproduces 1.00 / 0.75 / 0.75 / 0.50).
     **Seeds**: proven search terms (orders ≥ threshold, ACoS < goal, attributed via
     single-SKU source campaigns) become Exact keywords in the hero's EXACT campaign —
     bid = `clip(CPC × 1.1, $0.30, $2.00)`; ASIN-shaped terms are never keywords.
     Optional broad/phrase copies (×0.6/×0.75) go only into slots that are NEW this run.
     **Sculpting negatives**: boss-EXACT keywords + seeds are negated
     (`Campaign Negative Keyword · Negative Exact`) in the hero's AT/BROAD/PHRASE
     campaigns — skipping any campaign where the term is a live enabled keyword (a
     negative there would kill it) and anything already negated in the account.
   - **D · Pauses** — loser + EMPTY campaigns paused. **Locked until A, B and C are
     marked applied** (the overlap protects sales). Losers still pause even with orders
     (sales continue under the boss — that's the point of consolidation), but an EMPTY
     campaign at/above **protect min orders** has nowhere for its history to go, so it's
     excluded from the auto-pause and flagged for manual review instead. Explicit
     **protected campaign IDs** are never touched by B (bid cuts) or D (pauses) regardless
     of orders. A **Pause wave — revenue at risk** card lists every campaign D is about to
     pause that still carries orders, plus any protected-empty campaigns — never buried.
4. Stores a **day-0 benchmark** per hero SKU (single-SKU campaigns only). Upload a fresh
   bulk ~day 21 and the benchmark card shows the before/after verdict. Each hero row
   also carries its **BE ACoS** (break-even from the catalog listing's price +
   per-SKU COGS + the SKU's **real fees from the Transactions ledger**, matched by
   normalized SKU) and the ACoS cell colors red/green against it — runs created
   before this feature show "—" until the next upload.

**Heroes** default to the top-N SKUs by 60-day sales; override them (and the naming
template, budget, goal ACoS, seed thresholds, seed bid floor/ceiling, **per-slot default
bids**, **new-campaign bidding strategy**, force down-only, protect min orders, protected
campaign IDs) in **Settings** — changes apply on the next upload. Every export is logged
to the Change Log.

**Effective-bid ledger** — every bulk this app exports with bid/state changes (Waterfall,
Weekly, Mid-Month, Full Month, Pause/Scale, Bid Optimizer) records the exported values.
All later bid computations read the *effective* value (latest exported) instead of the
stale snapshot, so consecutive exports never double-apply or overwrite each other. When
you upload a new bulk, ledger rows that match the fresh snapshot auto-resolve; a banner
shows still-pending exports (with a stale warning after 7 days) — **mark all applied**
after you upload to Amazon, or **discard** if you threw the file away.

Endpoints: `POST /waterfall/upload`, `GET /waterfall/run`, `POST /waterfall/bulk?phase=`,
`POST /waterfall/applied?phase=`, `POST /waterfall/override` (boss re-election from the
grid), `GET /waterfall/benchmark`, `GET|PUT /waterfall/settings`, `GET /waterfall/ledger`.

### Cannibalization (keyword ownership detector)
Finds and resolves two overlap kinds from one uploaded SP bulk (same upload as
Waterfall — include the SP Search Term Report sheet). Account-level (base data).
The header follows the app-wide upload pattern: yellow **Upload Sponsored Products
Bulk** button, a meta line with the **last scanned file · findings count · scan
date** (persisted per audit), and a ghost **Clear** button (danger-confirmed,
`DELETE /cannibal/data`) that wipes the stored findings — nothing else is touched;
re-upload to re-scan.

- **Type 1 — duplicate targets (structural):** the same `keyword text + match type`
  (or the same product-targeting expression) enabled in **2+ campaigns**. Splits data,
  budgets compete. Auto clauses (close-match etc.) are excluded — they legitimately
  exist in every auto campaign.
- **Type 2 — cross-product term overlap (from the STR):** the same customer search term
  generating clicks/orders for **2+ different SKUs** — Amazon may serve the
  worse-converting product. SKU attribution goes term → source campaign → single-SKU
  mapping; multi-SKU campaigns attribute to **ALL** (reported, never auto-resolved).

**Ownership rule:** among candidates with ≥ 10 clicks — owner = **max CVR**, tiebreak
min ACoS; exactly one qualified → it; none → *insufficient data* (no action).
**Coexist** (grey, no action): every candidate is profitable (ACoS < goal) *and* has
volume — the term feeds both. **Same-SKU tier pairs** (exact in EXACT + broad in BROAD =
the waterfall working) only appear when the sculpting negative is missing — the finding
then carries just that negative (isolation repair, tagged `tier`).

**Resolution (you select, never auto):** Type 1 losers → keyword `State=paused` by exact
Keyword ID + `Campaign Negative Keyword · Negative Exact` in the loser campaign (winner
untouched; PT duplicates pause only). Type 2 losers → negativeExact of the term in the
loser SKU's AT/BROAD/PHRASE campaigns (never inside EXACT/PT money tiers).
**Converter guard:** a negative is never emitted into a campaign where that term is
converting (orders > 0 there) or is another live enabled keyword. ASIN-shaped terms are
never emitted as negative keywords. Pauses are recorded in the effective-bid ledger;
everything logs to the Change Log.

Click the **N ▤** candidates chip on any row for the drill-down (per-candidate SKU /
campaign / clicks / CVR / ACoS + the planned actions). Re-running the scan **replaces**
the findings (idempotent quarterly re-review). Endpoints: `POST /cannibal/run`,
`GET /cannibal/findings?kind=`, `POST /cannibal/bulk` — or fan out from the Waterfall
upload with `POST /waterfall/upload?engines=waterfall,cannibal`.

### Channels (SB / SD visibility)
Upload the **full Amazon bulk workbook** (all sheets) — the Channels tab reads three of
them into its own tables (never the audit star schema). Header follows the app-wide
pattern: yellow **Upload Amazon Bulk Workbook** button, a meta line with the **last
uploaded file · SB/SD row count · date** (persisted per audit), and a ghost **Clear**
(danger-confirmed, `DELETE /channels/data`) that wipes the SB/SD/SP snapshots —
brand terms survive.

- **SP** campaign totals (same file, so the mix compares like-for-like);
- **SB** from the **“SB Multi Ad Group Campaigns” sheet ONLY** — the legacy “Sponsored
  Brands Campaigns” sheet contains the *same* campaigns duplicated (verified on a real
  export); reading both would double-count;
- **SD** from “Sponsored Display Campaigns” (+ the **SB Search Term Report** for the
  read-only harvest list).

You get: **channel mix cards** (SP vs SB vs SD spend / sales / ACoS / ROAS / share —
answers “SB is 11.8% vs SP 39.4%” instantly), an **SB keyword table** with
`HIGH_ACOS` / `WASTED_SPEND` flags, a **brand vs non-brand donut** (defense-vs-growth
ratio) driven by a configurable per-store brand-term list (e.g. `pro ice, proice` —
matched on normalized terms, spaceless variants included), an **SD targeting table**,
a **dormant-channel banner** when SD exists but spent $0, and **read-only SB harvest
suggestions** (promote/negate candidates via the shared search-term engine). v1 is
audit visibility — SB/SD **bulk generation is deliberately not included** (the SB bulk
format differs; act inside Amazon's console). Endpoints: `POST /channels/upload`,
`GET /channels/summary|sb-keywords|sd-targets|sb-harvest`, `GET|PUT /channels/brand-terms`.

### Stores (all-stores overview)
The redesigned store picker — **every store in one panel**, Google-Drive style.
Account totals (Stores · Ad Spend · Ad Sales · ACoS · Flags) up top, then a **tile
grid**: one tile per store showing its name plus mini-stats (Ad Spend · ACoS vs your
goal in green/red · open flags) from its latest snapshot. **Click a store tile** to
drill into that store's **audit tiles** — each audit carries a yellow **month badge**
derived from the month of its latest uploaded snapshot (so you can instantly tell
which month each audit covers; `no data` before the first upload) and a sub-line with
the exact snapshot date. Click an audit tile to open it in PPC Optimization. Every
tile has a **⋮ menu** (store: view audits / open PPC / delete · audit: open / flush /
delete — flush & delete act on *that* tile, not just the current selection). The
`Stores › <store>` breadcrumb walks back up; the header search box filters whichever
level you're on.

### PPC Optimization — cadence flow
The PPC Optimization tab opens with an **Audit Cadence** header: your current **store**, a
**Month / Year** selector, and five **Audit Type** presets following the
audit-cadence strategy:

| Audit Type | Range | Action level | Its own table shows |
|---|---|---|---|
| Daily Watch | Today + Yesterday | Anomaly alert only | day-over-day spike tracker (separate panel) |
| Weekly Optimization | Last 7 days | Bid tweaks, harvest | per-week panels (Week 1–5+) → bid tweaks + harvest + trend (separate panel) |
| Mid-Month Check | Last 14 days | Bid adjust, add negatives | bid adjustments + heavy negative targeting panel (separate panel) |
| Full Month Audit | Last 30 days | Full optimization | full optimization panel — bids + harvest + negatives (separate panel) |
| Pause/Scale Audit | Last 60 days | Pause, kill, scale | cut/scale panel — pause dead targets & campaigns, scale winners (separate panel) |

**Process funnel (step-by-step).** Below the cadence header, every cadence shows a
**process funnel** — a numbered, self-advancing set of steps that walks you through the
correct rhythm: **export** the right Amazon report → **upload** it → **review** the
recommended actions → **download** the bulk & re-upload to Amazon. The active step is
detected live from what you've done: before you upload, Step 1 (export) is highlighted;
once data is in, the funnel advances to Review; once you download the bulk, all steps go
green. Watch-only **Daily Watch** has a three-step funnel (export → upload → scan) with no
download step. A progress bar tracks completion. It's guidance only — it never blocks you.

Each cadence tile in the header grid carries two tag buttons: **audit** (runs that
cadence's flag audit at the current Goal ACoS) and **clear** (danger-confirmed —
permanently wipes every upload behind that cadence: its search-term/watch data plus the
bulk-derived optimizer panels it feeds). Clear always targets that tile's own cadence
data, even when a different cadence is currently open; other cadences are untouched.
Full Month is the base audit data, so clearing it also resets the Dashboard KPIs and
flag table.

**Each cadence has its own dedicated panel.** All five — Daily Watch, Weekly, Mid-Month,
Full Month, Pause/Scale — render their own tool below the funnel (spike tracker /
Search-Term-Report optimization / cut-scale), each driven by its **own isolated upload**
(a bulk uploaded under one cadence only ever drives that cadence). Each type also shows
its **SOP effort checklist** — tick items off as
you do them; progress is **saved per store · month · type** so "May 2026 · Full Month
Audit" is revisitable and you apply the type each month. The month is a label on the run (the audit reads your latest uploaded bulk
snapshot); the header also captures the headline numbers (spend / sales / ACoS /
flags) at run time.

**Upload & Clear (one pattern everywhere).** Every cadence panel follows the same
header pattern as the Product Benchmark tab: a yellow **Upload Sponsored Products
Bulk** primary button on the right, a ghost **Clear** button next to it, and (for the
single-snapshot cadences — Mid-Month, Full Month, Pause/Scale) a meta line under the
title showing the **last uploaded file · its row count · upload date**. In the
Daily Watch / Weekly calendar grids the per-day / per-week tile's Upload button is
yellow while the tile still needs its file and turns ghost ("Re-upload") once data
is in.

**Clear** (danger-confirmed, cannot be undone) wipes that cadence's uploaded data —
and because a cadence upload also feeds the star schema behind the generic optimizer
panels below it (Bid Optimizer, Placement, ASIN tree, Harvest, N-gram), those clear
with it. Per cadence: **Daily Watch** — every uploaded day (watch-only; nothing else
touched); **Weekly** — every uploaded week + its optimizer data; **Mid-Month /
Pause/Scale** — the search-term snapshot(s) + their optimizer data; **Full Month** —
its snapshots + the audit's bulk-derived data (flag table / Dashboard KPIs / optimizer
panels), since Full Month lives in the base audit db — Monitoring, Product Ads,
Keywords and the Benchmark are never touched. Endpoints: `DELETE
/daily-watch/data`, `/weekly/data`, `/mid-month/data`, `/full-month/data`,
`/pause-scale/data`.

#### Daily Watch (spike & anomaly tracker)
Picking **Daily Watch** opens a day-over-day panel below the cadence header — for
catching spend spikes and anomalies fast, no structural changes.

1. **One upload panel per day, calendar-style.** You start with a single panel.
   Press the **＋ "add day"** tile to create another — up to **31 panels** (a full
   month). Each panel shows its calendar day number, its own date picker, and an
   **Upload** button; remove a panel with the **✕**. Set each panel's date, upload
   that day's bulk file, and the day is stored (re-uploading replaces it). Days
   **accumulate** — keep adding panels to build the trend. (Previously-uploaded days
   re-appear as filled panels when you return.)
2. **Compare any two days** — pick an earlier and a later day from the two dropdowns
   (they default to your two most recent uploads) and click **Compare**. You get:
   - **Account deltas** — spend / sales / clicks / orders / ACoS, later vs earlier,
     with the % change. Spend & ACoS rising shows **red** (bad), sales rising green.
   - **Anomalies** — auto-flagged per campaign: **spend spike** (≥1.5× and ≥$20),
     **ACoS spike** (≥10 pts and over goal), **sales drop** (sales halved while spend
     holds), **zero-order spend** ($25+ spent that day, 0 orders).
   - **Top movers** table — the campaigns with the biggest spend swing.
3. **Trend chart** — accumulated daily Ad Spend vs Ad Sales across every uploaded day.
4. **Monitor a campaign (isolated watchlist)** — every anomaly flag and every row in
   the Top movers table carries a **monitor** button. Hit it and the campaign moves
   into the **Monitored campaigns** card (the isolated area above the compare):
   watching-since date, ACoS when added, latest-day ACoS colored against your goal,
   spend/orders, and a status tag. On **every new day upload** the watchlist is
   re-evaluated: a monitored campaign whose ACoS that day is **at/under goal ACoS**
   (with converted sales — a zero-sales day never clears) is **auto-cleared** — it
   leaves the isolated area, shows in "recently cleared" with its clearing ACoS,
   and a toast announces it. Campaigns still over goal stay put; **unwatch**
   removes one manually. Endpoints: `GET/POST/DELETE /daily-watch/monitor(s)`;
   `POST /daily-watch/upload?target_acos=` returns `monitor_cleared`.

Daily Watch is **watch-only** — it raises alerts but emits no bulk file. Use the
Weekly / Mid-Month / Full / Pause-Scale types when you're ready to make changes.

#### Weekly Optimization (bid tweaks + search-term harvest)
Picking **Weekly Optimization** opens its own panel below the cadence header. It's
**Sponsored Products only** and is driven straight from the **SP Search Term Report**
sheet inside your bulk export — so every action points at the **exact entity IDs** the
report carries (Campaign / Ad Group / Keyword / Product Targeting ID), no name-matching.

1. **One upload panel per week, calendar-style.** You start with **Week 1–5** (minimum
   5 panels). Press the **＋ "add week"** tile to create another — up to **53** (a full
   year); *remove last week* drops the trailing panel (never below 5). Each panel uploads
   that week's SP bulk (re-uploading a week replaces just that week), so weeks **accumulate**
   into a trend. Each panel shows ✓ + that week's spend / orders once uploaded. Data is
   parsed into the Weekly cadence's own table and **only ever drives the Weekly cadence**.
2. **Pick the week to optimize** — the *Optimize week* dropdown (or a panel's *optimize ▸*)
   selects which uploaded week's Search Term Report builds the plan (defaults to the latest).
   The snapshot row shows that week's search terms · campaigns · spend / sales / ACoS · goal.
4. **Bid tweaks** — every existing keyword and product target is re-aggregated over the
   selected week and given a recomputed optimal bid (target-CPC, guardrailed: per-pass step
   cap, hard $ caps, never raise on thin data). Each row shows current → new bid, clicks,
   orders, ACoS and the reason. Bids update **by ID** (safest). **Overbid reset:** a bid
   above the hard cap ($5), or 3×+ the observed CPC, is treated as noise — instead of
   stepping down $0.20 per pass it resets straight to the computed target in one pass
   (the row's reason reads *"overbid $39.18 vs $1.76 CPC — reset to $0.50 in one pass"*). The Bid tweaks and both
   Harvest tables also carry a **BE ACoS** column — the ad group's product break-even
   (benchmark upload wins, else catalog listing price + per-SKU COGS + real
   Transactions-ledger fees) — with the row's ACoS colored red/green against it.
5. **Harvest — promote winners** — customer search terms with orders at/under goal ACoS
   become **Exact** keywords (or **product targets** when the term is an ASIN). An ad
   group that already mixes the wrong type, or an auto campaign clause, is skipped.
6. **Harvest — negate losers** — search terms that spent with **0 orders** become a
   **Negative Exact** keyword (ASIN terms → **Negative Product Targeting**).
7. **Tick the rows** you want (everything is pre-selected; per-section *select all*) and
   click **Download bulk** — one Amazon-validated SP bulk `.xlsx` for that week with the
   chosen bid updates + keyword/product-target creates + negatives. Re-upload it to Amazon.
8. **Week-over-week trend** — an Amazon-Ads-style metric chart across every uploaded week
   (pick up to 2 of ACoS / ROAS / CTR / CVR / CPC / spend / sales / orders / clicks / impressions).

Careful targeting rules are enforced so Amazon accepts the file: an ASIN search term is
always a product target (`asin="B0…"`), never a keyword (and vice-versa); a keyword and a
product target are never created in the same ad group; auto clauses (loose-/close-match,
substitutes, complements) are never promoted; duplicate rows are collapsed; and the big
16–18 digit IDs are kept as exact strings (never floats).

#### Mid-Month Check (bid adjustments + heavy negative targeting)
Picking **Mid-Month Check** opens its own panel — **Sponsored Products only**, the same
Search-Term-Report engine as Weekly but a **single panel** (one snapshot, no weeks) and
focused on **bid adjustments + negative targeting**.

1. **Upload one SP bulk** (with its *SP Search Term Report* sheet). It replaces the prior
   Mid-Month snapshot and **only ever drives the Mid-Month cadence**. The header shows
   search terms · campaigns · spend / sales / ACoS · goal.
2. **Bid adjustments** — every keyword and product target gets a recomputed guardrailed
   bid (target-CPC, by ID). Tuned for the 14-day mid-month window. All three tables
   (bid adjustments, wasted negatives, bleeders) carry a **BE ACoS** column — the ad
   group's product break-even (catalog listing + per-SKU COGS + real
   Transactions-ledger fees) — with the row's ACoS colored red/green against it.
3. **Negative targeting · wasted spend** — search terms that spent **$10+ with 0 orders**
   become **Negative Exact** keywords (ASIN terms → **Negative Product Targeting**).
   Pre-selected — this is the bulk of the mid-month work.
4. **Negative targeting · bleeders** — search terms that **did convert** but at **ACoS ≥
   2× goal** (converting-but-unprofitable). Pre-filtered to the ones worth acting on:
   **≥ 2 orders** (one order's ACoS is statistical noise) **and head spend** (≥ 2× the
   loser floor) — the long tail is dropped. Surfaced as an extra, **not pre-selected** tier
   (negating stops those sales). Best practice: **bid-down first** (run step 2, re-upload),
   then next cycle negate only the bleeders still above **break-even** after the cut.
5. **Tick the rows** (per-section *select all*) and click **Download bulk** — one
   Amazon-validated SP bulk `.xlsx` of bid updates + negatives. Re-upload it to Amazon.

Same Amazon-safety rules as Weekly (ASIN↔keyword separation, exact-string IDs, dedup).

#### Full Month Audit (full optimization)
Picking **Full Month Audit** opens its own panel — the **complete pass**, the superset of
the focused cadences in one place. **Sponsored Products only**, single panel, same
Search-Term-Report engine.

1. **Upload one SP bulk** (with its *SP Search Term Report* sheet). Replaces the prior Full
   Month snapshot; **only ever drives the Full Month cadence**. Uses the untuned 30-day
   thresholds for the **broadest** coverage.
2. **Bid adjustments** — recomputed guardrailed bid for every keyword / product target (by ID).
3. **Harvest · promote winners** — converting search terms at/under goal ACoS → **Exact**
   keywords (ASIN terms → product targets). Pre-selected.
4. **Negative targeting · wasted spend** — spent with **0 orders** → Negative Exact / Negative
   Product Targeting. Pre-selected.
5. **Negative targeting · bleeders** — converted but ACoS ≥ 2× goal (2+ orders, head spend).
   Surfaced, **not pre-selected** (negating stops sales — bid-down first, then negate next cycle).
6. **Tick the rows** (per-section *select all*) and **Download bulk** — one Amazon-validated SP
   bulk `.xlsx` with bid updates + promotes + negatives. Re-upload it to Amazon.

> The richer **Bid Optimizer**, **Placement Optimizer**, **Search Term Harvest** and **N-Gram
> Word Miner** panels (which read a full bulk loaded via the Uploads tab) still appear below
> for the deep monthly pass.

#### Pause/Scale Audit (cut & scale)
Picking **Pause/Scale Audit** opens its own panel — last-60-day **cut/scale** decisions.
Unlike the other cadences (which harvest customer *search terms*), Pause/Scale acts on the
**existing entities** the report carries. **Sponsored Products only**, single panel.

1. **Upload one SP bulk** (with its *SP Search Term Report* sheet). Replaces the prior
   Pause/Scale snapshot; **only ever drives the Pause/Scale cadence**.
2. **Scale winners → bid up** — keyword / product targets with **10+ orders at/under goal
   ACoS** get a controlled bid raise (capped +25%). Pre-selected.
3. **Pause dead targets** — keyword / product targets with **30+ clicks and 0 orders** →
   set **State = paused** (by ID). Pre-selected.
4. **Pause dead campaigns** — campaigns with **$50+ spend and 0 orders** → pause the whole
   campaign. **Not pre-selected** (it stops every ad in the campaign — review first).
5. **Tick the rows** (per-section *select all*) and **Download bulk** — one Amazon-validated
   SP bulk `.xlsx` of bid raises + target pauses + campaign pauses. Re-upload it to Amazon.

The 30-click / $50-spend / 10-order bars are deliberately strict — these are 60-day kill/scale
calls, not weekly tweaks. A healthy account may show only scale rows and no pauses.

### Monitoring — Daily SALES & PPC Tracker
A day-by-day tracker that consolidates your **Business Report (Sales & Traffic by
Date)** and your **Sponsored Products campaign report** by date, so you don't eyeball
53 columns each morning. Workflow:
- **Upload Daily Reports** (yellow button, app-wide upload pattern) — pick either
  report (CSV/XLSX, multi-select works); the type is auto-detected and rows accumulate
  by date (re-uploading the same file never duplicates; a business-only or PPC-only
  upload just fills its own columns). Money/percent/comma strings are cleaned
  automatically; percents shown as the plain number (24.03%). A meta line under the
  controls lists the **last few uploaded files** (name · days · report kind ·
  upload date, persisted per audit — Monitoring is cadence-agnostic so the list is
  shared across cadences). The ghost **Clear** button (danger-confirmed,
  `DELETE /monitoring/data`) wipes every uploaded tracker day; manual month-sales
  figures you typed into the overview are kept (hand-entered, not upload-derived).
- **Pick a range** — a **month** quick-pick or custom **from / to** dates. Any day in
  range with no data shows **"-"** (e.g. pick April but only May exists → April is all
  dashes).
- **Overall Performance** strip at the top — month totals + overall ratios (TACOS,
  Total Sales, Units, Ad Spend, Ad Sales, Orders, Clicks, Impressions, ACOS, ROAS,
  CPC, CTR, CVR), **vs last month** and **vs last year** sales + growth %, and a
  **run-rate estimate** for the month ("day X/N"). If a comparison month has no daily
  data uploaded, its cell becomes an **input** — type the total sales for that month
  and the growth % recomputes (saved per month, marked "·manual"; blank it to clear). Set a **TACOS target %** (default
  12) — the header flags whether you're at/below it (green) or over (red).
- **⬇ Export .xlsx** — downloads the selected range as a client-ready workbook
  with **native Excel charts**: an *Overview* sheet (range KPIs incl. TACOS vs
  target, health score, **weekday-vs-weekend avg-sales bar chart**, **B2B share
  pie**, alerts and recommendations tables) plus the *Daily Tracker* sheet —
  one row per calendar day with a **Total sales · Ad spend · Ad sales line
  chart** — with the exact
  reporting columns: Date · Total Sales · Units Ordered · Ad Spend · Ad Sales · Orders
  (PPC) · Clicks · Impressions. Units Ordered = the Business-Report Units Ordered
  (already includes B2B). Empty days export as 0 (not "-").
- **Daily table** mirrors your spreadsheet — Date · Total Sales · Units · Ad Spend ·
  Ad Sales · Orders (PPC) · Clicks · Impressions · **ACOS · ROAS · CPC · CTR · CVR ·
  TACOS** · plus Sessions · ASP · Buy Box · Refund · Sess CVR. The PPC ratios are
  derived per day: ACOS = ad spend ÷ ad sales, ROAS = ad sales ÷ ad spend, CPC = ad
  spend ÷ clicks, CTR = clicks ÷ impressions, **CVR = ad orders ÷ clicks**, **TACOS =
  ad spend ÷ total sales**. "Sess CVR" is the Business-Report Unit Session % (the
  conversion metric driving the alerts). Empty days show "-".
- **What you get** (all over the selected range):
  1. **Day-over-day deltas** (sales, units, sessions, CVR, ASP, buy box) — green up /
     red down, absolute + %.
  2. **7-day rolling average** lines for sales / sessions / CVR (smooths weekend noise).
  3. **CVR-fall alert** — CVR down 3 days running. **Buy-box alert** — latest day < 90%.
     **Refund-spike alert** — latest refund rate > 2× the 7-day avg *and* > 3%.
     **ASP-swing flag** — ASP ±15% vs 7-day avg (silent promo / coupon).
  4. **Traffic-vs-conversion divergence** — headline warning + a dual-axis chart
     (sessions bars vs CVR line) when sessions trend up while CVR trends down.
  - **Actions & Recommendations** — concrete next steps derived from the data, in
    **two buckets**: **PPC** (TACOS over target, high ACOS, low ROAS / CTR / ad CVR,
    traffic-up-conversion-down → negatives/relevance) and **Listing** (buy box < 90%,
    CVR sliding, refund spike, ASP/price swing, sessions falling → price / images /
    reviews / SEO). Each item is severity-ranked with the recommended action.
  5. **Weekday vs weekend** averages, **B2B vs total** split, and a **health score
     0–100** badge (green ≥70 / amber 40–69 / red <40).
- CVR = *Unit Session Percentage* (the primary conversion metric). Data is private to
  your account + selected store/audit.

### Keywords
**Keyword project bar (connects the whole Product Optimization group).** The top
of the tab carries the same project system as SEO / Listing Audit / Product
Overview: pick a **Listing Optimizer project** or create one (**new project** →
name + primary ASIN, exactly like the Listing Audit flow). Everything you mine
here can then be merged into that project's tracked-keyword list, where the
**SEO tab computes the indexed %** (ranked ÷ tracked per ASIN) and the
**Listing Audit checks usage in Title / Bullet Points / Description / backend
Search Terms** for every keyword:
- **Send N keywords to project** — pushes the whole mined pool (Brand Analytics
  SQP + Cerebro) into the selected project, deduped against what's already
  tracked (a duplicate only backfills a missing search volume; each keyword
  remembers its source: sqp / cerebro / harvest / ngram).
- **Search-term harvest → to keyword project** — the harvest table's selected
  customer search terms merge into the same project.
- **N-gram miner → winners to keyword project** — winning grams merge in too.
- **Copy AI relevancy prompt** — builds a complete, copy-paste prompt for any
  LLM: your **CURRENT listing data** (title, bullets, description, backend
  search terms, alt text, A+) vs your **PROPOSED listing data** (both from the
  project's Listing Copy), plus every tracked keyword with its search volume
  and source. The prompt asks for a table — Keyword · Relevancy 1-5 · In
  Current? · In Proposed? · Best Placement · Reason — plus the top missing
  keywords in the proposed copy and which keywords to drop. Endpoints:
  `POST /tracker/keywords/bulk`, `POST /keywords/to-project`,
  `GET /tracker/relevancy-prompt?project_id=`.

**Keyword mining** — consolidate research from two sources, deduped:
- Two upload cards following the app-wide pattern — yellow **Upload Brand Analytics
  SQP** and **Upload Helium10 Cerebro** buttons (the whole card is clickable and
  accepts drag & drop). Files upload *separately per source*; rows merge by
  normalized phrase (case/space folded), keeping the max search volume + each
  source's metrics (SQP purchases, Cerebro organic/sponsored rank, competing
  products). The mined-keywords header shows a meta line with the **last few
  uploaded files** (name · rows · source · date, persisted per audit + cadence),
  and the ghost **Clear** button (danger-confirmed) wipes the pool + the file list.
- **All** view — the deduped pool (volume, sources, ranks). **Recommend** view —
  generic keywords to target: non-branded (your store name + plurals excluded),
  not already running in the account, 1–5 words, ranked by opportunity (volume ×
  dual-source bonus). Each shows the reason it fired.
- Endpoints: `POST /keywords/upload?source=sqp|cerebro`, `GET /keywords`,
  `GET /keywords/recommend`, `DELETE /keywords`. Accepts `.xlsx/.csv`.

**Search-Term Harvest** and the **N-gram miner** now live on this tab (moved off PPC
Audit) — both are keyword-discovery tools, so they sit next to keyword mining:
- **Search-term harvest** — upload your **Sponsored Products bulk file** (the one
  with the embedded **SP Search Term Report** sheet): winners → Exact keywords,
  losers → Negative Exact, and because that sheet carries the report's **real
  Campaign / Ad Group / Keyword / Product-Targeting IDs**, the downloadable bulk
  creates/negates **by exact ID** — no name mapping, no "temporary ID" rejections
  (reuses the Weekly cadence engine; same Amazon-safety rules — ASIN terms become
  Product Targeting, no keyword/PT mixing per ad group, invalid keywords dropped).
  The candidates table shows each term's campaign + ad group (IDs in the tooltip)
  and a **BE ACoS** column — the ad group's product break-even (benchmark upload
  wins, else catalog price + per-SKU COGS + real Transactions-ledger fees, via
  the ad group's product ad) — with the term's ACoS colored red/green against
  it, so a "winner" converting above the product's break-even is visibly still
  losing money before you promote it.
  Dropping a **standalone STR** (no ID columns) still works as a fallback — it
  maps to the loaded account by campaign + ad-group name, and the panel tells you
  which path it used. Endpoints: `POST /harvest/from-bulk`,
  `POST /harvest/from-bulk/file` (legacy: `POST /harvest`, `/harvest/bulk`).
- **N-gram miner** — upload the same **SP bulk file** (its embedded SP Search Term
  Report sheet is auto-picked; a standalone STR works too): see winning / wasting
  *words* (1–3 grams) across all terms. Each gram carries a **BE ACoS** — the
  **spend-weighted break-even across the ad groups its terms ran in** (a word
  spans products, so its break-even is the weighted mix of theirs, from the
  catalog listings' price + per-SKU COGS + real Transactions-ledger fees; rows
  resolve by campaign + ad-group name against the loaded account) — and the
  gram's ACoS colors red/green against it.
Results persist across tab switches (lifted to app state).

### Product Optimization (Competitor Research / Indexed Keywords / SEO)
Replaces the manual "Competitor Research / Indexed Keywords / SEO" Google Sheet with an
in-app tracker — its own **Product Optimization** sidebar group (organic SEO, not part
of the PPC Suite) with three tabs sharing the same project data:
- **SEO** — search-visibility work: scorecards, movers, the keyword × ASIN rank grid
  and the PPC bridge suggestions.
- **Listing Audit** — the raw-copy analysis engine: paste listing copy per element,
  computed exact/broad markers, coverage and not-used-anywhere keywords.
- **Product Overview** — the competitor catalog: the transposed product matrix (images,
  attributes, KPI blocks, revenue donut, Yes/None health checks).

The project switcher and uploads (Cerebro / X-ray / Migrate sheet) sit at the top of
every tab; switching between the three keeps the active project and loaded data.
Multi-store; competitor sets are per tracker **project** (one per client product line,
e.g. "Project Snore").

**Raw-data flow (the normal path)** — no pre-computed sheet needed; you upload RAW
exports and the app processes the analysis itself:
1. **New project** — name it and (recommended) enter your primary ASIN.
2. **Upload Cerebro (raw)** — a raw Helium10 Cerebro export (`.csv/.xlsx`) seeds the
   keyword master list + organic ranks. Single-ASIN exports default to your primary
   ASIN (or fill the ASIN box); multi-ASIN exports (per-ASIN rank columns) are detected.
3. **Upload X-ray (raw)** — a raw Helium10 X-ray export (`.csv/.xlsx`) builds the
   competitor matrix. **Cerebro decides which ASINs count**: only X-ray rows whose ASIN
   appears in your Cerebro data (or is your primary) are displayed — an 80+-row X-ray
   against an 8-ASIN Cerebro shows just those 8 (the toast reports matched/skipped).
   Unmatched rows are stored hidden, so **upload order doesn't matter**: X-ray first,
   Cerebro after — the matching rows appear the moment Cerebro lands. Re-uploads refresh
   imported attributes but keep your manual audit edits (Yes/None rows). If more than 10
   competitors match, only the **top 10 by revenue** stay active (shown in the
   matrix/scorecards); your primary ASIN is always active and flagged ★.
4. **Paste your listing copy** — in the **Listing Audit** panel, click an element card
   (Title, Bullet Points, A+/Brand Story, Description, Search Terms, Alt Text) and paste
   the raw text. On save the app **computes** the `exact`/`broad` keyword markers itself
   (whole phrase present = exact; every word present = broad) — no hand-marking.

**Legacy one-time migration** — still supported: download the old Google Sheet as
`.xlsx` (all tabs) and hit **Migrate sheet**. Per the approved mapping
(`research_tracker/MAPPING.md`) it imports the Main keyword × ASIN rank grid, X-ray
competitor attributes, the manual listing-health audit block, Listing Audit usage
markers, Listing Copy blocks and the Search Terms tab's extras. Re-migrating the same
project name replaces it. Sheet-imported audit markers keep showing per element until
you paste raw copy for that element — then the computed markers take over.

**Ongoing snapshots** — upload a Helium10 **Cerebro** export (`.csv/.xlsx`) weekly.
Snapshots are **append-only** per date — re-importing a date replaces only that date, so
trends accumulate. Rank `0` or `-` = not ranked. Unknown keywords are added to the
master list.

**Views** (all recomputed live, matching the sheet's formulas):
- **Listing Audit (computed)** — six copy-element cards (chars, exact/broad counts,
  total exact SV — click to paste/edit raw copy), a red chip row of the top
  **not-used-anywhere** keywords by search volume worth working into the copy, a
  coverage counter (keywords used somewhere / tracked), and the keyword × element
  marker matrix (`exact` green / `broad` amber). SP/SB targeting marker columns from a
  sheet migration appear when present.
- **Competitor copy comparison** (inside Listing Audit) — one column per active
  competitor (image + brand + ASIN link) next to a highlighted **★ You** column.
  Paste each competitor's live copy manually per element (Title, Bullet Points,
  A+/Brand Story, Description, Alt Text — click a cell); the app computes the same
  chars / exact / broad / exact-SV stats against your tracked keywords, plus a
  **Keywords covered** bottom row (red when a competitor covers more than you).
  **Search Terms are not compared** — there's no data source for competitor backend
  keywords, so that row is deliberately absent (and the API rejects it).
- **Competitor matrix** — the sheet's Main-tab layout, rebuilt: product images on top,
  one column per ASIN (primary highlighted ★), attribute rows (Price, Sales, Revenue,
  BSR, Review Count, Star Ratings, Review Velocity, FBA Fees, Active Sellers, Buy Box,
  Fulfillment, Size Tier, Seller Country, Creation Date, computed Listing Age), the
  **Listing Health Score** row — **computed**, 1.25 points per Yes over the 8 audit
  checks, perfect 10 (color-tiered: ≥7.5 green, ≥5 yellow, >0 amber) — and the manual
  **Yes/None audit rows**
  (PDP Images/Videos, Brand Story, A+, Crawlable Text, Alt Text, Comparison Table,
  Amazon Badge — click a cell to toggle). Header shows the sheet's colored KPI blocks
  (Total Revenue green, Market Share yellow, Average Reviews) plus a revenue-share donut.
  ASINs link to their Amazon detail pages.
- **Listing Sanitizer** (top of Product Overview) — an Amazon banned-keyword checker
  for **your listing only** (competitors are never scanned). Hit **Edit banned list**
  and paste Amazon's banned/restricted terms once (one per line or comma-separated;
  the list is shared across projects — saving replaces it). Every element of YOUR
  pasted copy (Title, Bullet Points, A+, Description, Search Terms, Alt Text) is then
  checked and reported per element: green `clean`, or red `N flagged` with the exact
  banned phrases found as chips (e.g. *Title — 4 flagged: FDA approved, clinically
  proven, cure, non-toxic*). Matching is whole-word with case and punctuation folded,
  so `non-toxic` flags "Non Toxic" but `cure` does not flag "secures". Elements with
  no pasted copy show "nothing to check" — paste copy in the Listing Audit tab first.
- **Scorecards** — per ASIN: index rate (ranked/tracked), page-1 count, avg rank, page-1
  trend sparkline; primary card highlighted with coverage-vs-best-competitor. Header
  KPIs: top-10 revenue, market share, average reviews (the sheet's header block).
- **Keyword grid** — the sheet's Main-tab layout in one table: Keyword, SV, computed
  REL, the six **listing-element marker columns** (Title, Bullet Points, A+/Brand
  Story, Description, Search Terms, Alt Text — `exact` green / `broad` amber, computed
  from your pasted copy or the sheet import), then one column per ASIN with the
  **product image + brand + ASIN link stacked in the header** and rank cells
  heat-colored by page (page 1 green / page 2–3 amber / deeper muted / `—` unranked).
  **Click any rank to edit manually** — writes today's snapshot row, preserving the
  sheet habit. The **REL column is computed**: how many of the displayed ASINs use the
  keyword in their listing — Title + Bullet Points from the X-ray/sheet import, plus
  your pasted Listing Copy (Title / Bullets / Description) for the primary. Yellow =
  used by at least one listing; 0 = nobody uses it. Date-scoped; exportable as `.xlsx`
  (**Export matrix** — the client deliverable).
- **Movers** — climbers/decliners since the previous snapshot (Δ negative = improved),
  plus **newly ranked** and **lost** lists (new keywords never show a fake delta).
- **PPC bridge** — rank-support keywords (organic page 2–3, decent volume → exact-target
  to push to page 1) and competitor ASINs as product-target suggestions.
- **SEO recommendations** (on the SEO view above the movers, AND on the Listing
  Audit view right under the copy editor — edit copy and watch the recs react
  without switching tabs) — prioritized actions computed
  live from the Listing Audit copy vs the project's tracked keywords, severity-tagged
  high/medium/low: copy elements never pasted, **top-SV keywords not exact in the
  title** (exact title matches carry the most rank weight), **high-volume keywords
  covered nowhere**, title length checks (over 200 chars / under 80), fewer than 5
  bullet points, **backend search terms over Amazon's 249-byte limit** (the whole
  field is ignored beyond it), banned phrases present in your copy, and **backend
  words wasted** on terms the visible copy already indexes. Each rec lists the
  offending keywords with their search volume.
- **Backend search-term recommendation** (next to the recs) — a ready-to-paste
  generic-keywords line: the highest-search-volume tracked-keyword **words not
  already in your title/bullets/description** (Amazon indexes visible copy
  word-by-word, so repeating it back wastes bytes), deduped, banned-words
  excluded, packed to exactly ≤ 249 bytes. Shows the byte meter, how many
  uncovered candidate words exist, your current field's byte count, which of its
  words are wasted, and a **Copy line** button for Seller Central → Edit Listing
  → Keywords.
- **Current vs Proposed copy variant** — both the Listing Audit and the SEO
  recommendations carry a **Current | Proposed** toggle. *Proposed* is your draft
  rewrite: paste elements into it (or hit **Seed from current** to start from the
  live copy) and it gets the same exact/broad markers, coverage and SEO
  recommendations — computed **only from the pasted draft** (sheet-imported
  usage markers and competitor pastes stay on Current; the competitor comparison
  is hidden on Proposed). Iterate on the draft until its recommendations go
  quiet, then publish it on Amazon and paste it as the new Current. Endpoint:
  `GET /tracker/seo-recommend?variant=proposed`; `GET/PUT /tracker/listing`
  accept `variant` too.

- **Export Report** (yellow button in the project header, all three views) — one
  client-ready workbook with **native Excel charts**, one sheet per view:
  *Overview* (project KPIs, ASIN scorecard table, **page-1 keywords bar chart**,
  **revenue-share pie**), *SEO* (**rank-distribution pie** for your ASIN —
  page 1 / page 2–3 / deeper / unranked, a **page-1 trend line chart** across
  snapshots when history exists, and the movers list), *Listing Audit*
  (per-element coverage table + **stacked exact/broad bar chart**, the full
  severity-tagged SEO recommendations, the suggested ≤249-byte backend
  search-term line, top uncovered keywords) and *Product Overview* (competitor
  catalog — price / rating / reviews / revenue / BSR / listing age / health
  score — + **revenue bar chart**). Charts are real Excel charts, so they stay
  editable in Excel/Sheets. Endpoint: `GET /tracker/report/export?project_id=`.

Endpoints: `GET/POST/DELETE /tracker/projects`, `POST /tracker/migrate`,
`POST /tracker/import`, `POST /tracker/xray`, `GET/PUT /tracker/listing`,
`GET /tracker/matrix|scorecard|movers|export`, `PATCH /tracker/cell`,
`POST /tracker/ppc-suggest`, `GET /tracker/seo-recommend`,
`GET /tracker/report/export`. Base-db scoped (cadence-agnostic, like Monitoring).

### Strategy
**Tier Router** at the very top suggests your **campaign-architecture tier** from
how many products you actually sell. It counts advertisable units from the
store's Product Catalog (parents + standalone SKUs — child variations fold into
their parent and never add structure); before a catalog is uploaded it falls
back to the distinct advertised ASINs in the current audit's bulk. Seven tiers:

1. **1–5 · Full Waterfall (RAF Funnel)** — 1 campaign = 1 ASIN, AT → BROAD →
   PHRASE → EXACT → PT per product.
2. **6–20 · Hero Waterfall + SPAG** — top sellers get the full funnel, the rest
   a 3-campaign SPAG.
3. **21–50 · SPAG + ABC Tiering** — class-level ACoS targets, tail shares
   grouped auto catch-alls.
4. **51–100 · Goal-Segmented + Bid Automation** — LAUNCH / SCALE / PROFIT
   segments, exception-based review.
5. **101–500 · Category Clusters + Hero Carve-outs** — multi-ASIN ad groups by
   default, granularity is earned.
6. **501–1000 · Template Structure** — naming-convention-generated campaigns,
   bulk-file-only management.
7. **1000+ · Portfolio Machine** — velocity bands, budget as the steering
   wheel, humans clear exceptions only.

The card shows the suggested tier's structure, campaigns-per-ASIN, ACoS-target
scheme, automation level and key techniques, plus **which Audit Cadences to
run** (click a cadence chip to jump straight to its strategy set below) and
which app engines implement it. Notes call out category spread (3+ categories →
one Portfolio per category) and hero concentration (top-heavy catalogs manage
heroes a tier lower). **Show all 7 tiers** expands the full ladder with your
tier highlighted.

**Methodology map** below it shows how the playbook reads an account: pull
60-day data → read ACoS vs break-even → classify into one of four states (Below /
At / Above target · Over break-even) → apply the goal lever (cut · grow · rank ·
balance) → the always-on metric engine (bid · negate · harvest) → the 90-day
phases (diagnose → fix → optimize → scale). The map is **live**: each state box
shows the real count of your campaigns currently in that state (a "LIVE" badge
appears once the strategy set loads), with a note for campaigns still too thin
to classify.

**Account states** — the classifier behind the map, as a table: every campaign
lands in ONE state from its ACoS vs the per-ASIN goal vs the product's **real
break-even** (catalog + Transactions-ledger fees): *Below target* (lever:
grow), *At target* (±15% band; balance), *Above target* (cut), *Over
break-even* (cut hard — losing money per sale even if near goal), *No data*
(rank — keep building visibility; also catches spend-with-zero-sales as Over
break-even). Columns: state badge · campaign · spend · ACoS / BE (colored) ·
goal · lever · why. Computed for the generic advisor AND every cadence's
strategy set (each cadence classifies its own uploaded data).

**Per Audit Cadence** — the panel opens with a **cadence selector** (Daily, Weekly,
Mid-Month, Full Month, Pause/Scale). Pick one to load *its own* recommendation set.
**Weekly / Mid-Month / Full-Month / Pause-Scale each drive their own strategies from
their own uploaded data** (the cadence's `…TermFact` side table via its plan engine —
not the shared FactPerformance snapshot):
- **Weekly** — Search Term Harvesting (promote winners → Exact), Negative Keyword
  Sculpting (negate wasted terms), Bid Optimization (bid tweaks).
- **Mid-Month** — Negative Keyword Sculpting, Bleeder Negation (converting terms ≥ 2×
  goal ACoS), Bid Optimization.
- **Full-Month** — Harvesting + Negative Sculpting + Bleeder Negation + Bid Optimization
  (the superset).
- **Pause-Scale** — Exact Match Scaling (bid up proven winners), Pause Wasted Targets,
  Pause Wasted Campaigns.

Each strategy's **⬇ bulk** builds that cadence's Amazon bulk (exact IDs) and logs to the
Change Log; the filename carries the cadence. A cadence with no uploaded data shows an
empty set. Any other selection (Daily / legacy) still runs the generic account advisor.

**Strategy Advisor** runs the 16-strategy PPC playbook over the selected cadence. Two parts:
- **Recommendations** — per-campaign detected strategies (Harvesting, SKAG, Exact
  Scaling, Broad Research, Negative Sculpting, Budget Segmentation, Catch-All,
  Lifecycle, Portfolio…) with the numbers that triggered them, priority, and
  which engine runs it (e.g. "PPC → Harvest"). Each row shows **ACoS / BE** —
  the campaign's ACoS against its product's **real break-even** (catalog price
  + per-SKU COGS + the SKU's actual Transactions-ledger fees; ASIN match, else
  normalized-SKU listing match), red when above it. A dedicated
  **Over Break-Even (Bleeding)** strategy fires (high priority) whenever a
  campaign's ACoS exceeds the product's break-even regardless of the goal —
  "cut bids below break-even or pause; re-check price/COGS".
- **Playbook** — all strategies as a **table list** (was a card grid): Strategy ·
  Status · Criteria · Action · Run in, searchable and sortable like every other
  table. Status values: `active` (firing now), `available` (tool ready),
  `manual`, `needs config` (brand list), `n/a` (Dayparting — needs hourly data
  the bulk file lacks). Active bulk-capable rows carry the `⬇ bulk` button
  inline.
- **One-click bulk** — strategies with a `⬇ bulk` button generate their Amazon
  bulk file directly (and log to the Change Log): *Exact Match Scaling* (exact
  bid raises), *Negative Keyword Sculpting* (pause + negate wasted), *Placement
  Bid Optimization* (adjustment %), *Budget Segmentation* (+20% on capped
  campaigns). Others route to their tool or need a Search Term Report.

### Product Benchmark (under Uploads)
- **Product Benchmark** — **store-wide**: upload ONCE per store and every audit
  in that store auto-matches its ASINs against it (stored in the store's
  `_benchmark.json`; per-audit rows still override). The panel shows how many
  benchmark ASINs matched the current audit; unmatched rows are dimmed but kept
  for sibling audits. Break-even ACoS is derived from each ASIN's sale price and a
  default referral % (with a default-COGS % fallback). Lives in the **Uploads** tab.

### Product Benchmark (catalog tab)
Your **store-level product base**, built from the **Amazon Category Listings
Report** (Seller Central → Reports → Category Listings Report). Own sidebar tab
("Product Benchmark", below Product Optimization) — distinct from the break-even
Product Benchmark upload above.

- **Scope: per store.** One catalog per store, shared by every audit/cadence in
  it, never visible from another store (stored in the store's `_catalog.json`,
  inside your per-user store dir; deleted with the store). This is the product
  base other features can map against.
- **Upload & merge.** Amazon exports **one file per category** — upload each one
  (multi-select works) and they **merge by SKU**; re-uploading a file replaces
  its products with the fresh rows. The header lists every uploaded file with
  its row count. **Clear** wipes the catalog (confirm dialog; re-upload to rebuild).
- **What's extracted** (key-driven parse of the `Template` sheet, so Amazon's
  per-category column drift doesn't matter; the built-in `ABC123` example row is
  skipped): Title, Product Description, all 5 Bullet Points, Search Terms
  (generic keywords), Brand, Product Type, Status, ASIN, **Selling Price** (+
  sale & list price), **image links** (main + up to 8 alternates + swatch) and
  **variations** (Parent/Child, parent SKU, variation theme, color, size).
- **The table**: image thumbnail, title (click → full detail), SKU, ASIN
  (links to amazon.com), type, variation badge (parent · theme / child),
  color/size, price (sale price shown green with the old price struck through),
  status, and image / bullet / description-length counts (0 shown red — instant
  content-gap scan). Stats row: totals, variation families, children,
  standalone, priced, brands, missing image, missing description.
- **Detail view** (click any product): image gallery with thumbnails, brand /
  ASIN / parent SKU / theme / color / size, Selling-Sale-List price block, all
  bullet points, full description, search-term chips, and the **variation
  family** table (a parent lists its children; a child lists its parent and
  siblings — click through).
- **SEO recommendations (catalog-level).** Every non-parent product is checked
  against listing-quality rules straight from the report fields — no Product
  Optimization project needed: missing/short/over-200-char title, fewer than 5
  bullets, missing/thin description, **no backend search terms / field over
  Amazon's 249-byte limit / backend words wasted** on terms the visible copy
  already indexes, missing main image / fewer than 5 images. The table gets an
  **SEO** column (high+medium issue count per product, ✓ when clean, parents
  "—") and a **Listing Issues** stat; the detail view lists the full
  severity-tagged recommendations. Keyword-based recs (title coverage, the
  packed 249-byte search-term line) come from **Perform Listing Audit**, which
  hands the product to Product Optimization.
- **Perform Listing Audit** (every product row + the detail view): hands the
  product off to **Product Optimization** — pick an existing project or create
  one on the spot (name defaults to the product title, **primary ASIN is set to
  the product's ASIN automatically**; an existing project without a primary
  ASIN adopts it too, and the single-ASIN upload field arrives prefilled with
  the product's ASIN — nothing to type), and its **title, bullet
  points, description and search terms** are imported from the catalog into that
  project's own listing copy (elements empty in the report are skipped, so a
  manual paste is never wiped), then the **Listing Audit** view opens with that
  project selected. The product's search terms are also added as **tracked
  keywords** (source `search_terms`) so the **SEO** tab covers them: segments
  are split on commas/semicolons/newlines, anything still longer than 6 words
  is treated as Amazon's undelimited word-soup and split into single words
  (Amazon indexes the field word-by-word), and everything is deduped against
  the project's existing keyword list — re-importing never duplicates.
  Endpoint: `POST /tracker/listing/from-catalog` (`{project_id, sku}`).
- **Product Ads join + Break-Even metrics.** The catalog is connected to the
  **Product Ads** tab: every catalog ASIN is matched against the *selected
  audit's* Product Ads upload (the Sponsored Products bulk), adding three table
  columns — **Campaigns** (how many distinct campaigns advertise that ASIN,
  with a per-targeting-kind breakdown: `19A 13K 19P` = auto / keyword-target /
  product-target / `M` manual), **Ad Spend**, and **ACoS / BE** (the ASIN's PPC
  ACoS next to its break-even ACoS, green when profitable, red when bleeding;
  `∞` = spend with zero PPC sales). **Break-even ACoS** comes from the
  break-even Product Benchmark upload when you've uploaded one (that value
  wins), otherwise it's **derived from the catalog's selling price** (sale
  price when set): `BE = (price − referral fee − COGS%) ÷ price`, using the
  audit's econ defaults — so simply uploading the Category Listings Report
  gives every priced product a break-even baseline. The table adds
  **COGS and Profit-per-Unit columns**: **COGS** defaults to **40% of
  the selling price** and is editable inline per product — click the cell and
  type a decimal (`0.35`) or a percent (`35` / `35%`); empty resets to the 40%
  default (custom values render bright, defaults muted; overrides persist
  store-level in `_cogs.json`). **Profit / Unit** =
  `price − COGS − Amazon fee` (green/red). The detail view's PPC block shows
  the COGS/unit with its % and source. The **Amazon fee uses the SKU's REAL
  fees from the Transactions ledger** when it has order rows there — actual
  referral % (selling fees ÷ product sales) + actual **FBA $ per unit** — so
  the break-even is price-dependent (a fixed FBA fee weighs far more on a $10
  product than a $50 one); without ledger data it falls back to the 15%
  referral default and no FBA fee, which makes every default-COGS product read
  a flat 45%.
- **Upload Selling Economics** (header button, next to the catalog upload) — the
  **base fulfillment fee per unit** and the **referral fee per unit**, from
  Seller Central → Reports → **Business → Selling economics** (the SKU Economics
  export, e.g. `selling economics.csv`). The same button also reads an **FBA Fee
  Preview** (Reports → Fulfilment → Fee Preview); columns are matched loosely by
  name, so `Base fulfillment fee per unit`,
  `expected-domestic-fulfilment-fee-per-unit`, British/American spellings and the
  older `pick-pack` + `weight-handling` pair (summed) all resolve, and per-unit
  columns are never confused with their `quantity` / `total` twins.
  **Every sheet of a workbook is read.** If the export's second sheet is a
  **Referral Fee Preview**, its rows are applied ON TOP of the matching item
  (found by SKU, else ASIN) and **overwrite that item's referral fee** — the
  preview is the authoritative rate — after which Total Fees is recomputed. A
  preview row quoting only a *percentage* is priced off the item's own selling
  price; a preview row with no fee row of its own is kept as a referral-only
  item. You can also upload the Referral Fee Preview as its own separate file.
  Rows with a **referral fee but no fulfillment fee** (merchant-fulfilled
  listings) are now kept too — they get a real referral rate instead of the 15%
  default.
  **These two fees are the authoritative per-unit economics and beat the
  Transactions ledger**: the ledger's FBA average smears fee changes and
  multi-unit orders across a period, and its referral % is refund/promo-netted,
  while the report gives the current base fee and the **marginal** referral rate
  (`referral fee per unit ÷ average selling price`) that an incremental ad sale
  actually pays. SKUs with no sales yet get fees for the first time.
  **ASIN matching uses the child (or standalone) ASIN only** — the Selling
  economics export carries both `Parent ASIN` and `ASIN` and usually leaves
  `MSKU` empty, so rows key off the `ASIN` column and reach a catalog SKU through
  the catalog's SKU → ASIN map; a parent ASIN is not a purchasable unit and never
  receives a fee. Rows quoting no fee (zero-sales ASINs, most of the export) are
  skipped. Uploads MERGE by SKU/ASIN (store-level `_fba.json`, shared by every
  audit/cadence, deleted with the store). The table gains a **Total Fees**
  column — `base fulfillment fee per unit + referral fee per unit`, summed
  straight from the report and shown with its two parts (bright = from the
  report, muted = derived from the ledger / referral %, `—` = no fee data, so
  that product's break-even is optimistic). **That total is what break-even
  charges** as the Amazon fee, so profit/unit = `price − COGS − Total Fees`.
  The report quotes its total at ITS price, so when a listing sells at a
  different price the fulfillment fee stays fixed and the **referral is
  re-priced at the report's rate** — a fixed $ referral would be wrong at any
  other price. The cell tooltip says which applied: *from the fee report* (exact
  total), *report fees, referral re-priced*, or *derived* (no fee report for
  that item). The detail
  view adds **Total Fees / Unit**, **Fulfillment / Unit** and **Referral / Unit** stats.
  The header shows coverage (`N SKU fees · N ASINs`) with a ✕ to clear.
  Endpoints: `POST /catalog/fba-fees/upload`, `GET /catalog/fba-fees`,
  `DELETE /catalog/fba-fees`.
- The resulting **break-even ACoS**
  (`(price − COGS − Total Fees) ÷ price`, uploaded benchmark wins) surfaces on
  the **Product Ads tab** (per-product BE ACoS column) and **feeds the PPC
  Audit**: every catalog ASIN enters the audit's break-even map, so BLEEDING
  flags and BidOptimizer break-even caps benchmark each product's ads and
  campaigns against its real unit economics — no separate benchmark upload
  needed. Endpoint: `PUT /catalog/cogs` (`{sku, value}`). Stats row also adds
  **Advertised** (catalog products found in Product Ads), **Avg ACoS** (Σ ad spend ÷ Σ ad revenue
  across the advertised products' campaigns), **Campaigns**
  (account-wide distinct campaigns) and **Over / Under Break-Even** counts.
  The detail view gains a **PPC · Product Ads & Break-Even** block: campaigns /
  ad spend / PPC sales / ACoS stats, Break-Even ACoS + ROAS, profit & Amazon
  fee per unit, a profitable-or-bleeding verdict, and the ASIN's full
  per-campaign table (spend, sales, ACoS colored against break-even). No
  Product Ads upload in the selected audit → break-even still computes; the
  campaign columns show "—" with a hint to upload the bulk in Product Ads.
- **Export Report** (yellow button in the header) — a client-ready workbook with
  **native Excel charts**: an *Overview* sheet (catalog stats incl. listing
  issues / advertised / break-even counts, a **catalog-composition pie** and a
  **listing-issues-by-area bar**) and a *Products* sheet — one row per product
  with prices, content counts, SEO issue count, the per-unit economics
  (**COGS / Referral / Fulfillment / Profit** per unit) and the Product Ads /
  break-even join (campaigns, ad spend/sales, ACoS vs BE, verdict), sorted by
  ad spend, plus a **top-15 ad-spend bar** (or a most-issues bar when no
  Product Ads data). Endpoint: `GET /catalog/export`.
- Endpoints: `POST /catalog/upload`, `GET /catalog`, `GET /catalog/item?sku=`,
  `GET /catalog/export`, `DELETE /catalog`.
### Transactions (SKU ledger)
Own sidebar tab, grouped with Product Benchmark under **Product Base** — the
two store-level "product truth" features (what you sell + what it actually
earns). A **store-level transaction ledger** built from the **Payments Date
Range report** (Seller Central → Payments → Reports Repository → *Date Range
report*, transaction view, `.csv`/`.xlsx`). Filter by date to see SKU-level
orders, refunds, fees and net proceeds.

- Upload with the yellow **Upload
  Transaction Report** button; reports **merge** — each row is matched by its
  transaction identity (posted time + settlement + type + order + SKU): new
  transactions append, a **known transaction whose data changed re-uploads in
  place** (status flip Deferred → Released, fee corrections — the newest upload
  wins, never double-counted), identical rows skip. So monthly exports
  accumulate into one continuous ledger — upload May, then June, and the date
  filter slices across both (the header lists the uploaded files; **Clear**
  wipes the ledger for this store only, confirm dialog).
- **Filter by date**: two date pickers (bounded to the ledger's span) narrow
  everything below — stats, per-SKU rollup and the transaction list; **All
  dates** resets. The caption shows the ledger's full range and how many
  transactions the current window covers.
- **Stats row** for the selected window: Orders, Refunds (red), Units,
  Product Sales, Promos, Selling Fees, FBA Fees and **Net Proceeds** (green /
  red). Account-level rows that carry no SKU (bank **Transfers**, Service
  Fees, Shipping Services, FBA Inventory Fees) are kept but reported in a
  separate note line — they never pollute the SKU totals.
- **By SKU** table: one row per SKU in the window — orders, refunds, units
  (refund quantities subtract), product sales, promos, selling / FBA / other
  fees and **net proceeds** (Σ of the report's `total` column). **Click a
  SKU** to drill the transaction list below down to just that SKU (click
  again or "show all SKUs" to clear).
- **Transactions** table: every SKU-level row in the window — date, type
  (Order green / Refund red), order ID, SKU, quantity, ship-to city/state,
  product sales, promos, fees, signed total and settlement status —
  searchable and sortable like every other table.
- Parsing is tolerant: the quoted definition preamble is skipped
  automatically, columns are matched loosely by header name, `$`/commas are
  stripped, and dates like `Jun 1, 2026 5:43:55 AM PDT` are read from any
  marketplace's wording.
- **Export Report** (yellow button in the section header) — a client-ready
  workbook with **native Excel charts**, scoped to the **selected date
  window**: *Overview* (KPI list incl. account-level other/transfers, a
  **net-proceeds-by-SKU bar** and a **deductions pie** — selling / FBA /
  promo / other), *Daily Trend* (per-day orders/refunds/units/sales/net +
  a **product-sales-vs-net-proceeds line**), *By SKU* (the full rollup) and
  *Transactions* (every SKU-level row in the window). Endpoint:
  `GET /catalog/transactions/export?start=&end=`.
- Endpoints: `POST /catalog/transactions/upload`,
  `GET /catalog/transactions?start=&end=&sku=`, `DELETE /catalog/transactions`,
  `GET /catalog/transactions/export`.

### Change Log
Audit trail of every action written to a bulk export (bid changes, pauses,
negates, harvested keywords, placement %). Each row: when · source · action ·
entity · field · old → new · reason. Filter by source. Header follows the
app-wide pattern: `change log · audit trail · N` count, source-filter tags, and
the action buttons — yellow **Export .xlsx** primary, ghost **Report message**,
and a ghost **Clear** (danger-confirmed, `DELETE /changelog`) that permanently
wipes the log for this audit — **scoped to the active source filter** (ALL
selected = everything; Harvest selected = just harvest entries). Export first
if you need the record. Also cleared on flush.

Two client-report exports (respect the active source filter):
- **⬇ Export .xlsx** — downloads `ppc_change_log.xlsx`: a *Summary* sheet (change
  counts per action) + a *Change Log* sheet (the full trail). Attach to a client
  email.
- **✉ Report message** — generates a plain-text, copy-paste summary ("PPC
  Optimization Report — *date*", totals per action, then what we did grouped by
  engine). **⧉ copy** puts it on the clipboard; paste straight into chat/email.

### Machine Learning in the cadences
Every Audit Cadence (Weekly, Mid-Month, Full Month, Pause/Scale, Daily Watch) now runs a
small set of **NumPy-only, hand-rolled models** on top of the rule-based bid/harvest/
pause math — fit fresh at plan time on that cadence's own uploaded data, nothing
persisted, nothing sent anywhere. **Advisory only**: exported bulk files are unchanged —
the rule engine and its guardrails still decide bids and actions. Look for an **ML
Insights** card (✨) above each cadence's tables, and two extra columns — **Smoothed
CVR** and **ML Confidence** — on the bid/harvest/pause/scale tables themselves.

- **Empirical-Bayes CVR shrinkage.** The core problem with thin PPC data: a search term
  with 0 orders on 3 clicks does **not** have a 0% conversion rate — there just isn't
  enough evidence yet. Each cadence fits a Beta prior to the account's own
  (orders, clicks) pairs across every target, then blends each target's raw rate toward
  that account average, weighted by how much data the target has. Shown as **Smoothed
  CVR** (hover for the 90% credible interval) next to the raw ACoS/orders columns —
  low-click targets pull toward the account average, high-click targets barely move.
- **ML Confidence.** For every negate / bleeder / pause (loser) and promote / scale
  (winner) row, a calibrated probability — "how sure is this decision, given the
  account's own conversion-rate distribution and clicks seen" — colored green (≥90%),
  amber (70–89%), red (<70%). A 0-order term with 8 clicks and one with 80 clicks can
  both trigger the same rule; confidence tells them apart. Computed against an
  account-wide **break-even CVR** (shown in the ML Insights card) derived from average
  CPC/AOV at the goal ACoS.
- **Weekly forecast** (Weekly only, needs 3+ uploaded weeks). Holt double-exponential
  smoothing over the account's week-over-week spend/sales/ACoS series projects next
  week's numbers with an 80% interval — a first read on where the account is headed
  before you even upload next week's bulk.
- **Early Promote Candidates** (Full Month only). A logistic regression trained on the
  cadence's own aggregated search terms (features: clicks, CTR, term length, match type
  — never spend/orders, so it can't leak the label) scores terms still **below** the
  harvest order threshold by P(convert), surfacing the ones worth watching before they
  have enough orders to promote on rules alone. Gated on model quality (AUC ≥ 0.62) and
  minimum data (30+ terms, 5+ in each class) — silently absent otherwise.
- **Anomaly Scan** (Daily Watch). Robust (median/MAD, not mean/stddev — one real spike
  can't hide itself by inflating the scale) z-scores over the accumulated day series per
  KPI (spend, sales, orders, clicks, ACoS), direction-aware (a sales *drop* or spend
  *spike* is flagged "bad", the reverse "good"). Catches slow drifts and multi-day
  outliers the pairwise Yesterday/Today compare can miss. Needs 5+ uploaded days.
  Endpoint: `GET /daily-watch/anomalies`.
- **Every model degrades silently.** Too few targets/weeks/days/terms, no conversions at
  all, or a model that can't beat chance → that section just doesn't render (no "not
  enough data" placeholders). Small or new accounts see the plain rule-based tables
  exactly as before.
- All in `backend/app/pipeline/ml.py` (pure functions, no I/O, no RNG — same plan run
  twice gives the same numbers). Wired into `weekly.plan`, `midmonth.plan`,
  `fullmonth.plan`, `pausescale.plan` (`ml.enrich_plan`) and `dailywatch.anomalies`.
  Frontend: `components/MLInsights.jsx` (the card) + `mlCols`/`withML()` in
  `components/cadenceCols.jsx` (the table columns).

### Reports
One-screen exec report: **account health** verdict from flags, headline
KPIs (ad spend / ad sales / ACoS / **Avg Product ACoS** — Σ ad spend ÷ Σ ad
revenue across the per-product campaign rollups, colored against the Goal — /
**over break-even** — how many targets run above their product's break-even
ACoS, i.e. the BLEEDING count, red when non-zero), period delta, an **account
states** card — the Strategy methodology classifier's five state counts
(below / at / above target · over break-even · no data, colored) plus the
**top-10 spenders classified** (state badge · spend · ACoS/BE · lever · why) —
then the **action checklist as a table** (count · action · what it means · which tool runs it, sorted biggest
first), a **top movers table** (campaign spend/sales/orders/ACoS deltas vs the
previous snapshot — shown when history exists), and an **SEO · listing quality
& keyword coverage** section — how many catalog products carry high/medium listing issues (with a
per-area breakdown: search terms / images / bullets / description / title), the
**five worst offenders**, and one line per Product Optimization project with
keywords tracked, high/medium recommendation counts, a red **over-249-byte
backend field** badge when applicable, and the top keywords to work into the
copy. Sourced live from the Product Benchmark catalog (store-level) + the
tracker projects (base db) — sections hide when there's no catalog / no
projects. **⬇ Excel report** downloads a client-ready workbook with **native Excel
charts**: *Summary* (health verdict, KPI block incl. **targets over
break-even**, flag-breakdown table + **"Open flags by type" bar chart**, action
checklist + **Actions pie**), *Flags* (the full styled flag table — now with a
per-row **BE ACoS** column from the product's benchmark/catalog unit
economics), *Account states* (state counts + **campaigns-by-state pie** + every
campaign's classification: state, spend, ACoS/BE, goal, lever, why), *Top movers* (campaign deltas + **spend-Δ bar
chart**, when snapshot history exists) and *SEO* (**"Listing issues by area"
bar chart**, worst offenders, per-project keyword recs). Charts are real
Excel charts — editable in Excel/Sheets.

---

## 5. File formats (what to upload where)

| File | Where | Needs columns |
|---|---|---|
| **SP bulk** | PPC Optimization | Amazon "Sponsored Products Campaigns" sheet (standard export); optional "SP Search Term Report" sheet auto-harvested |
| **SP bulk (with STR sheet)** | Search-Term Harvest (preferred) / N-gram | "SP Search Term Report" sheet: Customer Search Term + Campaign/Ad Group/Keyword/PT **IDs** — harvest's output bulk acts by exact ID |
| **Search Term Report** | Harvest (fallback) / N-gram | Customer Search Term, Campaign Name, Ad Group Name, Clicks, Spend, Sales, Orders — maps by name |
| **Business Report** | Monitoring | ASIN + Ordered Product Sales (+ Units, Sessions, Page Views) |
| **Product Benchmark** | Uploads | ASIN + Break-even ACoS *or* ROAS (optional Sale Price, Target ACoS) |
| **Category Listings Report** | Product Benchmark tab | Seller Central export as-is (`Template` sheet with attribute-key row); one file per category, uploads merge by SKU |
| **Selling economics** | Product Benchmark tab | Seller Central → Reports → Business → Selling economics as-is (`.csv`/`.xlsx`): ASIN (+ Parent ASIN, MSKU) + `Base fulfillment fee per unit` + `Referral fee per unit` + `Average sales price` |
| **FBA Fee Preview** | Product Benchmark tab | Alternative to the above — Reports → Fulfilment → Fee Preview as-is (`.csv`/`.txt`/`.xlsx`): SKU + base fulfillment fee per unit |

All uploads accept **`.xlsx` / `.xlsm` / `.csv`** (CSV = single sheet). Parsers are
tolerant: `%` and `$` are stripped, 7/14-day attribution column drift handled, ROAS
auto-converted to ACoS, multi-sheet workbooks auto-pick the right sheet (e.g. the
benchmark workbook's `Product Data` tab).

**Download the exact format:** each uploader has a `⬇ template` link serving the
reference file from `preferred_templates/` (`GET /templates/{bulk|business|str|benchmark|fee_preview}`).
All four real Amazon exports there are verified to parse end-to-end.

---

## 6. Flags & the bid ladder

| Flag | Meaning | Action |
|---|---|---|
| **BLEEDING** | ACoS above the product's break-even — losing money per sale | Cut hard / pause |
| **HIGH_ACOS** | Over Goal ACoS | Bid ladder (below) |
| **SCALE ▲** | Under goal with real orders — headroom | Raise bid |
| **WASTED** | Spend, zero orders | Pause + negate |
| **OVERBID** | Bid ≫ actual CPC | Lower toward CPC |
| **LOW_CVR** | Low conversion | Listing/price issue, not bids |
| **LOW_CTR** | Low click-through | Relevance/image issue |

**Bid ladder (entities with sales, over goal):** uses snapshot history.
`REDUCE` (cut bid) → `MONITOR` (already cut, watch) → `PAUSE` (persistent loser).
On a single upload it falls back to severity (cut once, never pause on one bad
period). A per-ASIN **Goal ACoS** from the Benchmark file overrides the global goal.

---

## 7. Formulas

```
Ad spend     = Σ Spend of Entity=campaign rows (each campaign once; the per-ASIN
               rollup double-counts campaigns that run multiple ASINs)
ACoS         = ad spend / ad sales
ROAS         = 1 / ACoS
Break-even ACoS = (price − COGS − Total Fees) / price
               (Total Fees = base fulfillment fee per unit + referral fee per unit
               from the Selling economics report; without that upload the fee falls
               back to price · referral % + the ledger's FBA $/unit, and COGS to a
               default % of price)
```

---

## 8. Exports

- **Audit bulk file** (PPC Optimization) — selected flags → Amazon SP bulk update sheet.
- **Bid Optimizer bulk** — chosen optimal bids → bid-update sheet.
- **Placement bulk** — chosen placement % → Bidding-Adjustment sheet.
- **Harvest bulk file** — chosen search terms → keyword/negative create sheet.
- **Excel report** (Reports) — 3-sheet exec workbook (Summary, Flags, Top movers).

All exports are `.xlsx` you re-upload to Amazon manually (no Ads API).

---

## 9. Multi-store / multi-audit

Each store + audit is a fully isolated database file under
`backend/data/stores/<store>/<audit>.db`. Titles live in `_meta.json`. Deleting a
store/audit = delete its dir/file. Switching is instant; data never leaks across.

**Flush an audit** — the **Flush Current** button on the Stores tab's audits
table wipes ALL data in the active audit (bulk, benchmark, placements) after a confirm. The
audit and its Goal ACoS are kept; other audits are untouched. (`POST /flush`.)

**Delete** (Stores tab header buttons):
- **Store** — **Delete Current** (stores table header) deletes the store **and every audit
  + the store benchmark** under it (`DELETE /stores/{store}`). Blocked on the last
  store.
- **Audit** — **Delete Current** (audits table header) deletes just that audit's schema/db
  (`DELETE /projects/{project}`). Blocked on the last audit in a store (flush
  instead). Both confirm first and cannot be undone.

---

## 10. Optional local LLM

The Narrate panel works without any LLM (returns a notice). To enable, set env:
`LLM_PROVIDER` (ollama | lmstudio | openai_compat), `LLM_MODEL`, `LLM_BASE_URL`.
All bid math stays deterministic — the LLM only writes summaries.

---

## 11. Troubleshooting

- **Harvest finds nothing** → the STR's campaign/ad-group names must match the
  loaded bulk; loosen the Goal ACoS.
- **No PAUSE in the ladder** → needs ≥3 snapshots (uploads on different dates).

---

## Changelog

- **2026-07-26 · Windows file-handle fixes (uploads)** — workbook readers now close their
  file handle explicitly (`with pd.ExcelFile(...)`) in the Search Term Report, Product
  Benchmark, keyword-research, and sheet-name paths. On Windows a file that's still open
  can't be deleted, so when you uploaded a file the parser rejected, cleaning up the
  temporary copy failed and the clear "couldn't read that file" message was replaced by a
  server error. You now get the real message. The main bulk upload (`POST /upload`) also
  deletes its temporary copy when it finishes — previously every bulk upload left a full
  copy of the workbook behind in the system temp folder. No change to what you upload or
  to results; Linux/Mac behavior is unchanged.

- **2026-07-25 · Windows 11 compatibility** — store-level JSON files (benchmark,
  catalog, COGS, FBA fees, transactions, audit meta) are now read and written with an
  explicit `utf-8` encoding (`ensure_ascii=False` on writes). Fixes garbled text /
  `UnicodeEncodeError` on Windows, whose default text encoding (cp1252) mangled non-Latin
  product names, keywords, and symbols (é, ™, emoji, CJK); Linux/Mac hid it by defaulting
  to UTF-8. No behavior change on existing platforms. Setup note: on Windows activate the
  backend venv with `.venv\Scripts\activate` (not `source .venv/bin/activate`). Added
  `backend/run.bat` + `backend/run.ps1` (Windows mirrors of `run.sh` — seed once, then serve with reload) and
  a repo `.gitattributes` that pins text files to LF so a Windows checkout can't rewrite the
  bash `run.sh` shebang to CRLF (which would break it on Linux).

- **2026-07-24 · Faster bulk file reads (calamine engine)** — every `.xlsx/.xlsm` upload
  now parses through the Rust-based **calamine** reader (~8x faster than the old openpyxl
  path — a 120k-row Sponsored Products bulk drops from ~21s to ~2.5s; full ingest ~3.4s),
  with identical output so 16-18-digit IDs stay exact. Optional dependency: the app falls
  back to openpyxl automatically if `python-calamine` isn't installed (`pip install -r
  requirements.txt` to get it). Uploads that hand one file to several engines (audit +
  harvest + waterfall + cannibalization) benefit most. No change to what you upload.
- **2026-07-24 · Waterfall per-slot bids + new-campaign bidding strategy** — Settings now
  has a **per-slot default bid** grid (AT $0.30 · BROAD/PHRASE/EXACT $0.50 · PT $0.40) that
  drives each new campaign's ad group default bid + the `{bid}` name placeholder, and a
  **new-campaign bidding strategy** dropdown (down only / up and down / fixed) feeding the
  `{strategy}` placeholder. AT split-target bids now scale off the AT slot bid (defaults
  reproduce the old 1.00 / 0.75 / 0.75 / 0.50). `slot_bids` + `new_strategy` in DEFAULTS.
- **2026-07-24 · Waterfall ASIN×slot grid + boss override** — the plan now renders as a
  grid (rows = SKU, columns = the 5 funnel slots), each cell color-coded by
  competing-campaign count (green 1 / amber several / grey create). Clicking a
  multi-candidate cell opens a panel listing every competitor with orders/sales/ACoS and
  a radio to override the auto-elected boss; `POST /waterfall/override` rebuilds the plan
  from the raw bulk (saved on upload, cleared on Clear) — no re-upload needed. Boss map
  rows now carry full candidate metrics; `select_bosses(..., forced=)` honors overrides.
- **2026-07-24 · Waterfall: naming placeholders, strategy flip, pause protection** —
  `render_name` gained `{n}` (slot number), `{bid}` (boss ad group default bid),
  `{strategy}` (`down`/`up/down`, read from the actual bidding strategy in the data);
  new **force down-only** setting flips a boss's strategy to `down only` on rename when
  it's currently `up and down`; new **protect min orders** guards EMPTY campaigns with
  real orders from Phase D's auto-pause (flagged for manual review instead — losers still
  pause on schedule since sales continue under the boss); new **protected campaign IDs**
  setting excludes explicit IDs from Phase B and D entirely; seed-keyword bid clamp
  (`bid_floor`/`bid_ceiling`) is now configurable instead of hardcoded $0.30–$2.00. New
  **Pause wave — revenue at risk** card surfaces every Phase D pause candidate that still
  has orders, plus protected-empty campaigns, so nothing gets buried.
- **2026-07-23 · Machine learning across all Audit Cadences** — new
  `pipeline/ml.py` (NumPy-only, no new deps): empirical-Bayes CVR shrinkage +
  calibrated negate/promote/pause/scale confidence (all four cadences),
  Holt-forecast next week's spend/sales/ACoS (Weekly), a conversion-propensity
  logistic regression surfacing Early Promote Candidates (Full Month), and a
  robust median/MAD anomaly scan over the accumulated day series (Daily Watch,
  `GET /daily-watch/anomalies`). Advisory only — bulk exports unchanged. New
  **Smoothed CVR** / **ML Confidence** columns on the bid/harvest/pause/scale
  tables + an **ML Insights** card per cadence; every model degrades silently
  on small accounts. See "Machine Learning in the cadences" above.
- **2026-07-23 · Product Benchmark stat cards are clickable filters** — the
  catalog tab's stat boxes (Variation Families, Child Variations, Standalone,
  Priced, Missing Image/Description, Listing Issues, Advertised, Over/Under
  Break-Even) now filter the product table to the exact rows they count; active
  card highlights, a chip above the table shows the filter + matched count with
  ✕ to clear. Aggregate cards (Brands, Avg ACoS, Campaigns) stay static.
- **2026-07-23 · Base fulfillment + referral fee per unit feed the Product
  Benchmark** — new **Upload Selling Economics** button on the Product Benchmark
  tab ingests Seller Central's **Selling economics (SKU Economics)** report — or
  an **FBA Fee Preview** — into a store-level `_fba.json`, merged by SKU/ASIN.
  Columns are matched loosely (`Base fulfillment fee per unit`,
  `expected-domestic-fulfilment-fee-per-unit`, the older pick-pack +
  weight-handling pair, British/American spellings), and per-unit columns are
  never confused with their quantity/total twins. Both fees **beat the
  Transactions ledger** — the base fee is the current published one, and the
  referral rate is the marginal `fee per unit ÷ average price` (the ledger's is
  refund/promo-netted) — so break-even ACoS and profit/unit stop pricing
  fulfillment at $0 and stop under-charging referral. Fees map onto **child /
  standalone ASINs only**, never a `Parent ASIN`, and reach catalog SKUs through
  the catalog's SKU → ASIN map (the Selling economics export leaves MSKU empty).
  A **Referral Fee Preview** sheet inside the same workbook (or uploaded on its
  own) overrides the referral fee of each matching item — by SKU, else ASIN —
  and Total Fees is recomputed; percentage-only preview rows are priced off the
  item's selling price. Rows with a referral fee but no fulfillment fee
  (merchant-fulfilled) are kept as referral-only items.
  New **Total Fees** column (`base fulfillment + referral` per unit, summed from
  the report and charged as the exact $ Amazon fee in break-even) plus
  **Total Fees / Fulfillment / Referral per unit** detail stats; the exported
  workbook gains COGS / fulfillment / referral / total-fees / profit per-unit
  columns. The uploaded-benchmark path
  (`GET /benchmark`, `break_even_map`) uses these real fees too. Endpoints:
  `POST /catalog/fba-fees/upload`, `GET /catalog/fba-fees`,
  `DELETE /catalog/fba-fees`.
- **2026-07-22 · PPC Audit setup panels moved into a slide-in drawer** — the
  right sidebar (Audit setup checklist · Goal ACoS/ROAS · AI narration · Flag
  legend) is now an e-commerce-cart-style **overlay drawer** sliding in from
  the right, opened by a floating **Audit Setup** button and closed by ×, Esc,
  or the backdrop. Its open state persists across page refreshes. The audit
  tables/panels take the full page width.
- **2026-07-22 · Stores tab redesigned as Google-Drive-style tiles** — the
  stores and audits tables are replaced with a two-level tile grid: store tiles
  (name + spend/ACoS/flags mini-stats) drill into audit tiles on click, with a
  `Stores › <store>` breadcrumb back. Each **audit tile shows a month badge**
  (month of its latest uploaded snapshot — `GET /projects` now returns a
  `snapshot` date per audit) so you can see at a glance which month an audit
  covers. Per-tile ⋮ menus replace the header-wide Delete/Flush "Current"
  buttons and act on the clicked tile (delete any store, flush/delete any
  audit — not just the current one).
- **2026-07-21 · FamiliaOps storefront is now the root page** — visiting `/`
  shows the FamiliaOps landing (the store front); the console's login screen
  moved to `/login`, and the storefront's **Log In / Client login** links point
  there. Console URLs (`/<store>/<tab>`) are untouched, and after login the
  app returns you to your store's URL as before.
- **2026-07-21 · FamiliaOps agency page at `/familiaops`** — the provided
  FamiliaOps landing (services, stats, process, team, results, FAQ, booking
  CTA) converted verbatim to React as its own standalone public route. Its
  styles are scoped and code-split, so they never load inside the console app;
  the PPC-tool landing stays separate at `/landing.html`.
- **2026-07-21 · URL always names your real store** — the address bar no longer
  shows a placeholder store (e.g. `/zvalves/dashboard`) while the app is still
  loading; the URL is only written after your store list is validated, so it
  always reads `/<your-store>/<tab>[/<cadence>]`.
- **2026-07-21 · Marketing landing page** — new static page at `/landing.html`
  (Binance-style dark canvas, yellow accent, same Inter/JetBrains Mono type as
  the app): hero with the 7-tier structure ladder, stats strip, toolkit bento
  (cadences, Tier Recommendations, Waterfall, Cannibalization, Profit P&L,
  Monitoring, SEO), upload→review→export flow and a local-first closer. The
  only live links are the **Log in** buttons (they open the app's login page);
  everything else is presentation-only.
- **2026-07-22 · Per-keyword copy button** — every keyword in the mined table
  (All and Recommend views) has a clipboard icon beside it: one click copies
  the keyword text, with a confirmation toast.
- **2026-07-22 · Current listing vs forecast demand totals** — the forecast card
  gains a **current listing vs forecast · demand** block: for Search volume,
  BA impressions, BA purchases, STR impressions and STR orders it shows the
  total the CURRENT copy already covers → the projected total with your
  selected keywords added (`100 → 400 +300` style, green delta). Selected
  keywords the copy already covers add 0 (no double counting); no current copy
  pasted → current shows 0 with a hint.
- **2026-07-22 · Source filters on the mined table** — the header counts
  (`SQP 100 · Cerebro 2437 · STR 195 · multi N`) are now clickable filters:
  see exactly which keywords exist in SQP, Cerebro, STR, or in 2+ sources at
  once (**multi**). SQP rows were never missing — they just sort deep because
  Cerebro volumes dominate the volume sort; a keyword found in several sources
  shows every source tag on its row.
- **2026-07-21 · Backend search terms from harvest performance** — the backend
  Search Terms recommendation gains a basis toggle: **search volume** (research
  demand, as before) or **harvest performance** — Search-Term-Report keywords
  first, ordered by PPC proof (orders, then impressions): customers already
  bought through these terms. Same rules either way (words not in your visible
  copy, deduped, ~250-byte cap). Needs a harvest upload for the harvest basis.
- **2026-07-21 · "In listing" forecast tile (proposed-copy uplift)** — the
  forecast SEO scorecard gains a sixth tile: how many of the selected mined
  keywords the CURRENT copy covers → how many the PROPOSED title / bullets /
  description would cover. **No proposed copy pasted = 0** with a hint to add
  it in the SEO tab; with proposed copy, the green delta is the listing-indexed
  gain of your rewrite.
- **2026-07-21 · Visual keyword report + backend Search Terms recommendation** —
  with a project selected, a **keyword report · visual** card renders two
  charts (Chart.js, colorblind-validated palette): an **indexed-status
  distribution** stacked bar (ranked green · in-listing yellow · not-indexed
  blue, with counts) and **top 10 keywords by search volume** colored by their
  indexed status — un-indexed high-volume keywords stand out instantly. Below,
  a **backend Search Terms recommendation**: the highest-volume pool keywords'
  words that are NOT already in your visible copy, deduped and capped to
  Amazon's ~250-byte field, with byte counter and one-click **Copy** for
  Seller Central → Keywords → Search Terms. Endpoint:
  `GET /keywords/backend-terms?project_id=`.
- **2026-07-21 · One Export report for the whole Keywords tab** — the project
  bar gains **Export report**: one `ppc_keywords_report.xlsx` covering
  everything on the tab — **Summary** sheet (project, forecast current →
  projected, mined-pool scorecard, impression share, n-gram summary), plus
  **Mined Keywords**, **Recommendations**, **Harvest** and **N-Grams** sheets
  (whatever is loaded; empty sections are skipped). The N-gram panel's own
  export stays for gram-only reports.
- **2026-07-21 · N-gram: keywords only, selectable grams, summary + export** —
  ASIN-pattern search terms are excluded before mining (never pollute the word
  stats; a note counts them). A **run summary** strip shows Terms · Impressions
  · Clicks · Spend · Sales · ACoS · Winners · Wasters. Gram rows gain
  **checkboxes** (select-all respects the active filter): **selected to
  keyword project (N)** pushes exactly the ticked grams, and **Export report**
  downloads a two-sheet .xlsx (Summary + N-Grams) — selected grams only when
  any are ticked, else all.
- **2026-07-21 · N-gram scoped to the project's ASINs too** — like the harvest,
  the N-gram miner now keeps only Search-Term-Report rows from ad groups
  advertising the keyword project's ASIN(s) (matched via the bulk's Product Ad
  rows); a note above the table shows the ASIN(s) and how many rows from other
  ASINs were hidden. A standalone STR can't be mapped (no Product Ad rows) —
  the note says so and shows all rows.
- **2026-07-21 · One upload powers Harvest + N-gram** — uploading a bulk (or
  standalone STR) in the Search-Term Harvest now automatically runs the
  **N-gram word miner** on the same file: the harvest computes, the STR terms
  merge into the mined pool, and the n-gram table below fills — one file, all
  three. The N-gram panel's own upload button is gone: it's fed exclusively by
  the harvest upload (an empty state points there until a file is uploaded).
- **2026-07-21 · Impression Share, STR as a third keyword source, selection-only
  forecast** — uploading a bulk in the search-term harvest now also **merges its
  keyword terms into the mined pool** as a third source (**STR** tag, with the
  report's impressions/clicks/orders; same keyword-only + project-ASIN scoping
  as the harvest table). The forecast SEO scorecard adds **Impression Share**
  for keywords found in BOTH the research and the harvest: `STR impressions ÷
  total search volume × 100` (STR-only keywords without volume data are counted
  but excluded from the share). The mined-pool scorecard adds a **Not indexed**
  tile (neither ranked nor covered by the current copy — your growth
  candidates). The forecast card is **always visible** once a project + pool
  exist: with nothing ticked both sides show the current scorecard (forecast =
  current, "tick rows below to forecast"), while the **mined-pool scorecard and
  Impression Share keep showing whole-pool insight** (labeled "whole pool");
  every tick recomputes everything over the selection (labeled "N selected" /
  "selection"). The Recommend view has the same checkboxes as All (one shared
  selection).
- **2026-07-21 · Select keywords, then compute** — the mined-keywords table
  gains checkboxes (per row + select-all over the current filter). **Sending
  requires an explicit selection**: with nothing ticked the button is disabled
  ("Select keywords to send") — nothing is ever pushed by default. With
  keywords ticked, the **SEO scorecard preview**, the **mined-pool scorecard**
  and **Send N selected to project** all compute over the selection only;
  unticked, the preview shows the whole pool (clearly labeled "whole pool,
  nothing selected yet") as read-only insight. Select-all respects the active
  search/filter, so "filter to un-indexed → select all → preview → send" is
  one flow.
- **2026-07-21 · Per-keyword Indexed column in the mined table** — with a
  keyword project selected, the mined-keywords table gains an **Indexed**
  column next to Sources: **indexed · ranked** (green — a Cerebro organic rank
  exists for the ASIN, definitely indexed), **indexed · listing** (lime —
  every word of the keyword appears in the project's CURRENT listing copy),
  or "—" (not indexed yet — a growth candidate). Sortable and searchable, so
  one click surfaces every un-indexed keyword from Brand Analytics / Cerebro /
  harvest for the ASIN.
- **2026-07-21 · Mined-pool scorecard: is your research already indexed?** — the
  SEO scorecard preview gains a second block, **mined pool · already indexed
  for this ASIN**: of all Brand Analytics + Cerebro keywords in the pool, the
  share already ranked for the project's ASIN (Indexed %, e.g. 31/124 ranked =
  25.0%), Page 1 / Top 10 counts, avg rank, plus **In listing** — how many of
  the pool's keywords are fully covered by your CURRENT listing copy (all
  words present in title/bullets/description/backend). A by-source line splits
  SQP vs Cerebro indexed rates and shows today's SEO scorecard % next to them.
- **2026-07-21 · SEO scorecard preview in the Keywords tab (what-if)** — with a
  project selected and a mined pool loaded, a **SEO scorecard preview** card
  compares the CURRENT primary-ASIN scorecard against the PROJECTED one **if
  you add these keywords**: Indexed % · Page 1 · Top 10 · Avg rank · Tracked,
  current → projected with colored deltas, before you press Send. Keywords
  carrying a Cerebro organic rank project into ranked / page-1 / top-10 (they
  land for real with your next Cerebro snapshot import); the rest only grow
  the tracked denominator. The pool line shows new vs already-tracked vs
  Cerebro-ranked counts. Endpoint: `GET /keywords/project-preview?project_id=`.
- **2026-07-21 · Delete keyword project from the Keywords tab** — the project
  bar gains a **delete** button (danger-confirmed): removes the selected
  Listing Optimizer project with all its tracked keywords, competitors, rank
  snapshots and listing copy (it disappears from SEO / Listing Audit / Product
  Overview too — shared project). Selection and the SEO-impact card reset.
- **2026-07-21 · Before/after SEO comparison on every keyword push** — sending
  keywords to a project now shows an **SEO impact** card in the Keywords tab:
  Indexed % · Page 1 · Top 10 · Avg rank · Tracked, before → after with colored
  deltas (harvest / n-gram pushes show the indexed delta in their toast). An
  indexed-% drop after a push is expected math, not data loss: new keywords
  start unranked, so the denominator (tracked) grows while ranked stays put.
  The card explains it and the way back up: place the new keywords in Title /
  Bullets / backend Search Terms (AI relevancy prompt), run them in PPC, then
  re-import a Cerebro rank snapshot to measure the gain.
- **2026-07-21 · Search-term harvest shows keywords only, scoped to the project's
  ASINs** — in the Keywords tab, ASIN-shaped customer search terms are hidden
  (this panel mines keywords), and when a keyword project is selected the
  harvest keeps only terms from ad groups that advertise the project's ASIN(s),
  matched via the bulk's Product Ad rows. The note above the table reports how
  many ASIN terms and other-ASIN terms were hidden.
- **2026-07-21 · Keywords tab wired into the Listing Optimizer projects** — the
  Keywords tab now carries the same **project** system as SEO / Listing Audit
  (pick or create a project + primary ASIN). One click sends the whole mined
  pool (Brand Analytics SQP + Cerebro) into the project's tracked keywords;
  the harvest table's selected search terms and the n-gram miner's winners
  push into the same project. From there the SEO tab computes the **indexed %**
  and the Listing Audit checks **Title / Bullets / Description / backend**
  usage for every keyword. New **Copy AI relevancy prompt** button builds a
  ready-to-paste LLM prompt comparing every tracked keyword against the
  CURRENT and PROPOSED listing copy (relevancy 1-5, placement, what's missing).
- **2026-07-21 · Keywords tab moved to Product Optimization** — the Keywords
  tab now lives in the **Product Optimization** sidebar group (with SEO,
  Listing Audit, Product Overview) instead of PPC Suite. Same tab, same URL.
- **2026-07-21 · Structure Redesign removed; Consultation tab is now Tier
  Recommendations** — the tier-based restructure tab (and its `/restructure/*`
  engine) is gone; the Consultation group keeps two tabs: **Tier
  Recommendations** (renamed from Consultation, same tool — URL slug
  `/tier-recommendations`, old links redirect) and **Waterfall**. Old
  `/structure-redesign` links land on Tier Recommendations.
- **2026-07-21 · No more phantom-store requests on load** — panels used to start
  fetching before the store list arrived, using a guessed store (stale
  localStorage or the legacy `zvalves` default). If you didn't own that store
  the requests 404'd — or silently re-created a deleted store server-side. The
  app now waits for your store list, validates the selection (falling back to
  your first store), and only then mounts the data panels.
- **2026-07-21 · Consultation tab + group rename** — the Structure Redesign nav
  group is now **Consultation**, and its first tab is the new **Consultation**
  tool: upload one SP bulk → it counts advertised ASINs, routes the account to
  one of seven structure tiers (1–5 Waterfall … 1000+ Capital Allocation) and
  scans the bulk with that tier's thresholds — wasted spend, high ACoS,
  underexposed winners, overbids, mixed ad groups (tier-dependent policy) and
  harvest candidates, each with a concrete resolution. Tier card shows the
  structure blueprint, optimization loop, cautions and automation mode.
- **2026-07-21 · Changing the Goal ACoS now recomputes cadence results** — the
  Weekly / Mid-Month / Full Month / Pause-Scale plan panels used to keep showing
  the plan computed at the old goal after you changed the Goal ACoS; they now
  refetch (bid suggestions, promotes, negatives, bleeders, scale/pause verdicts
  all recompute). The cadence tile's **audit** button also re-audits at the
  current goal instead of returning the stored month snapshot — flag counts
  update when you tighten or loosen the goal.
- **2026-07-21 · Bulk Upload tab removed** — the one-file-feeds-everything suite
  upload is gone (buggy, and it blurred the per-cadence isolation). Every panel
  keeps its own Upload button; each cadence's upload lands in that cadence's own
  database file and never touches another cadence. Old `/bulk-upload` links land
  on PPC Optimization. A new end-to-end test uploads a different file into every
  cadence and asserts each keeps exactly its own data, and that re-uploading one
  cadence changes nothing anywhere else.
- **2026-07-21 · Opening a cadence run no longer 500s under concurrent requests** —
  two simultaneous opens of the same month's run (e.g. the header and an audit
  tile firing together) could both try to create it and hit the
  `UNIQUE(year, month, audit_type)` constraint; the loser now returns the
  winner's row instead of crashing.
- **2026-07-21 · Cross-cadence isolation hardened + regression-tested** — an
  upload into one cadence can no longer surface anywhere in another cadence:
  lifted Harvest / N-gram / narration results now clear on every cadence
  switch (they came from one cadence's data), and a new end-to-end test suite
  (`test_cadence_isolation.py`) uploads into Full Month / Weekly over HTTP and
  asserts every other cadence's plan, flag audit, dashboard and upload-meta
  stay empty — including with a mismatched `?audit_type=` (background panels).
  Follow-up: an upload finishing in one cadence no longer reloads the generic
  optimizer views (flag table, Bid Optimizer, Placement, ASIN tree, Dashboard,
  Reports) while a **different** cadence is on screen — those views only refetch
  when the data that landed belongs to the cadence being viewed.
- **2026-07-21 · Cadence panels are now fully independent (keep-alive + async
  uploads)** — an upload or clear in one cadence no longer reloads the other
  cadences' panels: each visited cadence panel stays mounted in the background
  and only refetches on its **own** data change (or an audit flush / store
  switch, which still reloads everything). Switching cadence is instant — no
  loading skeleton — and an upload still processing in one cadence keeps
  running while you browse the others. Server-side, every cadence route
  (`/daily-watch/*`, `/weekly/*`, `/mid-month/*`, `/full-month/*`,
  `/pause-scale/*`) is now pinned to its own cadence db, so a background
  panel's requests can never read or write another cadence's data.
- **2026-07-21 · Per-cadence clear button on the cadence tiles** — every Audit Type
  tile in the PPC Optimization header grid now has a **clear** button next to
  **audit**: danger-confirmed wipe of that cadence's uploads (search-term/watch
  data + the bulk-derived optimizer panels it feeds). Targets that tile's own
  cadence data even when another cadence is open; other cadences untouched.
  Full Month clear also resets the Dashboard KPIs / flag table (base audit data).
- **2026-07-21 · PPC Audit tab renamed to PPC Optimization** — same tab, same
  features; URL slug is now `/ppc-optimization` (old `/ppc-audit` links still
  open it). Older changelog entries below keep the old name.
- **2026-07-21 · Structure Redesign nav group** — Structure Redesign and Waterfall
  moved out of the PPC Suite group into their own collapsible **Structure
  Redesign** sidebar group, at the same level as PPC Suite (both are account
  restructure engines, not audit-cadence tools). Tabs and URLs unchanged.
- **2026-07-20 · Account-level engines cadence-scoped** — Waterfall, Structure
  Redesign, Cannibalization and Channels are scoped per Audit Cadence like the
  cadence panels, so each cadence's upload builds its own independent set;
  existing runs live on unchanged under Full Month. (The one-file "Bulk Upload"
  tab introduced alongside this was removed on 2026-07-21 — every panel uploads
  its own bulk.)
- **2026-07-20 · Uploads are much faster** — the workbook used to be re-read by
  every engine (~20s per read on a real bulk) and dimensions were written one row
  at a time. Sheets are now parsed once and shared, and dimension rows are written
  in bulk: a full-account upload dropped from ~227s to ~91s. Every panel's own
  upload benefits from the shared parse cache.
- **2026-07-20 · Huge restructure plans no longer wedge the app** — a plan with
  six figures of items produced a multi-megabyte response that the browser could
  not render and the dev-server proxy could not deliver, leaving the request hung.
  Waterfall / Structure Redesign now send the first 500 rows per phase plus the
  true totals; exports still carry every row.
- **2026-07-20 · Daily Watch campaign monitor (isolated watchlist)** — anomaly
  flags and Top-movers rows in the Daily Watch compare now carry a **monitor**
  button. Monitored campaigns sit in their own "Monitored campaigns" card
  (watching-since, ACoS then vs latest, aligned/over-goal status) isolated from
  the rest of the panel. Each new day's upload re-evaluates the list: a watch
  whose day ACoS lands at/under the goal ACoS auto-clears (toast + "recently
  cleared" history); zero-sales days never clear. Own `WatchedCampaign` table in
  the Daily cadence db.
- **2026-07-20 · Phase-applied no longer flips pending bid-ledger rows** — in
  Waterfall and Structure Redesign, marking phase A (or C/D) applied used to
  mark the run's *entire* bid ledger applied, including phase B cuts you hadn't
  uploaded yet — so the next export could double-cut. Only marking **phase B**
  applied resolves the ledger now.
- **2026-07-20 · Structure Redesign tab (tier-based restructure)** — new PPC
  Suite tab: upload one SP bulk and the engine detects the current campaign
  structure (ASIN count, per-SKU slot coverage, duplicates, multi-SKU
  catch-alls, archetype: waterfall / SPAG / catch-alls / flat), routes the
  account to its strategy tier by ASIN count (1–5 Full Waterfall … 1000+
  Portfolio Machine, manual override in Settings), classes every SKU
  (hero = full waterfall · spag = 3-campaign SPAG · tail = grouped auto
  catch-alls) and builds the phased A–D migration bulks (renames → wind-down
  bid cuts → creates born paused with STR seeds + sculpting negatives →
  gated pauses). Account-level, own tables, ChangeLog + BidLedger wired.
- **2026-07-20 · Overbid reset guardrail** — grossly inflated bids (above the $5
  hard cap, or 3×+ the observed CPC with a $1+ gap) previously only crawled down
  by the $0.20 per-pass step cap — a $39.18 bid was "cut" to $38.98 and would
  have taken years to normalize. Such bids are now flagged **overbid** and reset
  straight to the computed, hard-capped target in a single pass, with the reason
  column spelling it out. Applies to Weekly / Mid-Month / Full-Month bid tweaks
  and the generic Bid Optimizer; Pause/Scale scale-ups are now hard-capped too
  (an already-overbid winner is never scaled higher), and harvested keywords are
  never born with a bid over the cap.
- **2026-07-20 · Tier Router on the Strategy tab** — the Strategy panel now
  opens with a Tier Router card that auto-suggests your campaign-architecture
  tier (7 tiers, 1–5 up to 1000+ ASINs) from the store's Product Catalog count
  (parents + standalone; falls back to advertised ASINs from the loaded bulk
  before a catalog exists). Shows the tier's structure, ACoS scheme, automation
  level, techniques, recommended Audit Cadences (click to jump) and the app
  engines that implement it, plus an expandable ladder of all 7 tiers.
- **2026-07-19 · Fix "database is locked" errors during uploads** — while a big
  bulk upload (e.g. Full Month) was writing, other panels reading the same audit
  could fail with *database is locked* (Dashboard, plans, checklist toggles), and
  the upload itself could die the same way. All audit databases now run in
  SQLite WAL mode: readers and the writer no longer block each other, so panels
  stay live during uploads. Applies automatically — no action needed.
- **2026-07-19 · Faster Dashboard, Stores and PPC Audit loads** — large accounts
  (100k+ targets in one audit) no longer take seconds to open the Main Dashboard
  or the Stores overview. The audit flag engine and the ASIN tree builder were
  reworked to read only the columns and rows they need instead of loading every
  stored target: a full audit pass on a 326k-target account dropped from ~5.4s to
  ~0.7s, and the first (uncached) ASIN-tree build from ~23s to ~2s. No behavior
  change — flags, trees and reports are identical.
- **2026-07-17 · SKU Transactions Export Report (xlsx with charts)** — the
  SKU Transactions section gains the standard yellow **Export Report** button:
  one workbook honoring the current date filter — Overview (KPIs,
  net-by-SKU bar, deductions pie), Daily Trend (sales vs net line), By SKU,
  Transactions. Endpoint: `GET /catalog/transactions/export?start=&end=`.
- **2026-07-17 · Account states on the Main Dashboard** — the Dashboard's
  analytics hub gains an **account states** card (five colored counts + the
  top spender's classification, open → Strategy for the full table;
  `/dashboard/analytics` now honors goal ACoS + cadence), and the Dashboard
  Excel export's Overview sheet gains the counts + a **campaigns-by-state
  pie**.
- **2026-07-17 · Account states on the exec Reports tab** — the Reports page
  gains an **account states** card (five state counts + the top-10 spenders
  classified with state badge / ACoS vs BE / lever), and the Excel export
  gains an **Account states** sheet — counts + campaigns-by-state pie + the
  full per-campaign classification list.
- **2026-07-17 · Methodology map made real — per-campaign state classifier** —
  the Strategy tab's methodology diagram is now **live**: a new
  `account_states` classifier puts every campaign in one of the four
  ACoS-vs-break-even states (Below/At/Above target · Over break-even, ±15%
  at-target band, real-fee break-even; thin campaigns = No data / rank), the
  diagram's state boxes show the live campaign counts, and a new **Account
  states** table lists every classification (state · spend · ACoS/BE · goal ·
  lever · why). Runs for the generic advisor and every cadence strategy set.
- **2026-07-17 · Real-fee break-even in the Mid-Month Check cadence** — the
  Mid-Month plan's Bid adjustments / wasted-negative / bleeder rows all carry
  their ad group's product **BE ACoS** (catalog listing + real
  Transactions-ledger fees), ACoS colored red/green against it.
- **2026-07-17 · Real-fee break-even in the Weekly Optimization cadence** —
  the Weekly plan's Bid tweaks / promote / negate rows all carry their ad
  group's product **BE ACoS** (catalog listing + real Transactions-ledger
  fees), with each row's ACoS colored red/green against it (shared `withBE`
  column helper for the cadence tables).
- **2026-07-17 · Real-fee break-even in the N-gram miner** — every gram gains
  a **spend-weighted BE ACoS** across the ad groups its terms ran in (a word
  spans products, so its break-even is the weighted mix of theirs), with the
  gram's ACoS colored red/green against it.
- **2026-07-17 · Real-fee break-even in the Harvest panel** — every harvest
  candidate (bulk-ID path and standalone-STR fallback) carries its ad group's
  product **BE ACoS** (catalog listing + real Transactions-ledger fees), with
  the term's ACoS colored red/green against it — flags winners that convert
  above the product's break-even before you promote them.
- **2026-07-17 · Real-fee break-even in the Placement Optimizer** — every
  campaign+placement row carries the product's **BE ACoS** (via the campaign's
  product ad → catalog listing, real ledger fees), the ACoS colors against it,
  and a new **over BE** flag catches placements losing money per sale while
  still under the 2×-goal bleed threshold.
- **2026-07-17 · Real-fee break-even in the Bid Optimizer** — the optimizer's
  break-even cap now resolves through the catalog listing (per-SKU COGS +
  real Transactions-ledger fees, normalized-SKU fallback when ASINs drift),
  and the plan table gains a **BE ACoS** column with the ACoS colored
  red/green against it.
- **2026-07-17 · Real-fee break-even on the Strategy tab** — recommendation
  rows gain an **ACoS / BE** column (campaign ACoS vs the product's break-even
  from catalog COGS + real Transactions-ledger fees, red when above), and a
  new high-priority **Over Break-Even (Bleeding)** strategy fires when a
  campaign's ACoS exceeds its product's break-even regardless of the goal.
- **2026-07-17 · BE ACoS on the Waterfall benchmark** — every hero SKU row in
  the day-0 benchmark (and its Excel export) now carries the product's
  **break-even ACoS** from the catalog listing + real Transactions-ledger
  fees, with the ACoS cell colored red/green against it. New runs only —
  existing stored runs show "—" until the next bulk upload.
- **2026-07-17 · Break-even uses REAL fees from the Transactions ledger** —
  the derived BE ACoS was a constant 45% for every default-COGS product
  (percent-only inputs cancel the price out). Each SKU with order rows in the
  Transactions ledger now uses its **actual referral %** and **actual FBA $
  per unit** from that ledger, making break-even price-dependent
  (`BE = (price − referral − FBA − COGS) ÷ price`) — applied everywhere BE
  shows: Product Benchmark profit/fee, Product Ads BE column, PPC Audit flags,
  BidOptimizer caps, exec Reports. No ledger data → old 15%-referral fallback.
- **2026-07-17 · Break-even ACoS on the exec Reports tab** — the Reports KPI
  row gains an **over break-even** tile (targets above their product's
  break-even, red when non-zero); the Excel export's *Flags* sheet gains a
  per-row **BE ACoS** column and the *Summary* sheet a "Targets over
  break-even (BLEEDING)" KPI row.
- **2026-07-17 · Break-even joins the catalog LISTING by SKU** — Product Ads
  and the PPC Audit now match each advertised product to its Product Benchmark
  listing **by ASIN first, then by normalized SKU** (`PI 100` ↔ `pi-100`), and
  compute the **BE ACoS from that listing's COGS / profit-per-unit** — so the
  join works even when ASINs drift between the ad bulk and the Category
  Listings Report.
- **2026-07-17 · BE ACoS on the PPC Audit table** — every flag row now carries
  its ASIN's **break-even ACoS** (new column; flags gain a `break_even` field)
  and the Observed ACoS colors red/green against it — instant "is this target
  actually losing money" read straight from the product's unit economics.
- **2026-07-17 · Break-even ACoS moved to Product Ads** — the per-product
  **BE ACoS** column now lives on the **Product Ads** table (next to ACOS,
  which colors red/green against it) instead of Product Benchmark; the
  Benchmark tab keeps the editable **COGS** and **Profit / Unit** columns that
  drive it.
- **2026-07-17 · Per-product COGS + break-even columns on Product Benchmark** —
  every catalog product gains **COGS** (default **40% of selling price**,
  inline-editable per SKU as decimal `0.35` or percent `35%`, store-level
  overrides), **BE ACoS** and **Profit / Unit** columns; the detail view shows
  COGS/unit. Catalog products now **feed the PPC Audit's break-even map**
  (uploaded benchmark wins, catalog fills the rest), so BLEEDING flags and
  BidOptimizer caps benchmark each product's ads/campaigns against its unit
  economics. Endpoint: `PUT /catalog/cogs`.
- **2026-07-17 · Audit setup = table list** — the Audit setup checklist rows
  now render through the shared DataTable (lean): `tasks · n/total` count
  caption, sortable ✓/Task columns, `auto` tags on self-ticking rows, checkbox
  toggle + ✕ delete on manual rows — same table-list pattern as every other
  list in the app.
- **2026-07-17 · Audit checklist moved to PPC Audit** — the checklist left the
  Main Dashboard (now purely the analytics hub) and became a compact **Audit
  setup** card at the top of the PPC Audit right sidebar, next to the Goal
  ACoS control it belongs with. Smaller rows, slim progress bar, green ✓ at
  100%; auto-expands while setup is incomplete and remembers a manual
  open/collapsed choice.
- **2026-07-17 · Dashboard Export Report (xlsx with charts)** — the Main
  Dashboard gains the standard yellow **Export Report** button: one workbook
  mirroring the hub — Overview (PPC KPIs, flags-by-type bar, account-states
  counts + campaigns-by-state pie), Features
  (Product Ads status pie + catalog/monitoring blocks), Transactions (top-SKU
  net bar + daily sales-vs-net line), Top movers (spend-Δ bar). Endpoint:
  `GET /dashboard/export`. The analytics assembly moved to
  `pipeline/dashboard.py`, shared by the endpoint and the export.
- **2026-07-17 · Dashboard = analytics hub** — the Main Dashboard now
  integrates every report/data source: new `GET /dashboard/analytics` rolls up
  **Product Ads** (products/campaigns/spend/sales/ACoS/status split), the
  **Product Benchmark catalog** (listing issues, break-even counts), the
  **Transactions ledger** (orders/refunds/units/net + a daily
  sales-vs-net-proceeds line chart + top SKUs), **Monitoring** (14-day health
  score, KPIs, active alerts), snapshot **top movers**, and Change Log /
  Keywords counters — each block with an **open →** jump to its tab and a
  what-to-upload hint when its source is empty.
- **2026-07-17 · Transactions = own tab (Product Base group)** — SKU
  Transactions moved out of the Product Benchmark tab into its own
  **Transactions** sidebar tab; Product Benchmark and Transactions now form
  the collapsible **Product Base** nav group (the store-level product truth:
  catalog + payment ledger). Same features, same store-level data — nothing to
  re-upload; URL `/⟨store⟩/transactions`.
- **2026-07-17 · SKU Transactions merge = update-in-place** — re-uploading a
  transaction report now **updates known rows whose data changed** (matched by
  posted time + settlement + type + order + SKU; newest upload wins — status
  flips and fee corrections replace the stored row instead of double-counting)
  while new months keep accumulating for the date filter. Upload toast reports
  added / updated / already-in-ledger counts.
- **2026-07-17 · Table pagination readout fix** — every table's footer showed a
  phantom trailing `0` after the row count (e.g. "1–50 of 8480" for 848 rows)
  when no search/filter was active; the count now reads correctly app-wide.
- **2026-07-17 · SKU Transactions on Product Benchmark** — the Product
  Benchmark tab gains a store-level **transaction ledger** from the Payments
  **Date Range report** (transaction view): upload merges + dedupes overlapping
  months, a **date filter** narrows a stats row (orders / refunds / units /
  product sales / promos / selling & FBA fees / net proceeds), a **per-SKU
  rollup** table and the full **SKU-level transaction list** (click a SKU row
  to drill down). Account-level rows (transfers, service fees) are reported
  separately, never in the SKU totals. Endpoints:
  `POST /catalog/transactions/upload`, `GET /catalog/transactions`,
  `DELETE /catalog/transactions`.
- **2026-07-15 · Avg Product ACoS on the exec Reports tab** — the Reports
  KPI tiles and the Excel export's Summary sheet gain the same **Avg Product
  ACoS** figure (Σ ad spend ÷ Σ ad revenue across the per-product campaign
  rollups).
- **2026-07-15 · Avg Product ACoS on the Dashboard** — the Dashboard KPI row
  gains an **avg product acos** tile (Σ ad spend ÷ Σ ad revenue across the
  per-product campaign rollups from the audit's ASIN tree), colored against
  the Goal ACoS.
- **2026-07-15 · Average product ACoS** — the Product Ads and Product Benchmark
  stat rows (and both tabs' Export Reports) gain **Avg Product ACoS**, computed
  per the reporting spec as Σ Total Ad Spend ÷ Σ Total Ad Revenue across all
  the products' campaigns (zero-sale spend included in the numerator).
- **2026-07-15 · Product Benchmark Export Report (xlsx with charts)** — new
  yellow **Export Report** button on the catalog tab: Overview sheet (stats,
  catalog-composition pie, listing-issues-by-area bar) + Products sheet
  (per-product content/SEO/PPC/break-even row set with an ad-spend or
  most-issues bar chart). `GET /catalog/export`.
- **2026-07-15 · Product Ads Export Report (xlsx with charts)** — new yellow
  **Export Report** button on the Product Ads tab: Overview sheet (account
  KPIs, products-by-status pie, campaigns-by-targeting-kind bar) + Products
  sheet (per-ASIN+SKU metrics sorted by spend, top-15 ad-spend bar).
  `GET /product-ads/export`.
- **2026-07-15 · Monitoring export gets charts** — the Monitoring tab's
  .xlsx export is now a charted workbook: Overview sheet (range KPIs, TACOS vs
  target, health score, weekday/weekend bar, B2B pie, alerts +
  recommendations) and the Daily Tracker sheet with a total-sales / ad-spend /
  ad-sales line chart. The export also respects the panel's TACOS target.
- **2026-07-15 · Exec-report Excel gets charts** — the Reports tab's Excel
  export is rebuilt with native Excel charts and styled headers: Summary
  (flag-breakdown bar + actions pie), Flags (full styled table), Top movers
  (spend-Δ bar, when history exists) and SEO (issues-by-area bar + worst
  offenders + per-project recs).
- **2026-07-15 · Product Optimization exec report (xlsx with charts)** — new
  yellow **Export Report** button on the Product Optimization header (SEO /
  Listing Audit / Product Overview views): one workbook with native Excel
  charts mirroring the views — Overview sheet (KPIs, scorecards, page-1 bar,
  revenue-share pie), SEO sheet (rank-distribution pie, page-1 trend line,
  movers), Listing Audit sheet (element-coverage stacked bar,
  recommendations, the 249-byte backend line, uncovered keywords), Product
  Overview sheet (competitor table + revenue bar).
  `GET /tracker/report/export?project_id=`.
- **2026-07-15 · Channels pattern + Clear** — the Channels header matches the
  app-wide pattern: yellow **Upload Amazon Bulk Workbook** button,
  last-uploaded-file meta line (name · SB/SD rows · date, persisted per audit),
  and a danger-confirmed **Clear** (`DELETE /channels/data`) that wipes the
  SB/SD/SP snapshots while keeping the brand-term list.
- **2026-07-15 · Waterfall pattern + Clear** — the Waterfall header matches the
  app-wide pattern: yellow **Upload Sponsored Products Bulk**, a
  last-uploaded-file meta line (name · campaigns · date, persisted per audit),
  and a danger-confirmed **Clear** (`DELETE /waterfall/data`) that wipes all
  runs (settings + bid ledger kept). The day-0 benchmark is now a sortable
  DataTable.
- **2026-07-15 · Dashboard flag-breakdown table** — the Dashboard gains a
  table list under the KPI tiles: one row per flag type (count · flag · what it
  means · which tool runs it, sorted by count; HIGH_ACOS shows its
  reduce/monitor/pause ladder split inline) — the breakdown that used to hide
  in the tile subtitles.
- **2026-07-15 · Reports tab table pattern** — the exec report's action
  checklist is now a table (count · action · what it means · run in, sorted by
  count) instead of a six-number grid; the report's **top movers** (already in
  the payload, never rendered) get their own table (spend/sales/orders/ACoS
  deltas vs the previous snapshot); the SEO worst-offenders and
  per-project rows are proper lean tables with sortable columns.
- **2026-07-15 · Strategy playbook as a table** — the per-cadence playbook
  reference is now a searchable/sortable table (Strategy · Status · Criteria ·
  Action · Run in, with inline `⬇ bulk` buttons on active strategies) instead
  of a card grid — same table pattern as the rest of the app.
- **2026-07-15 · Change Log pattern + Clear** — the Change Log header matches
  the app-wide pattern: entry count in the title, yellow **Export .xlsx**
  primary button, ghost **Report message**, and a new danger-confirmed
  **Clear** (`DELETE /changelog`) that wipes the log for this audit, scoped to
  the active source filter.
- **2026-07-15 · Users tab management pattern** — the Users tab now matches the
  Stores-tab management pattern: `users · N` header with a yellow **New User**
  button that opens a modal form (replacing the always-visible inline form),
  your own row highlighted with `● you`, person icons per row; reset-password /
  delete actions unchanged.
- **2026-07-14 · Store & audit management moved to the Stores tab** — the
  sidebar's store/audit pickers are gone; the sidebar keeps a compact
  `store › audit` breadcrumb button (click → Stores tab). The Stores tab is
  now the management home: the stores KPI table gains **New Store / Delete
  Current** header buttons (row click switches store, `open →` jumps to PPC
  Audit), and a new **audits table** below lists the current store's audits
  (click/`open →` opens it in PPC Audit; **New Audit / Flush Current / Delete
  Current** in the header).
- **2026-07-14 · Sidebar store list (was a dropdown)** — the STORE picker gets
  the same table-list treatment: every store is a visible row (lime highlight +
  ✓ on the active one), clicking switches store and reloads its audit list;
  new/delete buttons sit above the list. Also fixed a latent race this
  surfaced: two parallel requests first-touching the same new audit db could
  both run table creation and one 500'd with "table dim_product already
  exists" — engine creation is now locked.
- **2026-07-14 · Sidebar audit list (was a dropdown)** — the AUDIT picker in the
  sidebar is now a table-style list: every audit is a visible row (scrolls past
  five), the active one is highlighted with a ✓, and clicking a row selects
  that audit AND opens the PPC Audit tab. The new / flush / delete buttons
  moved above the list and act on the selected audit.
- **2026-07-14 · Cannibalization upload pattern + Clear** — the Cannibalization
  header now matches the app-wide pattern: yellow **Upload Sponsored Products
  Bulk** button, last-scanned-file meta line (name · findings · date, persisted
  per audit), and a danger-confirmed **Clear** (`DELETE /cannibal/data`) that
  wipes the stored findings only.
- **2026-07-14 · N-gram miner takes the bulk file too** — the N-gram dropzone
  follows the same pattern: upload the SP bulk (its embedded SP Search Term
  Report sheet is auto-picked) or a standalone STR; clearer error when a file
  has no search-term sheet.
- **2026-07-14 · Search-Term Harvest from the bulk file (exact IDs)** — the
  Keywords tab's harvest now takes the **SP bulk file** (with its embedded SP
  Search Term Report sheet) as the primary upload: candidates carry the
  report's real Campaign/Ad Group/Keyword/PT IDs and the output bulk
  creates/negates by exact ID via the Weekly engine (`POST /harvest/from-bulk`
  + `/from-bulk/file`). A new Campaign · Ad Group column shows where each term
  ran. Standalone STRs still work as a name-mapping fallback with a visible
  notice.
- **2026-07-14 · SEO in the exec report** — the Reports tab (and its Excel
  export, new **SEO** sheet) gains an **SEO · listing quality & keyword
  coverage** section: catalog products with high/medium listing issues +
  per-area breakdown + five worst offenders, and one row per Product
  Optimization project (tracked keywords, high/medium rec counts, over-249-byte
  backend-field badge, top keywords to work in).
- **2026-07-14 · Catalog-level SEO recommendations (Product Benchmark)** — every
  non-parent catalog product is checked against listing-quality rules from the
  Category Listings Report fields alone (title/bullet/description lengths,
  missing or over-249-byte backend search terms, wasted backend words, missing
  main image / thin gallery): new **SEO** issue-count table column, **Listing
  Issues** stat, and a severity-tagged recommendations block in the product
  detail view — with the keyword-based recs one click away via Perform Listing
  Audit.
- **2026-07-14 · SEO recommendations on the Listing Audit tab** — the SEO
  recommendations + backend search-term cards now also render under the copy
  editor on the Listing Audit view (same variant toggle, kept in sync), so you
  can edit copy and watch the recommendations react without switching tabs.
- **2026-07-14 · Proposed-variant SEO recommendations** — the Listing Audit and
  SEO recommendation cards gain a **Current | Proposed** toggle: draft a rewrite
  in the Proposed variant (paste per element, or **Seed from current**) and get
  the same markers, coverage and SEO + backend search-term recommendations
  computed from the draft alone — current copy, sheet-imported markers and
  competitor pastes never leak in. Iterate until the draft's recs go quiet,
  then publish.
- **2026-07-14 · SEO + backend search-term recommendations (Product
  Optimization)** — the SEO view gains two cards computed from the Listing Audit
  copy vs the tracked keywords (`GET /tracker/seo-recommend`): prioritized
  severity-tagged **SEO recommendations** (missing copy, top-SV keywords not
  exact in the title, keywords covered nowhere, title-length / bullet-count /
  249-byte checks, banned phrases, wasted backend words) and a **ready-to-paste
  backend search-term line** — the highest-SV uncovered keyword words (visible
  copy is already indexed, so its words are excluded), banned-free, packed to
  ≤ 249 bytes with a byte meter and a Copy button.
- **2026-07-14 · Keywords upload pattern** — the Keywords tab's two research
  dropzones now carry yellow **Upload Brand Analytics SQP** / **Upload Helium10
  Cerebro** buttons (cards stay drag & drop), the mined-keywords header gains a
  last-uploaded-files meta line (name · rows · source · date, persisted per
  audit + cadence), and Clear is restyled to the standard danger-confirmed
  ghost button (it also resets the file list).
- **2026-07-14 · Monitoring upload pattern + Clear** — the Monitoring tab now
  follows the same header pattern: yellow **Upload Daily Reports** button, a
  meta line listing the last few uploaded files (name · days · kind · date,
  persisted per audit, cadence-agnostic), and a danger-confirmed **Clear**
  (`DELETE /monitoring/data`) that wipes every uploaded tracker day — manual
  month-sales overrides survive.
- **2026-07-14 · Product Ads upload pattern + Clear** — the Product Ads tab now
  follows the same header pattern: yellow **Upload Sponsored Products Bulk**
  button, last-uploaded-file meta line (name · rows · date), and a
  danger-confirmed **Clear** (`DELETE /product-ads/data`) that wipes its
  snapshot (own table only; the Product Benchmark campaigns/ACoS join for that
  audit empties too).
- **2026-07-14 · Cadence upload pattern + per-cadence Clear** — every PPC Audit
  cadence panel now follows the Product Benchmark header pattern: yellow **Upload
  Sponsored Products Bulk** primary button, ghost **Clear** button, and (Mid-Month /
  Full Month / Pause/Scale) a last-uploaded-file meta line (name · rows · date,
  persisted per audit + cadence). Daily Watch / Weekly grid tiles show a yellow
  Upload until the tile has data, then ghost Re-upload. New danger-confirmed
  **Clear** for all five cadences (`DELETE /daily-watch|weekly|mid-month|
  full-month|pause-scale /data`) — wipes the cadence's uploads AND the star schema
  they fed, so the optimizer sub-panels (Bid Optimizer / Placement / ASIN tree /
  Harvest / N-gram) clear with it; Full Month's warns it also clears the audit's
  bulk-derived dashboard/flag data (Monitoring, Product Ads, Keywords, Benchmark
  untouched). SQLite busy-timeout raised to 30s so a big Clear can't 500 concurrent
  panel reads with "database is locked".
- **2026-07-14 · Product Benchmark ↔ Product Ads join + Break-Even metrics** —
  the catalog tab now matches every ASIN against the selected audit's Product
  Ads upload: new **Campaigns** (distinct count + auto/keyword/product/manual
  breakdown), **Ad Spend** and **ACoS / BE** table columns, Advertised /
  Campaigns / Over- & Under-Break-Even stats, and a **PPC · Product Ads &
  Break-Even** block in the detail view (campaign table with ACoS colored
  against break-even, profit & Amazon fee per unit, profitable/bleeding
  verdict). Break-even ACoS = uploaded Product Benchmark value when present,
  else derived from the catalog selling price + the audit's econ defaults
  (`(price − referral − COGS%) ÷ price`). `GET /catalog` / `GET /catalog/item`
  return the joined data (`ads`, `be`, `be_status`).
- **2026-07-13 · Perform Listing Audit from Product Benchmark** — every catalog
  product (table row + detail view) gets a "Listing Audit" button: choose or
  create a Product Optimization project (new projects auto-set their primary
  ASIN to the product's ASIN; projects without one adopt it, and the ASIN
  upload field lands prefilled) and the product's title / bullets /
  description / search terms are imported from the catalog into the project's
  own listing copy (empty report elements skipped, manual pastes preserved),
  its search terms are added as tracked keywords for the SEO tab (phrases kept,
  word-soup split into words, deduped — re-import never duplicates), then the
  Listing Audit view opens with that project selected. Endpoint:
  `POST /tracker/listing/from-catalog`.
- **2026-07-13 · Product Benchmark catalog (Category Listings Report)** — new
  head-menu tab: upload Amazon Category Listings Reports (one per category;
  they merge by SKU) into a **store-level product catalog** — title,
  description, bullet points, selling/sale/list price, image links and
  variation families (parent/child + theme + color/size). Product table with
  thumbnails and content-gap counts, full detail modal with image gallery and
  click-through variation family. Store-scoped: never overlaps another store.
  Endpoints: `POST /catalog/upload`, `GET /catalog`, `GET /catalog/item`,
  `DELETE /catalog`.
- **2026-07-13 · Listing Sanitizer (Amazon banned keywords)** — new checker card at
  the top of Product Overview: maintain a banned/restricted keyword list (paste once,
  shared across projects) and every element of YOUR pasted listing copy is scanned —
  per-element report with flagged counts and the exact banned phrases as red chips.
  Whole-word matching, case/punctuation folded; your listing only, competitors never
  scanned. Endpoints: `GET/PUT /tracker/banned`, `GET /tracker/sanitize`.
- **2026-07-13 · Listing Audit: competitor copy comparison** — paste each
  competitor's Title / Bullet Points / A+ / Description / Alt Text manually
  (click a cell in the new comparison table); exact/broad markers and exact-SV
  compute against the same tracked keywords, with a Keywords-covered row to
  benchmark your listing against each competitor. Search Terms deliberately
  excluded for competitors (no data source). `ListingCopy` gains an `asin`
  column (auto-migrated); `PUT /tracker/listing` accepts `asin`.
- **2026-07-13 · Product Overview (was Product List)** — the third Product
  Optimization tab is renamed; URL is now `/…/product-overview` (old
  `/product-list` slug redirects).
- **2026-07-13 · Listing Audit: 25× faster on big keyword lists** — the computed
  listing analysis normalized the full copy text once per keyword × element
  (~19 s on a 10k-keyword Cerebro list); copy is now folded once per element and
  marker counts accumulate in a single pass (~0.7 s). Same results.
- **2026-07-13 · Product Optimization group (was Listing Optimizer)** — the single
  Listing Optimizer tab is now a **Product Optimization** sidebar dropdown with three
  tabs over the same project data: **SEO** (scorecards, movers, keyword grid, PPC
  bridge), **Listing Audit** (raw-copy engine + markers) and **Product Overview**
  (competitor matrix). Project switcher + uploads appear on every tab; the active
  project survives switching. URLs: `/…/seo`, `/…/listing-audit`, `/…/product-overview`
  (the old `/listing-optimizer` and `/product-list` slugs redirect).
- **2026-07-12 · Listing Optimizer: sheet-style keyword grid** — the coverage matrix is
  now a full replica of the Google Sheet's Main tab: the six listing-element marker
  columns (Title / Bullet Points / A+ / Description / Search Terms / Alt Text,
  `exact`/`broad` chips computed live) sit between REL and the ASIN columns, and every
  ASIN column header stacks the **product image, brand name (★ = you) and a clickable
  ASIN link** — data joined from the X-ray import. The separate keyword×element marker
  table inside the Listing Audit panel was removed (redundant); the panel keeps the
  copy-editor cards, coverage counter and "not used anywhere" list.
- **2026-07-12 · Listing Optimizer: computed REL (relevancy)** — the coverage matrix's
  REL column is no longer the sheet's manual tag: it now counts **how many of the
  displayed ASINs use the keyword in their product listing** (exact phrase in Title +
  Bullet Points from X-ray/sheet data; the primary ASIN also counts its pasted Listing
  Copy Title/Bullets/Description). Recomputes live on every X-ray/copy change; exported
  matrix carries the computed value.
- **2026-07-12 · Listing Optimizer: upload order no longer matters (bug fix)** —
  uploading X-ray before Cerebro used to drop the unmatched competitor rows for good,
  leaving only your ASIN's data. Unmatched X-ray rows are now stored **hidden** and
  re-activate automatically when a Cerebro upload starts tracking their ASIN — both
  orders produce identical results. The Cerebro import re-syncs competitor visibility
  (match + top-10-by-revenue cap) after every upload.
- **2026-07-12 · Listing Optimizer: computed Listing Health Score** — the score is no
  longer typed in by hand: each of the 8 audit checks (PDP Images/Videos, Brand Story,
  Generic/Premium A+, Crawlable Text, Alt Text, Comparison Table, Amazon's
  Badge/Highlight) is worth **1.25 points — all Yes = perfect 10**. Toggling a Yes/None
  cell recomputes instantly; the score row is color-tiered (≥7.5 green, ≥5 yellow,
  >0 amber, 0 muted) and shows `x.xx /10`. Manual score editing removed (sheet-imported
  scores ignored).
- **2026-07-12 · Listing Optimizer: Cerebro-matched X-ray + top-10 cap** — the X-ray
  import now keeps only rows whose ASIN appears in your Cerebro data (plus the primary):
  a 97-row X-ray against an 8-ASIN Cerebro imports exactly those 8, skips 89 (toast
  reports matched/skipped), and purges stale unmatched competitors from older imports.
  When more than 10 competitors match, only the top 10 by revenue stay **active** —
  competitor matrix, scorecards and the coverage-matrix columns all cap accordingly
  (primary always shown). Upload order: Cerebro first, then X-ray.
- **2026-07-12 · Listing Optimizer: real Helium10 export tolerance** — raw parsers now
  match the actual H10 CSVs (e.g. `Guide Templates/`): X-ray headers matched loosely
  (BOM, `Price  $`, `Fees  $`, `ASIN Sales`/`ASIN Revenue`, `Active Sellers`,
  `Image URL`, `Ratings`), `Mar 22, 2011`-style creation dates parsed to ISO (fixes
  Listing Age); Cerebro exports carrying **both** `Position (Rank)` and per-competitor
  ASIN rank columns import fully — the rank column defaults to the project's primary
  ASIN, competitor columns are picked up alongside. Verified on the bundled sample:
  2,373 keywords / 1,969 ranks / 97 X-ray ASINs in one upload each.
- **2026-07-11 · Listing Optimizer: rename + RAW-data flow** — the SEO Tracker tab is
  now **Listing Optimizer**, and it no longer needs the pre-computed Google Sheet:
  **New project** creates a blank project (name + primary ASIN), then raw Helium10
  exports drive everything — **Upload Cerebro (raw)** seeds keywords + ranks
  (single-ASIN exports default to the primary ASIN), **Upload X-ray (raw)** upserts the
  competitor matrix by ASIN (manual audit edits preserved on re-upload). New **Listing
  Audit** panel: paste raw copy per element (Title/BPs/A+/Description/Search
  Terms/Alt Text) and the app computes the `exact`/`broad` markers, per-element
  exact counts + total exact SV, coverage, a top "not used anywhere" keyword list and
  the keyword × element marker matrix. Sheet-imported markers remain as fallback per
  element until raw copy is pasted. Sheet migration kept (legacy). New
  `POST /tracker/projects`, `POST /tracker/xray`, `GET/PUT /tracker/listing`.
- **2026-07-11 · SEO Tracker: competitor matrix (sheet layout)** — the tracker now opens
  with the sheet's Main-tab **competitor matrix**, transposed exactly like the original:
  product images, one column per ASIN (primary ★-highlighted), every X-ray attribute row
  + computed Listing Age, the yellow **Listing Health Score** row (click to edit) and the
  manual **Yes/None audit rows** (click to toggle — persists via
  `PATCH /tracker/competitor`), topped by the colored KPI blocks (Total Revenue /
  Market Share / Avg Reviews) and a revenue-share donut. New `GET /tracker/competitors`.
- **2026-07-11 · SEO Tracker (Competitor Research / Indexed Keywords)** — new top-level
  tab (own feature, separate from the PPC Suite) replacing the "Competitor Research /
  Indexed Keywords / SEO" Google Sheet. One-time
  sheet migration (per the approved `research_tracker/MAPPING.md`: keyword×ASIN rank
  grid, X-ray competitor attributes + manual listing-health audit, Listing Audit
  usage markers, Listing Copy current/proposed, Search Terms keywords), then weekly
  Cerebro snapshot imports (append-only per date — trends accumulate; same-date re-import
  replaces that date only). Views: per-ASIN scorecards (index rate, page-1 count, avg
  rank, sparkline, coverage-vs-best) + sheet-header KPIs (top-10 revenue / market share /
  avg reviews), the heat-colored coverage matrix (click a cell to edit a rank manually),
  movers since last snapshot (climbers/decliners/new/lost), PPC rank-support + competitor
  product-target suggestions, and an xlsx matrix export. New tables `TrackerProject`,
  `TrackedCompetitor`, `TrackedKeyword`, `RankSnapshot`, `KeywordUsage`, `ListingCopy`;
  routes under `/tracker/*`; 12 new tests (fixture built from the real sheet's layout).
- **2026-07-10 · Search-Term Harvest + N-gram moved to Keywords** — both keyword-discovery
  tools now live on the **Keywords** tab (next to keyword mining) instead of the PPC Audit
  tab. Same functionality; results still persist across tab switches (app-level state).
- **2026-07-10 · Fix: panels fetched with the default Goal ACoS (0.25) before the saved
  one loaded** — on first load the app seeded `targetAcos` with the global default (0.25)
  and children (Placement Optimizer, Bid Optimizer, dashboard audit, cadence runs) fetched
  immediately — so `/placements?...&target_acos=0.25` fired even though the audit's saved
  Goal ACoS was 20%. Fixed: `targetAcos` now starts **null** and is only set once the real
  project list + its saved `acos_threshold` load; every auto-fetching panel waits for a
  non-null value before calling the API. Result: the first (and only) request already
  carries the audit's real Goal ACoS.
- **2026-07-10 · Fix: Placement Optimizer (+ generic panels) empty after cadence upload** —
  the cadence uploads (Full Month, Mid-Month, Pause/Scale, Weekly) parsed only the SP
  Search Term Report into their own tables, so the star-schema panels — **Placement
  Optimizer**, Bid Optimizer, ASIN Tree, Harvest, N-gram — had no data ("no placement data
  in this bulk file") once the standalone Uploads tab was removed. Two-part fix: **(1)**
  these cadence uploads now **also** run the full ingest→clean→load on the same bulk
  (`weekly.load_star_schema`), populating `FactPerformance` + `FactPlacement` + dims in that
  cadence's db; **(2)** a successful cadence upload now **bumps the app data version**
  (`onUploaded` → `bump`), so the generic panels actually refetch and display the new data
  instead of showing a stale empty state. Tolerant: a Search-Term-only file with no
  campaign / Bidding-Adjustment rows leaves the star schema untouched (no error). Placement
  still needs the bulk's **Bidding Adjustment** placement rows present to show
  recommendations. So every cadence now drives the Placement Optimizer from its own upload.
- **2026-07-10 · Flag legend, back & unmissable** — the **Flag legend + bid ladder**
  reference (BLEEDING / HIGH_ACOS / SCALE ▲ / WASTED / OVERBID / LOW_CVR / LOW_CTR, plus
  the REDUCE → MONITOR → PAUSE ladder) is now a shared `FlagLegend` component. It still
  sits in the PPC Audit right rail, and is **also** available as a collapsible
  "flag legend & bid ladder" row inside the Audit Cadence header — so it's reachable for
  every cadence, even where the generic flag table is hidden.
- **2026-07-09 · Cadence process funnel** — every Audit Cadence now opens with a
  step-by-step **process funnel** below the header: numbered steps (export the right
  Amazon report → upload → review the recommended actions → download bulk & re-upload to
  Amazon) with a live-highlighted current step, green ticks for finished steps, and a
  progress bar. The active step is derived from real panel state (uploaded? bulk
  downloaded?), so it self-advances as you work. Watch-only Daily Watch has a 3-step
  funnel (no download). Guidance only — never blocks. (`CadenceFunnel.jsx`; each cadence
  panel emits its stage via `onStage`.)
- **2026-07-09 · Store name in the URL** — the active store is now the first URL segment:
  `/<store>/<tab>[/<cadence>]`, e.g. `/zvalves/ppc-audit/daily-watch`. Deep-links open the
  named store directly; browser back/forward restore it. An unknown store slug falls back
  to your first store. Built on the History API (no router dep).
- **2026-07-09 · Placement panel upgrade + Channels (SB/SD) tab** — Placement optimizer
  now flags the classic placement diseases per campaign: `FLAT_MODIFIER` (same % on
  every placement with spend), `PLACEMENT_BLEED` (placement ACoS ≥ 2× goal),
  `TOS_STARVED` (top-of-search converts under goal but gets < 25% of spend). New
  modifier math: cut = `clip(current% × goal/ACoS, 0, 400)` (never raises a bleeding
  placement), TOS raises step **+25** capped at **150**; Product Page floors at **0%** —
  when it still bleeds there, opt-in **companion base-bid cuts** (via `safe_bid_cut`,
  ledger-recorded) ship in the same bulk. Bulk rows now carry Bidding Strategy; the
  scorecard adds CVR / CPC / share-of-spend (`fact_placement.strategy` auto-migrated).
  New **Channels** tab: SP vs SB vs SD mix cards, SB keyword flags, brand vs non-brand
  donut (per-store `brand_terms` list), SD dormancy banner, read-only SB STR harvest.
  SB ingests the **Multi Ad Group sheet only** (legacy sheet = duplicates). Tables
  `sb_fact` / `sd_fact` / `sp_channel_fact` (base db); `pipeline/channels.py`,
  `/channels/*`, `Channels.jsx`.
- **2026-07-09 · Cannibalization / Keyword Ownership Detector** — new **Cannibalization**
  tab (PPC Suite): upload the SP bulk → Type 1 duplicate targets (same keyword+match or
  PT expression in 2+ campaigns) + Type 2 cross-product term overlap (same search term
  selling for 2+ SKUs, via the STR). Owner = max CVR (≥10 clicks, tiebreak min ACoS);
  coexist when everyone's profitable with volume; same-SKU tier pairs surface only as
  missing sculpting negatives. Selected losers → keyword/PT pauses by exact ID +
  `Campaign Negative Keyword · Negative Exact`, with the converter/live-keyword guard
  (never negate where the term converts or another live keyword would die). Findings
  regenerate idempotently per scan (`overlap_finding` table, base db); exports log to
  Change Log + BidLedger. `pipeline/cannibal.py`, `/cannibal/*` routes,
  `Cannibalization.jsx`; Waterfall upload can fan out via `?engines=waterfall,cannibal`.
- **2026-07-09 · Waterfall Restructure Engine + safe bid math + effective-bid ledger** —
  new **Waterfall** tab (PPC Suite): upload the full SP bulk → per-campaign SKU+slot
  classification (Auto type beats name; MULTI/EMPTY/mixed warnings) → profitable-first
  boss election per SKU+slot → **4 phased bulk exports** (A renames · B loser bid cuts ·
  C creates born-paused + seed keywords + sculpting campaign-negatives · D pauses, gated
  until A–C applied) + day-0 hero benchmark with day-21 verdict. New
  `metrics.safe_bid_cut` fixes the live up/down bug where CPC-based cuts *raised* bids
  (CPC ≈ 2× bid) — wired into Weekly/Mid-Month/Full-Month bid tweaks and the Bid
  Optimizer cut paths (a cut can never raise). New **BidLedger** (`pipeline/ledger.py`):
  every exported bid/state change is recorded; subsequent computations read effective
  values; new-bulk uploads auto-reconcile; pending/stale exports surface in the Waterfall
  tab with mark-applied / discard. Tables `waterfall_run` / `waterfall_item` /
  `bid_ledger` live in the base project db.
- **2026-07-08 · Product Ads — campaign tracing by targeting kind** — each SKU now traces
  its campaigns by type: **Automatic**, **Keyword-target**, **Product-target** (new
  Auto / KW tgt / PT tgt columns, sortable), with account-wide totals in the header and
  per-ASIN counts + a **Type** badge in the drill-down. Backend classifies each campaign
  from the bulk's Campaign **Targeting Type** + Keyword / Product Targeting entity rows
  (`productads.classify_campaigns`) and stamps `campaign_type` on every Product Ad row
  (new column, auto-migrated via `_ensure_schema`). Needs the full SP bulk (with campaign
  + target entity rows).
- **2026-07-06 · Animated success toasts on every transaction** — every state-changing or
  file-producing action now fires an animated toast (top-right): store/audit create +
  delete, flush, all bulk/Excel downloads, all cadence + Product-Ads + benchmark + keyword
  uploads, remove-week / clear-all, change-log export + copy, per-cadence audit runs,
  strategy bulks, user create/delete/reset. Success = green Material `check_circle` that
  pops with a ring pulse + shrinking timer bar; failures raise a red `error` toast. New
  `components/Toast.jsx` (`ToastProvider` + `useToast()`), mounted once in `App`; four
  animations added to `index.css` (`toastIn` / `iconPop` / `ringPulse` / `toastBar`).
- **2026-07-06 · URL routing** — the active tab (and cadence, for cadence tabs) now lives
  in the URL (store prefixed as of 2026-07-09): `/<store>/<tab>[/<cadence>]`, e.g.
  `/zvalves/ppc-audit/daily-watch`, `/zvalves/strategy/weekly`, `/zvalves/dashboard`.
  Deep links + browser back/forward work; the path updates as
  you navigate. Built on the History API — no router dependency. (Tab slugs: `ppc-audit`,
  `product-ads`, `change-log`; cadence slugs: `daily-watch`, `weekly`, `mid-month`,
  `full-month`, `pause-scale`.)
- **2026-07-06 · Fix: stale data after store / cadence switch** — switching store or
  Audit Cadence no longer shows the previous scope's data (needing a hard cache clear).
  Two causes fixed: (1) the api client now sends every request with `cache: 'no-store'`
  so the browser never serves a scoped GET from disk cache; (2) the active scope
  (`store` / `project` / `audit_type`) is set on the api client **during render** instead
  of in an effect — child effects fire before the parent's, so the old timing let a child
  refetch with the previous scope.
- **2026-07-06 · Monitoring metric explorer — 4 metrics** — the **Monitoring** metric
  explorer now plots **up to 4 metrics** at once (was 2), matching Daily Watch. Hover
  tooltips show each value; distinct units still collapse onto two y-axes.
- **2026-07-06 · Cadence-driven strategies** — Weekly / Mid-Month / Full-Month /
  Pause-Scale now compute their strategies from **their own uploaded data** (each
  cadence's `…TermFact` side table via its plan engine), not the shared FactPerformance
  snapshot. New `pipeline/cadstrat.py` maps each cadence's plan lists (harvest promotes /
  negates / bleeders / bid tweaks / scales / pauses / campaign-pauses) into the advisor's
  recommendation + playbook shape, and builds each strategy's Amazon bulk (reusing the
  cadence's own `to_bulk` + Change Log). `/strategy` + `/strategy/bulk` route these four
  `audit_type`s to `cadstrat`; everything else keeps the generic account advisor.
- **2026-07-06 · Strategy per Audit Cadence** — the **Strategy** panel now opens with a
  cadence selector (Daily / Weekly / Mid-Month / Full Month / Pause-Scale). Clicking a
  cadence loads that cadence's own recommendation strategies + playbook. One-click bulks
  and the tile rec-count follow the selected cadence. Backend: `GET /strategy` +
  `POST /strategy/bulk` gained an `audit_type` param (cadence-tuned thresholds via
  `cadence.thresholds_for`); `api.strategy` / `api.strategyBulk` pass the chosen cadence.
- **2026-07-04 · Material Icons throughout** — the app's icon system is now **Material
  Symbols** (font already loaded) via the shared `Icon` component, replacing the old
  unicode geometric glyphs. Sidebar nav + PPC Suite group + Users (dashboard / storefront /
  ads_click / shopping_bag / monitoring / key / strategy / assessment / history / apps /
  group), sidebar chrome (menu, chevron_left, add, delete, delete_sweep, expand/chevron),
  and every action marker — upload / download / content_copy / close / warning /
  check_circle / circle / refresh, plus the `⬇ template` links. Textual arrows (→ ←) and
  the LLM status dot stay as-is (typography, not icons).
- **2026-07-04 · Buttons — loading spinner while working** — every action button now shows
  an inline spinner and blocks further clicks while its request is in flight (upload,
  download/bulk build, compare, narrate, audit, submit, refresh, etc.). One global CSS
  rule (`button[aria-busy="true"]` in `index.css`) draws the spinner in the button's own
  text color; each async button sets `aria-busy` from its loading flag — so the whole app
  animates consistently with no per-button markup.
- **2026-07-04 · Per-cadence Audit button** — each **Audit Cadence** preset tile (Daily,
  Weekly, Mid-Month, Full Month, Pause/Scale) has its own **▶ audit** button that runs
  that cadence's audit (flags + Ad Spend/Sales/ACoS capture + SOP effort checklist) at the
  current Goal ACoS for the selected month/year, persisted to that cadence's own db. The
  tile then shows its result inline (**N flags · ACoS**, or **no data**). Replaces the
  earlier single *Audit all cadences* button on the Goal ACoS control. Each run is the
  monthly capture: first click records it, later clicks reopen it.
- **2026-07-04 · Uploads tab (Upload Central) removed** — the guided upload stepper and
  its **Uploads** nav entry (under **PPC Suite**) are gone, along with its standalone SP
  bulk dropzone, **Product Benchmark** uploader, and standalone STR harvest/n-gram step.
  Uploads now live inside the panels that use them — each **Audit Cadence** panel and
  **Product Ads** carry their own bulk upload. The Dashboard's **→ Product Benchmark**
  shortcut was removed with it.
- **2026-07-04 · Weekly Optimization — clear all data** — a **Clear all data** button in
  the Weekly Optimization header wipes every uploaded week at once (danger confirm,
  cannot be undone), resetting the grid to the empty Week 1–5 panels. Complements the
  existing per-week **✕** remove. Backend: `DELETE /weekly/data` → `weekly.delete_all`.
- **2026-06-29 · Daily Watch trend — 4 metrics** — the **trend · accumulated days**
  chart in the **Daily Watch** cadence now plots **up to 4 metrics** at once (was 2).
  `MetricChart` gained a `max` prop (default 2, so Monitoring + Weekly charts keep the
  2-metric cap); 4 line colors; distinct units still collapse onto two y-axes (left /
  right). PPC Audit dropzone removed earlier this day too.
- **2026-06-29 · PPC Audit dropzone removed** — the standalone **drop SP bulk** dropzone
  inside **PPC Audit** is gone; use the bulk upload in **Uploads**.
- **2026-06-29 · PPC Suite nav group** — the five PPC-workflow tabs (**Uploads**,
  **PPC Audit**, **Product Ads**, **Keywords**, **Strategy**) are now nested under a
  collapsible **PPC Suite** group in the sidebar (click the group header to expand /
  collapse, **▾/▸**). The group auto-expands when one of its tabs is active and is open
  by default. Top-level tabs (Dashboard, Stores, Monitoring, Reports, Change Log, Users)
  unchanged.
- **2026-06-29 · Sales & Costs removed** — the **Sales report** (Business Report /
  manual account total → Organic, TACoS, ad-dependency), the **Costs** grid (per-ASIN
  COGS/FBA/referral/misc + econ refund/referral/default-COGS settings), and the
  **profit P&L** (revenue, net profit, margin, ROI, Amazon fees, refunds, est. payout,
  per-product P&L) were deleted — the whole **Sales & Costs** sidebar tab is gone. The
  **Dashboard** and **Reports** tabs are now **PPC-only** (account KPIs: ad spend / ad
  sales / ACoS / flags / wasted / scale; the Excel report drops the "P&L by product"
  sheet → Summary + Flags + Top movers). **Product Benchmark** (per-ASIN sale price +
  break-even ACoS) now lives under the **Uploads** tab. The **Monitoring** tracker
  (which independently uses Business Report + Sponsored Products reports and shows
  TACOS) is unaffected.
- **Mid-Month + Full Month — compare to previous upload** — both single-panel cadences now
  keep your **previous** upload alongside the current one. After a 2nd upload a **Compare to
  previous** button appears → same account-delta / anomaly-flag / top-movers view as Daily
  Watch & Weekly (previous → current). The plan still runs only on the current snapshot. New
  `GET /mid-month/compare` + `GET /full-month/compare` (`midmonth.compare` / `fullmonth.compare`,
  via the shared `weekly.compare_rows` engine). Tables gain a `period` column (0=current,
  1=previous; legacy single-snapshot data auto-migrates as current).
- **Weekly Optimization — compare weeks** — same as Daily Watch's day compare but week-over-week:
  pick two uploaded weeks → account deltas (spend/sales/clicks/orders/ACoS, spend & ACoS rising =
  red), **anomaly flags** (spend spike ≥1.5× & ≥$20, ACoS spike ≥10pp over goal, sales drop, zero-order
  spend) and a **top-movers** table. New `GET /weekly/compare?prev=&cur=` (`weekly.compare`).
- **Weekly Optimization — remove a week** — each week panel with data now has a **✕** that
  deletes that week's data server-side (panel resets to empty, persisted across tab-switch /
  refresh); *remove last week* also deletes the trailing week's data. New
  `DELETE /weekly/week?week=` (`weekly.delete_week`).
- **Daily Watch — remove panel now deletes the day** — removing a day panel that had data
  now deletes that day server-side, so it stays gone after switching tabs or refreshing (was
  re-seeding from the saved day). New `DELETE /daily-watch/day?day=` (`dailywatch.delete_day`).
- **Every table identical — design, sorting, filtering** — all tables now share one
  `DataTable` (built on the existing table controls), so each one has the **same** look,
  **free-text search**, **click-to-sort columns**, **per-column + composite filters**,
  **page-size + pagination**, and the sticky header. The cadence panels (Weekly bid-tweaks /
  harvest, Mid-Month negatives + bleeders, Full Month full-optimization, Pause/Scale
  scale/pause/campaign), the Daily Watch per-campaign movers, and the Product Ads drill-down
  (ads + campaigns) — previously plain tables with no search/sort — now match the rest of the
  app. Row selection (the cadence checkboxes) is preserved inside the unified table.
  **Lean mode:** the panels' many short sub-tables drop the search/filter/page-size bar and
  pagination (just a title + the table, with sort + select-all still in the header) until a
  table grows past ~12 rows, at which point the full controls reappear — so a panel like Full
  Month no longer stacks four search bars, but a long negatives list still gets search + paging.
- **Sticky table headers** — on mouse/hover devices every table is now its own scroll box
  (up to 70% of the screen) with a **frozen column header**: scroll a long table with the
  wheel and its header stays pinned to the top of that table so you never lose the columns.
  The header sticks only inside its own table — never to the page — so the **browser
  scrollbar still scrolls the page normally** (the table's wheel scroll continues onto the
  page once it reaches its end). Short tables are unchanged. Applies to **every table** in
  the app (Audit, Product Ads, all cadence panels, Monitoring, Sales, Keywords, Change Log…).
- **Product Ads — own bulk upload + own table** — Product Ads is now **fully separate from
  the PPC Audit table**: it has its **own Upload bulk button** and its **own data model**
  (`product_ad_fact`). Upload a Sponsored Products bulk → its Product Ad rows (Entity =
  `Product Ad`, with ASIN/SKU + metrics) parse straight into that table (replaced per
  upload), independent of the audit pipeline. The drill-down now shows ads + **per-campaign
  rollups** from this data (audit flags / strategy recs dropped — those belong to the PPC
  Audit model). Empty state prompts for the upload. IDs kept as exact strings.
- **Pause/Scale Audit — cut/scale panel** — the **Pause/Scale** cadence now has its own
  dedicated **single panel** (Sponsored Products only), the last cadence to be converted —
  **all five now have dedicated panels**, none use the generic flag table. Unlike the others
  it acts on the **existing entities** (not customer search terms): upload one SP bulk →
  **scale winners** (10+ orders ≤ goal → bid up, +25% cap), **pause dead targets** (30+
  clicks, 0 orders → state=paused), **pause dead campaigns** ($50+ spend, 0 orders → pause
  whole campaign, not pre-selected). Own table (`pause_scale_term_fact`); shares the Weekly
  engine's new `aggregate_targets`. Bids/pauses emit by exact entity ID.
- **Full Month Audit — full optimization panel** — the **Full Month** cadence now has its
  own dedicated **single panel** (Sponsored Products only), the superset of the focused
  cadences: upload one SP bulk → bid adjustments **+** harvest promote (winners) **+**
  negatives (wasted) **+** bleeders, all at once → tick rows → download one validated SP
  bulk. Its own table (`full_month_term_fact`); reuses the shared `weekly.py` engine. The
  generic flag table is now hidden for Full Month (its own panel replaces it); the richer
  Bid Optimizer / Placement / Harvest / N-Gram panels still appear below. **All four**
  cadences (Daily/Weekly/Mid-Month/Full-Month) now have dedicated panels — only Pause/Scale
  uses the generic flag table.
- **Mid-Month bleeders — noise filter** — the bleeder tier (converted but ACoS ≥ 2× goal)
  now requires **≥ 2 orders** (one order's ACoS is statistical noise) **and** spend ≥ 2× the
  loser floor (head $-bleeders only), so single-order / long-tail rows no longer clutter the
  list. The reason line shows `$spend / orders @ ACoS` for at-a-glance triage.
- **Mid-Month Check — bid adjustments + heavy negative targeting** — the **Mid-Month**
  cadence now has its own dedicated **single panel** (Sponsored Products only), reusing the
  Weekly SP-Search-Term-Report engine: upload one SP bulk → recomputed guardrailed bids +
  **two negative tiers** — *wasted* (spent, 0 orders; pre-selected) and *bleeders* (converted
  but ACoS ≥ 2× goal; surfaced but not pre-selected, since negating them stops sales) →
  tick rows → download a validated SP bulk. Its own table (`mid_month_term_fact`), so a
  Mid-Month bulk only drives the Mid-Month cadence. The shared compute lives in `weekly.py`
  (`compute_bid_tweaks` / `compute_harvest` with a `bleeder_acos_mult`) — no duplication.
- **Weekly Optimization — per-week panels (Week 1–5+)** — the Weekly panel now mirrors
  Daily Watch's calendar grid, but the cells are **weeks**: it starts with **Week 1–5**
  (minimum 5), **＋ add week** up to 53. Each week panel uploads its own SP bulk (upsert per
  week), weeks **accumulate into a week-over-week trend**, and an *Optimize week* selector
  picks which uploaded week's Search Term Report builds the bid-tweak + harvest plan
  (default = latest). Bulk downloads are named per week. Backed by a `week` column on
  `weekly_term_fact` (legacy single-snapshot data auto-migrates to Week 1).
- **Weekly Optimization — bid tweaks + search-term harvest** — the **Weekly** audit
  cadence has its own dedicated panel (like Daily Watch), **Sponsored Products only**,
  driven straight from the **SP Search Term Report** sheet in your bulk export. Every
  keyword/product-target gets a recomputed guardrailed bid, and every customer search term
  is classified (winner → promote to Exact / product target, loser → Negative Exact /
  Negative Product Targeting). Tick rows → download one Amazon-validated SP bulk file.
  Actions point at the **exact entity IDs** the report carries (Campaign / Ad Group /
  Keyword / Product Targeting ID) — kept as exact strings — with full ASIN-vs-keyword /
  no-type-mix / no-auto-promote / dedup safety. Stored in the Weekly cadence's **own table**
  (`weekly_term_fact`), so a Weekly bulk only ever drives the Weekly cadence.
- **Monitoring — multi-file upload** — the daily-report uploader now accepts **many
  files at once** (Business Reports + Sponsored Products reports together). They ingest
  sequentially (idempotent upsert by date) and the banner summarizes each file's days /
  type / range, listing any failures separately.
- **Amazon-Ads-style metric charts** — the Monitoring tracker and Daily Watch trend
  now use an interactive **metric explorer**: a row of metric chips (each showing its
  period total) where you pick **up to 2** to plot as a time-series line. Includes
  **CTR, CVR, ROAS, ACOS** plus Spend/Sales/Orders/Clicks/Impressions/CPC/TACOS. When
  the two metrics use different units they get their **own left/right y-axis** (like
  the Amazon Ads console); **hover** anywhere shows a tooltip with each metric's value,
  formatted by type (%, $, ×). New reusable `MetricChart.jsx`.
- **90% zoom + skeleton loaders** — the app now renders at 90% so dense tables fit
  on screen without a horizontal scrollbar. While data loads, panels show shimmering
  **skeleton placeholders** (table/stat/card shapes) instead of a spinner — Stores,
  Product Ads, PPC Audit table, Bid/Placement optimizer, Sales, Benchmark, Profit,
  Reports, Strategy, Monitoring, Keywords, Trends, Change Log, Users.
- **Each cadence is its own isolated dataset** — every Audit Cadence (Daily Watch,
  Weekly, Mid-Month, Full Month, Pause/Kill-Scale) now has its **own bulk upload and
  its own data**, stored in a separate db file. Uploading a bulk under **Weekly** only
  audits Weekly — its campaigns, flags, bid optimizer, placement optimizer, search-term
  harvest, n-gram miner, negatives, and pause/kill/scale tables **don't overlap** any
  other cadence. Switching cadence shows that cadence's data. **Shared** across all
  cadences (entered once): your **Goal ACoS**, **Product Costs**, **Benchmark**, and the
  **Monitoring** daily tracker. *Existing data stays as the **Full Month** cadence; the
  other cadences start empty until you upload a bulk to each.*
- **ASIN-rooted tree shows all ASINs** — the tree previously rendered only the
  single top-spend ASIN (the dashboard sent just one node). It now lists **every
  ASIN** as a collapsible row → expand to its **campaigns** → expand to each campaign's
  **ad groups → connected ads + targets**. Added a search box (ASIN / campaign) and
  per-ASIN rolled-up spend / ACoS.
- **Per-cadence audit tables** — each Audit Type now shows its **own focused table**
  from the uploaded bulk instead of the same full flag list: Weekly = bid-tweak
  targets (over-goal + overbid), Mid-Month = negatives & bid-adjust (wasted, over-goal,
  low-CTR), Pause/Scale = cut (bleeders, wasted) + scale (winners), Full Month = all
  flags. Daily Watch stays watch-only (spike tracker, no flag table). The table title
  + filter chips reflect the active cadence.
- **Daily Watch — calendar panels** — replaced the fixed Yesterday/Today pair with a
  **calendar-style grid of day panels**: start with one, click the **＋** tile to add
  another (up to **31** = a month), each with its own date + upload. Days accumulate
  into the trend; compare **any two** uploaded days from dropdowns (default = the two
  most recent). Previously-uploaded days reappear as filled panels.
- **Themed modals** — replaced the browser's grey pop-ups (New store / New audit
  prompts, and the Delete / Flush / Clear-keywords / Delete-user / Reset-password
  confirmations) with on-brand dark modals: clearer titles, full warning text,
  destructive actions in **red** with backdrop-dismiss disabled so you can't lose
  data by mis-clicking. The Product Ads "view selected" drill-down now opens in a
  centered modal (Esc or click-outside to close) instead of pushing the page down.
- **Daily Watch isolated storage** — Daily Watch now keeps its **own data table**
  (`DailyWatchFact`), fully separate from the main audit's snapshots. Uploading
  daily files for spike-tracking no longer touches (or shifts the "latest snapshot"
  of) the Weekly / Mid-Month / Full Month / Pause-Scale cadences — those share the
  one monthly bulk, Daily Watch is an independent daily time series. Flush clears it
  too.
- **Daily Watch (spike & anomaly tracker)** — selecting the **Daily Watch** audit
  type now opens a day-over-day panel under the PPC Audit cadence header: two upload
  slots (**Yesterday** / **Today**) that store each bulk file as a dated snapshot,
  a **Compare** that shows account deltas + per-campaign anomaly flags (spend spike,
  ACoS spike, sales drop, zero-order spend), and an accumulated Spend-vs-Sales trend
  chart. Watch-only (no bulk file emitted). New `pipeline/dailywatch.py`,
  `routers/dailywatch.py` (`/daily-watch/upload|days|compare|series`),
  `DailyWatch.jsx`.
- **Stores overview + PPC Audit cadence flow** — new **Stores** tab: all-stores KPI
  table (spend/sales/ACoS/ASINs/flags), click to open. PPC Audit now leads with an
  **Audit Cadence** header: store + month/year + five Audit Type presets
  (Daily/Weekly/Mid-Month/Full-Month/Pause-Scale) that re-tune the flag engine and
  carry an SOP effort checklist, saved per store·month·type. New
  `pipeline/cadence.py`, `models.CadenceRun/CadenceTask`, `routers/cadence.py`,
  `GET /stores/overview`, `audit_type` on `/audit` `/asins` `/dashboard`;
  `StoresOverview.jsx`, `AuditCadence.jsx`.
- **Binance-style UI redesign** — whole app reskinned to the Binance design language:
  near-black canvas, surface-card panels, hairline borders, a single **Binance Yellow**
  accent (black text on yellow CTAs), trading **green up / red down** for +/- values,
  Inter for copy + JetBrains Mono for all numbers, small radii, flat color-block depth.
  Token-driven so every screen restyles at once.
- **Monitoring · export .xlsx** — download the daily tracker for the selected range
  (Date · Total Sales · Units Ordered · Ad Spend · Ad Sales · Orders (PPC) · Clicks ·
  Impressions). Units Ordered = Business-Report units (already includes B2B); empty
  days export as 0. New `monitoring.export_xlsx`, `GET /monitoring/export`.
- **Monitoring · Actions & Recommendations** — data-driven next steps, segmented into
  **PPC** (TACOS/ACOS/ROAS/CTR/ad-CVR, traffic-vs-conversion) and **Listing** (buy box,
  CVR, refunds, price swing, traffic). Severity-ranked. `monitoring._recommendations`.
- **Monitoring · manual comparison sales** — when "vs last month" / "vs last year"
  has no uploaded daily data, the cell is now editable: type that month's total sales
  and growth % recomputes. Stored per month (`MonthSalesOverride`, `POST
  /monitoring/month-sales`); daily data always wins over a manual figure.
- **Collapsible sidebar** — hide/show the nav via the **☰** button in the header (or
  **‹‹** in the sidebar); more width for wide tables. State persists across reloads.
- **Monitoring · Overall Performance header** — month totals + overall ratios, vs
  last-month / vs last-year sales + growth %, run-rate month estimate, and a TACOS
  target flag (default 12%, configurable). New `monitoring._overview`; `GET
  /monitoring` takes `&target=`.
- **Monitoring · PPC ratio columns** — daily table now carries the derived PPC
  metrics matching the standard daily report: **ACOS, ROAS, CPC, CTR, CVR (ad
  orders ÷ clicks), TACOS (ad spend ÷ total sales)** — computed per day, never
  stored, "-" when no data. (`monitoring._row_dict`.)
- **Monitoring · Daily SALES & PPC Tracker** — new tab consolidating the daily
  Business Report + Sponsored Products report by date into an accumulating tracker.
  Month / custom date-range picker (missing days → "-"), day-over-day deltas, 7-day
  rolling lines, alerts (CVR-fall, buy-box <90%, refund spike >2×7d-avg & >3%, ASP
  ±15% swing), traffic-vs-CVR divergence (dual-axis chart), weekday/weekend, B2B
  split, and a 0–100 health badge. New `models.FactDaily`, `pipeline/monitoring.py`,
  `routers/monitoring.py`, `Monitoring.jsx`; charts via Chart.js (`chart.js` +
  `react-chartjs-2`). Idempotent ingest; percents stored as plain numbers.
- **Per-user data isolation** — every user now has their **own** stores + audits;
  data is never shared between accounts. Store directories are namespaced by user id
  (`u<id>__<store>`), translated transparently at the request boundary, so all
  pipeline routers are isolated with no per-router code. New users auto-get an empty
  *My Store*; the bundled demo lives only in **SAdmin**. User ids never reuse and
  deleting a user purges their data. Touches `database.py` (scoping + `get_db`),
  `auth.py`, `routers/stores.py`, `routers/costs.py`/`sales.py`, `main.py` seed.
- **Self sign-up** — login screen now has a Create-account toggle: username +
  password (6+ chars) → account created + auto signed-in. No email/OTP. Public
  `POST /auth/register` (normal user only). `Login.jsx` + `api.register`.
- **Authentication** — the app now requires login (username + password). Superuser
  **SAdmin / RootPass** seeded on first run; superusers manage accounts in a new
  **Users** tab. Server-side bearer-token sessions, **one active session per user**
  (new login revokes the old), 12h sliding expiry, stdlib PBKDF2 password hashing —
  no new dependencies, scales to 1000+ users. Central `data/auth.db`; every data API
  is gated, only `/auth/*` + `/health` are public. New `auth.py`, `routers/auth.py`,
  `Login.jsx`, `Users.jsx`; client attaches the token to every request and drops to
  the login screen on any 401.
- **Product Ads · AOV column** — added **AOV** (average order value = consolidated
  Ad Sales ÷ Orders per ASIN) alongside Unit Price (Ad Sales ÷ Units). Field `aov`.
- **Product Ads · Unit Price** — the price column now divides Ad Sales by **Units**
  (was Orders). An order can carry multiple units, so sales/orders over-stated the
  price; sales/units gives the true per-unit sale price even with many ads/campaigns
  per ASIN. Column renamed AOV → Unit Price (field `unit_price`).
- **Bulk upload: big-ID + invalid-keyword fixes** — fixed the bulk-file rejections:
  - **IDs read as strings** — Amazon's 16-18 digit IDs overflow float precision, so
    they were being mangled on read (→ "requires an actual Keyword ID, rather than a
    temporary ID" and ID collisions → "Duplicate Id"). `ingest` now reads every ID
    column as text and keeps it exact; generators emit IDs via `bulkfmt.idstr`.
  - **Keyword validation** — harvest now drops search terms that can't be Amazon
    keywords (over 80 chars / 10 words, control or ￼ / ™ / quote / slash chars) →
    no more "Keyword is invalid".
  - **More dedup** — generators skip promoting a keyword/ASIN product target that
    already exists in the ad group ("already exists"), and `automate` dedups every
    output row (update + create) so no "Duplicate Id" / "Duplicate Keyword Text".

  Note: a workbook with extra sheets like *Audit Recommendations* / *Bulk Upload
  Ready* or Sponsored-Display *Shopper Cohort* columns is **not** an app export —
  upload only the single *Sponsored Products Campaigns* sheet the app generates.
- **All tables: per-column filter funnel** — every numeric column header now has an
  Amazon-style **▾** filter: operator (greater than / ≥ / equals / ≤ / less than) +
  number input, in a portal popover (no clipping in scroll areas). Backed by the same
  filter engine as the composite bar, so the two stay in sync (`components/table.jsx`).
- **All tables: composite filters** — new **⛃ filters** builder in every table
  toolbar: stack multiple per-column conditions (AND-combined) on top of search +
  sort. Text ops (contains / is / is not / is empty), number ops (≥ > ≤ < = ≠ /
  between). Filterable columns are auto-derived from the data, so all ~17 tables get
  it with no per-table code (`components/table.jsx`).
- **Product Ads · multi-select drill-down** — select one+ ASINs (checkbox column /
  page select-all) → **view selected** opens a per-ASIN detail panel: all ads,
  audit actions (flags + bid/pause/negate), and strategy recommendations, with a
  roll-up stat strip. New `GET /product-ads/detail?asins=…` (`productads.detail`,
  reuses `build_tree` / `audit` / `strategy.analyze`).
- **Bulk files pass Amazon validation** — every generated bulk now routes negatives
  through a shared `bulkfmt` validity layer: ASIN search terms are negated as
  `asin="B0…"` **product targets** (not keywords), auto-campaign clauses (loose/
  close-match, substitutes, complements) are never emitted as negative product
  targets, and negatives that repeat in the file or **already exist in the account**
  are dropped — killing the "Duplicate Keyword Text" / "already exists" / "Unsupported
  negative targeting expression" rejections. To know what's already negated, uploads
  now store the account's existing Negative Keyword / Negative Product Targeting rows
  (excluded from audit/bid math). **Re-upload your bulk once** so the app learns your
  current negatives. Touches `bulkfmt.py`, `load.py`, `automate.py`, `harvest.py`,
  `audit.build_tree`.
- **All tables: search · sort · paginate** — new shared `components/table.jsx`
  (`useTableControls` hook + `TableToolbar` / `Th` / `Pagination`). Every data table
  (PPC Audit, Product Ads, Strategy, Keywords, Bid Optimizer, Placement, Harvest,
  N-gram, Trends, Sales, Benchmark, Costs, Profit P&L, Change Log, Reports winners/
  leaks) now has a search box, Excel-style per-column sort (A-Z / Z-A / off; numbers
  asc/desc), a 10 / 50 / 300 / All page-size selector, and prev/next pagination.
  Selections + bulk exports still use the full set. (Supersedes the Product-Ads-only
  search/pagination.)
- **Product Ads · AOV** — new column per ASIN: Ad Sales ÷ Orders when there are
  orders; **0 orders + ad spend → negative −spend** (red) to flag bleeding ASINs;
  no orders + no spend → Product Benchmark sale price. (Replaces the earlier Sell
  Price column.)
- **Strategy methodology map** — Strategy tab now opens with a visual decision-tree
  diagram (pull data → read ACoS vs break-even → 4 states → goal lever → metric
  engine → 90-day phases). New static `components/StrategyFlow.jsx`.
- **Change Log client reports** — Change Log tab now exports the trail for
  sending to a client: **⬇ .xlsx** (`ppc_change_log.xlsx`, Summary + full-log
  sheets) and **✉ report message** (copy-paste plain-text optimization summary).
  Both honor the source filter. New `GET /changelog/export` + `GET
  /changelog/report` (`changelog.export_xlsx` / `changelog.report_text`).
- **Product Ads tab** — every Product Ad (ASIN + SKU) from the Bulk PPC file with
  current metrics (spend, sales, orders, clicks, impressions, ACOS, ROAS, CPC, CTR,
  CVR) + an exact account total. New `GET /product-ads` (`pipeline/productads.py`).
  Rows consolidated by (ASIN, SKU) — duplicate ads merged, counts summed, rates
  recomputed, `×N` badge for merge count. Per-product **status** (no campaign / no
  traffic / no orders / converting) surfaces ASINs that need a push or a new
  campaign; action items sort to top + a header attention banner.
- **Bid guardrails** — new `pipeline/bid_optimizer.py` (pure, one `CONFIG` dict):
  data-threshold skip, hard caps, and per-cycle step limits for every bid/placement
  change. Retrofitted into Bid Optimizer + Placement Optimizer (placement caps now
  0–150 / 0–200 instead of 0–900; bids gain absolute $ caps + step limits; raises
  require ≥3 orders). Step-limited rows are labeled.
- **Bulk-file validity fixes** — harvest now emits ASIN search terms as
  (Negative) Product Targeting (`asin="..."`) instead of keywords, collapses
  duplicate rows, and never negates Automatic-campaign clauses (loose/close-match,
  substitutes, complements); the automate export skips those clauses too. Harvest
  also no longer suggests promotes Amazon rejects — positives into Auto campaigns
  ("only negatives allowed") or keyword/product-target mixes in one ad group ("ad
  group cannot have both"). Fixes those bulk upload errors. ("Already exists" rows
  are harmless re-suggested negatives, not failures.)
- **Keyword mining** (new Keywords tab) — consolidate Brand Analytics SQP +
  Helium10 Cerebro (deduped by phrase) + generic-keyword recommendations.
- Uploads accept **CSV** everywhere (bulk, STR, Business Report, benchmark).
- Fix: Harvest + N-gram results lifted to app state — survive tab switches and are
  shared across the PPC and Uploads panels; Upload Central step 5 now ticks ✓ and
  embeds both Harvest + N-gram.
- **Uploads tab (Upload Central)** — all uploads in one numbered stepper with live
  ✓ per step + required-progress bar + per-step template links.
- Benchmark: **default COGS %** fallback (unit cost blank/0 → % of selling price)
  and **Profit/unit** = Price − (COGS + Amazon fee), shown per product.
- Bulk upload auto-harvests an embedded **SP Search Term Report** sheet if present
  (optional; skipped when absent), pre-loading candidates into the Harvest panel.
- Schema: star-schema FKs now `ON DELETE CASCADE` with SQLite FK enforcement
  enabled (deleting a campaign removes its ad-groups → targets/ads). Loader defers
  FK checks to commit so any insert order is fine. New audits get the cascade
  schema; the seed was re-created on it.
- Fix: deleting a store/audit no longer resurrects it — the UI switches away
  first so no in-flight refresh re-creates it via `get_db` auto-create.
- **Delete** — store-level (cascades to all audits + benchmark) and audit-level
  (`DELETE /stores/{store}`, `DELETE /projects/{project}`); `🗑` buttons in the
  sidebar, guarded against deleting the last store/audit.
- Fix: account PPC **ad cost / ACoS / TACoS / net profit** now use Entity=campaign
  Spend (each campaign once) instead of the ASIN rollup, which double-counted
  multi-ASIN campaigns (was inflating ad cost ~18× on real data).
- Template downloads served from `preferred_templates/` (`/templates/{kind}`) with
  `⬇ template` links on every uploader; all real exports verified end-to-end.
- Strategy **one-click bulk** (`POST /strategy/bulk`) for Exact Scaling /
  Negative Sculpting / Placement / Budget; **store-wide Product Benchmark**
  (upload once per store, all audits match against it).
- **Per-audit checklist** — auto items (computed from state) + manual tasks
  (`/checklist` CRUD); on the Dashboard with a progress bar.
- **Strategy Advisor** — 16-strategy playbook runner (`GET /strategy`): per-campaign
  recommendations routed to the executing engine + playbook status board.
- ASIN tree: state separation (Enabled/Paused/Archived) — filter + dots, archived
  hidden by default.
- **Change Log / Audit Trail** — every bulk export auto-logs its actions
  (old → new + reason); new Change Log sidebar section + `GET /changelog`.
- UI: left **sidebar** nav (was top tabs); store/audit selectors + flush moved there.
- Blank upload **templates** in `templates/` (bulk, STR, business report, benchmark).
- Per-audit **flush** button + `POST /flush` (wipe one audit's data, keep the audit).
- Bid optimization: **Bid Optimizer** (full-portfolio target-CPC bids) and
  **Placement Optimizer** (ToS/PP/Rest %), both with bulk export. Placement data
  (`Bidding Adjustment` rows) now loaded into `FactPlacement`.
- Reporting summary: Reports tab (account health, KPIs, period delta, action
  checklist, top winners/leaks) + Excel export (`/report/summary`, `/report/export`).
- Performance: single `/dashboard` call per refresh + cached ASIN tree.
- Snapshot-consistency fixes (current period everywhere), per-ASIN goal override,
  manual-total alignment, attribution warning.
- Goal ROAS control; Product Benchmark upload + BLEEDING flag.
- Profit P&L layer + tabbed dashboard (Dashboard / PPC Audit / Sales & Costs).
- Sales report (Organic + PPC + TACoS), reporting summary KPIs, bid ladder.
- Scale Winners, Trend tracking, N-gram miner.
- Per-audit Goal ACoS; Store → Audit hierarchy; multi-store isolation.
- Search-term harvest (winners → Exact, losers → Negative Exact).
