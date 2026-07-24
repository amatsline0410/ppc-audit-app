import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { Spinner, pct, money, TemplateLink, TableSkeleton, Icon } from './ui.jsx'
import { useTableControls, TableToolbar, Pagination, Th } from './table.jsx'
import { useToast } from './Toast.jsx'

// Product Benchmark: per-ASIN break-even ACoS for PPC. Upload (ASIN + Break-even
// ACoS/ROAS, optional Sale Price) or fall back to costs-derived break-even.
export function BenchmarkPanel({ scope, onLoaded }) {
  const toast = useToast()
  const inputRef = useRef()
  const [drag, setDrag] = useState(false)
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let live = true
    api.benchmark().then(d => live && setData(d)).catch(() => {})
    return () => { live = false }
  }, [scope])

  async function upload(file) {
    if (!file) return
    setErr(null); setBusy(true)
    try { const d = await api.uploadBenchmark(file); setData(d); toast.success(`Benchmark uploaded · ${d.matched ?? d.count ?? 0}/${d.count ?? 0} matched`); onLoaded?.() }
    catch (e) { setErr(String(e)); toast.error(String(e)) }
    finally { setBusy(false) }
  }

  const rows = data?.rows || []
  const ctl = useTableControls(rows, { searchKeys: ['asin', 'source'], deps: [scope] })

  return (
    <div className="card">
      <div className="p-4 border-b border-edge">
        <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1">
          product benchmark · break-even
          <span className="tag border border-cyan/30 text-cyan ml-2 normal-case">store-wide</span>
          <TemplateLink kind="benchmark" />
        </div>
        <div className="text-xs text-mute font-mono">
          upload ONCE per store — every audit in this store auto-matches its ASINs against it.
          (ASIN + Break-even ACoS or ROAS, optional Sale Price). targets above break-even flag <span className="text-red">BLEEDING</span>.
          {data?.matched != null && <span className="text-lime"> {data.matched}/{data.count} matched in this audit.</span>}
        </div>
      </div>

      <div className="p-4">
        <div
          onDragOver={e => { e.preventDefault(); setDrag(true) }}
          onDragLeave={() => setDrag(false)}
          onDrop={e => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files[0]) }}
          onClick={() => inputRef.current?.click()}
          className={`card p-5 cursor-pointer text-center transition-colors ${drag ? 'border-lime bg-lime/5' : 'border-dashed'}`}
        >
          <input ref={inputRef} type="file" accept=".xlsx,.xlsm,.csv" hidden onChange={e => upload(e.target.files[0])} />
          {busy ? <Spinner label="loading benchmark…" /> : (
            <div className="font-mono text-sm">
              <div className="text-lime text-base mb-1 inline-flex items-center gap-1"><Icon name="upload" size={18} /> drop Product Benchmark .xlsx</div>
              <div className="text-mute">no file? break-even is auto-derived from your costs + sale price</div>
            </div>
          )}
        </div>
      </div>

      {err && <div className="mx-4 mb-4 card border-red/40 p-3 font-mono text-sm text-red">⚠ {err}</div>}

      {data === null && <TableSkeleton rows={6} cols={6} />}

      {rows.length > 0 && (
        <>
        <TableToolbar ctl={ctl} placeholder="search ASIN / source…" />
        <div className="overflow-auto max-h-[360px]">
          <table className="w-full text-sm font-mono">
            <thead className="sticky top-0 bg-panel text-mute text-[11px] uppercase">
              <tr className="border-b border-edge">
                <Th ctl={ctl} k="asin">ASIN</Th>
                <Th ctl={ctl} k="sale_price" align="right">Sale price</Th>
                <Th ctl={ctl} k="cogs" align="right">COGS</Th>
                <Th ctl={ctl} k="amazon_fee" align="right">Amazon fee</Th>
                <Th ctl={ctl} k="profit_per_unit" align="right">Profit/unit</Th>
                <Th ctl={ctl} k="break_even_acos" align="right">Break-even ACoS</Th>
                <Th ctl={ctl} k="break_even_roas" align="right">Break-even ROAS</Th>
                <Th ctl={ctl} k="source">Source</Th>
              </tr>
            </thead>
            <tbody>
              {ctl.view.map((r, i) => (
                <tr key={i} className={`border-b border-edge/50 hover:bg-edge/30 ${r.in_audit === false ? 'opacity-50' : ''}`}>
                  <td className="p-2 text-slate-200" title={r.in_audit === false ? 'not in this audit — kept for other audits in this store' : 'matched in this audit'}>{r.asin}{r.in_audit === false ? ' ·' : ''}</td>
                  <td className="p-2 text-right text-slate-300">{r.sale_price != null ? money(r.sale_price) : '—'}</td>
                  <td className="p-2 text-right text-slate-300" title={r.cogs_default ? 'default % of price (no unit cost set)' : ''}>{r.cogs != null ? money(r.cogs) : '—'}{r.cogs_default ? ' %' : ''}</td>
                  <td className="p-2 text-right text-red">{r.amazon_fee != null ? money(r.amazon_fee) : '—'}</td>
                  <td className={`p-2 text-right font-bold ${r.profit_per_unit == null ? 'text-mute' : r.profit_per_unit >= 0 ? 'text-lime' : 'text-red'}`}>{r.profit_per_unit != null ? money(r.profit_per_unit) : '—'}</td>
                  <td className="p-2 text-right text-lime">{r.break_even_acos != null ? pct(r.break_even_acos) : '—'}</td>
                  <td className="p-2 text-right text-cyan">{r.break_even_roas != null ? `${r.break_even_roas}×` : '—'}</td>
                  <td className="p-2"><span className="tag border border-edge text-mute">{r.source || '—'}</span></td>
                </tr>
              ))}
              {ctl.view.length === 0 && <tr><td colSpan="8" className="p-6 text-center text-mute">no matches</td></tr>}
            </tbody>
          </table>
        </div>
        <Pagination ctl={ctl} />
        </>
      )}
    </div>
  )
}
