import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { Spinner, money, Icon } from './ui.jsx'
import { MetricChart } from './MetricChart.jsx'
import { DataTable } from './table.jsx'
import { useModals } from './Modal.jsx'
import { useToast } from './Toast.jsx'
import { MLInsights } from './MLInsights.jsx'

const MAX_PANELS = 31   // one calendar month
const DAY_MS = 86400000
const iso = (d) => d.toISOString().slice(0, 10)
const addDays = (isoStr, n) => iso(new Date(new Date(isoStr).getTime() + n * DAY_MS))
const dayNum = (isoStr) => new Date(isoStr).getDate()   // calendar day-of-month
const cleanErr = (e) => String(e?.message || e).replace(/^Error:\s*/, '')
const pp = (x) => (x == null ? '—' : `${Number(x).toFixed(1)}%`)
const SEV = { high: 'text-down border-down/40', med: 'text-amber border-amber/40', low: 'text-mute border-edge' }
let _pid = 0

// Daily Watch — the Daily cadence's anomaly tracker. A calendar-style grid of
// per-day upload panels: start with one, hit ＋ to add another (up to 31 = a
// month). Each panel uploads one day's bulk; days accumulate into a trend, and
// any two can be compared for spend spikes / anomalies. Watch-only.
export function DailyWatch({ scope, targetAcos, onStage }) {
  const toast = useToast()
  const { confirm } = useModals()
  const today = iso(new Date())
  const [panels, setPanels] = useState([{ id: ++_pid, date: today, totals: null }])
  const [days, setDays] = useState([])           // uploaded dates (server)
  const [trend, setTrend] = useState([])         // accumulated daily totals
  const [cmpA, setCmpA] = useState('')           // compare: earlier day
  const [cmpB, setCmpB] = useState('')           // compare: later day
  const [cmp, setCmp] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [mons, setMons] = useState(null)         // isolated monitor area
  const [anomalies, setAnomalies] = useState([]) // ML robust-anomaly scan

  function loadMonitors() {
    api.dailyWatchMonitors(targetAcos).then(setMons).catch(() => {})
  }
  async function watch(campaignId, name) {
    try {
      const r = await api.dailyWatchMonitor(campaignId, name)
      toast.success(r.added ? `Monitoring “${name}”` : 'Already monitored')
      loadMonitors()
    } catch (e) { toast.error(cleanErr(e)) }
  }
  async function unwatch(campaignId, name) {
    try { await api.dailyWatchUnmonitor(campaignId); toast.success(`Stopped monitoring “${name}”`); loadMonitors() }
    catch (e) { toast.error(cleanErr(e)) }
  }

  // load accumulated days; seed one panel per uploaded day so prior data shows.
  function refresh(seed = false) {
    api.dailyWatchSeries().then(d => {
      const ds = d.days || []
      setTrend(ds)
      setDays(ds.map(x => x.date))
      if (seed && ds.length) {
        setPanels(ds.map(x => ({ id: ++_pid, date: x.date, totals: x })))
      }
    }).catch(() => {})
    api.dailyWatchAnomalies().then(d => setAnomalies(d.anomalies || [])).catch(() => setAnomalies([]))
  }
  useEffect(() => {
    setPanels([{ id: ++_pid, date: today, totals: null }]); setCmp(null); setErr(null)
    refresh(true); loadMonitors()
  }, [scope])  // eslint-disable-line

  // default the compare selects to the two most-recent uploaded days
  useEffect(() => {
    if (days.length >= 2) { setCmpB(days[days.length - 1]); setCmpA(days[days.length - 2]) }
    else { setCmpA(''); setCmpB('') }
  }, [days.join(',')])  // eslint-disable-line
  // funnel progress — watch-only cadence (no download step)
  useEffect(() => { onStage?.({ uploaded: days.length > 0, hasRows: days.length > 0, downloaded: false }) }, [days.length])  // eslint-disable-line

  function addPanel() {
    setErr(null)
    setPanels(ps => {
      if (ps.length >= MAX_PANELS) return ps
      const last = ps[ps.length - 1]?.date || today
      return [...ps, { id: ++_pid, date: addDays(last, 1), totals: null }]
    })
  }
  async function removePanel(id) {
    let removed
    setPanels(ps => {
      if (ps.length <= 1) return ps
      removed = ps.find(p => p.id === id)
      return ps.filter(p => p.id !== id)
    })
    // if that panel had uploaded data, delete the day server-side so it doesn't re-seed
    if (removed?.totals && removed.date) {
      try { await api.dailyWatchDelete(removed.date); toast.success(`Day ${removed.date} removed`); refresh() }
      catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    }
  }
  // wipe every uploaded day at once (grid resets to a single today panel)
  async function clearAll() {
    setErr(null)
    const ok = await confirm({
      title: 'Clear all Daily Watch data?', danger: true, confirmLabel: 'Clear all',
      message: `This permanently deletes all ${days.length} uploaded day${days.length === 1 ? '' : 's'} of Daily Watch data (trend + compares). `
        + 'Watch-only cadence — nothing else is affected.\n\nThis cannot be undone — re-upload the daily bulks to rebuild.',
    })
    if (!ok) return
    try {
      await api.dailyWatchClearAll()
      setPanels([{ id: ++_pid, date: today, totals: null }]); setCmp(null)
      refresh()
      toast.success('Cleared all Daily Watch data')
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
  }

  function setPanelDate(id, date) { setPanels(ps => ps.map(p => (p.id === id ? { ...p, date } : p))) }
  function setPanelTotals(id, totals) { setPanels(ps => ps.map(p => (p.id === id ? { ...p, totals } : p))) }

  async function doCompare() {
    setErr(null); setCmp(null)
    if (!cmpA || !cmpB) { setErr('Pick two uploaded days to compare.'); return }
    if (cmpA === cmpB) { setErr('Pick two different days to compare.'); return }
    if (!days.includes(cmpA) || !days.includes(cmpB)) {
      setErr('Please add your files to compare data — both days must be uploaded first.'); return
    }
    setBusy(true)
    try { setCmp(await api.dailyWatchCompare(cmpA, cmpB, targetAcos)) }
    catch (e) { setErr(cleanErr(e)) }
    finally { setBusy(false) }
  }

  const uploaded = panels.filter(p => p.totals).length

  return (
    <div className="card">
      <div className="p-4 border-b border-edge flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider">daily watch · spike & anomaly tracker</div>
          <div className="font-mono text-xs text-mute mt-1">Add a panel per day, upload its bulk → accumulate a trend & flag spikes. Watch-only.</div>
        </div>
        <div className="flex items-center gap-3">
          <div className="font-mono text-[10px] text-mute">{days.length} day{days.length === 1 ? '' : 's'} uploaded · {panels.length}/{MAX_PANELS} panels</div>
          {days.length > 0 && (
            <button onClick={clearAll} className="btn btn-ghost text-xs flex items-center gap-1 hover:text-down">
              <Icon name="delete" size={14} /> Clear
            </button>
          )}
        </div>
      </div>

      {/* calendar grid of day panels + the add tile */}
      <div className="p-4 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-2">
        {panels.map((p, i) => (
          <DayPanel key={p.id} index={i} panel={p} removable={panels.length > 1}
            onDate={(d) => setPanelDate(p.id, d)} onRemove={() => removePanel(p.id)}
            onUploaded={(res) => {
              setPanelTotals(p.id, res.totals); toast.success(`Day ${p.date} uploaded`); refresh()
              const cl = res.monitor_cleared || []
              if (cl.length) toast.success(`${cl.length} monitored campaign${cl.length === 1 ? '' : 's'} aligned to goal — cleared: ${cl.map(c => c.name).join(', ')}`)
              loadMonitors()
            }} setErr={setErr} toast={toast} targetAcos={targetAcos} />
        ))}
        {panels.length < MAX_PANELS && (
          <button onClick={addPanel} title="Add another day"
            className="rounded-lg border border-dashed border-edge hover:border-primary text-mute hover:text-primary
                       flex flex-col items-center justify-center gap-1 min-h-[128px] transition-colors">
            <Icon name="add" size={28} />
            <span className="font-mono text-[10px] uppercase tracking-wider">add day</span>
          </button>
        )}
      </div>

      {/* isolated monitor area — watched campaigns, auto-cleared on alignment */}
      {mons && (mons.active.length > 0 || mons.cleared.length > 0) && (
        <MonitorCard mons={mons} onUnwatch={unwatch} />
      )}

      {/* compare any two uploaded days */}
      <div className="px-4 pb-4 flex items-end gap-2 flex-wrap border-t border-edge pt-4">
        <DaySelect label="Compare" value={cmpA} onChange={setCmpA} days={days} />
        <span className="font-mono text-mute text-xs pb-2">→</span>
        <DaySelect label="with" value={cmpB} onChange={setCmpB} days={days} />
        <button onClick={doCompare} disabled={busy || days.length < 2} aria-busy={busy}
          className="btn btn-primary disabled:opacity-50">{busy ? 'Comparing…' : 'Compare'}</button>
        {days.length < 2 && !err && (
          <div className="font-mono text-xs text-mute pb-2">Please add your files to compare data — upload at least two days above.</div>
        )}
      </div>
      {err && <div className="mx-4 mb-4 card border-down/40 p-2 font-mono text-xs text-down">⚠ {err}</div>}

      {cmp && <CompareResult cmp={cmp} onWatch={watch}
        watched={new Set((mons?.active || []).map(w => w.campaign_id))} />}
      {trend.length > 0
        ? <Trend days={trend} />
        : <div className="px-4 pb-4 border-t border-edge pt-4 font-mono text-xs text-mute">
            No daily data yet — upload a day's bulk file in a panel above to start the trend.
          </div>}
      {anomalies.length > 0 && (
        <div className="px-4 pb-4">
          <MLInsights ml={null} anomalies={anomalies} title="ML Anomaly Scan" />
        </div>
      )}
    </div>
  )
}

function DaySelect({ label, value, onChange, days }) {
  return (
    <label className="font-mono text-[10px] text-mute uppercase tracking-wider">{label}
      <select value={value} onChange={e => onChange(e.target.value)} disabled={!days.length}
        className="block mt-1 bg-panel border border-edge rounded px-2 py-1.5 font-mono text-xs text-slate-100 focus:outline-none focus:border-primary disabled:opacity-50">
        {!days.length && <option value="">no days</option>}
        {days.map(d => <option key={d} value={d}>{d}</option>)}
      </select>
    </label>
  )
}

// one calendar cell: day-of-month badge, date picker, upload, mini totals.
function DayPanel({ index, panel, removable, onDate, onRemove, onUploaded, setErr, toast, targetAcos }) {
  const ref = useRef()
  const [busy, setBusy] = useState(false)
  const t = panel.totals

  async function pick(e) {
    const f = e.target.files?.[0]; if (!f) return
    setErr(null); setBusy(true)
    try { onUploaded(await api.dailyWatchUpload(f, panel.date, targetAcos)) }
    catch (er) { setErr(cleanErr(er)); toast?.error(cleanErr(er)) }
    finally { setBusy(false); if (ref.current) ref.current.value = '' }
  }

  return (
    <div className={`rounded-lg border p-2 flex flex-col gap-1.5 ${t ? 'border-primary/40 bg-primary/[0.04]' : 'border-edge'}`}>
      <div className="flex items-center justify-between">
        <span className={`font-mono text-lg font-bold leading-none ${t ? 'text-primary' : 'text-slate-300'}`}>{dayNum(panel.date)}</span>
        <div className="flex items-center gap-1">
          <span className="font-mono text-[9px] text-mute uppercase">day {index + 1}</span>
          {removable && (
            <button onClick={onRemove} title="Remove" className="text-mute hover:text-down leading-none">
              <Icon name="close" size={14} />
            </button>
          )}
        </div>
      </div>
      <input type="date" value={panel.date} onChange={e => onDate(e.target.value)}
        className="bg-panel border border-edge rounded px-1.5 py-1 font-mono text-[10px] text-slate-100 focus:outline-none focus:border-primary w-full" />
      {/* upload follows the app-wide pattern: yellow primary when the panel still
          needs its file, ghost once data is in (re-upload is a correction) */}
      <button onClick={() => ref.current?.click()} disabled={busy} aria-busy={busy}
        className={`${t ? 'btn btn-ghost' : 'btn btn-primary'} text-[11px] py-1 w-full disabled:opacity-50 flex items-center justify-center gap-1`}>
        {busy ? '…' : <><Icon name={t ? 'sync' : 'upload'} size={13} />{t ? 'Re-upload' : 'Upload'}</>}
      </button>
      <input ref={ref} type="file" accept=".xlsx,.xlsm,.csv" onChange={pick} className="hidden" />
      {t
        ? <div className="font-mono text-[10px] text-up leading-tight">✓ {money(t.spend)} · {t.orders} ord</div>
        : <div className="font-mono text-[10px] text-mute">no file yet</div>}
    </div>
  )
}

// the isolated area: active watches (latest-day KPIs, aligned flag) + recent clears
function MonitorCard({ mons, onUnwatch }) {
  const goal = mons.target_acos
  const activeCols = [
    { key: 'name', label: 'Campaign', render: r => <span className="truncate inline-block align-bottom text-slate-100" style={{ maxWidth: 260 }} title={r.name}>{r.name}</span> },
    { key: 'added_date', label: 'Watching since', cellClass: 'text-mute',
      render: r => `${r.added_date || '—'}${r.days_watched != null ? ` (${r.days_watched}d)` : ''}` },
    { key: 'added_acos', label: 'ACoS then', align: 'right', cellClass: 'text-mute', render: r => pp(r.added_acos) },
    { key: 'acos', label: 'ACoS latest', align: 'right', render: r => (
        r.acos == null ? <span className="text-mute">no data</span>
          : <span className={r.acos <= goal ? 'text-up' : 'text-down'}>{pp(r.acos)}</span>) },
    { key: 'spend', label: 'Spend', align: 'right', cellClass: 'text-mute', render: r => (r.spend == null ? '—' : money(r.spend)) },
    { key: 'orders', label: 'Orders', align: 'right', cellClass: 'text-mute', render: r => r.orders ?? '—' },
    { key: 'aligned', label: 'Status', render: r => (
        r.aligned
          ? <span className="tag bg-up text-ink">aligned — clears on next upload</span>
          : <span className="tag border border-edge text-amber">over goal {pp(goal)}</span>) },
    { key: 'un', label: '', render: r => (
        <button onClick={() => onUnwatch(r.campaign_id, r.name)} title="Stop monitoring"
          className="tag border border-edge text-mute hover:text-down">unwatch</button>) },
  ]
  return (
    <div className="mx-4 mb-4 card border-primary/30">
      <div className="p-3 border-b border-edge flex items-center justify-between gap-2 flex-wrap">
        <div className="text-mute text-[10px] font-mono uppercase tracking-wider">
          <Icon name="visibility" size={12} className="align-[-2px]" /> monitored campaigns · {mons.active.length} active
          <span className="ml-2 normal-case">isolated watchlist — a campaign clears itself when a new day's upload shows it at/under goal ACoS {pp(goal)}</span>
        </div>
        {mons.latest_day && <span className="font-mono text-[10px] text-mute">latest day {mons.latest_day}</span>}
      </div>
      <div className="p-3 space-y-3">
        <DataTable columns={activeCols} rows={mons.active} rowKey={r => r.campaign_id} lean
          empty="Nothing monitored — hit the eye button on a campaign in the compare table below." />
        {mons.cleared.length > 0 && (
          <div>
            <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-1">recently cleared (aligned to goal)</div>
            {mons.cleared.map((c, i) => (
              <div key={i} className="font-mono text-xs text-up">
                ✓ {c.name} — {pp(c.cleared_acos)} on {c.cleared_date}
                {c.added_acos != null && <span className="text-mute"> (was {pp(c.added_acos)})</span>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function CompareResult({ cmp, onWatch, watched }) {
  const a = cmp.account
  return (
    <div className="px-4 pb-4 space-y-4 border-t border-edge pt-4">
      <div className="text-mute text-[10px] font-mono uppercase tracking-wider">
        {cmp.prev_day} → {cmp.cur_day}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        <Delta label="Ad Spend" cell={a.spend} fmt={money} invert />
        <Delta label="Ad Sales" cell={a.sales} fmt={money} />
        <Delta label="Clicks" cell={a.clicks} fmt={(x) => x} />
        <Delta label="Orders" cell={a.orders} fmt={(x) => x} />
        <Delta label="ACoS" cell={a.acos} fmt={pp} invert noPct />
      </div>

      {/* anomaly flags */}
      <div>
        <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-2">
          anomalies · {cmp.flags.length}
        </div>
        {cmp.flags.length === 0
          ? <div className="font-mono text-xs text-up">✓ No spikes or anomalies day-over-day.</div>
          : <div className="space-y-1">
              {cmp.flags.map((f, i) => (
                <div key={i} className={`flex items-start gap-2 font-mono text-xs border-l-2 pl-2 ${SEV[f.severity] || SEV.low}`}>
                  <span className="uppercase text-[9px] mt-0.5">{f.severity}</span>
                  <span><span className="text-slate-200">{f.campaign}</span> — {f.message}</span>
                  {onWatch && !watched?.has(f.campaign_id) && (
                    <button onClick={() => onWatch(f.campaign_id, f.campaign)} title="Monitor this campaign"
                      className="tag border border-edge text-mute hover:text-primary shrink-0">
                      <Icon name="visibility" size={11} className="align-[-2px]" /> monitor
                    </button>
                  )}
                  {watched?.has(f.campaign_id) && <span className="tag border border-primary/40 text-primary shrink-0">monitored</span>}
                </div>
              ))}
            </div>}
      </div>

      {/* per-campaign deltas (top movers) */}
      <DataTable columns={cmpCols(onWatch, watched)} rows={cmp.campaigns} rowKey={(r) => r.campaign_id} lean
        empty="no campaign rows for these days" placeholder="search campaign…"
        initial={{ sort: { key: 'spend_delta', dir: 'desc' } }} />
    </div>
  )
}

// per-campaign movers table columns (Daily Watch compare). acos_* are percent
// numbers (e.g. 25.0); spend rising = bad (red), sales rising = good (green).
// Built per-render so the Monitor button knows the current watchlist.
const cmpCols = (onWatch, watched) => [
  { key: 'name', label: 'Campaign', render: r => <span className="truncate inline-block align-bottom text-slate-100" style={{ maxWidth: 260 }} title={r.name}>{r.name}</span> },
  { key: 'spend_delta', label: 'Spend Δ', align: 'right', render: r => (
      <span className={r.spend_delta > 0 ? 'text-down' : r.spend_delta < 0 ? 'text-up' : 'text-mute'}>
        {r.spend_delta > 0 ? '+' : ''}{money(r.spend_delta)}{r.spend_pct != null ? ` (${r.spend_pct > 0 ? '+' : ''}${r.spend_pct}%)` : ''}
      </span>) },
  { key: 'sales_delta', label: 'Sales Δ', align: 'right', render: r => (
      <span className={r.sales_delta > 0 ? 'text-up' : r.sales_delta < 0 ? 'text-down' : 'text-mute'}>
        {r.sales_delta > 0 ? '+' : ''}{money(r.sales_delta)}
      </span>) },
  { key: 'acos_cur', label: 'ACoS', align: 'right', cellClass: 'text-mute', render: r => `${pp(r.acos_prev)} → ${pp(r.acos_cur)}` },
  { key: 'orders_cur', label: 'Orders', align: 'right', cellClass: 'text-mute' },
  { key: 'monitor', label: '', render: r => (
      watched?.has(r.campaign_id)
        ? <span className="tag border border-primary/40 text-primary">monitored</span>
        : <button onClick={() => onWatch?.(r.campaign_id, r.name)} title="Monitor — isolate this campaign until it aligns to goal ACoS"
            className="tag border border-edge text-mute hover:text-primary">
            <Icon name="visibility" size={11} className="align-[-2px]" /> monitor
          </button>) },
]

// invert: a rising value is "bad" (spend/ACoS up = red). noPct: hide % change.
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

// Amazon-Ads-style metric registry for the Daily Watch trend (CTR/CVR/ROAS/ACOS first).
const DW_METRICS = [
  { key: 'acos', label: 'ACOS', kind: 'pct', get: d => d.acos },
  { key: 'roas', label: 'ROAS', kind: 'ratio', get: d => d.roas },
  { key: 'ctr', label: 'CTR', kind: 'pct', get: d => d.ctr },
  { key: 'cvr', label: 'CVR', kind: 'pct', get: d => d.cvr },
  { key: 'cpc', label: 'CPC', kind: 'money', get: d => d.cpc },
  { key: 'spend', label: 'Ad Spend', kind: 'money', get: d => d.spend },
  { key: 'sales', label: 'Ad Sales', kind: 'money', get: d => d.sales },
  { key: 'orders', label: 'Orders', kind: 'count', get: d => d.orders },
  { key: 'clicks', label: 'Clicks', kind: 'count', get: d => d.clicks },
  { key: 'impressions', label: 'Impressions', kind: 'count', get: d => d.impressions },
]

function Trend({ days }) {
  const labels = days.map(d => d.date.slice(5))
  return (
    <div className="px-4 pb-4 border-t border-edge pt-4">
      <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-2">trend · accumulated days · pick up to 4 metrics</div>
      <MetricChart labels={labels} rows={days} metrics={DW_METRICS} defaults={['spend', 'sales']} height={240} max={4} />
    </div>
  )
}
