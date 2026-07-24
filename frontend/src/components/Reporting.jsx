import React from 'react'
import { money, pct } from './ui.jsx'

function Kpi({ label, value, accent, hint, big }) {
  return (
    <div className="card p-3" title={hint || ''}>
      <div className="text-mute text-[10px] font-mono uppercase tracking-wider">{label}</div>
      <div className={`mt-1 font-mono font-bold ${big ? 'text-xl' : 'text-lg'} ${accent || 'text-slate-100'}`}>{value}</div>
    </div>
  )
}

// Top-of-dashboard reporting summary. Drives off /report; degrades gracefully
// before a sales report is loaded (organic/total/TACoS show as —).
export function ReportSummary({ report, targetAcos }) {
  const s = report?.sales || {}
  const L = report?.ladder || {}
  const hasTotal = s.total_sales != null
  const acos = s.acos
  const tacos = s.tacos

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <Kpi label="ad spend" value={money(s.ppc_spend)} />
        <Kpi label="ppc sales" value={money(s.ppc_sales)} />
        <Kpi label="organic sales" value={hasTotal ? money(s.organic_sales) : '—'}
          accent={hasTotal ? 'text-lime' : 'text-mute'} hint={hasTotal ? '' : 'load a Sales report to compute organic'} />
        <Kpi label="total sales" value={hasTotal ? money(s.total_sales) : '—'}
          hint={hasTotal ? '' : 'load a Sales report'} />
        <Kpi label="acos" value={pct(acos)} big
          accent={acos != null && acos > targetAcos ? 'text-red' : 'text-lime'} />
        <Kpi label="tacos" value={hasTotal ? pct(tacos) : '—'} big
          accent={!hasTotal ? 'text-mute' : (tacos != null && tacos > targetAcos ? 'text-amber' : 'text-cyan')}
          hint={hasTotal ? 'ad spend ÷ total sales — true cost of growth' : 'load a Sales report for TACoS'} />
      </div>

      <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
        <Kpi label="flags" value={report?.flags?.total ?? '—'} accent="text-amber" />
        <Kpi label="reduce bid" value={L.reduce ?? 0} accent="text-cyan" hint="ladder: cut bid toward goal" />
        <Kpi label="monitor" value={L.monitor ?? 0} accent="text-amber" hint="ladder: cut, now watching" />
        <Kpi label="pause" value={L.pause ?? 0} accent="text-red" hint="ladder: persistent loser — stop" />
        <Kpi label="scale ▲" value={report?.scale_winners ?? 0} accent="text-lime" hint="profitable, raise bid" />
        <Kpi label="wasted spend" value={money(report?.wasted_spend)} accent="text-red" />
      </div>
    </div>
  )
}
