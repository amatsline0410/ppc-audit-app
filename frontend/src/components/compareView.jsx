import React from 'react'
import { money, Icon } from './ui.jsx'
import { DataTable } from './table.jsx'

// Shared period-over-period compare result (Daily Watch / Weekly / Mid-Month /
// Full Month). `cmp` = { account, campaigns, flags }; `heading` = the period label
// (e.g. "Week 1 → Week 2" or "Previous → Current").
const SEV = { high: 'text-down border-down/40', med: 'text-amber border-amber/40', low: 'text-mute border-edge' }
const ppN = (x) => (x == null ? '—' : `${Number(x).toFixed(1)}%`)   // acos = percent number

// account delta card (invert: a rising value is bad → red). noPct: hide % change.
function Delta({ label, cell, fmt, invert, noPct }) {
  const up = cell.delta != null && cell.delta > 0
  const good = cell.delta == null || cell.delta === 0 ? null : (invert ? !up : up)
  const color = good == null ? 'text-mute' : good ? 'text-up' : 'text-down'
  return (
    <div className="card p-2">
      <div className="text-mute text-[9px] font-mono uppercase tracking-wider">{label}</div>
      <div className="font-mono text-sm font-bold text-slate-100 mt-0.5">{fmt(cell.cur)}</div>
      <div className={`font-mono text-[10px] ${color}`}>
        {cell.delta == null ? '—' : `${cell.delta > 0 ? '+' : ''}${fmt(cell.delta)}`}
        {!noPct && cell.pct != null ? ` (${cell.pct > 0 ? '+' : ''}${cell.pct}%)` : ''}
      </div>
    </div>
  )
}

// per-campaign movers table (spend rising = bad/red, sales rising = good/green)
const CMP_COLS = [
  { key: 'name', label: 'Campaign', render: r => <span className="truncate inline-block align-bottom text-slate-100" style={{ maxWidth: 260 }} title={r.name}>{r.name}</span> },
  { key: 'spend_delta', label: 'Spend Δ', align: 'right', render: r => (
      <span className={r.spend_delta > 0 ? 'text-down' : r.spend_delta < 0 ? 'text-up' : 'text-mute'}>
        {r.spend_delta > 0 ? '+' : ''}{money(r.spend_delta)}{r.spend_pct != null ? ` (${r.spend_pct > 0 ? '+' : ''}${r.spend_pct}%)` : ''}
      </span>) },
  { key: 'sales_delta', label: 'Sales Δ', align: 'right', render: r => (
      <span className={r.sales_delta > 0 ? 'text-up' : r.sales_delta < 0 ? 'text-down' : 'text-mute'}>
        {r.sales_delta > 0 ? '+' : ''}{money(r.sales_delta)}
      </span>) },
  { key: 'acos_cur', label: 'ACoS', align: 'right', cellClass: 'text-mute', render: r => `${ppN(r.acos_prev)} → ${ppN(r.acos_cur)}` },
  { key: 'orders_cur', label: 'Orders', align: 'right', cellClass: 'text-mute' },
]

export function CompareResult({ cmp, heading }) {
  const a = cmp.account
  return (
    <div className="px-4 pb-4 space-y-4 border-t border-edge pt-4">
      <div className="text-mute text-[10px] font-mono uppercase tracking-wider">{heading}</div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        <Delta label="Ad Spend" cell={a.spend} fmt={money} invert />
        <Delta label="Ad Sales" cell={a.sales} fmt={money} />
        <Delta label="Clicks" cell={a.clicks} fmt={(x) => x} />
        <Delta label="Orders" cell={a.orders} fmt={(x) => x} />
        <Delta label="ACoS" cell={a.acos} fmt={ppN} invert noPct />
      </div>

      <div>
        <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-2">anomalies · {cmp.flags.length}</div>
        {cmp.flags.length === 0
          ? <div className="font-mono text-xs text-up inline-flex items-center gap-1"><Icon name="check_circle" size={12} /> No spikes or anomalies.</div>
          : <div className="space-y-1">
              {cmp.flags.map((f, i) => (
                <div key={i} className={`flex items-start gap-2 font-mono text-xs border-l-2 pl-2 ${SEV[f.severity] || SEV.low}`}>
                  <span className="uppercase text-[9px] mt-0.5">{f.severity}</span>
                  <span><span className="text-slate-200">{f.campaign}</span> — {f.message}</span>
                </div>
              ))}
            </div>}
      </div>

      <DataTable columns={CMP_COLS} rows={cmp.campaigns} rowKey={(r) => r.campaign_id} lean
        empty="no campaign rows" placeholder="search campaign…"
        initial={{ sort: { key: 'spend_delta', dir: 'desc' } }} />
    </div>
  )
}
