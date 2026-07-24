import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { Spinner, money, pct, TemplateLink, TableSkeleton, Icon } from './ui.jsx'
import { useTableControls, TableToolbar, Pagination, Th } from './table.jsx'
import { useToast } from './Toast.jsx'

// ---- delta helpers ----
const d0 = (x) => (x == null ? '—' : (x >= 0 ? `+${x}` : `${x}`))
const dMoney = (x) => (x == null ? '—' : (x >= 0 ? '+' : '−') + '$' + Math.abs(Math.round(x)).toLocaleString())
const dPct = (x) => (x == null ? '—' : (x >= 0 ? '+' : '−') + (Math.abs(x) * 100).toFixed(1) + 'pt')
const upClass = (x, goodWhenDown = false) => {
  if (x == null || x === 0) return 'text-mute'
  const good = goodWhenDown ? x < 0 : x > 0
  return good ? 'text-lime' : 'text-red'
}

// Period-over-period trend (needs >=2 uploads with different snapshot dates).
export function TrendsPanel({ scope }) {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let live = true
    setBusy(true); setErr(null)
    api.trends().then(r => { if (live) setData(r) }).catch(e => live && setErr(String(e)))
      .finally(() => live && setBusy(false))
    return () => { live = false }
  }, [scope])

  const ctl = useTableControls(data?.movers || [], {
    searchKeys: ['name', 'campaign_id'],
    accessors: { name: m => m.name || m.campaign_id }, deps: [scope, data],
  })

  return (
    <div className="card">
      <div className="p-4 border-b border-edge">
        <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1">trends · period over period</div>
        <div className="text-xs text-mute font-mono">latest two snapshots in this audit. upload again on a later date to build history.</div>
      </div>

      {busy && <TableSkeleton rows={6} cols={5} toolbar={false} />}
      {err && <div className="m-4 card border-red/40 p-3 font-mono text-sm text-red inline-flex items-center gap-1"><Icon name="warning" size={14} /> {err}</div>}

      {data && !busy && !data.have_history && (
        <div className="p-5 font-mono text-sm text-mute">
          only one snapshot ({data.snapshots[0] || '—'}). Upload a newer bulk file to compare.
        </div>
      )}

      {data && data.have_history && (
        <div className="p-4 space-y-4">
          <div className="font-mono text-[11px] text-mute">{data.previous} → {data.current}</div>
          <div className="grid grid-cols-4 gap-3">
            {[
              ['spend', dMoney(data.totals.delta.spend), upClass(data.totals.delta.spend, true)],
              ['sales', dMoney(data.totals.delta.sales), upClass(data.totals.delta.sales)],
              ['orders', d0(data.totals.delta.orders), upClass(data.totals.delta.orders)],
              ['acos', dPct(data.totals.delta.acos), upClass(data.totals.delta.acos, true)],
            ].map(([k, v, cls]) => (
              <div key={k} className="card p-3">
                <div className="text-mute text-[10px] font-mono uppercase tracking-wider">{k} Δ</div>
                <div className={`mt-1 text-lg font-mono font-bold ${cls}`}>{v}</div>
              </div>
            ))}
          </div>

          <TableToolbar ctl={ctl} placeholder="search campaign…" />
          <div className="overflow-auto max-h-[300px]">
            <table className="w-full text-sm font-mono">
              <thead className="sticky top-0 bg-panel text-mute text-[11px] uppercase">
                <tr className="border-b border-edge">
                  <Th ctl={ctl} k="name">Campaign</Th>
                  <Th ctl={ctl} k="spend_delta" align="right">Spend Δ</Th>
                  <Th ctl={ctl} k="orders_delta" align="right">Orders Δ</Th>
                  <Th ctl={ctl} k="acos_delta" align="right">ACoS Δ</Th>
                </tr>
              </thead>
              <tbody>
                {ctl.view.map((m, i) => (
                  <tr key={i} className="border-b border-edge/50 hover:bg-edge/30">
                    <td className="p-2 max-w-[220px] truncate text-slate-200" title={m.name}>{m.name || m.campaign_id}</td>
                    <td className={`p-2 text-right ${upClass(m.spend_delta, true)}`}>{dMoney(m.spend_delta)}</td>
                    <td className={`p-2 text-right ${upClass(m.orders_delta)}`}>{d0(m.orders_delta)}</td>
                    <td className={`p-2 text-right ${upClass(m.acos_delta, true)}`}>{dPct(m.acos_delta)}</td>
                  </tr>
                ))}
                {ctl.view.length === 0 && <tr><td colSpan="4" className="p-6 text-center text-mute">{ctl.query ? 'no matches' : 'no campaign movement'}</td></tr>}
              </tbody>
            </table>
          </div>
          <Pagination ctl={ctl} />
        </div>
      )}
    </div>
  )
}

