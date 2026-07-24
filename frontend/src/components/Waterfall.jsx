import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { Icon, money, CardSkeleton } from './ui.jsx'
import { DataTable } from './table.jsx'
import { useToast } from './Toast.jsx'
import { useModals } from './Modal.jsx'

// Waterfall Restructure Engine — one uploaded bulk → a phased restructure plan
// into the RAF funnel (AT → BROAD → PHRASE → EXACT + PT, 1 SKU per campaign).
// Four gated phase exports: A renames → B loser bid cuts → C creates (born
// paused) + seeds + sculpting negatives → D pauses (locked until A–C applied).
const cleanErr = (e) => String(e?.message || e).replace(/^Error:\s*/, '')
const pctf = (v) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)

const PHASES = [
  ['A', 'Renames', 'Boss campaigns renamed to the funnel template + budget set. Zero risk — run first.'],
  ['B', 'Loser bid cuts', 'Every enabled target in loser campaigns bid down (transitional overlap — losers keep serving cheap while bosses take over).'],
  ['C', 'Creates', 'Missing funnel slots created BORN PAUSED (down-only training wheels) + proven seed keywords + sculpting negatives upstream.'],
  ['D', 'Pauses', 'Loser + empty campaigns paused. Locked until A–C are marked applied.'],
]

const SLOTS = ['AT', 'KWT-BROAD', 'KWT-PHRASE', 'KWT-EXACT', 'PT']
const SLOT_SHORT = { AT: 'AT', 'KWT-BROAD': 'BROAD', 'KWT-PHRASE': 'PHRASE', 'KWT-EXACT': 'EXACT', PT: 'PT' }

const ACTION_TAG = {
  rename: 'rename', rename_adgroup: 'ad group', bid_cut: 'bid ↓',
  create_campaign: 'campaign +', create_adgroup: 'ad group +', create_ad: 'ad +',
  create_keyword: 'seed kw', create_pt: 'target +', negative: 'neg exact', pause: 'pause',
}

function detailOf(r) {
  switch (r.action) {
    case 'rename': return `${r.old_name || '—'} → ${r.new_name}`
    case 'rename_adgroup': return `${r.old_name || '—'} → ${r.new_name}`
    case 'bid_cut': return `${r.label || r.target_id}: $${r.old_bid?.toFixed?.(2) ?? r.old_bid} → $${r.new_bid?.toFixed?.(2) ?? r.new_bid}`
    case 'create_campaign': return `${r.name} · $${r.budget}/day · ${r.strategy}`
    case 'create_adgroup': return `${r.name} · default bid $${r.default_bid}`
    case 'create_ad': return `SKU ${r.sku}`
    case 'create_keyword': return `“${r.text}” · ${r.match} @ $${r.bid}`
    case 'create_pt': return `${r.expression} @ $${r.bid}`
    case 'negative': return `“${r.term}” · ${r.match}`
    case 'pause': return `${r.name}${r.reason ? ` — ${r.reason}` : ''}`
    default: return ''
  }
}

const phaseCols = [
  { key: 'action', label: 'Action', render: r => <span className="tag border border-edge text-mute">{ACTION_TAG[r.action] || r.action}</span> },
  { key: 'sku', label: 'SKU', render: r => r.sku || '—' },
  { key: 'slot', label: 'Slot', render: r => r.slot || '—' },
  { key: 'detail', label: 'Detail', value: detailOf, render: r => <span className="text-slate-200">{detailOf(r)}</span> },
  { key: 'campaign_id', label: 'Campaign', render: r => <span className="text-mute">{r.campaign_id}</span> },
]

const bossCols = [
  { key: 'sku', label: 'SKU' },
  { key: 'slot', label: 'Slot' },
  { key: 'boss_name', label: 'Boss campaign', render: r => <span className="text-slate-200">{r.boss_name}</span> },
  { key: 'sales', label: 'Sales', align: 'right', render: r => money(r.sales) },
  { key: 'acos', label: 'ACoS', align: 'right', value: r => (r.acos == null ? null : r.acos * 100),
    render: r => <span className={r.acos != null && r.acos > 0.5 ? 'text-down' : ''}>{pctf(r.acos)}</span> },
  { key: 'losers', label: 'Losers', align: 'right',
    render: r => r.losers ? <span className="text-down">{r.losers}</span> : <span className="text-mute">0</span> },
]

