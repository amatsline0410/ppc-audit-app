import React, { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { Icon } from './ui.jsx'
import { DataTable } from './table.jsx'

// Per-audit setup checklist — compact sidebar card on the PPC Optimization tab (next
// to the Goal ACoS control, where the audit workflow happens). Auto items tick
// themselves from real state (uploads, costs, exports); manual items are user
// tasks. Items render through the shared DataTable (lean) so the checklist
// follows the same table-list pattern as every other list in the app.
// Collapsed state persists; auto-opens while setup is incomplete.
const OPEN_KEY = 'ppc_checklist_open'

export function ChecklistCard({ scope }) {
  const [data, setData] = useState(null)
  const [text, setText] = useState('')
  const [open, setOpen] = useState(() => {
    const v = localStorage.getItem(OPEN_KEY)
    return v == null ? null : v === '1'          // null = no choice yet -> auto
  })
  const [err, setErr] = useState(null)

  function load() { api.checklist().then(setData).catch(e => setErr(String(e))) }
  useEffect(() => { load() }, [scope])  // eslint-disable-line

  async function add() {
    if (!text.trim()) return
    try { await api.addTask(text.trim()); setText(''); load() } catch (e) { setErr(String(e)) }
  }
  async function toggle(id, done) { try { await api.toggleTask(id, done); load() } catch (e) { setErr(String(e)) } }
  async function remove(id) { try { await api.deleteTask(id); load() } catch (e) { setErr(String(e)) } }

  if (!data) return null
  const { done, total } = data.progress
  const pct = total ? Math.round((done / total) * 100) : 0
  const isOpen = open == null ? pct < 100 : open   // no saved choice: open while incomplete
  const setOpenSave = (v) => { setOpen(v); localStorage.setItem(OPEN_KEY, v ? '1' : '0') }

  // one table-list over both kinds: auto items (read-only, tick from real
  // state) + manual tasks (toggle / delete)
  const rows = [
    ...data.auto.map(a => ({ kind: 'auto', id: `a:${a.key}`, label: a.label, done: a.done, hint: a.hint })),
    ...data.manual.map(m => ({ kind: 'manual', id: `m:${m.id}`, mid: m.id, label: m.text, done: m.done })),
  ]

  const COLS = [
    { key: 'done', label: '✓', align: 'right', value: x => (x.done ? 1 : 0),
      render: x => x.kind === 'auto'
        ? <span title={`${x.hint || ''} (auto — ticks itself from real data)`}
            className={`w-3.5 h-3.5 rounded border inline-flex items-center justify-center text-[9px] ${x.done ? 'bg-lime/20 border-lime text-lime' : 'border-edge text-mute'}`}>{x.done ? '✓' : ''}</span>
        : <button onClick={() => toggle(x.mid, !x.done)} title={x.done ? 'mark not done' : 'mark done'}
            className={`w-3.5 h-3.5 rounded border inline-flex items-center justify-center text-[9px] ${x.done ? 'bg-cyan/20 border-cyan text-cyan' : 'border-edge text-mute hover:border-cyan'}`}>{x.done ? '✓' : ''}</button> },
    { key: 'label', label: 'Task', value: x => x.label,
      render: x => (
        <span title={x.kind === 'auto' ? `${x.hint || ''} (auto)` : x.label}
          className={`inline-block max-w-[170px] truncate align-bottom text-xs ${x.done ? (x.kind === 'manual' ? 'text-mute line-through' : 'text-slate-300') : x.kind === 'auto' ? 'text-mute' : 'text-slate-300'}`}>
          {x.label}
        </span>) },
    { key: 'kind', label: '', align: 'right', value: x => x.kind,
      render: x => x.kind === 'auto'
        ? <span className="text-slate-600 text-[9px]">auto</span>
        : <button onClick={() => remove(x.mid)} title="delete task"
            className="text-mute hover:text-red text-[11px]">✕</button> },
  ]

  return (
    <div className="card">
      <button onClick={() => setOpenSave(!isOpen)} className="w-full p-3 flex items-center gap-2 text-left">
        <Icon name="checklist" size={14} className={pct === 100 ? 'text-up' : 'text-lime'} />
        <span className="text-mute text-[10px] font-mono uppercase tracking-wider flex-1">audit setup</span>
        <span className={`font-mono text-[11px] whitespace-nowrap ${pct === 100 ? 'text-up' : 'text-mute'}`}>
          {pct === 100 ? '✓ done' : `${done}/${total}`}
        </span>
        <span className="text-mute text-[10px]">{isOpen ? '▾' : '▸'}</span>
      </button>
      <div className="px-3 -mt-1 pb-2">
        <div className="h-1 bg-edge rounded overflow-hidden">
          <div className={`h-full transition-all ${pct === 100 ? 'bg-up' : 'bg-lime'}`} style={{ width: `${pct}%` }} />
        </div>
      </div>

      {isOpen && (
        <div className="px-3 pb-3 space-y-2">
          {err && <div className="font-mono text-[11px] text-red">⚠ {err}</div>}

          <DataTable title={`tasks · ${done}/${total}`} lean leanRows={30}
            columns={COLS} rows={rows} rowKey={x => x.id} empty="no tasks" />

          {/* add task */}
          <div className="flex gap-1.5">
            <input value={text} onChange={e => setText(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && add()} placeholder="add a task…"
              className="flex-1 min-w-0 bg-panel border border-edge rounded px-2 py-1 font-mono text-[11px] text-slate-100 focus:outline-none focus:border-lime" />
            <button onClick={add} className="btn btn-ghost text-[11px]">add</button>
          </div>
        </div>
      )}
    </div>
  )
}
