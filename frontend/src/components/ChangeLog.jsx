import React, { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { Spinner, TableSkeleton, Icon } from './ui.jsx'
import { useTableControls, TableToolbar, Pagination, Th } from './table.jsx'
import { useModals } from './Modal.jsx'
import { useToast } from './Toast.jsx'

const SRC = [['', 'ALL'], ['audit_bulk', 'Audit'], ['bid_optimizer', 'Bid Opt'],
  ['placement', 'Placement'], ['harvest', 'Harvest']]
const SRC_CLR = {
  audit_bulk: 'text-amber', bid_optimizer: 'text-cyan', placement: 'text-lime', harvest: 'text-lime',
}

// Change Log / Audit Trail: every action written to a bulk export, old -> new + why.
export function ChangeLogPanel({ scope }) {
  const toast = useToast()
  const { confirm } = useModals()
  const [entries, setEntries] = useState([])
  const [source, setSource] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [report, setReport] = useState(null)   // client report message text
  const [copied, setCopied] = useState(false)
  const ctl = useTableControls(entries, {
    searchKeys: ['source', 'action', 'label', 'entity_type', 'field', 'old_value', 'new_value', 'reason'],
    deps: [scope, source],
  })

  function load(src) {
    setBusy(true); setErr(null)
    api.changelog(src || undefined).then(r => setEntries(r.entries)).catch(e => setErr(String(e)))
      .finally(() => setBusy(false))
  }
  useEffect(() => { load(source); setReport(null) }, [scope, source])

  async function downloadXlsx() {
    setErr(null)
    try {
      const blob = await api.changelogExport(source || undefined)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'ppc_change_log.xlsx'; a.click()
      URL.revokeObjectURL(url)
      toast.success('Change log exported to .xlsx')
    } catch (e) { setErr(String(e)); toast.error(String(e)) }
  }
  async function buildReport() {
    setErr(null)
    try {
      const r = await api.changelogReport(source || undefined)
      setReport(r.text)
    } catch (e) { setErr(String(e)) }
  }
  async function clearLog() {
    const scoped = source ? `the ${SRC.find(([v]) => v === source)?.[1]} entries` : 'ALL entries'
    const ok = await confirm({
      title: 'Clear change log?', danger: true, confirmLabel: 'Clear log',
      message: `Permanently deletes ${scoped} of this audit's change log — the record of what was `
        + 'exported to Amazon. Export the .xlsx first if you need to keep it.\n\nThis cannot be undone.',
    })
    if (!ok) return
    try {
      const r = await api.changelogClear(source || undefined)
      toast.success(`Cleared ${r.deleted} change-log entr${r.deleted === 1 ? 'y' : 'ies'}`)
      setReport(null); load(source)
    } catch (e) { setErr(String(e)); toast.error(String(e)) }
  }
  async function copyReport() {
    try { await navigator.clipboard.writeText(report || ''); setCopied(true); setTimeout(() => setCopied(false), 1500); toast.success('Report message copied to clipboard') }
    catch (e) { /* clipboard blocked — user can select the textarea */ toast.error('Copy blocked — select the text manually') }
  }

  return (
    <div className="card">
      <div className="p-4 border-b border-edge flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1">change log · audit trail · {entries.length}</div>
          <div className="text-xs text-mute font-mono">every action written to a bulk export — old → new value, with the reason.</div>
        </div>
        <div className="flex gap-1 items-center flex-wrap">
          {SRC.map(([v, label]) => (
            <button key={v} onClick={() => setSource(v)}
              className={`tag ${source === v ? 'bg-lime text-ink' : 'border border-edge text-mute hover:text-slate-300'}`}>{label}</button>
          ))}
          <button onClick={() => load(source)} aria-busy={busy} title="refresh" className="tag border border-edge text-mute hover:text-lime inline-flex items-center"><Icon name="refresh" size={14} /></button>
          <span className="w-px h-4 bg-edge mx-1" />
          <button onClick={downloadXlsx} disabled={!entries.length}
            className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50"><Icon name="download" size={14} /> Export .xlsx</button>
          <button onClick={buildReport} disabled={!entries.length}
            className="btn btn-ghost text-xs flex items-center gap-1 disabled:opacity-40"><Icon name="mail" size={14} /> Report message</button>
          <button onClick={clearLog} disabled={!entries.length}
            className="btn btn-ghost text-xs flex items-center gap-1 hover:text-down disabled:opacity-40"><Icon name="delete" size={14} /> Clear</button>
        </div>
      </div>

      {report != null && (
        <div className="p-4 border-b border-edge bg-edge/10">
          <div className="flex items-center justify-between mb-2">
            <div className="text-mute text-[11px] font-mono uppercase tracking-wider">client report message</div>
            <div className="flex gap-1">
              <button onClick={copyReport} className="tag border border-edge text-mute hover:text-lime inline-flex items-center gap-1">{copied ? <><Icon name="check_circle" size={14} /> copied</> : <><Icon name="content_copy" size={14} /> copy</>}</button>
              <button onClick={() => setReport(null)} className="tag border border-edge text-mute hover:text-red"><Icon name="close" size={14} /></button>
            </div>
          </div>
          <textarea readOnly value={report} onFocus={(e) => e.target.select()}
            className="w-full h-64 bg-panel border border-edge rounded p-3 font-mono text-xs text-slate-200" />
        </div>
      )}

      {busy && <TableSkeleton rows={8} cols={5} toolbar={false} />}
      {err && <div className="m-4 card border-red/40 p-3 font-mono text-sm text-red inline-flex items-center gap-1"><Icon name="warning" size={14} /> {err}</div>}

      {!busy && <TableToolbar ctl={ctl} placeholder="search action / entity / reason…" />}
      {!busy && (
        <div className="overflow-auto max-h-[600px]">
          <table className="w-full text-sm font-mono">
            <thead className="sticky top-0 bg-panel text-mute text-[11px] uppercase">
              <tr className="border-b border-edge">
                <Th ctl={ctl} k="ts">When</Th><Th ctl={ctl} k="source">Source</Th>
                <Th ctl={ctl} k="action">Action</Th><Th ctl={ctl} k="label">Entity</Th>
                <Th ctl={ctl} k="field">Field</Th><Th ctl={ctl} k="old_value" align="right">Old</Th>
                <Th ctl={ctl} k="new_value" align="right">New</Th><Th ctl={ctl} k="reason">Reason</Th>
              </tr>
            </thead>
            <tbody>
              {ctl.view.map((e) => (
                <tr key={e.id} className="border-b border-edge/50 hover:bg-edge/30">
                  <td className="p-2 text-mute whitespace-nowrap">{(e.ts || '').replace('T', ' ').slice(0, 16)}</td>
                  <td className={`p-2 ${SRC_CLR[e.source] || 'text-mute'}`}>{e.source}</td>
                  <td className="p-2 text-slate-200">{e.action}</td>
                  <td className="p-2 max-w-[200px] truncate text-slate-300" title={e.label}>{e.label || e.entity_type}</td>
                  <td className="p-2 text-mute">{e.field}</td>
                  <td className="p-2 text-right text-mute">{e.old_value ?? '—'}</td>
                  <td className="p-2 text-right text-lime">{e.new_value ?? '—'}</td>
                  <td className="p-2 max-w-[260px] truncate text-mute text-xs" title={e.reason}>{e.reason}</td>
                </tr>
              ))}
              {ctl.view.length === 0 && <tr><td colSpan="8" className="p-6 text-center text-mute">{ctl.query ? 'no matches' : 'no actions logged yet — export a bulk file from any engine'}</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {!busy && <Pagination ctl={ctl} />}
    </div>
  )
}