export function WaterfallPanel({ scope, targetAcos }) {
  const toast = useToast()
  const { confirm } = useModals()
  const ref = useRef()
  const [state, setState] = useState(null)
  const [settings, setSettings] = useState(null)
  const [showSettings, setShowSettings] = useState(false)
  const [ledger, setLedger] = useState(null)
  const [bench, setBench] = useState(null)
  const [busy, setBusy] = useState(false)
  const [dl, setDl] = useState(null)          // phase being exported
  const [err, setErr] = useState(null)
  const [sel, setSel] = useState({ A: new Set(), B: new Set(), C: new Set(), D: new Set() })

  function seed(st) {
    setState(st)
    if (st?.phases) {
      const next = {}
      for (const p of 'ABCD') next[p] = new Set((st.phases[p] || []).filter(i => i.selected).map(i => i.id))
      setSel(next)
    }
  }

  function load() {
    api.waterfallRun().then(seed).catch(() => setState(null))
    api.waterfallSettings().then(setSettings).catch(() => {})
    api.waterfallLedger().then(setLedger).catch(() => {})
    api.waterfallBenchmark().then(setBench).catch(() => {})
  }
  useEffect(() => { setState(null); setErr(null); load() }, [scope])  // eslint-disable-line

  async function upload(file) {
    if (!file) return
    setBusy(true); setErr(null)
    try {
      const st = await api.waterfallUpload(file)
      seed(st)
      toast.success(`Plan built · ${st.boss_map?.length || 0} boss groups`)
      api.waterfallBenchmark().then(setBench).catch(() => {})
      api.waterfallLedger().then(setLedger).catch(() => {})
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setBusy(false); if (ref.current) ref.current.value = '' }
  }

  function toggle(phase) {
    return (key) => setSel(s => {
      const n = new Set(s[phase]); n.has(key) ? n.delete(key) : n.add(key)
      return { ...s, [phase]: n }
    })
  }
  function setMany(phase) {
    return (keys, on) => setSel(s => {
      const n = new Set(s[phase]); keys.forEach(k => on ? n.add(k) : n.delete(k))
      return { ...s, [phase]: n }
    })
  }

  async function exportPhase(phase) {
    const ids = [...sel[phase]]
    if (!ids.length) { setErr(`Nothing selected in phase ${phase}.`); return }
    if (phase === 'D') {
      const ok = await confirm({
        title: 'Export Phase D (pauses)?', danger: true, confirmLabel: 'Export pauses',
        message: 'This bulk pauses loser + empty campaigns. Only upload it once phases A–C are live in Amazon and the bosses are serving.' })
      if (!ok) return
    }
    setDl(phase); setErr(null)
    try {
      const blob = await api.waterfallBulk(phase, ids)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = `waterfall_phase_${phase}_bulk.xlsx`; a.click()
      URL.revokeObjectURL(url)
      toast.success(`Phase ${phase} bulk downloaded · ${ids.length} rows`)
      api.waterfallLedger().then(setLedger).catch(() => {})
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setDl(null) }
  }

  async function markApplied(phase) {
    const ok = await confirm({
      title: `Mark phase ${phase} applied?`,
      message: 'Confirm you uploaded this phase\'s bulk file to Amazon Ads. This advances the run (and unlocks Phase D after A–C).',
      confirmLabel: 'Mark applied' })
    if (!ok) return
    try { seed(await api.waterfallApplied(phase)); toast.success(`Phase ${phase} marked applied`) }
    catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
  }

  async function clearAll() {
    const ok = await confirm({
      title: 'Clear waterfall plan?', danger: true, confirmLabel: 'Clear plan',
      message: 'Removes every waterfall run (plan history + phase progress + the day-0 benchmark baseline). '
        + 'Settings and the bid ledger are kept.\n\nThis cannot be undone — re-upload the bulk to rebuild.',
    })
    if (!ok) return
    try {
      await api.waterfallClear()
      setErr(null); toast.success('Cleared waterfall plan')
      load()
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
  }

  async function overrideBoss(overrides) {
    setBusy(true); setErr(null)
    try {
      const st = await api.waterfallOverride(overrides)
      seed(st)
      toast.success('Boss pick updated · plan rebuilt')
      api.waterfallBenchmark().then(setBench).catch(() => {})
      api.waterfallLedger().then(setLedger).catch(() => {})
    } catch (e) { setErr(cleanErr(e)); toast.error(cleanErr(e)) }
    finally { setBusy(false) }
  }

  async function saveSettings(patch) {
    try {
      const s = await api.waterfallSaveSettings({ ...settings, ...patch })
      setSettings(s); toast.success('Waterfall settings saved — re-upload the bulk to rebuild the plan')
    } catch (e) { toast.error(cleanErr(e)) }
  }

  const run = state?.run
  const applied = new Set(run?.applied_phases || [])
  const sm = state?.summary

  return (
    <div className="space-y-6">
      <div className="card">
        <div className="p-4 border-b border-edge flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider">waterfall restructure · RAF funnel (AT → broad → phrase → exact + PT)</div>
            <div className="font-mono text-xs text-mute mt-1">
              Upload the FULL Sponsored Products bulk (campaigns + ad groups + product ads + keywords, ideally with the SP Search Term Report). One SKU per campaign; boss per slot; 4 phased bulk files.
            </div>
            {state?.upload_meta && (
              <div className="font-mono text-xs text-mute mt-1 flex gap-3 flex-wrap">
                <span><Icon name="description" size={11} className="align-[-1px]" /> {state.upload_meta.file} · {state.upload_meta.rows} campaigns</span>
                <span>updated {state.upload_meta.uploaded}</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setShowSettings(o => !o)} className="btn btn-ghost text-xs flex items-center gap-1">
              <Icon name="tune" size={14} />Settings
            </button>
            <button onClick={() => ref.current?.click()} disabled={busy} aria-busy={busy}
              className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
              <Icon name={busy ? 'sync' : 'upload'} size={14} />{busy ? 'Building plan…' : 'Upload Sponsored Products Bulk'}
            </button>
            {run && (
              <button onClick={clearAll} className="btn btn-ghost text-xs flex items-center gap-1 hover:text-down">
                <Icon name="delete" size={14} /> Clear
              </button>
            )}
            <input ref={ref} type="file" accept=".xlsx,.xlsm" className="hidden" onChange={e => upload(e.target.files?.[0])} />
          </div>
        </div>

        {err && <div className="mx-4 mt-4 card border-down/40 p-2 font-mono text-xs text-down inline-flex items-center gap-1"><Icon name="warning" size={12} /> {err}</div>}

        {showSettings && settings && (
          <SettingsDrawer settings={settings} onSave={saveSettings} />
        )}

        {ledger?.count > 0 && (
          <div className="mx-4 mt-4 card border-amber/40 p-3 font-mono text-xs flex items-center justify-between gap-3 flex-wrap">
            <span className="text-amber">
              <Icon name="pending_actions" size={12} /> {ledger.count} exported bid change{ledger.count === 1 ? '' : 's'} not yet confirmed in a new snapshot
              {ledger.stale > 0 && <span className="text-down"> · {ledger.stale} older than 7 days</span>}
            </span>
            <span className="flex gap-2">
              <button onClick={async () => { await api.waterfallLedgerApplied({}); api.waterfallLedger().then(setLedger) }}
                className="tag border border-edge text-up hover:bg-up hover:text-ink">mark all applied</button>
              <button onClick={async () => { await api.waterfallLedgerDiscard({}); api.waterfallLedger().then(setLedger) }}
                className="tag border border-edge text-mute hover:text-red">discard all</button>
            </span>
          </div>
        )}

        {busy && !run && <div className="p-4"><CardSkeleton lines={6} /></div>}

        {!busy && !run && (
          <div className="p-8 text-center">
            <div className="font-mono text-sm text-slate-200">No restructure plan yet</div>
            <div className="font-mono text-xs text-mute mt-1">
              Upload your full Sponsored Products bulk export above. The engine maps every campaign to its SKU + funnel slot,
              elects a profitable boss per slot, and builds the 4 phased bulk files (renames → bid cuts → creates → pauses).
            </div>
          </div>
        )}

        {run && (
          <div className="p-4 space-y-5">
            <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
              <Mini label="Campaigns" value={sm?.campaigns ?? '—'} />
              <Mini label="Single-SKU" value={sm?.single_sku ?? '—'} />
              <Mini label="Boss groups" value={state.boss_map?.length ?? 0} />
              <Mini label="Multi-SKU ⚠" value={sm?.multi?.length ?? 0} warn={(sm?.multi?.length || 0) > 0} />
              <Mini label="Mixed types ⚠" value={sm?.mixed?.length ?? 0} warn={(sm?.mixed?.length || 0) > 0} />
              <Mini label="Heroes" value={(run.heroes || []).length} />
            </div>
            <div className="font-mono text-[11px] text-mute">
              heroes: <span className="text-lime">{(run.heroes || []).join(' · ') || '—'}</span>
              {sm?.multi?.length > 0 && <span className="ml-3">multi-SKU campaigns are listed but excluded from the per-SKU funnel</span>}
            </div>

            <WaterfallGrid state={state} onOverride={overrideBoss} busy={busy} />

            <DataTable title={`Boss map · ${state.boss_map.length} SKU+slot groups`} columns={bossCols}
              rows={state.boss_map} rowKey={(r) => `${r.sku}|${r.slot}`} lean leanRows={16} scope={scope}
              empty="No SKU+slot groups (no single-SKU campaigns found)." placeholder="search sku / campaign…" />

            {(state.warnings?.with_orders?.length > 0 || state.warnings?.protected_empty?.length > 0) && (
              <WarningsCard warnings={state.warnings} />
            )}

            {PHASES.map(([p, title, blurb]) => {
              const items = state.phases?.[p] || []
              const locked = p === 'D' && !state.d_unlocked
              const isApplied = applied.has(p)
              return (
                <div key={p}>
                  <div className="flex items-center justify-between gap-3 flex-wrap mb-1">
                    <div className="font-mono text-xs">
                      <span className={`tag mr-2 ${isApplied ? 'bg-up text-ink' : 'border border-edge text-lime'}`}>Phase {p}{isApplied ? ' ✓' : ''}</span>
                      <span className="text-slate-200">{title}</span>
                      <span className="text-mute"> — {blurb}</span>
                    </div>
                    {items.length > 0 && (
                      <div className="flex items-center gap-2">
                        <button onClick={() => exportPhase(p)} disabled={locked || dl === p || sel[p].size === 0}
                          title={locked ? 'Locked until phases A, B and C are marked applied' : undefined}
                          className="btn btn-ghost text-xs flex items-center gap-1 disabled:opacity-40">
                          <Icon name={locked ? 'lock' : 'download'} size={14} />
                          {dl === p ? 'Building…' : `Export (${sel[p].size})`}
                        </button>
                        {!isApplied && (
                          <button onClick={() => markApplied(p)} className="btn btn-ghost text-xs flex items-center gap-1">
                            <Icon name="task_alt" size={14} />Mark applied
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                  <DataTable title={`${items.length} actions`} columns={phaseCols} rows={items}
                    rowKey={(r) => r.id} lean leanRows={10} scope={scope}
                    selectable selected={sel[p]} onToggle={toggle(p)} onToggleAll={setMany(p)}
                    empty="No actions in this phase." placeholder="search sku / detail…" />
                </div>
              )
            })}

            {bench?.rows?.length > 0 && <BenchmarkCard bench={bench} />}
          </div>
        )}
      </div>
    </div>
  )
}

// ASIN×slot grid — rows = SKU, columns = the 5 funnel slots. Each cell is the
// candidate count, color-coded: green = 1 clean candidate, amber = several (a
// boss was auto-picked — click to override), grey = 0 (slot will be created in
// Phase C). Clicking a cell with candidates opens the override panel below.
function WaterfallGrid({ state, onOverride, busy }) {
  const [open, setOpen] = useState(null)     // "sku|slot" of the open cell
  const bySlot = {}                          // sku -> slot -> group row
  for (const g of state.boss_map || []) (bySlot[g.sku] ||= {})[g.slot] = g
  // rows: heroes first (they get the full funnel), then any other SKU present
  const heroes = state.run?.heroes || []
  const others = Object.keys(bySlot).filter(s => !heroes.includes(s)).sort()
  const skus = [...heroes.filter(s => bySlot[s]), ...others]
  if (!skus.length) return null

  const openGroup = open ? bySlot[open.split('|')[0]]?.[open.split('|')[1]] : null

  async function pick(sku, slot, campaignId) {
    const overrides = { ...(state.overrides || {}) }
    const key = `${sku}|${slot}`
    // picking the auto-elected default clears the override; else set it
    const g = bySlot[sku]?.[slot]
    const autoId = g?.candidates?.find(c => c.is_boss && !g.boss_forced)?.campaign_id
    if (campaignId === autoId && !g?.boss_forced) delete overrides[key]
    else overrides[key] = campaignId
    await onOverride(overrides)
    setOpen(null)
  }

  return (
    <div className="card p-4 space-y-3">
      <div className="text-mute text-[11px] font-mono uppercase tracking-wider">
        ASIN × slot grid — click a multi-candidate cell to override the boss pick
      </div>
      <div className="overflow-x-auto">
        <table className="w-full font-mono text-xs border-separate" style={{ borderSpacing: 3 }}>
          <thead>
            <tr>
              <th className="text-left text-mute font-normal text-[10px] uppercase tracking-wider px-2">SKU</th>
              {SLOTS.map(s => (
                <th key={s} className="text-mute font-normal text-[10px] uppercase tracking-wider px-2 text-center">{SLOT_SHORT[s]}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {skus.map(sku => (
              <tr key={sku}>
                <td className="px-2 text-slate-200 whitespace-nowrap">{sku}</td>
                {SLOTS.map(slot => {
                  const g = bySlot[sku]?.[slot]
                  const n = g?.candidates?.length || 0
                  const key = `${sku}|${slot}`
                  const isOpen = open === key
                  let cls, label
                  if (n === 0) { cls = 'border-edge text-mute bg-transparent'; label = '＋ create' }
                  else if (n === 1) { cls = 'border-up/40 text-up bg-up/5'; label = '1' }
                  else { cls = `border-amber/50 text-amber bg-amber/5 ${g.boss_forced ? 'ring-1 ring-lime' : ''}`; label = `${n}` }
                  return (
                    <td key={slot} className="text-center">
                      <button disabled={n === 0 || busy}
                        onClick={() => setOpen(isOpen ? null : key)}
                        title={n === 0 ? 'no candidate — created in Phase C' : `${n} competing campaign${n === 1 ? '' : 's'}${g.boss_forced ? ' · overridden' : ''} — click to pick boss`}
                        className={`w-full min-w-[64px] rounded border px-2 py-1.5 ${cls} ${isOpen ? 'ring-1 ring-lime' : ''} ${n === 0 ? 'cursor-default' : 'hover:border-lime'} disabled:opacity-60`}>
                        {label}{g?.boss_forced ? ' ✎' : ''}
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {openGroup && (
        <CandidatePanel group={openGroup} busy={busy} onPick={pick} onClose={() => setOpen(null)} />
      )}
    </div>
  )
}

function CandidatePanel({ group, onPick, onClose, busy }) {
  const cands = [...(group.candidates || [])].sort((a, b) => (b.sales || 0) - (a.sales || 0))
  return (
    <div className="card border-lime/30 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="font-mono text-xs text-slate-200">
          {group.sku} · <span className="text-lime">{SLOT_SHORT[group.slot]}</span>
          <span className="text-mute"> — pick the boss campaign (keeps its ID + history)</span>
        </div>
        <button onClick={onClose} className="text-mute hover:text-slate-200"><Icon name="close" size={14} /></button>
      </div>
      <div className="space-y-1">
        {cands.map(c => (
          <label key={c.campaign_id}
            className={`flex items-center gap-3 px-2 py-1.5 rounded border cursor-pointer font-mono text-xs ${c.is_boss ? 'border-lime/50 bg-lime/5' : 'border-edge hover:border-mute'} ${busy ? 'opacity-60 pointer-events-none' : ''}`}>
            <input type="radio" name={`boss-${group.sku}-${group.slot}`} checked={!!c.is_boss}
              onChange={() => onPick(group.sku, group.slot, c.campaign_id)} className="accent-primary" />
            <span className="flex-1 text-slate-200 truncate" title={c.name}>{c.name}</span>
            <span className="text-mute whitespace-nowrap">{c.orders || 0} ord</span>
            <span className="text-mute whitespace-nowrap w-20 text-right">{money(c.sales)}</span>
            <span className={`whitespace-nowrap w-16 text-right ${c.acos != null && c.acos > 0.5 ? 'text-down' : 'text-mute'}`}>{pctf(c.acos)}</span>
            {c.is_boss && <span className="tag bg-lime text-ink">boss</span>}
          </label>
        ))}
      </div>
    </div>
  )
}

// Revenue-at-risk from the pause wave — must never be buried. with_orders =
// loser/empty campaigns Phase D will pause that still carry orders (loser
// consolidation is intentional, sales continue under the boss; empty ones with
// orders past protect_min_orders are excluded from D and listed separately).
function WarningsCard({ warnings }) {
  const wo = warnings.with_orders || []
  const pe = warnings.protected_empty || []
  return (
    <div className="card border-amber/40 p-4 space-y-3">
      <div className="text-amber text-[11px] font-mono uppercase tracking-wider flex items-center gap-1">
        <Icon name="warning" size={13} /> Pause wave — revenue at risk
      </div>
      {wo.length > 0 && (
        <div className="space-y-1">
          <div className="font-mono text-[10px] text-mute">{wo.length} campaign{wo.length === 1 ? '' : 's'} in Phase D still has orders (sales continue under the boss after consolidation):</div>
          {wo.map(w => (
            <div key={w.campaign_id} className="font-mono text-xs flex items-center justify-between gap-3 px-2 py-1 rounded border border-edge">
              <span className="text-slate-200">{w.name}</span>
              <span className="text-mute">{w.orders} orders · {money(w.sales)}</span>
            </div>
          ))}
        </div>
      )}
      {pe.length > 0 && (
        <div className="space-y-1">
          <div className="font-mono text-[10px] text-mute">{pe.length} empty campaign{pe.length === 1 ? '' : 's'} protected from auto-pause (orders ≥ protect_min_orders, no boss to consolidate into — needs manual review):</div>
          {pe.map(w => (
            <div key={w.campaign_id} className="font-mono text-xs flex items-center justify-between gap-3 px-2 py-1 rounded border border-edge">
              <span className="text-slate-200">{w.name}</span>
              <span className="text-mute">{w.orders} orders · {money(w.sales)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function SettingsDrawer({ settings, onSave }) {
  const [s, setS] = useState(settings)
  useEffect(() => setS(settings), [settings])
  const cell = 'bg-panel border border-edge rounded px-2 py-1.5 font-mono text-xs text-slate-200 w-full focus:outline-none focus:border-mute'
  const stratSfx = s.new_strategy === 'up_down' ? 'up/down' : 'down'
  const exBid = ((s.slot_bids || {})['KWT-EXACT'] ?? 0.50).toFixed(2)
  const preview = String(s.naming_template || '')
    .replace('{sku}', 'PI-220').replace('{asin}', 'B000LI9SI6').replace('{slot}', 'KWT - EXACT')
    .replace('{n}', '4').replace('{bid}', exBid).replace('{strategy}', stratSfx)
  return (
    <div className="mx-4 mt-4 card p-4 space-y-3">
      <div className="text-mute text-[10px] font-mono uppercase tracking-wider">waterfall settings — applied on the next upload</div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="block">
          <span className="font-mono text-[10px] text-mute uppercase tracking-wider">naming template ({'{sku} {asin} {slot} {n} {bid} {strategy}'})</span>
          <input className={cell} value={s.naming_template || ''} onChange={e => setS({ ...s, naming_template: e.target.value })} />
          <span className="font-mono text-[10px] text-mute">preview: <span className="text-lime">{preview}</span></span>
        </label>
        <label className="block">
          <span className="font-mono text-[10px] text-mute uppercase tracking-wider">hero SKUs (comma-separated, blank = top N by sales)</span>
          <input className={cell} value={(s.heroes || []).join(', ')}
            onChange={e => setS({ ...s, heroes: e.target.value.split(',').map(x => x.trim()).filter(Boolean) })}
            placeholder="auto (top N)" />
        </label>
        <label className="block">
          <span className="font-mono text-[10px] text-mute uppercase tracking-wider">goal ACoS (fraction)</span>
          <input className={cell} type="number" step="0.01" min="0.01" max="2" value={s.goal_acos ?? 0.25}
            onChange={e => setS({ ...s, goal_acos: parseFloat(e.target.value) || 0.25 })} />
        </label>
        <label className="block">
          <span className="font-mono text-[10px] text-mute uppercase tracking-wider">daily budget $ (bosses + new campaigns)</span>
          <input className={cell} type="number" step="1" min="1" value={s.budget ?? 10}
            onChange={e => setS({ ...s, budget: parseFloat(e.target.value) || 10 })} />
        </label>
        <label className="block">
          <span className="font-mono text-[10px] text-mute uppercase tracking-wider">seed min orders</span>
          <input className={cell} type="number" step="1" min="1" value={s.seed_min_orders ?? 1}
            onChange={e => setS({ ...s, seed_min_orders: parseInt(e.target.value) || 1 })} />
        </label>
        <label className="block">
          <span className="font-mono text-[10px] text-mute uppercase tracking-wider">hero count (when auto)</span>
          <input className={cell} type="number" step="1" min="1" value={s.hero_n ?? 5}
            onChange={e => setS({ ...s, hero_n: parseInt(e.target.value) || 5 })} />
        </label>
        <label className="block">
          <span className="font-mono text-[10px] text-mute uppercase tracking-wider">seed bid floor $</span>
          <input className={cell} type="number" step="0.05" min="0.02" value={s.bid_floor ?? 0.30}
            onChange={e => setS({ ...s, bid_floor: parseFloat(e.target.value) || 0.30 })} />
        </label>
        <label className="block">
          <span className="font-mono text-[10px] text-mute uppercase tracking-wider">seed bid ceiling $</span>
          <input className={cell} type="number" step="0.05" min="0.02" value={s.bid_ceiling ?? 2.00}
            onChange={e => setS({ ...s, bid_ceiling: parseFloat(e.target.value) || 2.00 })} />
        </label>
        <label className="block">
          <span className="font-mono text-[10px] text-mute uppercase tracking-wider">protect min orders (guards EMPTY campaigns from auto-pause)</span>
          <input className={cell} type="number" step="1" min="0" value={s.protect_min_orders ?? 1}
            onChange={e => setS({ ...s, protect_min_orders: parseInt(e.target.value) || 0 })} />
        </label>
        <label className="block">
          <span className="font-mono text-[10px] text-mute uppercase tracking-wider">new-campaign bidding strategy</span>
          <select className={cell} value={s.new_strategy || 'down'}
            onChange={e => setS({ ...s, new_strategy: e.target.value })}>
            <option value="down">Dynamic bids — down only</option>
            <option value="up_down">Dynamic bids — up and down</option>
            <option value="fixed">Fixed bid</option>
          </select>
          <span className="font-mono text-[10px] text-mute">applied to every campaign Phase C creates (feeds {'{strategy}'} in the name)</span>
        </label>
        <label className="block md:col-span-2">
          <span className="font-mono text-[10px] text-mute uppercase tracking-wider">protected campaign IDs (comma-separated — never bid-cut or paused)</span>
          <input className={cell} value={(s.protected_campaign_ids || []).join(', ')}
            onChange={e => setS({ ...s, protected_campaign_ids: e.target.value.split(',').map(x => x.trim()).filter(Boolean) })}
            placeholder="none" />
        </label>
      </div>

      <div>
        <div className="font-mono text-[10px] text-mute uppercase tracking-wider mb-1.5">per-slot default bid $ (NEW campaigns — feeds the ad group default bid + {'{bid}'} in the name; AT split targets scale off AT)</div>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          {SLOTS.map(slot => (
            <label key={slot} className="block">
              <span className="font-mono text-[10px] text-mute">{SLOT_SHORT[slot]}</span>
              <input className={cell} type="number" step="0.05" min="0.02"
                value={(s.slot_bids || {})[slot] ?? ''}
                onChange={e => setS({ ...s, slot_bids: { ...(s.slot_bids || {}), [slot]: parseFloat(e.target.value) || 0 } })} />
            </label>
          ))}
        </div>
      </div>
      <label className="font-mono text-xs text-mute flex items-center gap-2">
        <input type="checkbox" checked={!!s.seed_copies} onChange={e => setS({ ...s, seed_copies: e.target.checked })} className="accent-primary" />
        seed broad/phrase copies (×0.6 / ×0.75 bid) into NEW empty slots
      </label>
      <label className="font-mono text-xs text-mute flex items-center gap-2">
        <input type="checkbox" checked={!!s.force_down_only} onChange={e => setS({ ...s, force_down_only: e.target.checked })} className="accent-primary" />
        force bosses running "up and down" to "down only" on rename (Phase A) — some accounts deliberately run up/down, leave off if so
      </label>
      <button onClick={() => onSave(s)} className="btn btn-primary text-xs">Save settings</button>
    </div>
  )
}

// day-0 benchmark — same DataTable kit as every other list
function BenchmarkCard({ bench }) {
  const d = (v, invert = false) => {
    if (v == null) return <span className="text-mute">—</span>
    const good = invert ? v < 0 : v > 0
    return <span className={good ? 'text-up' : v === 0 ? 'text-mute' : 'text-down'}>{v > 0 ? '+' : ''}{typeof v === 'number' ? +v.toFixed(2) : v}</span>
  }
  const cols = [
    { key: 'sku', label: 'SKU', render: r => <span className="text-slate-200">{r.sku}</span> },
    { key: 'spend', label: 'Spend', align: 'right', value: r => r.day0.spend, render: r => money(r.day0.spend) },
    { key: 'sales', label: 'Sales', align: 'right', value: r => r.day0.sales, render: r => money(r.day0.sales) },
    { key: 'orders', label: 'Orders', align: 'right', value: r => r.day0.orders, render: r => r.day0.orders },
    { key: 'acos', label: 'ACoS', align: 'right', value: r => r.day0.acos,
      render: r => {
        const be = r.current?.break_even_acos ?? r.day0.break_even_acos
        const a = r.day0.acos
        return <span className={be != null && a != null ? (a > be ? 'text-down' : 'text-up') : ''}
          title={be != null ? `break-even ${(be * 100).toFixed(1)}% — red = ACoS above it` : ''}>{pctf(a)}</span>
      } },
    { key: 'be_acos', label: 'BE ACoS', align: 'right',
      value: r => r.current?.break_even_acos ?? r.day0.break_even_acos ?? -1,
      render: r => {
        const be = r.current?.break_even_acos ?? r.day0.break_even_acos
        return be != null
          ? <span className="text-mute" title="break-even ACoS: catalog price + per-SKU COGS + the SKU's real fees from the Transactions ledger">{pctf(be)}</span>
          : <span className="text-mute">—</span>
      } },
    { key: 'd_sales', label: 'Δ Sales', align: 'right', value: r => r.delta?.sales,
      render: r => bench.same_run ? <span className="text-mute">—</span> : d(r.delta?.sales) },
    { key: 'd_acos', label: 'Δ ACoS', align: 'right', value: r => r.delta?.acos,
      render: r => bench.same_run ? <span className="text-mute">—</span> : d(r.delta?.acos != null ? +(r.delta.acos * 100).toFixed(1) : null, true) },
  ]
  return (
    <div className="card">
      <DataTable lean leanRows={12}
        title={`day-0 benchmark ${bench.same_run ? '· upload a fresh bulk later for the day-21 verdict' : `· day-0 run #${bench.day0_run} vs run #${bench.current_run}`}`}
        columns={cols} rows={bench.rows} rowKey={r => r.sku} empty="no benchmark rows" />
    </div>
  )
}

function Mini({ label, value, warn }) {
  return (
    <div className="card p-2">
      <div className="text-mute text-[9px] font-mono uppercase tracking-wider">{label}</div>
      <div className={`font-mono text-sm font-bold mt-0.5 ${warn ? 'text-amber' : 'text-slate-100'}`}>{value}</div>
    </div>
  )
}
