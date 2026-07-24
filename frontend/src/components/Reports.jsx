import React, { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { money, pct, CardSkeleton, StatsSkeleton, Icon } from './ui.jsx'
import { DataTable } from './table.jsx'
import { useToast } from './Toast.jsx'

const HEALTH = {
  healthy: 'border-lime/40 text-lime', leaking: 'border-amber/40 text-amber',
  ad_heavy: 'border-amber/40 text-amber', unprofitable: 'border-red/40 text-red',
  insufficient_data: 'border-edge text-mute',
}
const dMoney = (x) => (x == null ? '—' : (x >= 0 ? '+' : '−') + '$' + Math.abs(Math.round(x)).toLocaleString())
const dPct = (x) => (x == null ? '—' : (x >= 0 ? '+' : '−') + (Math.abs(x) * 100).toFixed(1) + 'pt')
const sign = (x, goodDown = false) => (x == null || x === 0 ? 'text-mute' : (goodDown ? x < 0 : x > 0) ? 'text-lime' : 'text-red')

function Tile({ label, value, accent }) {
  return (
    <div className="card p-3">
      <div className="text-mute text-[10px] font-mono uppercase tracking-wider">{label}</div>
      <div className={`mt-1 text-lg font-mono font-bold ${accent || 'text-slate-100'}`}>{value}</div>
    </div>
  )
}

// Reporting summary: exec report + Excel export. Read-only over the live audit.
export function ReportsPanel({ scope, targetAcos }) {
  const toast = useToast()
  const [d, setD] = useState(null)
  const [busy, setBusy] = useState(false)
  const [dl, setDl] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let live = true
    setBusy(true); setErr(null)
    api.reportSummary(targetAcos).then(r => live && setD(r)).catch(e => live && setErr(String(e)))
      .finally(() => live && setBusy(false))
    return () => { live = false }
  }, [scope, targetAcos])

  async function download() {
    setDl(true); setErr(null)
    try {
      const blob = await api.reportExport(targetAcos)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'ppc_report.xlsx'; a.click()
      URL.revokeObjectURL(url)
      toast.success('Excel report downloaded')
    } catch (e) { setErr(String(e)); toast.error(String(e)) }
    finally { setDl(false) }
  }

  if (busy && !d) return (
    <div className="space-y-5"><StatsSkeleton count={4} /><CardSkeleton lines={5} /></div>
  )
  if (err) return <div className="card border-red/40 p-3 font-mono text-sm text-red inline-flex items-center gap-1"><Icon name="warning" size={14} /> {err}</div>
  if (!d) return null

  const k = d.kpis || {}
  const A = d.actions || {}
  // action checklist as a table list: what to do, how many targets, where to run it
  const ACTION_ROWS = [
    { action: 'Cut bleeding', n: A.cut_bleeding, cls: 'text-red',
      what: 'Targets above break-even — losing money on every ad sale', tool: 'PPC Optimization → flag table' },
    { action: 'Negate wasted', n: A.negate_wasted, cls: 'text-red',
      what: 'Spend with zero orders — add as Negative Exact', tool: 'Keywords → Search-Term Harvest' },
    { action: 'Pause', n: A.pause, cls: 'text-red',
      what: 'Bid-ladder end stage — reduced & monitored, still losing', tool: 'PPC Optimization → flag table' },
    { action: 'Reduce bid', n: A.reduce_bid, cls: 'text-cyan',
      what: 'Over goal ACoS — first ladder step, cut the bid', tool: 'PPC Optimization → Bid Optimizer' },
    { action: 'Monitor', n: A.monitor, cls: 'text-amber',
      what: 'Bid already reduced — watch before pausing', tool: 'PPC Optimization → flag table' },
    { action: 'Scale winners', n: A.scale_winners, cls: 'text-lime',
      what: 'Under goal with orders — raise bid / budget', tool: 'PPC Optimization → Bid Optimizer' },
  ]
  const MOVER_COLS = [
    { key: 'name', label: 'Campaign', render: r => <span className="inline-block max-w-[260px] truncate align-bottom text-slate-200" title={r.name}>{r.name || r.campaign_id}</span> },
    { key: 'spend_delta', label: 'Spend Δ', align: 'right',
      render: r => <span className={r.spend_delta > 0 ? 'text-down' : r.spend_delta < 0 ? 'text-up' : 'text-mute'}>{dMoney(r.spend_delta)}</span> },
    { key: 'spend_cur', label: 'Spend', align: 'right', render: r => money(r.spend_cur) },
    { key: 'sales_cur', label: 'Sales', align: 'right', render: r => money(r.sales_cur) },
    { key: 'orders_delta', label: 'Orders Δ', align: 'right',
      render: r => <span className={sign(r.orders_delta)}>{r.orders_delta > 0 ? `+${r.orders_delta}` : r.orders_delta}</span> },
    { key: 'acos_cur', label: 'ACoS', align: 'right', cellClass: 'text-mute',
      render: r => `${r.acos_prev != null ? pct(r.acos_prev) : '—'} → ${r.acos_cur != null ? pct(r.acos_cur) : '—'}` },
  ]

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className={`card px-4 py-3 border ${HEALTH[d.health.status] || 'border-edge'}`}>
          <span className="font-mono text-[10px] uppercase tracking-wider text-mute">account health</span>
          <div className="font-mono font-bold text-lg">{d.health.label}</div>
          <div className="font-mono text-xs text-mute">{d.health.note}</div>
        </div>
        <div className="flex items-center gap-3">
          <span className="font-mono text-xs text-mute">snapshot {d.snapshot || '—'} · goal {pct(d.target_acos)} / {d.target_roas}×</span>
          <button onClick={download} disabled={dl} aria-busy={dl} className="btn btn-primary">{dl ? 'building…' : <><Icon name="download" size={14} /> Excel report</>}</button>
        </div>
      </div>

      {/* headline PPC KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <Tile label="ad spend" value={money(k.ad_spend)} accent="text-amber" />
        <Tile label="ad sales" value={money(k.ad_sales)} />
        <Tile label="acos" value={k.acos != null ? pct(k.acos) : '—'} accent={k.acos > d.target_acos ? 'text-red' : 'text-lime'} />
        <Tile label="avg product acos" value={k.avg_product_acos != null ? pct(k.avg_product_acos) : '—'}
          accent={k.avg_product_acos == null ? 'text-mute' : k.avg_product_acos > d.target_acos ? 'text-red' : 'text-lime'} />
        <Tile label="over break-even" value={A.cut_bleeding ?? 0}
          accent={A.cut_bleeding ? 'text-red' : 'text-lime'} />
        <Tile label="wasted" value={money(d.wasted_spend)} accent="text-red" />
      </div>

      {/* period delta */}
      {d.period && (
        <div className="card p-4">
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-2">vs previous · {d.period.previous} → {d.period.current}</div>
          <div className="grid grid-cols-4 gap-3 font-mono">
            <Tile label="spend Δ" value={dMoney(d.period.delta.spend)} accent={sign(d.period.delta.spend, true)} />
            <Tile label="sales Δ" value={dMoney(d.period.delta.sales)} accent={sign(d.period.delta.sales)} />
            <Tile label="orders Δ" value={d.period.delta.orders >= 0 ? `+${d.period.delta.orders}` : d.period.delta.orders} accent={sign(d.period.delta.orders)} />
            <Tile label="acos Δ" value={dPct(d.period.delta.acos)} accent={sign(d.period.delta.acos, true)} />
          </div>
        </div>
      )}

      {/* account states — the Strategy methodology classifier, exec view */}
      {d.states && (
        <div className="card">
          <div className="p-4 border-b border-edge">
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider">account states · acos vs break-even, per campaign</div>
          </div>
          <div className="p-4 grid grid-cols-2 md:grid-cols-5 gap-3">
            {[['below_target', 'below target · grow', 'text-up'],
              ['at_target', 'at target · balance', 'text-cyan'],
              ['above_target', 'above target · cut', 'text-amber'],
              ['over_break_even', 'over break-even · cut hard', 'text-down'],
              ['no_data', 'no data · rank', 'text-mute']].map(([k, label, cls]) => (
              <div key={k}>
                <div className="text-mute text-[10px] font-mono uppercase tracking-wider">{label}</div>
                <div className={`mt-0.5 text-xl font-mono font-bold ${cls}`}>{(d.states.counts?.[k] ?? 0).toLocaleString()}</div>
              </div>
            ))}
          </div>
          {(d.states.top || []).length > 0 && (
            <DataTable title="top spenders classified" lean leanRows={10}
              columns={[
                { key: 'state', label: 'State', value: x => x.state,
                  render: x => { const M = { below_target: ['Below target', 'text-up border-up/40'], at_target: ['At target', 'text-cyan border-cyan/40'], above_target: ['Above target', 'text-amber border-amber/40'], over_break_even: ['Over break-even', 'text-down border-down/40'], no_data: ['No data', 'text-mute border-edge'] }
                    const [label, cls] = M[x.state] || [x.state, 'text-mute border-edge']
                    return <span className={`tag border whitespace-nowrap ${cls}`}>{label}</span> } },
                { key: 'campaign', label: 'Campaign', render: x => (
                    <span className="inline-block max-w-[260px] truncate align-bottom text-slate-200" title={x.campaign}>{x.campaign || x.campaign_id}</span>) },
                { key: 'spend', label: 'Spend', align: 'right', render: x => money(x.spend) },
                { key: 'acos', label: 'ACoS / BE', align: 'right', value: x => x.acos ?? 9,
                  render: x => (
                    <span>
                      <span className={x.break_even != null && x.acos != null ? (x.acos > x.break_even ? 'text-down' : 'text-up') : 'text-mute'}>
                        {x.acos != null ? pct(x.acos) : x.spend ? '∞' : '—'}
                      </span>
                      <span className="text-mute"> / {x.break_even != null ? pct(x.break_even) : '—'}</span>
                    </span>) },
                { key: 'lever', label: 'Lever', render: x => <span className="text-cyan text-xs whitespace-nowrap">{x.lever}</span> },
                { key: 'why', label: 'Why', cellClass: 'text-mute text-xs',
                  render: x => <span className="inline-block max-w-[260px] truncate align-bottom" title={x.why}>{x.why}</span> },
              ]}
              rows={d.states.top} rowKey={x => x.campaign_id} empty="no campaigns" />
          )}
        </div>
      )}

      {/* action checklist — table list (was a 6-number grid) */}
      <div className="card">
        <DataTable title={`action checklist · ${d.flags.total} flags`} lean leanRows={10}
          columns={[
            { key: 'n', label: '#', align: 'right', value: r => r.n || 0,
              render: r => <span className={`font-bold text-base ${r.n ? r.cls : 'text-mute'}`}>{r.n || 0}</span> },
            { key: 'action', label: 'Action', render: r => <span className="text-slate-200 whitespace-nowrap">{r.action}</span> },
            { key: 'what', label: 'What it means', cellClass: 'text-mute text-xs',
              render: r => <span className="inline-block max-w-[360px] truncate align-bottom" title={r.what}>{r.what}</span> },
            { key: 'tool', label: 'Run in', render: r => <span className="text-cyan text-xs whitespace-nowrap">{r.tool}</span> },
          ]}
          rows={ACTION_ROWS} rowKey={r => r.action} empty="no actions"
          initial={{ sort: { key: 'n', dir: 'desc' } }} />
      </div>

      {/* top movers vs previous snapshot — table list (was unrendered) */}
      {(d.movers || []).length > 0 && (
        <div className="card">
          <DataTable title={`top movers · vs previous snapshot · ${d.movers.length}`} lean leanRows={10}
            columns={MOVER_COLS} rows={d.movers} rowKey={r => r.campaign_id}
            empty="no movers" initial={{ sort: { key: 'spend_delta', dir: 'desc' } }} />
        </div>
      )}

      {/* SEO recommendations — catalog listing quality + Product Optimization projects */}
      {d.seo && <SeoReport seo={d.seo} />}
    </div>
  )
}

