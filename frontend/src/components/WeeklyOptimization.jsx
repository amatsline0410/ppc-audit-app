import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { Icon, money, CardSkeleton } from './ui.jsx'
import { MetricChart } from './MetricChart.jsx'
import { DataTable } from './table.jsx'
import { CompareResult } from './compareView.jsx'
import { useModals } from './Modal.jsx'
import { useToast } from './Toast.jsx'
import { pp, bidKey, hKey, bidCols, harvestCols, withBE, withML } from './cadenceCols.jsx'
import { MLInsights } from './MLInsights.jsx'

// Weekly Optimization — the Weekly cadence's focus: bid tweaks + search-term
// harvest, driven straight from the bulk's SP Search Term Report. Like Daily
// Watch's calendar grid, but the panels are WEEKS: start with Week 1–5 (minimum
// 5), press ＋ to add another. Each week panel uploads that week's SP bulk; weeks
// accumulate into a trend. Pick a week to optimize → recomputed bids + harvest →
// download an Amazon bulk that points at the exact entity IDs the report carried.
const MIN_PANELS = 5      // Week 1..5 always shown
const MAX_PANELS = 53     // a calendar year of weeks
const cleanErr = (e) => String(e?.message || e).replace(/^Error:\s*/, '')
let _pid = 0

