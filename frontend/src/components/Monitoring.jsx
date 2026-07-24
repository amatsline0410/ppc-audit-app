import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { Spinner, money, StatsSkeleton, CardSkeleton, Icon } from './ui.jsx'
import { useTableControls, TableToolbar, Pagination, Th } from './table.jsx'
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, Tooltip, Legend, Filler,
} from 'chart.js'
import { Line, Chart } from 'react-chartjs-2'
import { MetricChart } from './MetricChart.jsx'
import { useModals } from './Modal.jsx'
import { useToast } from './Toast.jsx'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, Tooltip, Legend, Filler)

// Amazon-Ads-style metric registry for the daily tracker (CTR/CVR/ROAS/ACOS first).
const MON_METRICS = [
  { key: 'acos', label: 'ACOS', kind: 'pct', get: r => r.acos },
  { key: 'roas', label: 'ROAS', kind: 'ratio', get: r => r.roas },
  { key: 'ctr', label: 'CTR', kind: 'pct', get: r => r.ctr },
  { key: 'cvr', label: 'CVR', kind: 'pct', get: r => r.ppc_cvr },
  { key: 'tacos', label: 'TACOS', kind: 'pct', get: r => r.tacos },
  { key: 'cpc', label: 'CPC', kind: 'money', get: r => r.cpc },
  { key: 'ordered_sales', label: 'Total Sales', kind: 'money', get: r => r.ordered_sales },
  { key: 'ppc_spend', label: 'Ad Spend', kind: 'money', get: r => r.ppc_spend },
  { key: 'ppc_sales', label: 'Ad Sales', kind: 'money', get: r => r.ppc_sales },
  { key: 'ppc_orders', label: 'Orders', kind: 'count', get: r => r.ppc_orders },
  { key: 'ppc_clicks', label: 'Clicks', kind: 'count', get: r => r.ppc_clicks },
  { key: 'ppc_impressions', label: 'Impressions', kind: 'count', get: r => r.ppc_impressions },
]

// percents are stored as plain numbers (24.03); dash for missing.
const dash = (x) => (x == null ? '—' : x)
const p = (x) => (x == null ? '—' : `${Number(x).toFixed(2)}%`)
const m = (x) => (x == null ? '—' : money(x))
const n = (x) => (x == null ? '—' : Number(x).toLocaleString())
const d2 = (x) => (x == null ? '—' : Number(x).toFixed(2))

const GRID = 'rgba(255,255,255,0.06)'
const TICK = '#7a8694'
const baseOpts = {
  responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
  plugins: { legend: { labels: { color: TICK, font: { family: 'monospace', size: 10 } } } },
  scales: { x: { grid: { color: GRID }, ticks: { color: TICK, font: { size: 9 }, maxRotation: 0, autoSkip: true } } },
}

// up=green / down=red delta chip
function Delta({ d, fmt = (x) => x }) {
  if (!d || d.abs == null) return <span className="text-mute">—</span>
  const up = d.abs >= 0
  return (
    <span className={up ? 'text-up' : 'text-down'}>
      {up ? '▲' : '▼'} {fmt(Math.abs(d.abs))}{d.pct != null && <span className="text-mute"> ({d.pct >= 0 ? '+' : ''}{d.pct}%)</span>}
    </span>
  )
}

function HealthBadge({ h }) {
  if (!h || h.score == null) return <span className="tag border border-edge text-mute">health —</span>
  const c = h.band === 'green' ? 'bg-lime text-ink' : h.band === 'amber' ? 'bg-amber text-ink' : 'bg-red text-white'
  return <span className={`tag ${c} font-bold`} title={JSON.stringify(h.parts)}>health {h.score}/100</span>
}

const ALERT_CLR = { high: 'border-red/40 text-red', medium: 'border-amber/40 text-amber' }
const SEV_DOT = { high: 'text-rose-400', medium: 'text-amber-400', low: 'text-mute' }

// one bucket of recommendations (PPC or Listing)
function RecList({ title, items }) {
  return (
    <div className="card">
      <div className="p-3 border-b border-edge text-mute text-[11px] font-mono uppercase tracking-wider">{title} · {items.length}</div>
      <div className="divide-y divide-edge/40 max-h-80 overflow-auto">
        {items.map((r, i) => (
          <div key={i} className="p-3 font-mono text-xs flex items-start gap-2">
            <span className={`${SEV_DOT[r.severity] || 'text-mute'} font-bold`}><Icon name="circle" size={10} /></span>
            <div className="min-w-0">
              <div className="text-slate-200">{r.title}</div>
              <div className="text-mute mt-0.5">{r.action}</div>
            </div>
          </div>
        ))}
        {items.length === 0 && <div className="p-4 text-center text-mute font-mono text-xs">no actions — looking healthy ✓</div>}
      </div>
    </div>
  )
}

