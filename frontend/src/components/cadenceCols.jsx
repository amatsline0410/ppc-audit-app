import React from 'react'
import { money } from './ui.jsx'

// Shared cell formatters + DataTable column defs for the cadence panels (Weekly /
// Mid-Month / Full Month / Pause-Scale), so every cadence table is identical in
// design, sorting and filtering. `value` feeds sort/filter; `render` is display.
export const m2 = (x) => (x == null ? '—' : `$${Number(x).toFixed(2)}`)
export const pp = (x) => (x == null ? '—' : `${(Number(x) * 100).toFixed(0)}%`)   // fraction → %
export const bidKey = (b) => `${b.kind}:${b.id}`
export const hKey = (h) => `${h.ad_group_id}|${h.search_term.toLowerCase()}`
export const cKey = (c) => `camp:${c.campaign_id}`

const trunc = (txt, w, cls = 'text-slate-100') =>
  <span className={`truncate inline-block align-bottom ${cls}`} style={{ maxWidth: w }} title={txt}>{txt}</span>

// bid adjustment / tweak table (keyword + product-target updates)
export const bidCols = [
  { key: 'label', label: 'Target', render: b => trunc(b.label, 240) },
  { key: 'kind', label: 'Type', render: b => (b.kind === 'keyword' ? `kw · ${b.match_type || ''}` : 'product') },
  { key: 'clicks', label: 'Clicks', align: 'right', cellClass: 'text-mute' },
  { key: 'orders', label: 'Orders', align: 'right', cellClass: 'text-mute' },
  { key: 'acos', label: 'ACoS', align: 'right', cellClass: 'text-mute', value: b => b.acos, render: b => pp(b.acos) },
  { key: 'current_bid', label: 'Bid', align: 'right', render: b => (
      b.overbid
        ? <span className="text-down font-semibold" title="Overbid — bid is above the hard cap or far over the observed CPC; reset in one pass">{m2(b.current_bid)} ⚠</span>
        : <span className="text-mute">{m2(b.current_bid)}</span>) },
  { key: 'suggested_bid', label: '→ New', align: 'right', render: b => (
      <span className={`font-semibold ${b.direction === 'raise' ? 'text-up' : 'text-down'}`}>
        {m2(b.suggested_bid)} <span className="text-[10px]">({b.delta > 0 ? '+' : ''}{b.delta})</span>
      </span>) },
  { key: 'reason', label: 'Why', render: b => trunc(b.reason, 220, 'text-mute') },
]

// break-even column + ACoS coloring, for cadences whose plan rows carry
// `break_even` (the ad group's product break-even ACoS: benchmark upload wins,
// else catalog listing price + per-SKU COGS + real Transactions-ledger fees).
// withBE(cols) inserts the BE column after ACoS and recolors the ACoS cell
// red/green against it.
export const beCol = {
  key: 'break_even', label: 'BE ACoS', align: 'right', cellClass: 'text-mute',
  value: r => r.break_even ?? -1,
  render: r => r.break_even != null
    ? <span title="the ad group's product break-even ACoS (catalog + real Transactions-ledger fees)">{pp(r.break_even)}</span>
    : '—',
}

// ML columns — empirical-Bayes smoothed CVR + a calibrated confidence (present
// only when the row was stamped by pipeline/ml.py; withML() appends them for
// any cadence table whose rows carry `row.ml`, no-op otherwise).
function ConfidenceCell({ ml }) {
  if (!ml || ml.confidence == null) return <span className="text-mute">—</span>
  const pct = ml.confidence * 100
  const cls = pct >= 90 ? 'text-up' : pct >= 70 ? 'text-amber' : 'text-down'
  return <span className={cls} title="calibrated confidence this decision is correct, from the account's own conversion-rate posterior">{pct.toFixed(0)}%</span>
}

export const mlCols = [
  { key: 'ml_cvr', label: 'Smoothed CVR', align: 'right', cellClass: 'text-mute',
    value: r => r.ml?.cvr_smoothed ?? -1,
    render: r => r.ml
      ? <span title={`90% credible interval ${pp(r.ml.cvr_lo)}–${pp(r.ml.cvr_hi)} · empirical-Bayes shrinkage toward the account's own conversion rate — corrects raw rates on thin click data`}>{pp(r.ml.cvr_smoothed)}</span>
      : '—' },
  { key: 'ml_confidence', label: 'ML Confidence', align: 'right',
    value: r => r.ml?.confidence ?? -1, render: r => <ConfidenceCell ml={r.ml} /> },
]