const V = {
  winner: 'bg-lime/15 text-lime border border-lime/30',
  waster: 'bg-red/15 text-red border border-red/30',
  neutral: 'border border-edge text-mute',
}

// N-gram miner: STR -> winning/wasting WORDS across all search terms.
// res/onRes optional: when provided, result is lifted to the parent so it
// survives tab switches and is shared across panel instances.
export function NgramPanel({ targetAcos, res: resProp, onRes, noUpload }) {
  const toast = useToast()
  const inputRef = useRef()
  const [drag, setDrag] = useState(false)
  const [name, setName] = useState(null)
  const [resLocal, setResLocal] = useState(null)
  const res = onRes ? resProp : resLocal
  const setRes = onRes || setResLocal
  const [filter, setFilter] = useState('ALL')   // ALL | winner | waster | neutral
  const [n, setN] = useState('ALL')              // ALL | 1 | 2 | 3
  const [busy, setBusy] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [selGrams, setSelGrams] = useState(new Set())   // ticked grams — push/export scope
  const [err, setErr] = useState(null)

  // new result = new selection slate
  useEffect(() => { setSelGrams(new Set()) }, [res])

  function toggleGram(g) {
    setSelGrams(s => { const x = new Set(s); x.has(g) ? x.delete(g) : x.add(g); return x })
  }

  async function exportReport() {
    const chosen = selGrams.size ? grams.filter(g => selGrams.has(g.gram)) : grams
    if (!chosen.length) return
    setExporting(true)
    try {
      const blob = await api.ngramExport(chosen, res?.summary)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'ppc_ngram_report.xlsx'; a.click()
      URL.revokeObjectURL(url)
      toast.success(`N-gram report exported · ${chosen.length} gram${chosen.length === 1 ? '' : 's'}${selGrams.size ? ' (selected)' : ''}`)
    } catch (e) { toast.error(String(e).replace(/^Error:\s*/, '')) }
    finally { setExporting(false) }
  }

  async function run(file) {
    if (!file) return
    setName(file.name); setErr(null); setBusy(true); setRes(null)
    try { setRes(await api.ngrams(file, { targetAcos })) }
    catch (e) { setErr(String(e)) }
    finally { setBusy(false) }
  }

  const grams = res?.grams || []
  const rows = useMemo(() => grams.filter(g =>
    (filter === 'ALL' || g.verdict === filter) && (n === 'ALL' || g.n === Number(n))
  ), [grams, filter, n])
  const ctl = useTableControls(rows, {
    searchKeys: ['gram', 'verdict'], deps: [filter, n, res],
  })
  const counts = useMemo(() => ({
    winner: grams.filter(g => g.verdict === 'winner').length,
    waster: grams.filter(g => g.verdict === 'waster').length,
  }), [grams])

  return (
    <div className="card">
      <div className="p-4 border-b border-edge">
        <div className="text-mute text-[11px] font-mono uppercase tracking-wider mb-1">n-gram word miner <TemplateLink kind="str" /></div>
        <div className="text-xs text-mute font-mono">
          {noUpload ? (
            <>fed by the <span className="text-slate-200">Search-Term Harvest upload above</span> — the same file's
            SP Search Term Report shows which WORDS (1–3 grams) win or waste across every term.</>
          ) : (
            <>upload your Sponsored Products <span className="text-slate-200">bulk file</span> (with its SP Search Term Report sheet) →
            see which WORDS (1–3 grams) win or waste across every term. A standalone STR works too.</>
          )}
        </div>
      </div>

      {!noUpload && (
      <div className="p-4">
        <div
          onDragOver={e => { e.preventDefault(); setDrag(true) }}
          onDragLeave={() => setDrag(false)}
          onDrop={e => { e.preventDefault(); setDrag(false); run(e.dataTransfer.files[0]) }}
          onClick={() => inputRef.current?.click()}
          className={`card p-5 cursor-pointer text-center transition-colors ${drag ? 'border-lime bg-lime/5' : 'border-dashed'}`}
        >
          <input ref={inputRef} type="file" accept=".xlsx,.xlsm,.csv" hidden onChange={e => run(e.target.files[0])} />
          {busy ? <Spinner label="mining n-grams…" /> : (
            <div className="font-mono text-sm">
              <span className="btn btn-primary text-xs inline-flex items-center gap-1 mb-2 pointer-events-none">
                <Icon name="upload" size={14} /> Upload Sponsored Products Bulk
              </span>
              <div className="text-mute text-xs">{name || `bulk with SP Search Term Report sheet (or a standalone STR) — or drag & drop · goal ACoS ${pct(targetAcos)}`}</div>
            </div>
          )}
        </div>
      </div>
      )}

      {noUpload && !res && (
        <div className="p-6 text-center font-mono text-xs text-mute">
          No n-gram data yet — upload a bulk (or standalone STR) in the Search-Term Harvest above and
          the word analysis appears here automatically.
        </div>
      )}

      {err && <div className="mx-4 mb-4 card border-red/40 p-3 font-mono text-sm text-red inline-flex items-center gap-1"><Icon name="warning" size={14} /> {err}</div>}

      {res?.scope && (
        <div className="px-4 pb-2 font-mono text-[11px] text-mute">
          {res.scope.note
            ? res.scope.note
            : <>scoped to project ASIN{res.scope.asins.length === 1 ? '' : 's'} <span className="text-slate-200">{res.scope.asins.join(', ')}</span> · {res.scope.hidden_rows} row{res.scope.hidden_rows === 1 ? '' : 's'} from other ASINs hidden</>}
        </div>
      )}
      {res && (
        <>
          {/* run summary */}
          {res.summary && (
            <div className="px-4 pb-3">
              <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
                {[
                  ['Terms', res.summary.terms.toLocaleString()],
                  ['Impr.', res.summary.impressions.toLocaleString()],
                  ['Clicks', res.summary.clicks.toLocaleString()],
                  ['Spend', money(res.summary.spend)],
                  ['Sales', money(res.summary.sales)],
                  ['ACoS', res.summary.acos == null ? '—' : pct(res.summary.acos)],
                  ['Winners', res.summary.winners, 'text-up'],
                  ['Wasters', res.summary.wasters, 'text-down'],
                ].map(([label, v, cls]) => (
                  <div key={label} className="card p-2">
                    <div className="text-mute text-[9px] font-mono uppercase tracking-wider">{label}</div>
                    <div className={`font-mono text-sm font-bold mt-0.5 ${cls || 'text-slate-100'}`}>{v}</div>
                  </div>
                ))}
              </div>
              {res.asin_terms_hidden > 0 && (
                <div className="font-mono text-[10px] text-mute mt-2">
                  {res.asin_terms_hidden} ASIN-pattern search term{res.asin_terms_hidden === 1 ? '' : 's'} excluded — keywords only.
                </div>
              )}
            </div>
          )}

          <div className="flex items-center justify-between px-4 pb-3 border-b border-edge gap-2 flex-wrap">
            <div className="flex gap-1 flex-wrap">
              {[['ALL', grams.length], ['winner', counts.winner], ['waster', counts.waster]].map(([f, c]) => (
                <button key={f} onClick={() => setFilter(f)}
                  className={`tag ${filter === f ? 'bg-lime text-ink' : 'border border-edge text-mute hover:text-slate-300'}`}>
                  {f.toUpperCase()} {c}
                </button>
              ))}
              {['ALL', '1', '2', '3'].map(x => (
                <button key={x} onClick={() => setN(x)}
                  className={`tag ${n === x ? 'bg-cyan text-ink' : 'border border-edge text-mute hover:text-slate-300'}`}>
                  {x === 'ALL' ? 'n=all' : `${x}-gram`}
                </button>
              ))}
            </div>
            <div className="flex gap-2 items-center">
              <button disabled={!selGrams.size}
                title="merge the SELECTED grams into the shared keyword project (pick it in the Keywords tab)"
                onClick={async () => {
                  const pid = Number(api.kwProject.get())
                  if (!pid) { toast.error('Pick a keyword project in the Keywords tab first'); return }
                  const chosen = grams.filter(g => selGrams.has(g.gram)).map(g => ({ keyword: g.gram }))
                  try {
                    const r = await api.trackerAddKeywords(pid, chosen, 'ngram')
                    const seo = (r.seo_before?.indexed != null && r.seo_after?.indexed != null)
                      ? ` · indexed ${(r.seo_before.indexed * 100).toFixed(1)}% → ${(r.seo_after.indexed * 100).toFixed(1)}%` : ''
                    toast.success(`+${r.added} grams → “${r.project.name}” · ${r.duplicates} already tracked${seo}`)
                  } catch (e) { toast.error(String(e).replace(/^Error:\s*/, '')) }
                }}
                className="btn btn-ghost text-xs flex items-center gap-1 disabled:opacity-50">
                <Icon name="playlist_add" size={14} /> selected to keyword project ({selGrams.size})
              </button>
              <button onClick={exportReport} disabled={exporting || !grams.length} aria-busy={exporting}
                title="download the summary + grams as .xlsx (selected grams only when any are ticked)"
                className="btn btn-primary text-xs flex items-center gap-1 disabled:opacity-50">
                <Icon name="download" size={14} />{exporting ? 'Building…' : `Export report${selGrams.size ? ` (${selGrams.size})` : ''}`}
              </button>
            </div>
          </div>

          <TableToolbar ctl={ctl} placeholder="search word / phrase…" />
          <div className="overflow-auto max-h-[420px]">
            <table className="w-full text-sm font-mono">
              <thead className="sticky top-0 bg-panel text-mute text-[11px] uppercase">
                <tr className="border-b border-edge">
                  <th className="p-2 text-left w-8">
                    <input type="checkbox" className="accent-lime"
                      checked={ctl.view.length > 0 && ctl.view.every(g => selGrams.has(g.gram))}
                      onChange={() => setSelGrams(s => {
                        const x = new Set(s)
                        const all = ctl.view.every(g => x.has(g.gram))
                        ctl.view.forEach(g => (all ? x.delete(g.gram) : x.add(g.gram)))
                        return x
                      })} />
                  </th>
                  <Th ctl={ctl} k="gram">Word / phrase</Th>
                  <Th ctl={ctl} k="verdict">Verdict</Th>
                  <Th ctl={ctl} k="terms" align="right">Terms</Th>
                  <Th ctl={ctl} k="spend" align="right">Spend</Th>
                  <Th ctl={ctl} k="sales" align="right">Sales</Th>
                  <Th ctl={ctl} k="orders" align="right">Orders</Th>
                  <Th ctl={ctl} k="acos" align="right">ACoS</Th>
                  <Th ctl={ctl} k="break_even" align="right">BE ACoS</Th>
                </tr>
              </thead>
              <tbody>
                {ctl.view.map((g, i) => (
                  <tr key={i} className="border-b border-edge/50 hover:bg-edge/30">
                    <td className="p-2 w-8">
                      <input type="checkbox" className="accent-lime"
                        checked={selGrams.has(g.gram)} onChange={() => toggleGram(g.gram)} />
                    </td>
                    <td className="p-2 max-w-[220px] truncate text-slate-200" title={g.gram}>{g.gram}</td>
                    <td className="p-2"><span className={`tag ${V[g.verdict]}`}>{g.verdict}</span></td>
                    <td className="p-2 text-right text-mute">{g.terms}</td>
                    <td className="p-2 text-right text-slate-300">{money(g.spend)}</td>
                    <td className="p-2 text-right text-slate-300">{money(g.sales)}</td>
                    <td className="p-2 text-right text-slate-300">{g.orders}</td>
                    <td className={`p-2 text-right ${g.break_even != null && g.acos != null ? (g.acos > g.break_even ? 'text-down' : 'text-up') : 'text-slate-300'}`}
                      title={g.break_even != null ? `weighted break-even ${(g.break_even * 100).toFixed(1)}% — red = the word converts above the products' break-even` : ''}>{pct(g.acos)}</td>
                    <td className="p-2 text-right text-mute"
                      title="spend-weighted break-even ACoS across the ad groups this word ran in (catalog listings' price + per-SKU COGS + real Transactions-ledger fees)">
                      {g.break_even != null ? pct(g.break_even) : '—'}</td>
                  </tr>
                ))}
                {ctl.view.length === 0 && <tr><td colSpan="9" className="p-6 text-center text-mute">{ctl.query ? 'no matches' : 'no grams — load a fuller report or loosen filters'}</td></tr>}
              </tbody>
            </table>
          </div>
          <Pagination ctl={ctl} />
        </>
      )}
    </div>
  )
}