// month <input type=month> value helpers
const ym = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
const iso = (d) => d.toISOString().slice(0, 10)

// "Overall Performance" header strip — month totals + overall ratios + vs last
// month / last year + run-rate estimate. Mirrors the reporting-overview report.
function Cell({ label, value, sub, accent }) {
  return (
    <div className="px-3 py-2 border-r border-edge/40 last:border-0 min-w-[92px]">
      <div className="text-mute text-[9px] font-mono uppercase tracking-wider whitespace-nowrap">{label}</div>
      <div className={`font-mono text-sm font-bold mt-0.5 whitespace-nowrap ${accent || 'text-slate-100'}`}>{value}</div>
      {sub != null && <div className="text-[10px] font-mono text-mute whitespace-nowrap">{sub}</div>}
    </div>
  )
}
function Growth({ g }) {
  if (g == null) return <span className="text-mute">—</span>
  return <span className={g >= 0 ? 'text-up' : 'text-down'}>{g >= 0 ? '+' : ''}{g}%</span>
}
// vs last-month / last-year cell. When that month has no daily data ('manual'/'none')
// it becomes an editable input so you can type the figure in.
function CompareCell({ label, c, onSet }) {
  const editable = c.source !== 'daily'
  const [v, setV] = useState(c.sales ?? '')
  useEffect(() => { setV(c.sales ?? '') }, [c.sales, c.source])
  function save() {
    const num = v === '' ? null : parseFloat(v)
    if ((num ?? null) !== (c.sales ?? null)) onSet(c.year, c.month, isNaN(num) ? null : num)
  }
  return (
    <div className="px-3 py-2 border-r border-edge/40 min-w-[110px]">
      <div className="text-mute text-[9px] font-mono uppercase tracking-wider whitespace-nowrap">{label}{c.source === 'manual' && <span className="text-amber-400"> ·manual</span>}</div>
      {editable ? (
        <input value={v} onChange={e => setV(e.target.value)} onBlur={save}
          onKeyDown={e => e.key === 'Enter' && e.target.blur()} inputMode="decimal" placeholder="enter $"
          className="bg-panel border border-edge rounded px-1 py-0.5 mt-0.5 font-mono text-sm font-bold text-cyan w-24 focus:outline-none focus:border-lime" />
      ) : (
        <div className="font-mono text-sm font-bold mt-0.5 text-cyan whitespace-nowrap">{m(c.sales)}</div>
      )}
      <div className="text-[10px] font-mono"><Growth g={c.growth} /></div>
    </div>
  )
}
function Overview({ o, onSetMonth }) {
  if (!o) return null
  return (
    <div className="card overflow-x-auto">
      <div className="px-3 py-2 border-b border-edge text-mute text-[11px] font-mono uppercase tracking-wider flex items-center justify-between gap-2">
        <span>overall performance</span>
        <span className={o.tacos_below_target ? 'text-lime' : 'text-rose-400'}>
          TACOS {o.tacos == null ? '—' : `${o.tacos}%`} {o.tacos_below_target ? `≤ target ${o.target_tacos}% ✓` : `> target ${o.target_tacos}%`}
        </span>
      </div>
      <div className="flex items-stretch divide-x divide-edge/40">
        <Cell label="TACOS" value={o.tacos == null ? '—' : `${o.tacos}%`} accent={o.tacos_below_target ? 'text-lime' : 'text-rose-400'} />
        <Cell label="Total Sales" value={m(o.total_sales)} accent="text-lime" />
        <Cell label="Units Ordered" value={n(o.units_ordered)} />
        <Cell label="Ad Spend" value={m(o.ad_spend)} />
        <Cell label="Ad Sales" value={m(o.ad_sales)} />
        <Cell label="Orders (PPC)" value={n(o.ppc_orders)} />
        <Cell label="Clicks" value={n(o.clicks)} />
        <Cell label="Impressions" value={n(o.impressions)} />
        <Cell label="ACOS" value={o.acos == null ? '—' : `${o.acos}%`} />
        <Cell label="ROAS" value={o.roas == null ? '—' : `${d2(o.roas)}×`} />
        <Cell label="CPC" value={o.cpc == null ? '—' : `$${d2(o.cpc)}`} />
        <Cell label="CTR" value={o.ctr == null ? '—' : `${o.ctr}%`} />
        <Cell label="CVR" value={o.cvr == null ? '—' : `${o.cvr}%`} />
        <CompareCell label={`vs ${o.last_month.label}`} c={o.last_month} onSet={onSetMonth} />
        <CompareCell label={`vs ${o.last_year.label}`} c={o.last_year} onSet={onSetMonth} />
        <Cell label={`${o.estimate.label} est. sales`} value={m(o.estimate.sales)} sub={`run-rate · day ${o.estimate.day}/${o.estimate.days_in_month}`} accent="text-amber" />
      </div>
    </div>
  )
}