function SeoReport({ seo }) {
  const c = seo.catalog
  return (
    <div className="card p-4 space-y-4">
      <div className="text-mute text-[11px] font-mono uppercase tracking-wider">seo · listing quality &amp; keyword coverage</div>

      {c && (
        <div className="space-y-2">
          <div className="font-mono text-xs">
            <span className={c.with_issues ? 'text-amber' : 'text-lime'}>{c.with_issues}</span>
            <span className="text-mute"> of {c.products} catalog products carry high/medium listing issues</span>
          </div>
          <div className="flex gap-1.5 flex-wrap">
            {Object.entries(c.by_area).sort((a, b) => b[1] - a[1]).map(([a, n]) => (
              <span key={a} className="tag border border-edge text-mute">{a.replace('_', ' ')} · <span className="text-amber">{n}</span></span>
            ))}
          </div>
          {c.worst.length > 0 && (
            <DataTable title="worst offenders" lean leanRows={10}
              columns={[
                { key: 'issues', label: '#', align: 'right', render: p => <span className="text-down font-bold">{p.issues}</span> },
                { key: 'title', label: 'Product', render: p => <span className="inline-block max-w-[320px] truncate align-bottom text-slate-200" title={p.title}>{p.title || '—'}</span> },
                { key: 'sku', label: 'SKU', cellClass: 'text-mute' },
                { key: 'asin', label: 'ASIN', cellClass: 'text-mute', render: p => p.asin || '—' },
                { key: 'high', label: 'High', align: 'right', render: p => p.high ? <span className="text-down">{p.high}</span> : <span className="text-mute">0</span> },
              ]}
              rows={c.worst} rowKey={p => p.sku} empty="none" />
          )}
        </div>
      )}

      {seo.projects.length > 0 && (
        <DataTable title="product optimization projects · keyword-based recs" lean leanRows={10}
          columns={[
            { key: 'name', label: 'Project', render: p => <span className="inline-block max-w-[260px] truncate align-bottom text-slate-200" title={p.name}>{p.name}</span> },
            { key: 'keywords', label: 'Keywords', align: 'right', render: p => p.keywords.toLocaleString() },
            { key: 'high', label: 'High', align: 'right', render: p => p.high ? <span className="text-down">{p.high}</span> : <span className="text-mute">0</span> },
            { key: 'medium', label: 'Med', align: 'right', render: p => p.medium ? <span className="text-amber">{p.medium}</span> : <span className="text-mute">0</span> },
            { key: 'st_current_bytes', label: 'Backend field', align: 'right',
              render: p => p.st_over
                ? <span className="tag border border-down/40 text-down whitespace-nowrap">{p.st_current_bytes}B &gt; 249B</span>
                : <span className="text-mute">{p.st_current_bytes}B</span> },
            { key: 'top', label: 'Work in', cellClass: 'text-mute text-xs',
              value: p => p.top_keywords.join(', '),
              render: p => <span className="inline-block max-w-[280px] truncate align-bottom" title={p.top_keywords.join(', ')}>{p.top_keywords.join(', ') || '—'}</span> },
          ]}
          rows={seo.projects} rowKey={p => p.id} empty="no projects" />
      )}
      <div className="font-mono text-[10px] text-mute">
        Full detail: Product Benchmark (per-product listing issues) · Product Optimization → SEO / Listing Audit (keyword coverage + the 249-byte backend line).
      </div>
    </div>
  )
}
