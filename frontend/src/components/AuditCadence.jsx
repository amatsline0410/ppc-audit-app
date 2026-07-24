import React, { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { money, pct, Icon, FlagLegend } from './ui.jsx'
import { DailyWatch } from './DailyWatch.jsx'
import { WeeklyOptimization } from './WeeklyOptimization.jsx'
import { MidMonth } from './MidMonth.jsx'
import { FullMonth } from './FullMonth.jsx'
import { PauseScale } from './PauseScale.jsx'
import { CadenceFunnel } from './CadenceFunnel.jsx'
import { useToast } from './Toast.jsx'
import { useModals } from './Modal.jsx'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// Audit cadence header for the PPC Optimization tab: store + month/year + Audit Type
// preset (re-tunes the flag engine) + the SOP effort checklist (persisted per
// store/month/type). Picking a type retunes the audit via `setAuditType`.
// each cadence's dedicated panel — kept mounted once visited (hidden, not
// unmounted) so switching cadence is instant and an upload running in one
// cadence keeps going in the background while you browse the others.
const CADENCE_PANELS = {
  daily: DailyWatch, weekly: WeeklyOptimization, mid_month: MidMonth,
  full_month: FullMonth, pause_scale: PauseScale,
}

export function AuditCadence({ scope, baseScope, resetVer = 0, cadVers = {}, onCadenceData,
                               storeTitle, targetAcos, auditType, setAuditType, onActivePreset }) {
  const toast = useToast()
  const { confirm } = useModals()
  const today = new Date()
  const [presets, setPresets] = useState([])
  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth() + 1)
  const [run, setRun] = useState(null)
  const [err, setErr] = useState(null)
  const [runs, setRuns] = useState({})        // per-cadence audit result: auditType -> run|null
  const [auditing, setAuditing] = useState(null)   // which cadence is auditing right now
  const [clearing, setClearing] = useState(null)   // which cadence is clearing right now
  const [stages, setStages] = useState({})     // funnel progress PER cadence: key -> {uploaded,hasRows,downloaded}
  const [seen, setSeen] = useState({})         // cadences whose panel has been opened (keep-alive)
  const [legendOpen, setLegendOpen] = useState(false)   // collapsible flag legend

  useEffect(() => { api.cadencePresets().then(d => setPresets(d.presets)).catch(() => {}) }, [])

  function loadRun() {
    if (!auditType || targetAcos == null) return   // wait for the per-audit Goal ACoS
    api.createCadenceRun(year, month, auditType, targetAcos).then(setRun).catch(e => setErr(String(e)))
  }
  // open / create the run whenever store · month · year · type changes
  useEffect(() => { loadRun() }, [scope, year, month, auditType])   // eslint-disable-line
  // per-tile audit results are month/store-specific — clear when those change
  useEffect(() => { setRuns({}) }, [scope, year, month])   // eslint-disable-line
  // funnel progress is kept per cadence — only a store/audit switch or a flush resets it
  useEffect(() => { setStages({}) }, [baseScope, resetVer])   // eslint-disable-line
  // mark the active cadence's panel as opened (it stays mounted from then on)
  useEffect(() => { setSeen(s => (s[auditType] ? s : { ...s, [auditType]: true })) }, [auditType])

  // run THIS cadence's audit (flags + ACoS capture + SOP checklist) at the current
  // Goal ACoS, for the selected month/year. Persists to that cadence's own db.
  async function auditCadence(key) {
    setErr(null); setAuditing(key)
    const label = presets.find(p => p.key === key)?.label || key
    try {
      const r = await api.createCadenceRun(year, month, key, targetAcos, true)   // explicit re-audit at the current goal
      setRuns(m => ({ ...m, [key]: r }))
      if (key === auditType) setRun(r)   // reflect immediately in the detail card
      toast.success(r == null ? `${label} audited · no data` : `${label} audited · ${r.flags} flag${r.flags === 1 ? '' : 's'}`)
    } catch (e) { setErr(String(e)); toast.error(String(e)) }
    finally { setAuditing(null) }
  }

  // wipe ONE cadence's uploaded data straight from its tile — hits that cadence's
  // own db file (explicit audit_type override), other cadences untouched.
  async function clearCadence(p) {
    setErr(null)
    const ok = await confirm({
      title: `Clear ${p.label} data?`, danger: true, confirmLabel: 'Clear data',
      message: `Permanently deletes every upload behind the ${p.label} cadence — its search-term/watch data `
        + 'and the bulk-derived optimizer panels it feeds. Other cadences are not affected.'
        + (p.key === 'full_month' ? '\n\nFull Month lives in the base audit data — this also clears the Dashboard KPIs and flag table.' : '')
        + '\n\nThis cannot be undone — re-upload the bulk to rebuild.',
    })
    if (!ok) return
    setClearing(p.key)
    try {
      await api.cadenceClear(p.key)
      setRuns(m => { const n = { ...m }; delete n[p.key]; return n })
      setStages(m => ({ ...m, [p.key]: {} }))
      toast.success(`Cleared ${p.label} data`)
      // reload this cadence's panel; global views only refetch if it's the active cadence
      onCadenceData?.(p.key)
    } catch (e) { setErr(String(e)); toast.error(String(e)) }
    finally { setClearing(null) }
  }

  async function toggle(t) {
    try { await api.toggleCadenceTask(t.id, !t.done); loadRun() } catch (e) { setErr(String(e)) }
  }

  const active = presets.find(p => p.key === auditType)
  // surface the active cadence preset to the parent so the audit table can scope
  // itself to this cadence's focus (or hide for the watch-only Daily cadence).
  useEffect(() => { if (active) onActivePreset?.(active) }, [active])  // eslint-disable-line
  const years = [today.getFullYear(), today.getFullYear() - 1, today.getFullYear() - 2]

  return (
    <div className="space-y-4">
    <div className="card">
      <div className="p-4 border-b border-edge flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider">audit cadence</div>
          <div className="font-mono text-sm text-slate-100 mt-0.5">{storeTitle} · {MONTHS[month - 1]} {year}{active ? ` · ${active.label}` : ''}</div>
        </div>
        <div className="flex items-end gap-2">
          <label className="font-mono text-[10px] text-mute uppercase tracking-wider">Month
            <select value={month} onChange={e => setMonth(Number(e.target.value))} className="block mt-1 bg-panel border border-edge rounded px-2 py-1.5 font-mono text-xs text-slate-100 focus:outline-none focus:border-primary">
              {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
            </select>
          </label>
          <label className="font-mono text-[10px] text-mute uppercase tracking-wider">Year
            <select value={year} onChange={e => setYear(Number(e.target.value))} className="block mt-1 bg-panel border border-edge rounded px-2 py-1.5 font-mono text-xs text-slate-100 focus:outline-none focus:border-primary">
              {years.map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>
        </div>
      </div>

      {/* audit type presets */}
      <div className="p-4 grid grid-cols-2 md:grid-cols-5 gap-2 border-b border-edge">
        {presets.map(p => {
          const on = p.key === auditType
          const r = runs[p.key]   // undefined = not run yet, null = no data, obj = result
          return (
            <div key={p.key}
              className={`flex flex-col rounded-lg border p-3 transition-colors ${on ? 'border-primary bg-primary/10' : 'border-edge hover:border-mute'}`}>
              <button onClick={() => setAuditType(p.key)} className="text-left">
                <div className={`font-mono text-xs font-semibold ${on ? 'text-primary' : 'text-slate-200'}`}>{p.label}</div>
                <div className="font-mono text-[10px] text-mute mt-1">{p.range}</div>
                <div className="font-mono text-[10px] text-mute">{p.action_level}</div>
              </button>
              <div className="mt-2 pt-2 border-t border-edge/60 flex items-center justify-between gap-1">
                <span className="font-mono text-[10px] min-w-0 truncate">
                  {r === undefined ? <span className="text-mute/60">not run</span>
                    : r === null ? <span className="text-mute">no data</span>
                    : <><span className="text-primary font-bold">{r.flags}</span><span className="text-mute"> flags · {r.acos == null ? '—' : pct(r.acos)}</span></>}
                </span>
                <span className="inline-flex items-center gap-1 shrink-0">
                  <button onClick={() => auditCadence(p.key)} aria-busy={auditing === p.key} title="run this cadence's audit"
                    className="tag border border-edge text-mute hover:text-primary hover:border-primary inline-flex items-center gap-0.5">
                    <Icon name="play_arrow" size={13} />audit
                  </button>
                  <button onClick={() => clearCadence(p)} aria-busy={clearing === p.key} title="clear this cadence's uploaded data"
                    className="tag border border-edge text-mute hover:text-down hover:border-down inline-flex items-center gap-0.5">
                    <Icon name="delete" size={13} />clear
                  </button>
                </span>
              </div>
            </div>
          )
        })}
      </div>

      {err && <div className="m-4 card border-down/40 p-2 font-mono text-xs text-down inline-flex items-center gap-1"><Icon name="warning" size={12} /> {err}</div>}

      {/* Flag legend — collapsible, available for every cadence */}
      <div className="px-4 py-3 border-b border-edge">
        <button onClick={() => setLegendOpen(o => !o)}
          className="w-full flex items-center justify-between gap-2 font-mono text-[11px] text-mute uppercase tracking-wider hover:text-slate-200">
          <span className="inline-flex items-center gap-1"><Icon name="help" size={13} /> flag legend &amp; bid ladder</span>
          <Icon name={legendOpen ? 'expand_less' : 'expand_more'} size={16} />
        </button>
        {legendOpen && <FlagLegend className="mt-3" />}
      </div>

      {/* run snapshot + SOP effort checklist */}
      {run && (
        <div className="p-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="space-y-2">
            <div className="text-mute text-[10px] font-mono uppercase tracking-wider">captured at run · {(run.created_at || '').slice(0, 10)}</div>
            <div className="grid grid-cols-3 gap-2">
              <Mini label="Ad Spend" value={money(run.ad_spend)} />
              <Mini label="Ad Sales" value={money(run.ad_sales)} />
              <Mini label="ACoS" value={run.acos == null ? '—' : pct(run.acos)} />
            </div>
            <Mini label="Flags" value={run.flags} />
          </div>
          <div className="lg:col-span-2">
            <div className="text-mute text-[10px] font-mono uppercase tracking-wider mb-2">
              effort checklist · {run.done}/{run.total} done
            </div>
            <div className="space-y-1">
              {run.tasks.map(t => (
                <label key={t.id} className="flex items-start gap-2 font-mono text-xs cursor-pointer">
                  <input type="checkbox" checked={t.done} onChange={() => toggle(t)} className="accent-primary mt-0.5" />
                  <span className={t.done ? 'text-mute line-through' : 'text-slate-200'}>{t.text}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>

    {active && <CadenceFunnel cadence={auditType} label={active.label} stage={stages[auditType] || {}} />}

    {/* keep-alive: every visited cadence panel stays mounted (hidden when inactive) —
        switching cadence is instant, an in-flight upload keeps running in the
        background, and each panel refetches ONLY on its own cadence version bump
        (upload/clear in one cadence never reloads the others). */}
    {Object.entries(CADENCE_PANELS).map(([key, Panel]) => (seen[key] || key === auditType) && (
      <div key={key} className={key === auditType ? '' : 'hidden'}>
        <Panel scope={`${baseScope}:r${resetVer}:c${cadVers[key] || 0}`} targetAcos={targetAcos}
          onStage={s => setStages(m => ({ ...m, [key]: s }))}
          onUploaded={key === 'daily' ? undefined : () => onCadenceData?.(key)} />
      </div>
    ))}
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