export function MonitoringPanel({ scope }) {
  const toast = useToast()
  const { confirm } = useModals()
  const today = new Date()
  const [start, setStart] = useState(iso(new Date(today.getFullYear(), today.getMonth(), 1)))
  const [end, setEnd] = useState(iso(today))
  const [target, setTarget] = useState(12)   // TACOS target %
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [up, setUp] = useState(null)        // last upload result
  const inputRef = useRef()

  function load() {
    setBusy(true); setErr(null)
    api.monitoring(start, end, target).then(setData).catch(e => setErr(String(e))).finally(() => setBusy(false))
  }
  useEffect(() => { load() }, [scope, start, end, target])   // eslint-disable-line

  async function upload(files) {
    const list = Array.from(files || [])
    if (!list.length) return
    setBusy(true); setErr(null); setUp(null)
    const ok = []; const fails = []
    // upload sequentially — each report is an idempotent upsert by date
    for (const f of list) {
      try { ok.push({ name: f.name, ...(await api.uploadMonitoring(f)) }) }
      catch (e) { fails.push(`${f.name}: ${String(e.message || e)}`) }
    }
    const totalDays = ok.reduce((a, r) => a + (r.days || 0), 0)
    setUp({ files: ok, total_days: totalDays, fails })
    if (ok.length) toast.success(`Uploaded ${totalDays} day(s) from ${ok.length} file(s)`)
    if (fails.length) { setErr(`${fails.length} file(s) failed:\n${fails.join('\n')}`); toast.error(`${fails.length} file(s) failed to upload`) }
    load()
  }
  async function clearAll() {
    const ok = await confirm({
      title: 'Clear Monitoring data?', danger: true, confirmLabel: 'Clear data',
      message: 'Removes every uploaded tracker day (Business Report + Sponsored Products daily data) for '
        + 'this audit. Manual month-sales figures you typed into the overview are kept.'
        + '\n\nThis cannot be undone — re-upload the daily reports to rebuild.',
    })
    if (!ok) return
    try {
      await api.monitoringClear()
      setUp(null); setErr(null)
      toast.success('Cleared Monitoring data')
      load()
    } catch (e) { setErr(String(e.message || e)); toast.error(String(e.message || e)) }
  }
  async function exportXlsx() {
    setErr(null)
    try {
      const blob = await api.monitoringExport(start, end, target)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = `daily_tracker_${start}_${end}.xlsx`; a.click()
      URL.revokeObjectURL(url)
      toast.success('Daily tracker exported to .xlsx')
    } catch (e) { setErr(String(e.message || e)); toast.error(String(e.message || e)) }
  }
  // pick a whole month with one control
  function pickMonth(v) {
    if (!v) return
    const [y, mo] = v.split('-').map(Number)
    setStart(`${v}-01`)
    setEnd(iso(new Date(y, mo, 0)))   // day 0 of next month = last day of this month
  }

  const rows = data?.rows || []
  const ctl = useTableControls(rows, { searchKeys: ['date', 'weekday'], deps: [scope, start, end] })

  // chart x-labels (gaps stay as null -> broken line)
  const labels = rows.map(r => r.date.slice(5))   // MM-DD
  // divergence dual-axis: sessions bars (left) + CVR line (right)
  const divChart = {
    labels,
    datasets: [
      { type: 'bar', label: 'Sessions', data: rows.map(r => r.sessions), backgroundColor: 'rgba(45,189,182,0.35)', yAxisID: 'y' },
      { type: 'line', label: 'CVR %', data: rows.map(r => r.unit_session_pct), borderColor: '#FCD535', tension: 0.3, spanGaps: false, pointRadius: 0, yAxisID: 'y1' },
    ],
  }
  const divOpts = {
    ...baseOpts,
    scales: {
      ...baseOpts.scales,
      y: { position: 'left', grid: { color: GRID }, ticks: { color: TICK, font: { size: 9 } }, title: { display: true, text: 'sessions', color: TICK } },
      y1: { position: 'right', grid: { drawOnChartArea: false }, ticks: { color: TICK, font: { size: 9 } }, title: { display: true, text: 'CVR %', color: TICK } },
    },
  }

  const ww = data?.weekday_weekend || {}
  const b2b = data?.b2b || {}

  return (
    <div className="space-y-6">
      {/* controls */}
      <div className="card p-4 flex items-end gap-4 flex-wrap">
        <div>
          <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-1">month</div>
          <input type="month" onChange={e => pickMonth(e.target.value)}
            className="bg-panel border border-edge rounded px-2 py-1.5 font-mono text-xs text-slate-100 focus:outline-none focus:border-lime" />
        </div>
        <div>
          <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-1">from</div>
          <input type="date" value={start} onChange={e => setStart(e.target.value)}
            className="bg-panel border border-edge rounded px-2 py-1.5 font-mono text-xs text-slate-100 focus:outline-none focus:border-lime" />
        </div>
        <div>
          <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-1">to</div>
          <input type="date" value={end} onChange={e => setEnd(e.target.value)}
            className="bg-panel border border-edge rounded px-2 py-1.5 font-mono text-xs text-slate-100 focus:outline-none focus:border-lime" />
        </div>
        <div>
          <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-1">TACOS target %</div>
          <input type="number" step="0.5" value={target} onChange={e => setTarget(parseFloat(e.target.value) || 0)}
            className="bg-panel border border-edge rounded px-2 py-1.5 font-mono text-xs text-slate-100 w-20 focus:outline-none focus:border-lime" />
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={exportXlsx} disabled={!data || !data.data_days} className="btn btn-ghost text-xs disabled:opacity-40 inline-flex items-center gap-1"><Icon name="download" size={14} /> export .xlsx</button>
          <input ref={inputRef} type="file" accept=".csv,.xlsx,.xlsm" multiple hidden
            onChange={e => { upload(e.target.files); e.target.value = '' }} />
          <button onClick={() => inputRef.current?.click()} disabled={busy} aria-busy={busy}
            className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
            <Icon name={busy ? 'sync' : 'upload'} size={14} />{busy ? 'Reading…' : 'Upload Daily Reports'}</button>
          {data?.data_days > 0 && (
            <button onClick={clearAll} className="btn btn-ghost text-xs flex items-center gap-1 hover:text-down">
              <Icon name="delete" size={14} /> Clear
            </button>
          )}
        </div>
        {data?.upload_meta?.files?.length > 0 && (
          <div className="w-full text-xs text-mute font-mono flex gap-3 flex-wrap pt-1">
            {data.upload_meta.files.map(f => (
              <span key={f.name} title={`uploaded ${f.uploaded || ''} · ${f.kind === 'business' ? 'Business Report' : 'Sponsored Products'}`}>
                <Icon name="description" size={11} className="align-[-1px]" /> {f.name} · {f.days}d
              </span>
            ))}
            {data.upload_meta.updated && <span>updated {data.upload_meta.updated}</span>}
          </div>
        )}
      </div>
      {up && up.files?.length > 0 && (
        <div className="card border-lime/30 p-2 font-mono text-xs text-lime space-y-0.5">
          <div className="inline-flex items-center gap-1"><Icon name="check_circle" size={14} /> ingested {up.total_days} day(s) from {up.files.length} file(s){up.fails?.length ? ` · ${up.fails.length} failed` : ''}</div>
          {up.files.map((f, i) => (
            <div key={i} className="text-mute">· {f.name} → {f.days} day(s), {f.kind === 'business' ? 'Business Report' : 'Sponsored Products'}{f.range ? ` (${f.range[0]} → ${f.range[1]})` : ''}</div>
          ))}
        </div>
      )}
      {err && <div className="card border-red/40 p-3 font-mono text-sm text-red inline-flex items-center gap-1"><Icon name="warning" size={14} /> {err}</div>}

      {busy && !data && <div className="space-y-5"><StatsSkeleton count={5} /><CardSkeleton lines={6} /></div>}

      {data && <Overview o={data.overview} onSetMonth={(y, mo, v) => api.setMonthSales(y, mo, v).then(() => { toast.success('Month sales saved'); load() }).catch(e => { setErr(String(e)); toast.error(String(e)) })} />}

      {data && (
        <>
          {/* headline: latest day + health + divergence */}
          <div className="card p-4">
            <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
              <div className="text-mute text-[11px] font-mono uppercase tracking-wider">
                daily tracker · {data.range.start} → {data.range.end} · {data.data_days} days of data{data.missing_days ? ` · ${data.missing_days} missing` : ''}
              </div>
              <div className="flex items-center gap-2">
                {data.divergence && <span className="tag bg-red/15 text-red border border-red/30 inline-flex items-center gap-1"><Icon name="warning" size={12} /> traffic up / CVR down</span>}
                <HealthBadge h={data.health} />
              </div>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              {[['Sales', data.deltas.ordered_sales, m], ['Units', data.deltas.units_ordered, n],
                ['Sessions', data.deltas.sessions, n], ['CVR', data.deltas.unit_session_pct, (x) => `${d2(x)}%`],
                ['ASP', data.deltas.asp, m], ['Buy Box', data.deltas.buy_box_pct, (x) => `${d2(x)}%`]].map(([lbl, dd, fmt]) => (
                <div key={lbl} className="card p-2">
                  <div className="text-mute text-[10px] font-mono uppercase tracking-wider">{lbl} Δ vs prior day</div>
                  <div className="font-mono text-sm mt-1"><Delta d={dd} fmt={fmt} /></div>
                </div>
              ))}
            </div>
          </div>

          {/* alerts */}
          {data.alerts.length > 0 && (
            <div className="space-y-2">
              {data.alerts.map((a, i) => (
                <div key={i} className={`card p-3 font-mono text-sm border inline-flex items-center gap-1 ${ALERT_CLR[a.severity] || 'border-edge text-mute'}`}><Icon name="warning" size={14} /> {a.msg}</div>
              ))}
            </div>
          )}

          {/* actions & recommendations — segmented PPC vs Listing */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <RecList title="PPC actions & recommendations" items={(data.recommendations || []).filter(r => r.category === 'ppc')} />
            <RecList title="Listing actions & recommendations" items={(data.recommendations || []).filter(r => r.category === 'listing')} />
          </div>

          {/* metric explorer — Amazon-Ads-style: pick up to 4 metrics, dual-axis */}
          <div className="card p-4">
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-3">metric explorer · pick up to 4 · hover for values</div>
            <MetricChart labels={labels} rows={rows} metrics={MON_METRICS} defaults={['acos', 'roas']} height={300} max={4} />
          </div>
          <div className="card p-4">
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-2">traffic vs conversion · sessions (bars) vs CVR (line)</div>
            <div className="h-64"><Chart type="bar" data={divChart} options={divOpts} /></div>
          </div>

          {/* weekday/weekend + B2B */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="card">
              <div className="p-3 border-b border-edge text-mute text-[11px] font-mono uppercase tracking-wider">weekday vs weekend</div>
              <table className="w-full text-sm font-mono">
                <thead><tr className="text-mute text-[11px] uppercase border-b border-edge"><th className="p-2 text-left">Segment</th><th className="p-2 text-right">Avg Sales</th><th className="p-2 text-right">Avg CVR</th><th className="p-2 text-right">Days</th></tr></thead>
                <tbody>
                  {[['Mon–Fri', ww.weekday], ['Sat–Sun', ww.weekend]].map(([lbl, s]) => (
                    <tr key={lbl} className="border-b border-edge/40"><td className="p-2 text-slate-200">{lbl}</td><td className="p-2 text-right">{m(s?.avg_sales)}</td><td className="p-2 text-right">{p(s?.avg_cvr)}</td><td className="p-2 text-right text-mute">{dash(s?.days)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card">
              <div className="p-3 border-b border-edge text-mute text-[11px] font-mono uppercase tracking-wider">B2B vs total (B2C+B2B)</div>
              <table className="w-full text-sm font-mono">
                <thead><tr className="text-mute text-[11px] uppercase border-b border-edge"><th className="p-2 text-left">Metric</th><th className="p-2 text-right">Total</th><th className="p-2 text-right">B2B</th><th className="p-2 text-right">B2B %</th></tr></thead>
                <tbody>
                  {[['Sales', b2b.sales, m], ['Units', b2b.units, n], ['CVR (avg)', b2b.cvr, (x) => p(x)]].map(([lbl, s, fmt]) => {
                    const share = s && s.total ? `${((s.b2b || 0) / s.total * 100).toFixed(1)}%` : '—'
                    return <tr key={lbl} className="border-b border-edge/40"><td className="p-2 text-slate-200">{lbl}</td><td className="p-2 text-right">{fmt(s?.total)}</td><td className="p-2 text-right">{fmt(s?.b2b)}</td><td className="p-2 text-right text-cyan">{lbl.startsWith('CVR') ? '—' : share}</td></tr>
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* daily table */}
          <div className="card">
            <TableToolbar ctl={ctl} placeholder="search date / weekday…" />
            <div className="overflow-x-auto">
              <table className="w-full text-sm font-mono">
                <thead><tr className="text-mute text-[11px] uppercase tracking-wider border-b border-edge">
                  <Th ctl={ctl} k="date">Date</Th><Th ctl={ctl} k="weekday">Day</Th>
                  <Th ctl={ctl} k="ordered_sales" align="right">Total Sales</Th><Th ctl={ctl} k="units_ordered" align="right">Units</Th>
                  <Th ctl={ctl} k="ppc_spend" align="right">Ad Spend</Th><Th ctl={ctl} k="ppc_sales" align="right">Ad Sales</Th>
                  <Th ctl={ctl} k="ppc_orders" align="right">Orders (PPC)</Th><Th ctl={ctl} k="ppc_clicks" align="right">Clicks</Th>
                  <Th ctl={ctl} k="ppc_impressions" align="right">Impr</Th><Th ctl={ctl} k="acos" align="right">ACOS</Th>
                  <Th ctl={ctl} k="roas" align="right">ROAS</Th><Th ctl={ctl} k="cpc" align="right">CPC</Th>
                  <Th ctl={ctl} k="ctr" align="right">CTR</Th><Th ctl={ctl} k="ppc_cvr" align="right">CVR</Th>
                  <Th ctl={ctl} k="tacos" align="right">TACOS</Th>
                  <Th ctl={ctl} k="sessions" align="right">Sessions</Th><Th ctl={ctl} k="asp" align="right">ASP</Th>
                  <Th ctl={ctl} k="buy_box_pct" align="right">Buy Box</Th><Th ctl={ctl} k="refund_rate" align="right">Refund</Th>
                  <Th ctl={ctl} k="unit_session_pct" align="right">Sess CVR</Th>
                </tr></thead>
                <tbody>
                  {ctl.view.map(r => (
                    <tr key={r.date} className={`border-b border-edge/40 hover:bg-edge/20 ${r.weekend ? 'bg-edge/10' : ''}`}>
                      <td className="p-2 text-slate-200 whitespace-nowrap">{r.date}</td>
                      <td className={`p-2 ${r.weekend ? 'text-amber-400' : 'text-mute'}`}>{r.weekday}</td>
                      <td className="p-2 text-right">{m(r.ordered_sales)}</td>
                      <td className="p-2 text-right">{n(r.units_ordered)}</td>
                      <td className="p-2 text-right">{m(r.ppc_spend)}</td>
                      <td className="p-2 text-right">{m(r.ppc_sales)}</td>
                      <td className="p-2 text-right">{n(r.ppc_orders)}</td>
                      <td className="p-2 text-right">{n(r.ppc_clicks)}</td>
                      <td className="p-2 text-right">{n(r.ppc_impressions)}</td>
                      <td className="p-2 text-right">{p(r.acos)}</td>
                      <td className="p-2 text-right">{r.roas == null ? '—' : `${d2(r.roas)}×`}</td>
                      <td className="p-2 text-right">{r.cpc == null ? '—' : `$${d2(r.cpc)}`}</td>
                      <td className="p-2 text-right">{p(r.ctr)}</td>
                      <td className="p-2 text-right">{p(r.ppc_cvr)}</td>
                      <td className="p-2 text-right text-cyan">{p(r.tacos)}</td>
                      <td className="p-2 text-right">{n(r.sessions)}</td>
                      <td className="p-2 text-right">{m(r.asp)}</td>
                      <td className={`p-2 text-right ${r.buy_box_pct != null && r.buy_box_pct < 90 ? 'text-rose-400' : ''}`}>{p(r.buy_box_pct)}</td>
                      <td className={`p-2 text-right ${r.refund_rate != null && r.refund_rate > 3 ? 'text-rose-400' : ''}`}>{p(r.refund_rate)}</td>
                      <td className="p-2 text-right">{p(r.unit_session_pct)}</td>
                    </tr>
                  ))}
                  {ctl.view.length === 0 && <tr><td colSpan={20} className="p-6 text-center text-mute">no days in range — upload a daily report</td></tr>}
                </tbody>
              </table>
            </div>
            <Pagination ctl={ctl} />
          </div>
        </>
      )}
    </div>
  )
}