// Amazon-Ads-style metric registry for the week-over-week trend.
const WK_METRICS = [
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

function buildPanels(uploadedWeeks, seriesWeeks) {
  const maxW = Math.max(MIN_PANELS, uploadedWeeks.length ? Math.max(...uploadedWeeks) : 0)
  const byWeek = Object.fromEntries((seriesWeeks || []).map(w => [w.week, w]))
  const arr = []
  for (let w = 1; w <= maxW; w++) arr.push({ id: ++_pid, week: w, totals: byWeek[w] || null })
  return arr
}

export function WeeklyOptimization({ scope, targetAcos, onStage, onUploaded: onDataChange }) {
  const [panels, setPanels] = useState(() => buildPanels([], []))
  const [trend, setTrend] = useState([])         // per-week account totals (series)
  const [selWeek, setSelWeek] = useState(null)   // which uploaded week to optimize
  const [plan, setPlan] = useState(null)
  const [dl, setDl] = useState(false)
  const [dlDone, setDlDone] = useState(false)   // funnel: bulk downloaded this scope
  const [planBusy, setPlanBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [info, setInfo] = useState(null)
  const [sel, setSel] = useState(() => new Set())
  const [cmpA, setCmpA] = useState('')           // compare: earlier week
  const [cmpB, setCmpB] = useState('')           // compare: later week
  const [cmp, setCmp] = useState(null)
  const [cmpBusy, setCmpBusy] = useState(false)
  const { confirm } = useModals()
  const toast = useToast()

  // load uploaded weeks + the trend series; seed panels so prior weeks show filled
  function refresh(thenWeek) {
    return api.weeklySeries().then(d => {
      const ws = (d.weeks || [])
      setTrend(ws)
      const nums = ws.map(w => w.week)
      setPanels(ps => {
        const maxW = Math.max(MIN_PANELS, ps.length, nums.length ? Math.max(...nums) : 0)
        const byWeek = Object.fromEntries(ws.map(w => [w.week, w]))
        const arr = []
        for (let w = 1; w <= maxW; w++) {
          const ex = ps.find(p => p.week === w)
          arr.push({ id: ex?.id || ++_pid, week: w, totals: byWeek[w] || null })
        }
        return arr
      })
      const pick = thenWeek || (nums.length ? Math.max(...nums) : null)
      if (pick) loadPlan(pick)
      else { setPlan(null); setSelWeek(null) }
      return nums
    }).catch(() => {})
  }

  useEffect(() => {
    setPanels(buildPanels([], [])); setPlan(null); setSelWeek(null); setCmp(null)
    setErr(null); setInfo(null); setDlDone(false); refresh()
  }, [scope])  // eslint-disable-line

  // Goal ACoS changed: recompute the selected week's plan (bid tweaks + harvest
  // verdicts hang off it) and drop a stale compare — no need to reload the weeks.
  useEffect(() => {
    if (selWeek != null) { setCmp(null); loadPlan(selWeek) }
  }, [targetAcos])  // eslint-disable-line

  // default the compare selects to the two most-recent uploaded weeks
  useEffect(() => {
    const ws = trend.map(w => w.week)
    if (ws.length >= 2) { setCmpB(ws[ws.length - 1]); setCmpA(ws[ws.length - 2]) }
    else { setCmpA(''); setCmpB('') }
  }, [trend.map(w => w.week).join(',')])  // eslint-disable-line

  async function doCompare() {
    setErr(null); setCmp(null)
    const a = Number(cmpA), b = Number(cmpB)
    const ws = trend.map(w => w.week)
    if (!a || !b) { setErr('Pick two uploaded weeks to compare.'); return }
    if (a === b) { setErr('Pick two different weeks to compare.'); return }
    if (!ws.includes(a) || !ws.includes(b)) { setErr('Both weeks must be uploaded first.'); return }
    setCmpBusy(true)
    try { setCmp(await api.weeklyCompare(a, b, targetAcos)) }
    catch (e) { setErr(cleanErr(e)) }
    finally { setCmpBusy(false) }
  }

  function loadPlan(week) {
    setSelWeek(week); setPlanBusy(true)
    api.weeklyPlan(targetAcos, week).then(p => {
      setPlan(p); setSelWeek(p.week)
      const keys = [...p.bid_tweaks.map(bidKey), ...p.promotes.map(hKey), ...p.negates.map(hKey)]
      setSel(new Set(keys))
    }).catch(e => { setPlan(null); setErr(cleanErr(e)) })
      .finally(() => setPlanBusy(false))
  }

  function addPanel() {
    setErr(null)
    setPanels(ps => (ps.length >= MAX_PANELS ? ps
      : [...ps, { id: ++_pid, week: ps.length + 1, totals: null }]))
  }
  async function removeLast() {
    setErr(null)
    const last = panels[panels.length - 1]
    if (panels.length <= MIN_PANELS) return
    setPanels(ps => ps.slice(0, -1))
    // if that trailing week had data, delete it server-side so it doesn't re-seed
    if (last?.week && uploadedWeeks.includes(last.week)) {
      if (selWeek === last.week) { setPlan(null); setSelWeek(null) }
      try { await api.weeklyDelete(last.week); toast.success(`Week ${last.week} removed`); refresh() } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    }
  }
  // per-panel remove: delete that week's data (panel resets to empty), persisted
  async function removeWeek(week) {
    setErr(null)
    setPanels(ps => ps.map(p => (p.week === week ? { ...p, totals: null } : p)))
    if (selWeek === week) { setPlan(null); setSelWeek(null) }
    try { await api.weeklyDelete(week); toast.success(`Week ${week} removed`); refresh() } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
  }
  // wipe every uploaded week at once (panels reset to the empty Week 1..5 grid)
  async function clearAll() {
    setErr(null); setInfo(null)
    const ok = await confirm({
      title: 'Clear all Weekly data?',
      message: `This permanently deletes all ${uploadedWeeks.length} uploaded week${uploadedWeeks.length === 1 ? '' : 's'} of Weekly Optimization data, `
        + 'AND the bulk-derived data behind this cadence\'s optimizer panels below (Bid Optimizer, Placement, '
        + 'ASIN tree, Harvest, N-gram).\n\nThis cannot be undone — re-upload the bulks to rebuild.',
      danger: true, confirmLabel: 'Clear all',
    })
    if (!ok) return
    try {
      await api.weeklyClearAll()
      setPlan(null); setSelWeek(null); setCmp(null)
      setPanels(buildPanels([], []))
      await refresh()
      setInfo('Cleared all Weekly Optimization data.')
      toast.success('Cleared all Weekly data')
      onDataChange?.()   // bump dataVer so the optimizer sub-panels refetch (now empty)
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
  }

  function toggle(key) {
    setSel(s => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n })
  }
  function setMany(keys, on) {
    setSel(s => { const n = new Set(s); keys.forEach(k => on ? n.add(k) : n.delete(k)); return n })
  }

  async function download() {
    if (!plan) return
    const payload = {
      bid_tweaks: plan.bid_tweaks.filter(b => sel.has(bidKey(b))),
      promotes: plan.promotes.filter(h => sel.has(hKey(h))),
      negates: plan.negates.filter(h => sel.has(hKey(h))),
    }
    const n = payload.bid_tweaks.length + payload.promotes.length + payload.negates.length
    if (!n) { setErr('Nothing selected — tick at least one bid tweak or harvest row first.'); return }
    setDl(true); setErr(null)
    try {
      const blob = await api.weeklyBulk(payload)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url
      a.download = `weekly_optimization_week${plan.week}_bulk.xlsx`; a.click()
      URL.revokeObjectURL(url)
      setDlDone(true)
      setInfo(`Downloaded Week ${plan.week} bulk · ${n} row${n === 1 ? '' : 's'}. Re-upload it to Amazon Ads.`)
      toast.success(`Week ${plan.week} bulk downloaded · ${n} row${n === 1 ? '' : 's'}`)
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setDl(false) }
  }

  const uploadedWeeks = trend.map(w => w.week)
  const s = plan?.summary
  const selCount = plan ? [...plan.bid_tweaks.map(bidKey), ...plan.promotes.map(hKey), ...plan.negates.map(hKey)]
    .filter(k => sel.has(k)).length : 0
  const hasRows = plan && (plan.bid_tweaks.length + plan.promotes.length + plan.negates.length > 0)
  useEffect(() => { onStage?.({ uploaded: uploadedWeeks.length > 0, hasRows: !!hasRows, downloaded: dlDone }) }, [uploadedWeeks.length, hasRows, dlDone])  // eslint-disable-line

  return (
    <div className="card">
      <div className="p-4 border-b border-edge flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider">weekly optimization · bid tweaks + search-term harvest</div>
          <div className="font-mono text-xs text-mute mt-1">A panel per week — upload each week's Sponsored Products bulk (with its SP Search Term Report). Sponsored Products only.</div>
        </div>
        <div className="flex items-center gap-3">
          <div className="font-mono text-[10px] text-mute">{uploadedWeeks.length} week{uploadedWeeks.length === 1 ? '' : 's'} uploaded · {panels.length}/{MAX_PANELS} panels</div>
          {uploadedWeeks.length > 0 && (
            <button onClick={clearAll} className="btn btn-ghost text-xs flex items-center gap-1 hover:text-down">
              <Icon name="delete" size={14} /> Clear
            </button>
          )}
        </div>
      </div>

      {/* calendar-style grid of WEEK panels + the add tile */}
      <div className="p-4 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2">
        {panels.map(p => (
          <WeekPanel key={p.id} panel={p} active={selWeek === p.week}
            onUploaded={(res) => { toast.success(`Week ${res.week} uploaded`); refresh(res.week); onDataChange?.() }} onOptimize={() => loadPlan(p.week)}
            onRemove={() => removeWeek(p.week)} setErr={setErr} toast={toast} />
        ))}
        {panels.length < MAX_PANELS && (
          <button onClick={addPanel} title="Add another week"
            className="rounded-lg border border-dashed border-edge hover:border-primary text-mute hover:text-primary
                       flex flex-col items-center justify-center gap-1 min-h-[132px] transition-colors">
            <Icon name="add" size={28} />
            <span className="font-mono text-[10px] uppercase tracking-wider">add week</span>
          </button>
        )}
      </div>
      {panels.length > MIN_PANELS && (
        <div className="px-4 -mt-2 pb-2">
          <button onClick={removeLast} className="font-mono text-[10px] text-mute hover:text-down flex items-center gap-1">
            <Icon name="close" size={12} /> remove last week (Week {panels.length})
          </button>
        </div>
      )}

      {err && <div className="mx-4 mb-2 card border-down/40 p-2 font-mono text-xs text-down inline-flex items-center gap-1"><Icon name="warning" size={12} /> {err}</div>}
      {info && <div className="mx-4 mb-2 card border-up/40 p-2 font-mono text-xs text-up inline-flex items-center gap-1"><Icon name="check_circle" size={12} /> {info}</div>}

      {/* plan toolbar: which week to optimize + download */}
      {uploadedWeeks.length > 0 && (
        <div className="px-4 pb-2 flex items-end gap-2 flex-wrap border-t border-edge pt-4">
          <label className="font-mono text-[10px] text-mute uppercase tracking-wider">Optimize week
            <select value={selWeek || ''} onChange={e => loadPlan(Number(e.target.value))}
              className="block mt-1 bg-panel border border-edge rounded px-2 py-1.5 font-mono text-xs text-slate-100 focus:outline-none focus:border-primary">
              {uploadedWeeks.map(w => <option key={w} value={w}>Week {w}</option>)}
            </select>
          </label>
          {hasRows && (
            <button onClick={download} disabled={dl || !selCount} aria-busy={dl}
              className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name="download" size={14} />{dl ? 'Building…' : `Download Week ${plan.week} bulk (${selCount})`}
            </button>
          )}
        </div>
      )}

      {/* plan body */}
      {planBusy && <div className="p-4"><CardSkeleton lines={6} /></div>}

      {!planBusy && uploadedWeeks.length === 0 && (
        <div className="p-8 text-center border-t border-edge">
          <div className="font-mono text-sm text-slate-200">No Weekly data yet</div>
          <div className="font-mono text-xs text-mute mt-1">
            Upload a week's Sponsored Products bulk in a Week panel above — its SP Search Term Report drives
            the bid tweaks and search-term harvest. Data stays isolated to the Weekly cadence.
          </div>
        </div>
      )}

      {!planBusy && plan && (
        <div className="p-4 pt-2 space-y-5">
          {/* selected-week snapshot */}
          {s && (
            <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
              <Mini label={`Week ${plan.week} Terms`} value={s.terms} />
              <Mini label="Campaigns" value={s.campaigns} />
              <Mini label="Ad Spend" value={money(s.spend)} />
              <Mini label="Ad Sales" value={money(s.sales)} />
              <Mini label="ACoS" value={s.acos == null ? '—' : `${s.acos}%`} />
              <Mini label="Goal ACoS" value={pp(plan.target_acos)} />
            </div>
          )}

          <MLInsights ml={plan.ml} />

          <DataTable title={`Bid tweaks · ${plan.bid_tweaks.length}`} columns={withML(withBE(bidCols))} rows={plan.bid_tweaks}
            rowKey={bidKey} lean selectable selected={sel} onToggle={toggle} onToggleAll={setMany}
            scope={scope} empty="No bid changes — every target's bid is already near optimal." placeholder="search target / reason…" />
          <DataTable title={`Harvest · promote winners → Exact · ${plan.promotes.length}`} columns={withML(withBE(harvestCols('promote')))} rows={plan.promotes}
            rowKey={hKey} lean selectable selected={sel} onToggle={toggle} onToggleAll={setMany}
            scope={scope} empty="No winning search terms to promote yet." placeholder="search term / ad group…" />
          <DataTable title={`Harvest · negate losers → Negative Exact · ${plan.negates.length}`} columns={withML(withBE(harvestCols('negate')))} rows={plan.negates}
            rowKey={hKey} lean selectable selected={sel} onToggle={toggle} onToggleAll={setMany}
            scope={scope} empty="No wasted search terms to negate." placeholder="search term / ad group…" />
        </div>
      )}

      {/* compare any two uploaded weeks */}
      {uploadedWeeks.length > 0 && (
        <div className="px-4 pb-4 flex items-end gap-2 flex-wrap border-t border-edge pt-4">
          <WeekSelect label="Compare" value={cmpA} onChange={setCmpA} weeks={uploadedWeeks} />
          <span className="font-mono text-mute text-xs pb-2">→</span>
          <WeekSelect label="with" value={cmpB} onChange={setCmpB} weeks={uploadedWeeks} />
          <button onClick={doCompare} disabled={cmpBusy || uploadedWeeks.length < 2} aria-busy={cmpBusy}
            className="btn btn-primary disabled:opacity-50">{cmpBusy ? 'Comparing…' : 'Compare'}</button>
          {uploadedWeeks.length < 2 && !err && (
            <div className="font-mono text-xs text-mute pb-2">Upload at least two weeks to compare.</div>
          )}
        </div>
      )}
      {cmp && <CompareResult cmp={cmp} heading={`Week ${cmp.prev_week} → Week ${cmp.cur_week}`} />}

      {/* week-over-week trend */}
      {trend.length > 0 && (
        <div className="px-4 pb-4 border-t border-edge pt-4">
          <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-2">trend · accumulated weeks · pick up to 2 metrics</div>
          <MetricChart labels={trend.map(w => w.label)} rows={trend} metrics={WK_METRICS} defaults={['spend', 'sales']} height={240} />
        </div>
      )}
    </div>
  )
}

function WeekSelect({ label, value, onChange, weeks }) {
  return (
    <label className="font-mono text-[10px] text-mute uppercase tracking-wider">{label}
      <select value={value} onChange={e => onChange(e.target.value)} disabled={!weeks.length}
        className="block mt-1 bg-panel border border-edge rounded px-2 py-1.5 font-mono text-xs text-slate-100 focus:outline-none focus:border-primary disabled:opacity-50">
        {!weeks.length && <option value="">no weeks</option>}
        {weeks.map(w => <option key={w} value={w}>Week {w}</option>)}
      </select>
    </label>
  )
}


// one calendar cell: Week badge, upload, mini totals, "optimize this week".
function WeekPanel({ panel, active, onUploaded, onOptimize, onRemove, setErr, toast }) {
  const ref = useRef()
  const [busy, setBusy] = useState(false)
  const t = panel.totals

  async function pick(e) {
    const f = e.target.files?.[0]; if (!f) return
    setErr(null); setBusy(true)
    try { onUploaded(await api.weeklyUpload(f, panel.week)) }
    catch (er) { setErr(cleanErr(er)); toast?.error(cleanErr(er)) }
    finally { setBusy(false); if (ref.current) ref.current.value = '' }
  }

  return (
    <div className={`rounded-lg border p-2 flex flex-col gap-1.5 min-h-[132px] ${active ? 'border-primary bg-primary/[0.06]' : t ? 'border-primary/40 bg-primary/[0.04]' : 'border-edge'}`}>
      <div className="flex items-center justify-between">
        <span className={`font-mono text-sm font-bold leading-none ${t ? 'text-primary' : 'text-slate-300'}`}>Week {panel.week}</span>
        <div className="flex items-center gap-1">
          {t && <span className="font-mono text-[9px] text-up uppercase inline-flex items-center gap-1"><Icon name="check_circle" size={10} /> data</span>}
          {t && (
            <button onClick={onRemove} title="Remove this week's data" className="text-mute hover:text-down leading-none">
              <Icon name="close" size={14} />
            </button>
          )}
        </div>
      </div>
      {/* upload follows the app-wide pattern: yellow primary when the panel still
          needs its file, ghost once data is in (re-upload is a correction) */}
      <button onClick={() => ref.current?.click()} disabled={busy} aria-busy={busy}
        className={`${t ? 'btn btn-ghost' : 'btn btn-primary'} text-[11px] py-1 w-full disabled:opacity-50 flex items-center justify-center gap-1`}>
        {busy ? '…' : <><Icon name={t ? 'sync' : 'upload'} size={13} />{t ? 'Re-upload' : 'Upload'}</>}
      </button>
      <input ref={ref} type="file" accept=".xlsx,.xlsm,.csv" onChange={pick} className="hidden" />
      {t
        ? <>
            <div className="font-mono text-[10px] text-slate-200 leading-tight">{money(t.spend)} · {t.orders} ord</div>
            <button onClick={onOptimize}
              className={`mt-auto font-mono text-[10px] rounded px-1.5 py-1 border ${active ? 'border-primary text-primary' : 'border-edge text-mute hover:text-primary hover:border-primary'}`}>
              {active ? 'optimizing ▾' : 'optimize ▸'}
            </button>
          </>
        : <div className="font-mono text-[10px] text-mute mt-auto">no file yet</div>}
    </div>
  )
}

function Mini({ label, value }) {
  return (
    <div className="card p-2">
      <div className="text-mute text-[9px] font-mono uppercase tracking-wider">{label}</div>
      <div className="font-mono text-sm font-bold text-slate-100 mt-0.5">{value}</div>
    </div>
  )
}