export function withML(cols) {
  return [...cols, ...mlCols]
}

export function withBE(cols) {
  const i = cols.findIndex(c => c.key === 'acos')
  if (i < 0) return [...cols, beCol]
  const acos = {
    ...cols[i], cellClass: '',
    render: r => (
      <span className={r.break_even != null && r.acos != null ? (r.acos > r.break_even ? 'text-down' : 'text-up') : 'text-mute'}
        title={r.break_even != null ? `break-even ${(r.break_even * 100).toFixed(1)}% — red = above it (losing money per sale)` : ''}>
        {pp(r.acos)}
      </span>),
  }
  return [...cols.slice(0, i), acos, beCol, ...cols.slice(i + 1)]
}

// harvest table — kind: 'promote' | 'negate' | 'bleeder'
export function harvestCols(kind) {
  const promote = kind === 'promote'
  const showAcos = kind !== 'negate'
  const cols = [
    { key: 'search_term', label: 'Search Term', render: h => trunc(h.search_term, 220) },
    { key: 'as', label: 'As', cellClass: 'text-mute', render: h => (h.as === 'product_target' ? 'product (ASIN)' : 'keyword') },
    { key: 'ad_group_name', label: 'Ad Group', cellClass: 'text-mute', value: h => h.ad_group_name || h.ad_group_id,
      render: h => trunc(h.ad_group_name || h.ad_group_id, 200, 'text-mute') },
    { key: 'clicks', label: 'Clicks', align: 'right', cellClass: 'text-mute' },
    { key: 'spend', label: 'Spend', align: 'right', cellClass: promote ? 'text-mute' : 'text-down', render: h => money(h.spend) },
    { key: 'orders', label: 'Orders', align: 'right', cellClass: promote ? 'text-up' : 'text-mute' },
  ]
  if (showAcos) cols.push({ key: 'acos', label: 'ACoS', align: 'right', cellClass: promote ? 'text-mute' : 'text-down', value: h => h.acos, render: h => pp(h.acos) })
  if (promote) cols.push({ key: 'suggested_bid', label: 'Bid', align: 'right', cellClass: 'text-slate-100', render: h => m2(h.suggested_bid) })
  return cols
}

// pause/scale tables
export const scaleCols = [
  { key: 'label', label: 'Target', render: r => trunc(r.label, 240) },
  { key: 'kind', label: 'Type', cellClass: 'text-mute', render: r => (r.kind === 'keyword' ? `kw · ${r.match_type || ''}` : 'product') },
  { key: 'clicks', label: 'Clicks', align: 'right', cellClass: 'text-mute' },
  { key: 'orders', label: 'Orders', align: 'right', cellClass: 'text-up' },
  { key: 'acos', label: 'ACoS', align: 'right', cellClass: 'text-mute', value: r => r.acos, render: r => pp(r.acos) },
  { key: 'current_bid', label: 'Bid', align: 'right', cellClass: 'text-mute', render: r => m2(r.current_bid) },
  { key: 'suggested_bid', label: '→ New', align: 'right', render: r => (
      <span className="font-semibold text-up">{m2(r.suggested_bid)} <span className="text-[10px]">(+{r.delta})</span></span>) },
]

export const pauseCols = [
  { key: 'label', label: 'Target', render: r => trunc(r.label, 240) },
  { key: 'kind', label: 'Type', cellClass: 'text-mute', render: r => (r.kind === 'keyword' ? `kw · ${r.match_type || ''}` : 'product') },
  { key: 'clicks', label: 'Clicks', align: 'right', cellClass: 'text-mute' },
  { key: 'spend', label: 'Spend', align: 'right', cellClass: 'text-down', render: r => money(r.spend) },
  { key: 'orders', label: 'Orders', align: 'right', cellClass: 'text-mute' },
]

export const campaignCols = [
  { key: 'name', label: 'Campaign', render: c => trunc(c.name, 320) },
  { key: 'clicks', label: 'Clicks', align: 'right', cellClass: 'text-mute' },
  { key: 'spend', label: 'Spend', align: 'right', cellClass: 'text-down', render: c => money(c.spend) },
  { key: 'orders', label: 'Orders', align: 'right', cellClass: 'text-mute' },
]
