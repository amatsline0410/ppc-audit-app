import React, { useMemo, useState } from 'react'
import { FlagBadge, StageBadge, money, pct, Icon } from './ui.jsx'
import { useTableControls, TableToolbar, Pagination, Th } from './table.jsx'

const ALL_FLAGS = ['ALL', 'BLEEDING', 'HIGH_ACOS', 'SCALE_WINNER', 'WASTED_SPEND', 'OVERBID', 'LOW_CVR', 'LOW_CTR']

// `focus` (from the active Audit Cadence) restricts this table to that cadence's
// own flag set, so each cadence shows a distinct, bulk-derived view. Empty/undefined
// = full audit (Full Month). `title` labels the table with the cadence's intent.
export function AuditTable({ flags, selected, setSelected, onAutomate, automating, focus, title }) {
  const hasFocus = Array.isArray(focus) && focus.length > 0
  const [filter, setFilter] = useState('ALL')

  // only this cadence's flags feed the table; chips list ALL + the focus set
  const scoped = useMemo(
    () => (hasFocus ? flags.filter(f => focus.includes(f.flag)) : flags),
    [flags, focus, hasFocus]
  )
  const chips = hasFocus ? ['ALL', ...focus] : ALL_FLAGS

  // reset the sub-filter when the cadence focus changes (stale chip selection)
  React.useEffect(() => { setFilter('ALL') }, [focus])

  const base = useMemo(
    () => scoped.filter(f => filter === 'ALL' || f.flag === filter),
    [scoped, filter]
  )
  const ctl = useTableControls(base, {
    searchKeys: ['label', 'entity_id', 'flag', 'suggested_action'],
    accessors: { label: f => f.label || f.entity_id }, deps: [filter],
  })
  const rows = ctl.view
  const actionable = base.filter(f => f.new_bid != null)
  const allSel = actionable.length > 0 && actionable.every(f => selected.has(key(f)))

  function toggle(f) {
    const k = key(f); const s = new Set(selected)
    s.has(k) ? s.delete(k) : s.add(k); setSelected(s)
  }
  function toggleAll() {
    const s = new Set(selected)
    if (allSel) actionable.forEach(f => s.delete(key(f)))
    else actionable.forEach(f => s.add(key(f)))
    setSelected(s)
  }

  return (
    <div className="card">
      {title && (
        <div className="px-4 pt-3 pb-1">
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider">{title}</div>
        </div>
      )}
      <div className="flex items-center justify-between p-4 border-b border-edge">
        <div className="flex gap-1 flex-wrap">
          {chips.map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`tag ${filter === f ? 'bg-lime text-ink' : 'border border-edge text-mute hover:text-slate-300'}`}>
              {f === 'ALL' ? `ALL ${scoped.length}` : `${f} ${scoped.filter(x => x.flag === f).length}`}
            </button>
          ))}
        </div>
        <button disabled={selected.size === 0 || automating} onClick={onAutomate} aria-busy={automating}
          className={`btn ${selected.size ? 'btn-primary' : 'btn-ghost opacity-50'}`}>
          {automating ? 'building…' : <><Icon name="download" size={14} /> bulk file ({selected.size})</>}
        </button>
      </div>

      <TableToolbar ctl={ctl} placeholder="search target / flag / action…" />
      <div className="overflow-auto max-h-[480px]">
        <table className="w-full text-sm font-mono">
          <thead className="sticky top-0 bg-panel text-mute text-[11px] uppercase">
            <tr className="border-b border-edge">
              <th className="p-2 text-left w-8"><input type="checkbox" checked={allSel} onChange={toggleAll} className="accent-lime" /></th>
              <Th ctl={ctl} k="label">Target</Th>
              <Th ctl={ctl} k="flag">Flag</Th>
              <Th ctl={ctl} k="observed" align="right">Observed</Th>
              <Th ctl={ctl} k="break_even" align="right">BE ACoS</Th>
              <Th ctl={ctl} k="new_bid" align="right">Bid →</Th>
              <Th ctl={ctl} k="suggested_action">Action</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f, i) => (
              <tr key={i} className="border-b border-edge/50 hover:bg-edge/30">
                <td className="p-2">
                  {f.new_bid != null &&
                    <input type="checkbox" checked={selected.has(key(f))} onChange={() => toggle(f)} className="accent-lime" />}
                </td>
                <td className="p-2 max-w-[220px] truncate text-slate-200" title={f.label}>{f.label || f.entity_id}</td>
                <td className="p-2 whitespace-nowrap"><FlagBadge flag={f.flag} severity={f.severity} /> <StageBadge stage={f.stage} /></td>
                <td className={`p-2 text-right ${f.break_even != null && (f.flag.includes('ACOS') || f.flag === 'SCALE_WINNER' || f.flag === 'BLEEDING') && f.observed != null ? (f.observed > f.break_even ? 'text-down' : 'text-up') : 'text-slate-300'}`}
                  title={f.break_even != null ? `break-even ${(f.break_even * 100).toFixed(1)}% — red = observed ACoS above it` : ''}>
                  {(f.flag.includes('ACOS') || f.flag === 'SCALE_WINNER' || f.flag === 'BLEEDING') ? pct(f.observed) : f.flag === 'WASTED_SPEND' ? money(f.observed) : (f.observed ?? '—')}
                </td>
                <td className="p-2 text-right text-mute"
                  title="the ASIN's break-even ACoS — benchmark upload wins, else catalog price + per-SKU COGS (default 40%)">
                  {f.break_even != null ? pct(f.break_even) : '—'}</td>
                <td className="p-2 text-right text-lime">{f.new_bid != null ? `$${f.new_bid}` : '—'}</td>
                <td className="p-2 text-mute text-xs">{f.suggested_action}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan="7" className="p-6 text-center text-mute">{ctl.query ? 'no matches' : 'no flags at this threshold'}</td></tr>}
          </tbody>
        </table>
      </div>
      <Pagination ctl={ctl} />
    </div>
  )
}

function key(f) { return `${f.entity_id}:${f.flag}` }
export { key as flagKey }
